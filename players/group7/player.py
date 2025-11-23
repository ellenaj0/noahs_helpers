"""Player7: fresh helper redesign with stable pursuit and clear phases."""

from __future__ import annotations

import math
from collections import deque

from core.action import Action, Move, Obtain, Release
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
import core.constants as c


class Player7(Player):
    _group_last_logged: dict[int, int] = {}  # group_id -> last turn logged
    _group_first_window_done: dict[
        int, bool
    ] = {}  # track per-group first-window completion

    def __init__(
        self,
        id: int,
        ark_x: int,
        ark_y: int,
        kind: Kind,
        num_helpers: int,
        species_populations: dict[str, int],
    ):
        super().__init__(id, ark_x, ark_y, kind, num_helpers, species_populations)

        # Tunables consolidated into config for easy tuning
        self.config = self._init_config()

        # State
        self.turn = 0
        self.is_raining = False
        self._rain_started_at: int | None = None
        self.time_elapsed = 0
        self.last_snapshot: HelperSurroundingsSnapshot | None = None

        # Knowledge
        self.ark_status: dict[int, dict] = {}
        self.known: dict[tuple[int, int, int], dict] = {}

        # Behavior
        self._intend_obtain = False
        self._linger_until = 0
        self._blocked: dict[tuple[int, int], int] = {}
        self._recent: deque[tuple[int, int]] = deque(maxlen=self.config["recent_len"])
        self._cell_cache: dict[tuple[int, int], tuple[float, int]] = {}
        self._explored: set[tuple[int, int]] = set()  # Track explored

        # Pursuit
        self._tgt_cell: tuple[int, int] | None = None
        self._tgt_score: float = -1.0
        self._tgt_expires = 0
        self._lock_until = 0
        self._last_dist: float | None = None
        self._stuck = 0
        # Track chase attempts per cell to avoid infinite chasing
        self._chase_attempts: dict[tuple[int, int], int] = {}
        self._prev_flock_size = 0

        # Messaging
        self.priorities: set[tuple[int, int]] = set()
        self.messages_sent: set[int] = set()
        self.messages_to_send: list[int] = []
        self.last_seen_ark_animals: set[tuple[int, int]] = set()
        self._seen_carrying: dict[tuple[int, int], int] = {}
        self._claimed: dict[tuple[int, int], int] = {}

        # Rarity
        self.rarity = self._compute_rarity()
        self.territory = self._compute_territory()

        # Waiting / Formation
        self._formation_spacing = c.MAX_SIGHT_KM * 0.8
        self._waiting_position = self._compute_waiting_position()

        self.last_rendezvous_turn = 0

    def _init_config(self) -> dict:
        return {
            "linger_turns": 3,
            "block_after_fail": 3,
            "pursuit_hyst": 1.5,
            "pursuit_lock": 2,
            "recent_len": 10,
            "eta_buffer": 10,
            "recent_bias": 1.3,
            "swap_threshold": 1.5,
            "stuck_threshold": 3,
            "give_up_turns": 7,
        }

    def _init_sliding_window(self, num_groups: int):
        """Initialize sliding window positions and rotation parameters."""
        self.center_point = (c.X / 2, c.Y / 2)

        # Base number of slots
        self.num_slots = max(
            1, min(50, num_groups * 2)
        )  # use parameter, not self.num_groups
        self.slot_angles = [
            2 * math.pi * i / self.num_slots for i in range(self.num_slots)
        ]

        # Window sizing
        self.window_half_size = max(20, min(c.X, c.Y) / (2 * num_groups))
        self.window_radius = min(c.X, c.Y) / 2 - self.window_half_size

        # Rotation state
        self.slot_index = 0
        self.last_slot_turn = self.turn
        self.slot_turns = 50

        # Precompute window centers in a circle
        cx, cy = self.center_point
        r = self.window_radius
        self.precomputed_windows = [
            (cx + r * math.cos(angle), cy + r * math.sin(angle))
            for angle in self.slot_angles
        ]
        self.window_center = self.precomputed_windows[self.slot_index]

        # Group tracking
        self.group_helper_ids = []
        self.in_rendezvous = True
        self.group_rendezvous_started = True
        self.rendezvous_interval = 500

    def setup_groups(self, total_helpers):
        """Compute number of groups, assign helpers and species."""
        total_animals = sum(self.species_populations.values())
        groups_by_species = math.ceil(total_animals / 16)
        groups_by_helpers = math.ceil(total_helpers / 10)

        # Decide number of groups (1 <= num_groups <= total_helpers <= num_slots)
        self.num_groups = max(1, max(groups_by_species, groups_by_helpers))
        self.num_groups = min(self.num_groups, total_helpers)

        self._init_sliding_window(self.num_groups)

        # Assign group ID
        self.group_id = self.id % self.num_groups
        self.group_helper_ids = [
            hid
            for hid in range(total_helpers)
            if hid % self.num_groups == self.group_id
        ]

        # Disable rendezvous if group has only one helper
        if len(self.group_helper_ids) <= 1:
            self.in_rendezvous = False
            self.group_rendezvous_started = False
            self.rendezvous_interval = 0

        # Assign initial slot to group (spread across slot circle)
        slots_per_group = max(1, self.num_slots // self.num_groups)
        self.slot_index = min(self.group_id * slots_per_group, self.num_slots - 1)
        self.window_center = self.precomputed_windows[self.slot_index]
        self.last_slot_turn = self.turn

        # Assign species responsibility to this group
        species_list = sorted(self.species_populations.keys())
        for idx, letter in enumerate(species_list):
            if idx % self.num_groups == self.group_id:
                sid = ord(letter) - ord("a")
                self.priorities.add((sid, 0))
                self.priorities.add((sid, 1))

        # print(f"[Setup Groups] Helper {self.id} in group {self.group_id}")
        # print(f"Group members: {self.group_helper_ids}")
        # print(f"Assigned slot: {self.slot_index}, Window center: {self.window_center}")
        # print(f"Assigned species: {self.priorities}")

    def _update_window_center(self):
        """Rotate group to next slot if enough turns passed and not in rendezvous."""
        if not self.precomputed_windows:
            return

        if self.in_rendezvous:
            return

        if (self.turn - self.last_slot_turn) < self.slot_turns:
            return

        # Rotate to next slot in circle
        self.slot_index = (self.slot_index + 1) % self.num_slots
        self.window_center = self.precomputed_windows[self.slot_index]
        self.last_slot_turn = self.turn

        last_logged = Player7._group_last_logged.get(self.group_id, -1)
        if last_logged != self.turn:
            Player7._group_last_logged[self.group_id] = self.turn
            # print(f"[Group Rotation] Group {self.group_id} moved to slot {self.slot_index}, center {self.window_center}")

    def _move_to_window(self):
        """Move helper toward current window center if not already close."""
        if self._dist_to_point(self.window_center) > 5.0:
            return self._move_to(self.window_center)
        return None

    def _move_for_rendezvous(self):
        """
        Move toward assigned window. Periodic rendezvous starts after
        the group has reached its first window.
        """
        group_id = self.group_id
        dist_to_center = self._dist_to_point(self.window_center)

        # move to assigned window if not already close
        if dist_to_center > 5.0:
            return self._move_to(self.window_center)

        # Mark that this helper has reached its window
        self.first_window_reached = True

        # Initialize first-window done flag for the group
        if group_id not in self._group_first_window_done:
            self._group_first_window_done[group_id] = True
            self.last_rendezvous_turn = self.turn
            # print(f"[Group First Window Reached] Group {group_id} at turn {self.turn}")

        # Only start a new rendezvous if interval elapsed
        if (self.turn - self.last_rendezvous_turn) >= self.rendezvous_interval:
            if not self.in_rendezvous:
                self.in_rendezvous = True
                # print(f"[Rendezvous Start] Group {group_id} starting rendezvous at turn {self.turn}")

        # If currently in rendezvous, move toward window and check for completion
        if self.in_rendezvous:
            # Track visible group members
            visible_group_members = set()
            for cellview in self.sight:
                if (
                    math.hypot(
                        cellview.x - self.position[0], cellview.y - self.position[1]
                    )
                    <= 5.0
                ):
                    for helper in cellview.helpers:
                        if helper.id in self.group_helper_ids:
                            visible_group_members.add(helper.id)
            visible_group_members.add(self.id)

            group_ready = visible_group_members >= set(self.group_helper_ids)

            if dist_to_center > 5.0:
                return self._move_to(self.window_center)

            if group_ready:
                self.in_rendezvous = False
                self.last_rendezvous_turn = self.turn
                # print(f"[Rendezvous Complete] Group {group_id} finished rendezvous at turn {self.turn}")

    def _dist_to_point(self, point):
        x, y = self.position
        px, py = point
        return ((x - px) ** 2 + (y - py) ** 2) ** 0.5

    def _explore_within_window(self):
        """
        Explore but constrained to the sliding window.
        """

        t = self.territory

        # save original territory
        orig_min_x = t["min_x"]
        orig_max_x = t["max_x"]
        orig_min_y = t["min_y"]
        orig_max_y = t["max_y"]

        # apply window bounds
        wx, wy = self.window_center
        half = self.window_half_size

        t["min_x"] = int(max(0, wx - half))
        t["max_x"] = int(min(c.X - 1, wx + half))
        t["min_y"] = int(max(0, wy - half))
        t["max_y"] = int(min(c.Y - 1, wy + half))

        # explore using modified territory window
        mv = self._explore()

        # restore territory
        t["min_x"] = orig_min_x
        t["max_x"] = orig_max_x
        t["min_y"] = orig_min_y
        t["max_y"] = orig_max_y

        return mv

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        self.last_snapshot = snapshot
        self.sight = snapshot.sight
        self._update_state(snapshot)

        # Initialize priorities on first turn
        if self.turn == 1 and self.kind != Kind.Noah:
            self.setup_groups(self.num_helpers - 1)

        # Process ark view for communication
        if snapshot.ark_view:
            import heapq

            current_ark = {
                (a.species_id, a.gender.value) for a in snapshot.ark_view.animals
            }
            new_animals = current_ark - self.last_seen_ark_animals

            for sid, gender in new_animals:
                self.priorities.discard((sid, gender))
                # Ark message: bits 3-7=species, bit 2=gender, bit 1=ARK
                msg = (sid << 3) | (gender << 2) | 0b00000010
                if msg not in self.messages_sent:
                    heapq.heappush(self.messages_to_send, msg)
                    self.messages_sent.add(msg)

            self.last_seen_ark_animals = current_ark

        # Send queued message or default
        if self.messages_to_send:
            import heapq

            return heapq.heappop(self.messages_to_send)

        return self._encode_message()

    def get_action(self, messages: list[Message]) -> Action | None:
        if self.kind == Kind.Noah:
            return None

        self._process_messages(messages)

        self._update_window_center()

        # Move toward the window center if not at it

        if (self.turn - self.last_slot_turn) >= self.slot_turns:
            mv = self._move_to_window()
            if mv:
                return mv

        # Only then do other behavior like pursuit / explore / ark

        # rendezvous movement
        if self.in_rendezvous:
            mv = self._move_for_rendezvous()
            if mv:
                return mv

        # If in ark with empty flock, leave immediately
        if self.is_in_ark() and len(self.flock) == 0:
            # Clear behaviors and move to territory center
            self._linger_until = 0
            self._tgt_cell = None
            self._stuck = 0
            t = self.territory
            return self._move_to((t["cx"], t["cy"]))

        if self.is_raining:
            if not self.is_in_ark():
                return Move(*self.move_towards(*self.ark_position))
            else:
                return None  # Already on ark

        if self._should_return():
            # When returning, prioritize getting to ark
            if self.is_in_ark():
                return None

            # Clear all active behaviors when returning to ark
            self._linger_until = 0
            self._tgt_cell = None
            self._stuck = 0

            dist_to_ark = self._dist_to_ark()

            # If raining, calculate urgency
            if self.is_raining and self._rain_started_at is not None:
                elapsed = self.time_elapsed - self._rain_started_at
                left = c.START_RAIN - elapsed
                turns_to_ark = math.ceil(dist_to_ark / c.MAX_DISTANCE_KM)

                # If time is tight (less than 50 turns buffer), go direct
                if turns_to_ark + 50 >= left:
                    return self._move_to(self.ark_position)

                # If we have animals, go directly to ark
                if len(self.flock) > 0:
                    return self._move_to(self.ark_position)

            # If very close to ark, go to exact position
            if dist_to_ark <= 5:
                return self._move_to(self.ark_position)

            # If raining, go to ark (not waiting position)
            if self.is_raining:
                return self._move_to(self.ark_position)

            # Otherwise move toward waiting position near ark
            # This spreads helpers around ark when many return
            return self._move_to(self.ark_position)

        if self._should_offload():
            if self.is_in_ark():
                # In ark with full flock - offload everything
                if len(self.flock) > 0:
                    for animal in self.flock:
                        return Release(animal)
                return None
            # Clear all active behaviors when offloading
            self._linger_until = 0
            self._tgt_cell = None
            self._stuck = 0
            return self._move_to(self.ark_position)

        if self.turn < self._linger_until:
            a = self._best_here()
            if a is not None:
                self._intend_obtain = True
                return Obtain(a)

        comp = self._best_visible_completer()
        here_val = self._best_value_here()
        if comp is not None:
            pos, val = comp
            if val > here_val * 1.5:
                if self.is_flock_full():
                    rls = self._lowest_in_flock()
                    if rls is not None:
                        return Release(rls)
                return self._move_to(pos)

        a = self._best_here()
        if a is not None:
            if self.is_flock_full():
                r = self._choose_release(a)
                if r is not None:
                    return Release(r)
            else:
                self._intend_obtain = True
                # Broadcast that we're obtaining this animal
                import heapq

                self.priorities.discard((a.species_id, a.gender.value))
                msg = (a.species_id << 3) | (a.gender.value << 2) | 0b00000001
                if msg not in self.messages_sent:
                    heapq.heappush(self.messages_to_send, msg)
                    self.messages_sent.add(msg)
                return Obtain(a)

        mv = self._pursue_best_cell()
        if mv is not None:
            return mv

        # If flock is full and no valuable targets, return to ark
        if self.is_flock_full():
            if not self.is_in_ark():
                self._tgt_cell = None
                self._stuck = 0
                return self._move_to(self.ark_position)
            # In ark with full flock - offload
            if len(self.flock) > 0:
                for animal in self.flock:
                    return Release(animal)
            return None

        return self._explore_within_window()

    # -------- State & messages --------

    def _update_state(self, snap: HelperSurroundingsSnapshot) -> None:
        self.turn += 1
        self.time_elapsed = snap.time_elapsed

        # Save flock size before processing turn (for chase detection)
        self._prev_flock_size = len(self.flock)

        self.is_raining = snap.is_raining
        if self.is_raining and self._rain_started_at is None:
            self._rain_started_at = snap.time_elapsed

        self.position = snap.position
        self._recent.append((int(self.position[0]), int(self.position[1])))

        # Mark current position and all visible cells as explored
        curr_cell = (int(self.position[0]), int(self.position[1]))
        self._explored.add(curr_cell)
        for cv in snap.sight:
            self._explored.add((cv.x, cv.y))

        prev = len(self.flock)
        self.flock = snap.flock.copy()

        expired = [p for p, t in self._blocked.items() if t <= self.turn]
        for p in expired:
            del self._blocked[p]

        # Periodic cleanup: if too many blocked cells, clear old ones
        if len(self._blocked) > 20:
            cutoff = self.turn - 10
            old = [p for p, t in self._blocked.items() if t < cutoff]
            for p in old:
                del self._blocked[p]

        if self._intend_obtain:
            if len(self.flock) > prev:
                self._linger_until = self.turn + self.config["linger_turns"]
            else:
                cx, cy = int(self.position[0]), int(self.position[1])
                self._blocked[(cx, cy)] = self.turn + self.config["block_after_fail"]
        self._intend_obtain = False

        if snap.ark_view is not None:
            self._update_ark(snap.ark_view.animals)

        for cv in snap.sight:
            for an in cv.animals:
                key = (cv.x, cv.y, an.species_id)
                self.known[key] = {
                    "sid": an.species_id,
                    "gender": an.gender,
                    "pos": (cv.x, cv.y),
                    "seen": self.turn,
                }

    def _encode_message(self) -> int:
        if not self.flock:
            return 0
        # Encode: bits 0-4=species, bit 5=gender, bit 6=have, bit 7=claim
        best = max(self.flock, key=lambda a: self._value(a.species_id, a.gender))
        sid = best.species_id & 0x1F
        msg = sid
        from core.animal import Gender

        if best.gender == Gender.Female:
            msg |= 1 << 5
        msg |= 1 << 6  # Have this animal
        msg |= 1 << 7  # Claiming (avoid duplicates)
        return msg

    def _process_messages(self, messages: list[Message]) -> None:
        from core.animal import Gender
        import heapq

        # Expire old claims/sightings
        to_rm = [k for k, v in self._claimed.items() if v < self.turn - 20]
        for k in to_rm:
            del self._claimed[k]
        to_rm = [k for k, v in self._seen_carrying.items() if v < self.turn - 20]
        for k in to_rm:
            del self._seen_carrying[k]

        for m in messages:
            b = m.contents

            # Decode message
            from_ark = bool(b & 0b00000010)
            from_local = bool(b & 0b00000001)
            gender = (b & 0b00000100) >> 2
            sid = (b & 0b11111000) >> 3

            # Handle ark messages (release if we have it)
            if from_ark:
                for a in self.flock:
                    if a.species_id == sid and a.gender.value == gender:
                        # Mark for immediate release in get_action
                        self.priorities.discard((sid, gender))
                        break

            # Handle local helper messages (update priorities)
            if from_local:
                self.priorities.discard((sid, gender))

            # Forward message to neighbors
            if self.last_snapshot:
                neighbor_ids = {
                    h.id
                    for cv in self.last_snapshot.sight
                    for h in cv.helpers
                    if h.id != self.id
                }
                if b not in self.messages_sent and any(
                    n != m.from_helper.id for n in neighbor_ids
                ):
                    heapq.heappush(self.messages_to_send, b)
                    self.messages_sent.add(b)

            # Legacy protocol support:
            # Only apply for messages that DON'T use the new from_ark/from_local flags.
            # This avoids misinterpreting our new encoding and corrupting `_claimed`.
            if not from_ark and not from_local:
                female = (b >> 5) & 1
                have = (b >> 6) & 1
                claiming = (b >> 7) & 1
                g = Gender.Female if female else Gender.Male
                if have:
                    self._seen_carrying[(sid, g.value)] = self.turn
                if claiming:
                    self._claimed[(sid, g.value)] = self.turn

    # -------- Decision helpers --------

    def _should_return(self) -> bool:
        # Calculate distance to ark and turns needed
        dist_to_ark = self._dist_to_ark()
        turns_to_ark = math.ceil(dist_to_ark / c.MAX_DISTANCE_KM)

        if self.is_raining and self._rain_started_at is not None:
            # Rain has started - must reach ark well before T
            elapsed = self.time_elapsed - self._rain_started_at
            left = c.START_RAIN - elapsed

            # Add generous buffer to account for obstacles, detours, etc.
            # Need to be back at least 20 turns before T (T-20)
            buffer = 20

            # Return if we don't have enough time left
            if turns_to_ark + buffer >= left:
                return True

            # If we have animals, return even earlier to be safe
            if len(self.flock) > 0 and turns_to_ark + buffer + 10 >= left:
                return True

        # After 7 days (1008 turns): ensure we can get back if rain starts
        # We need to be within START_RAIN distance minus large buffer
        if self.time_elapsed >= 1008:
            # Stay within safe distance with 150 turn buffer
            max_safe_distance = (c.START_RAIN - 150) * c.MAX_DISTANCE_KM
            if dist_to_ark > max_safe_distance:
                return True

        return False

    def _should_offload(self) -> bool:
        if self.is_flock_full():
            return True
        if len(self.flock) >= 3:
            vals = [self._value(a.species_id, a.gender) for a in self.flock]
            vals.sort(reverse=True)
            return vals[0] >= 90 and vals[1] >= 80
        return False

    def _best_here(self):
        snap = self.last_snapshot
        if snap is None:
            return None
        cx, cy = int(self.position[0]), int(self.position[1])
        exp = self._blocked.get((cx, cy))
        if exp is not None and exp > self.turn:
            return None
        animals = None
        for cv in snap.sight:
            if cv.x == cx and cv.y == cy:
                animals = list(cv.animals)
                break
        if not animals:
            return None
        best = None
        best_val = -1.0
        best_comp = None
        best_comp_val = -1.0
        for a in animals:
            if a in self.flock:
                continue
            # Skip exact species+gender duplicates (we already carry one)
            if any(
                f.species_id == a.species_id and f.gender == a.gender
                for f in self.flock
            ):
                continue
            # Skip animals already in the ark (no extra value)
            if self._is_in_ark(a.species_id, a.gender):
                continue
            # IMPORTANT: do NOT skip just because of `_claimed` here.
            # If we're physically on the same cell as the animal, it's cheap
            # to pick it up, even if another helper "claimed" that species+gender.

            # Prioritize animals in priority set
            is_priority = (a.species_id, a.gender.value) in self.priorities
            val = self._value(a.species_id, a.gender)

            if is_priority:
                val *= 1.5  # Boost priority animals

            if self._would_complete(a.species_id, a.gender):
                if val > best_comp_val:
                    best_comp_val = val
                    best_comp = a
            if val > best_val:
                best_val = val
                best = a
        return best_comp or best

    def _best_value_here(self) -> float:
        snap = self.last_snapshot
        if snap is None:
            return 0.0
        cx, cy = int(self.position[0]), int(self.position[1])
        best = 0.0
        for cv in snap.sight:
            if cv.x == cx and cv.y == cy:
                for a in cv.animals:
                    best = max(best, self._value(a.species_id, a.gender))
                break
        return best

    def _lowest_in_flock(self):
        worst = None
        worst_val = float("inf")
        for a in self.flock:
            v = self._value(a.species_id, a.gender)
            if v < worst_val:
                worst_val = v
                worst = a
        return worst

    def _choose_release(self, target):
        if not self._would_complete(target.species_id, target.gender):
            return None
        worst = self._lowest_in_flock()
        if worst is None:
            return None
        tv = self._value(target.species_id, target.gender)
        wv = self._value(worst.species_id, worst.gender)
        # Only swap if target is significantly better
        return worst if tv > wv * self.config["swap_threshold"] else None

    def _best_visible_completer(self):
        snap = self.last_snapshot
        if snap is None:
            return None
        cx, cy = int(self.position[0]), int(self.position[1])
        best_pos = None
        best_val = -1.0
        for cv in snap.sight:
            if (cv.x, cv.y) == (cx, cy):
                continue
            exp = self._blocked.get((cv.x, cv.y))
            if exp is not None and exp > self.turn:
                continue
            cell_best = -1.0
            for a in cv.animals:
                # Skip duplicates in flock
                if any(
                    f.species_id == a.species_id and f.gender == a.gender
                    for f in self.flock
                ):
                    continue
                # Skip animals already in the ark
                if self._is_in_ark(a.species_id, a.gender):
                    continue
                if self._would_complete(a.species_id, a.gender):
                    cell_best = max(cell_best, self._value(a.species_id, a.gender))
            if cell_best < 0:
                continue
            if cell_best > best_val:
                best_val = cell_best
                best_pos = (cv.x, cv.y)
        if best_pos is None:
            return None
        return best_pos, best_val

    def _pursue_best_cell(self) -> Move | None:
        snap = self.last_snapshot
        if snap is None:
            return None
        curr = (int(self.position[0]), int(self.position[1]))

        # Clean up old chase attempts
        if self.turn % 50 == 0:
            self._chase_attempts.clear()

        # Check if we have an active target
        if (
            self._tgt_cell is not None
            and self._tgt_expires > self.turn
            and self._blocked.get(self._tgt_cell, 0) <= self.turn
        ):
            if self._tgt_cell == curr:
                # Reached target - check if we obtained an animal
                current_flock_size = len(self.flock)
                if self._prev_flock_size == current_flock_size:
                    # Flock didn't grow - animal likely moved away
                    cell_key = self._tgt_cell
                    self._chase_attempts[cell_key] = (
                        self._chase_attempts.get(cell_key, 0) + 1
                    )
                    # After 2 failed attempts at same cell, block it
                    if self._chase_attempts[cell_key] >= 2:
                        self._blocked[self._tgt_cell] = self.turn + 20
                        self._tgt_cell = None
                        self._last_dist = None
                        self._stuck = 0
                        self._recent.clear()
                        return None
                else:
                    # Success! Clear chase attempts for this cell
                    if self._tgt_cell in self._chase_attempts:
                        del self._chase_attempts[self._tgt_cell]
                # Clear target and continue
                self._tgt_cell = None
                self._last_dist = None
                self._stuck = 0
            else:
                # Check if making progress toward target
                tx, ty = self._tgt_cell
                dx = tx - self.position[0]
                dy = ty - self.position[1]
                d = max(0.0, math.hypot(dx, dy))

                if self._last_dist is not None:
                    if d >= self._last_dist - 1e-6:
                        self._stuck += 1
                    else:
                        self._stuck = 0

                self._last_dist = d

                if self._stuck >= self.config["stuck_threshold"]:
                    # Give up on this target
                    self._blocked[self._tgt_cell] = (
                        self.turn + self.config["give_up_turns"]
                    )
                    self._tgt_cell = None
                    self._last_dist = None
                    self._stuck = 0
                    self._recent.clear()
                else:
                    # Continue toward target only if still valuable
                    target_val = 0.0
                    for cv in snap.sight:
                        if (cv.x, cv.y) == self._tgt_cell:
                            for a in cv.animals:
                                if not any(
                                    f.species_id == a.species_id
                                    and f.gender == a.gender
                                    for f in self.flock
                                ):
                                    # Skip if already in ark
                                    if not self._is_in_ark(a.species_id, a.gender):
                                        target_val += self._value(
                                            a.species_id, a.gender
                                        )
                            break
                    # Only continue if target still has value
                    if target_val >= 5:
                        return self._move_to(self._tgt_cell)
                    else:
                        # Target no longer valuable
                        self._tgt_cell = None
                        self._stuck = 0

        # Find best animal to target
        best_cell = None
        best_score = -1.0

        for cv in snap.sight:
            tx, ty = cv.x, cv.y
            if (tx, ty) == curr:
                continue
            exp = self._blocked.get((tx, ty))
            if exp is not None and exp > self.turn:
                continue

            # Evaluate each animal in this cell
            for a in cv.animals:
                if any(
                    f.species_id == a.species_id and f.gender == a.gender
                    for f in self.flock
                ):
                    continue
                # Skip animals already in the ark
                if self._is_in_ark(a.species_id, a.gender):
                    continue
                if (a.species_id, a.gender.value) in self._claimed:
                    continue

                animal_val = self._value(a.species_id, a.gender)
                if animal_val <= 0:
                    continue

                dx = tx - self.position[0]
                dy = ty - self.position[1]
                dist = max(1.0, math.hypot(dx, dy))
                score = animal_val / dist

                # Penalize recent cells
                if (tx, ty) in self._recent:
                    score *= 0.5

                # Strong bonus for very close animals (likely obtainable)
                if dist <= 2.0:
                    score *= 1.5
                # Bonus for cells we can reach in 1 turn
                elif dist <= c.MAX_DISTANCE_KM:
                    score *= 1.3

                if score > best_score:
                    best_score = score
                    best_cell = (tx, ty)

        if best_cell is None:
            # No valuable cells, clear history
            if len(self._recent) > 5:
                self._recent.clear()
            return None

        # Pursue any positive value target (be more aggressive)
        if best_score < 1:
            return None

        # Set new target
        self._tgt_cell = best_cell
        self._tgt_score = best_score
        self._tgt_expires = self.turn + 5  # Shorter expiry
        self._lock_until = self.turn + 1  # Minimal lock
        dx = best_cell[0] - self.position[0]
        dy = best_cell[1] - self.position[1]
        self._last_dist = max(0.0, math.hypot(dx, dy))
        self._stuck = 0
        return self._move_to(best_cell)

    # -------- Scoring --------

    def _is_in_ark(self, sid: int, gender) -> bool:
        """Check if this species+gender is already in the ark."""
        from core.animal import Gender

        if gender is None or gender == Gender.Unknown:
            return False
        info = self.ark_status.get(sid)
        if info is None:
            return False
        return info.get(gender, False)

    def _would_complete(self, sid: int, gender) -> bool:
        from core.animal import Gender

        info = self.ark_status.get(sid, {Gender.Male: False, Gender.Female: False})
        if gender == Gender.Male:
            return info[Gender.Female] and not info[Gender.Male]
        if gender == Gender.Female:
            return info[Gender.Male] and not info[Gender.Female]
        return False

    def _value(self, sid: int, gender) -> float:
        from core.animal import Gender

        base = self.rarity.get(sid, 1.0)
        info = self.ark_status.get(sid, {Gender.Male: False, Gender.Female: False})
        if gender is None or gender == Gender.Unknown:
            return base * 50
        # If we already carry this species+gender in flock, make it worthless
        # so pursuit scoring and selection ignore duplicates.
        if any(f.species_id == sid and f.gender == gender for f in self.flock):
            return 0.0
        has_m = info[Gender.Male]
        has_f = info[Gender.Female]
        if (gender == Gender.Male and has_f and not has_m) or (
            gender == Gender.Female and has_m and not has_f
        ):
            boost = 1.0
            if (sid, gender.value ^ 1) in self._seen_carrying:
                boost = 1.2
            return base * 100 * boost
        if not has_m and not has_f:
            return base * 80
        return base * 10

    def _update_ark(self, animals) -> None:
        from core.animal import Gender

        self.ark_status = {}
        for a in animals:
            if a.species_id not in self.ark_status:
                self.ark_status[a.species_id] = {
                    Gender.Male: False,
                    Gender.Female: False,
                }
            if a.gender != Gender.Unknown:
                self.ark_status[a.species_id][a.gender] = True

    # -------- Movement & exploration --------

    def _move_to(self, pos: tuple[float, float]) -> Move:
        nx, ny = self.move_towards(pos[0], pos[1])
        # Clamp to valid field boundaries
        nx = max(0, min(nx, c.X - 1))
        ny = max(0, min(ny, c.Y - 1))

        # When moving to ark, ensure coordinates are floor values
        #        ark_x, ark_y = self.ark_position
        # Check if we're at the ark (within small distance)
        #        if abs(nx - ark_x) < c.EPS and abs(ny - ark_y) < c.EPS:
        #            # Floor the coordinates to match ark position
        #            nx = float(int(ark_x))
        #            ny = float(int(ark_y))

        return Move(nx, ny)

    def _explore(self) -> Move:
        """Explore territory with formation-aware coordination."""
        t = self.territory
        min_x, max_x = t["min_x"], t["max_x"]
        min_y, max_y = t["min_y"], t["max_y"]

        # First 7 days (1008 turns): explore entire field
        # After 7 days: stay within 7-day return distance from ark
        if self.time_elapsed >= 1008:
            # After 7 days, limit exploration to safe return radius
            # Safe distance = 7 days worth of travel minus safety buffer
            max_safe_distance = (c.START_RAIN - 150) * c.MAX_DISTANCE_KM
            ark_x, ark_y = self.ark_position

            # Calculate safe exploration bounds as a circle around ark
            safe_min_x = max(0, int(ark_x - max_safe_distance))
            safe_max_x = min(c.X - 1, int(ark_x + max_safe_distance))
            safe_min_y = max(0, int(ark_y - max_safe_distance))
            safe_max_y = min(c.Y - 1, int(ark_y + max_safe_distance))

            # Intersect with territory bounds
            min_x = max(min_x, safe_min_x)
            max_x = min(max_x, safe_max_x)
            min_y = max(min_y, safe_min_y)
            max_y = min(max_y, safe_max_y)

            # Periodically clear explored set within safe zone
            # This ensures helpers keep exploring rather than idling
            if self.turn % 500 == 0:
                # Keep explored cells outside safe zone marked
                safe_explored = {
                    (x, y)
                    for (x, y) in self._explored
                    if x < safe_min_x
                    or x > safe_max_x
                    or y < safe_min_y
                    or y > safe_max_y
                }
                self._explored = safe_explored

        # Check if too far from ark (beyond safe return distance)
        dist_to_ark = self._dist_to_ark()
        if self.time_elapsed >= 1008:
            max_safe_distance = (c.START_RAIN - 150) * c.MAX_DISTANCE_KM
            if dist_to_ark > max_safe_distance:
                # Too far! Return toward ark immediately
                return self._move_to(self.ark_position)

        # Systematic sweep pattern within territory
        if min_x > max_x or min_y > max_y:
            # Invalid bounds, move to ark
            return self._move_to(self.ark_position)

        width = max(1, max_x - min_x)
        height = max(1, max_y - min_y)

        # Use a continuous sweep pattern that avoids boundary edges
        # Add margin from edges to prevent getting stuck
        margin = min(3, width // 4, height // 4)  # Adaptive margin

        # Constrain sweep to interior
        sweep_min_x = min_x + margin
        sweep_max_x = max_x - margin
        sweep_min_y = min_y + margin
        sweep_max_y = max_y - margin

        # If territory too small, just use original bounds
        if sweep_min_x >= sweep_max_x or sweep_min_y >= sweep_max_y:
            sweep_min_x, sweep_max_x = min_x, max_x
            sweep_min_y, sweep_max_y = min_y, max_y

        sweep_width = max(1, sweep_max_x - sweep_min_x)
        sweep_height = max(1, sweep_max_y - sweep_min_y)

        # Zigzag sweep through interior
        row_height = c.MAX_SIGHT_KM * 2
        num_rows = max(1, int(sweep_height / row_height) + 1)

        # Calculate position in sweep cycle
        cycle_length = max(1, sweep_width * num_rows)
        position_in_cycle = (self.turn + self.id * 100) % cycle_length
        current_row = position_in_cycle // max(1, sweep_width)
        x_offset = position_in_cycle % max(1, sweep_width)

        # Y position (which row)
        y_tgt = sweep_min_y + min(current_row * row_height, sweep_height)

        # X position (progress within row)
        if current_row % 2 == 0:
            # Left to right sweep
            x_tgt = sweep_min_x + x_offset
        else:
            # Right to left sweep
            x_tgt = sweep_max_x - x_offset

        # Clamp to sweep bounds
        x_tgt = max(sweep_min_x, min(x_tgt, sweep_max_x))
        y_tgt = max(sweep_min_y, min(y_tgt, sweep_max_y))

        return self._move_to((x_tgt, y_tgt))

    # -------- Setup helpers --------

    def _compute_waiting_position(self) -> tuple[float, float]:
        """Compute a waiting position near ark for this helper.
        Spreads helpers in a circle to avoid crowding."""
        ark_x, ark_y = self.ark_position

        # Place helpers in a circle around ark
        # Radius of 3-5km keeps them close but spread out
        radius = 4.0
        angle = (2 * math.pi * self.id) / max(1, self.num_helpers)

        wait_x = ark_x + radius * math.cos(angle)
        wait_y = ark_y + radius * math.sin(angle)

        # Clamp to valid field bounds
        wait_x = max(0, min(wait_x, c.X - 1))
        wait_y = max(0, min(wait_y, c.Y - 1))

        return (wait_x, wait_y)

    def _compute_rarity(self) -> dict[int, float]:
        if not self.species_populations:
            return {}
        mx = max(self.species_populations.values())
        out: dict[int, float] = {}
        for letter, pop in self.species_populations.items():
            sid = ord(letter) - ord("a")
            out[sid] = (mx / pop) if pop > 0 else (mx * 10.0)
        return out

    def _compute_territory(self) -> dict[str, int]:
        # Compute grid dimensions to fit all helpers
        # Use ceiling of sqrt to ensure enough cells
        n = max(1, math.ceil(math.sqrt(self.num_helpers)))

        # If n×n is still not enough (shouldn't happen), increase n
        while n * n < self.num_helpers:
            n += 1

        size = c.X / n
        row = self.id // n
        col = self.id % n
        sx = col * size
        sy = row * size

        return {
            "min_x": int(sx),
            "max_x": int(min(sx + size, c.X - 1)),
            "min_y": int(sy),
            "max_y": int(min(sy + size, c.Y - 1)),
            "cx": int(sx + size / 2),
            "cy": int(sy + size / 2),
        }

    # -------- Utils --------

    def _dist_to_ark(self) -> float:
        dx = self.ark_position[0] - self.position[0]
        dy = self.ark_position[1] - self.position[1]
        return math.hypot(dx, dy)
