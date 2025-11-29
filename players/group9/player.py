from __future__ import annotations

import math
from math import ceil
from random import random
import core.constants as c
from core.animal import Gender
from typing import Any

from core.action import Action, Move, Obtain, Release
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.cell_view import CellView
from core.views.player_view import Kind


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return (abs(x1 - x2) ** 2 + abs(y1 - y2) ** 2) ** 0.5


class Player9(Player):
    FLOCK_CAPACITY = 4
    # Shared short-lived claims across helpers: {(x,y): (owner_id, ttl)}
    shared_claims: dict[tuple[int, int], tuple[int, int]] = {}
    CLAIM_TTL = 6

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

        self.is_raining = False
        self.hellos_received: list[int] = []
        self.num_helpers = num_helpers

        # Initialize ark_inventory so the linter is happy.
        self.ark_inventory: dict[str, set[str]] = {}

        # --- Communication and Targeting ---
        self.noah_target_species: str | None = None

        # Sort species from rarest to commonest
        self.rarity_order = sorted(
            species_populations.keys(), key=lambda s: species_populations.get(s, 0)
        )

        # Create a mapping for 1-byte messages
        self.int_to_species: dict[int, str] = {
            i + 1: species for i, species in enumerate(self.rarity_order)
        }
        self.species_to_int: dict[str, int] = {
            species: i for i, species in self.int_to_species.items()
        }

        # Each helper gets its own sweep direction (angle) so they fan out.
        # Use (id-1) to get denser packing and add a small deterministic jitter
        if num_helpers > 0:
            idx = (id - 1) % num_helpers
            base = float(idx) / float(num_helpers)
            jitter = ((id * 9973) % 1000) / 1000.0 * 0.05
            self.sweep_angle = 2.0 * math.pi * ((base + jitter) % 1.0)
        else:
            self.sweep_angle = 0.0

        # Assign roles: 0 = sweeper, 1 = cluster hunter, 2 = ark-runner
        r = self.id % 3
        if r == 0:
            self.role = "sweeper"
            self.corridor_lookahead = 3.0
            self.corridor_width = 2.0
        elif r == 1:
            self.role = "cluster"
            self.corridor_lookahead = 0.0
            self.corridor_width = 3.5
            self.cluster_radius = 12.0
        else:
            self.role = "ark_runner"
            self.corridor_lookahead = 1.0
            self.corridor_width = 2.0
            self.ark_radius = 8.0
            self.ark_bonus = 10.0
        # track small local extra-collects (reset at ark)
        self.local_collects = 0

        if self.kind == Kind.Noah:
            print("I am Noah. I will coordinate.")
        else:
            print(f"I am Helper {self.id}. My sweep angle is {self.sweep_angle:.2f}")
        # helper state for simple pick-and-return behavior
        self.stay_turns: int = 0
        self.last_cell = None
        self.last_flock_size = 0
        self.stuck_turns = 0
        # how many adjacent/local extra collects allowed between ark deliveries
        self.max_local_collects = 2
        self.local_collects = 0
        # zigzag state for sweep movement
        self.zigzag_phase = False
        self.zigzag_threshold = 50.0
        self.zigzag_amplitude = 0.8

    # ---------- Core Helper Functions ----------

    def _get_my_cell(self) -> CellView:
        xcell, ycell = tuple(map(int, self.position))
        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} failed to find own cell")
        return self.sight.get_cellview_at(xcell, ycell)

    # --- Robust "un-stuck" function ---
    def _get_random_move(self) -> tuple[float, float]:
        """
        Tries 10 times to find a valid random move.
        If it fails, it tries to move to center, then to ark,
        then stays put. This is to prevent any freezes.
        """
        old_x, old_y = self.position

        # 1. Try 10 random moves
        for _ in range(10):
            dx, dy = random() - 0.5, random() - 0.5
            new_x, new_y = old_x + dx, old_y + dy
            if self.can_move_to(new_x, new_y):
                return new_x, new_y

        # 2. Fallback 1: Try to move to the center
        new_x, new_y = self.move_towards(500.0, 500.0)
        if self.can_move_to(new_x, new_y):
            return new_x, new_y

        # 3. Fallback 2: Try to move to the Ark
        new_x, new_y = self.move_towards(*self.ark_position)
        if self.can_move_to(new_x, new_y):
            return new_x, new_y

        # 4. Fallback 3: Stay put (absolute last resort)
        return old_x, old_y

    # ---------- Coordinated Hunting Logic ----------

    def _find_rarest_needed_species(self) -> str | None:
        """(Noah's logic) Finds the rarest species we don't have 2 of."""
        for species in self.rarity_order:
            if species not in self.ark_inventory:
                return species  # We have none
            if len(self.ark_inventory.get(species, set())) < 2:
                return species  # We only have one gender
        return None  # We have saved all species!

    def _roundtrip_safe(
        self,
        snapshot: HelperSurroundingsSnapshot,
        cell_x: int,
        cell_y: int,
        extra_margin: int = 3,
    ) -> bool:
        # Estimate turns needed to go from ark to cell and back
        dx = (cell_x + 0.5) - self.ark_position[0]
        dy = (cell_y + 0.5) - self.ark_position[1]
        dist = math.hypot(dx, dy)
        turns_out = ceil(dist / c.MAX_DISTANCE_KM)
        available = self._get_available_turns(snapshot)
        return 2 * turns_out + extra_margin <= available

    def _get_available_turns(self, snapshot: HelperSurroundingsSnapshot) -> int:
        # Track rain start turn and compute remaining safe turns
        if snapshot.is_raining and getattr(self, "rain_start_turn", None) is None:
            self.rain_start_turn = snapshot.time_elapsed
        if getattr(self, "rain_start_turn", None) is not None:
            turns_since = snapshot.time_elapsed - self.rain_start_turn
            return max(0, c.START_RAIN - turns_since)
        return max(0, c.MIN_T - snapshot.time_elapsed)

    def _get_best_animal_on_cell(self, cellview: CellView) -> Any | None:
        """(Helper logic) Finds the best animal to Obtain on the current cell."""
        if not cellview.animals:
            return None

        # build set of (species,gender) already in flock to avoid duplicates
        flock_pairs: set[tuple[str, Gender]] = set()
        for a in self.flock:
            try:
                flock_pairs.add((str(a.species_id), a.gender))
            except Exception:
                pass

        # Priority 1: Get the animal Noah wants (if it doesn't duplicate our flock)
        if self.noah_target_species:
            for animal in cellview.animals:
                species_name = str(animal).split(" ")[0]
                # skip species already completed in ark
                if (
                    species_name in self.ark_inventory
                    and len(self.ark_inventory.get(species_name, set())) >= 2
                ):
                    continue
                if species_name == self.noah_target_species:
                    pair = (species_name, animal.gender)
                    if pair not in flock_pairs:
                        return animal

        # Priority 2: Prefer needed species (one gender missing on ark)
        for animal in cellview.animals:
            if animal.gender == Gender.Unknown:
                continue
            s = str(animal.species_id)
            pair = (s, animal.gender)
            if pair in flock_pairs:
                continue
            # skip species already completed in ark
            if s in self.ark_inventory and len(self.ark_inventory.get(s, set())) >= 2:
                continue
            # prefer species not yet paired on ark
            if s not in self.ark_inventory or len(self.ark_inventory.get(s, set())) < 2:
                return animal

        # Priority 3: any animal we don't already carry
        for animal in cellview.animals:
            if animal.gender == Gender.Unknown:
                continue
            pair = (str(animal.species_id), animal.gender)
            if pair in flock_pairs:
                continue
            return animal

        return None

    def _find_best_animal_to_chase(self) -> tuple[int, int] | None:
        """(Helper logic) Finds the best animal to chase in sight."""
        target_cells: list[tuple[float, tuple[int, int]]] = []
        any_cells: list[tuple[float, tuple[int, int]]] = []
        CLUSTER_RADIUS = getattr(self, "cluster_radius", 8.0)
        ARK_PROXIMITY_BONUS = 6.0  # prefer cells nearer the ark

        for cellview in self.sight:
            if not cellview.animals:
                continue

            # skip cells claimed by other helpers
            claim = Player9.shared_claims.get((cellview.x, cellview.y))
            if claim and claim[0] != self.id:
                continue

            dist = distance(*self.position, cellview.x, cellview.y)
            animals_count = len(cellview.animals)

            # Compute local cluster size (animals in neighboring cells within cluster radius)
            local_count = animals_count
            for other in self.sight:
                if other is cellview:
                    continue
                if not getattr(other, "animals", None):
                    continue
                if distance(cellview.x, cellview.y, other.x, other.y) <= CLUSTER_RADIUS:
                    local_count += len(other.animals)

            # Prefer nearby clusters (multiple animals across adjacent cells) strongly
            if local_count >= 2 and dist <= CLUSTER_RADIUS:
                # treat as high-priority by reducing effective distance (moderate)
                target_cells.append((dist * 0.5, (cellview.x, cellview.y)))
                continue
            # Prioritize cells that complete pairs or match Noah's target
            pair_bonus = 0.0
            for animal in cellview.animals:
                try:
                    s = str(animal.species_id)
                except Exception:
                    s = str(animal)
                # skip species already completed in ark
                if (
                    s in self.ark_inventory
                    and len(self.ark_inventory.get(s, set())) >= 2
                ):
                    continue
                has_m = s in self.ark_inventory and "M" in self.ark_inventory.get(
                    s, set()
                )
                has_f = s in self.ark_inventory and "F" in self.ark_inventory.get(
                    s, set()
                )
                if not (has_m and has_f):
                    pair_bonus = max(pair_bonus, 8.0)
                if self.noah_target_species and s == self.noah_target_species:
                    pair_bonus += 4.0

            if pair_bonus > 0.0:
                # apply pair / Noah bonus
                target_cells.append((dist - pair_bonus, (cellview.x, cellview.y)))
                continue

            # apply ark proximity bonus for general cells as a fallback
            ark_dist = distance(
                self.ark_position[0],
                self.ark_position[1],
                cellview.x + 0.5,
                cellview.y + 0.5,
            )
            adj = max(0.0, (100.0 - ark_dist) / 20.0) * ARK_PROXIMITY_BONUS
            any_cells.append((dist - adj, (cellview.x, cellview.y)))

        # Priority 1: Go for the closest cell that has our target or cluster
        if target_cells:
            target_cells.sort(key=lambda x: x[0])
            return target_cells[0][1]

        # Priority 2: No target in sight. Go for the closest *any* animal.
        if any_cells:
            any_cells.sort(key=lambda x: x[0])
            return any_cells[0][1]

        return None

    def _find_animal_to_drop(self) -> Any | None:
        """Find an animal in flock that should be dropped: duplicates or completed pairs."""
        if not self.flock:
            return None

        # Build flock inventory
        flock_inv = {}
        for a in self.flock:
            try:
                s = str(a.species_id)
                g = (
                    "M"
                    if a.gender == Gender.Male
                    else ("F" if a.gender == Gender.Female else None)
                )
                if g:
                    flock_inv.setdefault(s, set()).add(g)
            except Exception:
                pass

        # Find animals that are duplicates or complete pairs already in ark
        for a in self.flock:
            try:
                s = str(a.species_id)
                g = (
                    "M"
                    if a.gender == Gender.Male
                    else ("F" if a.gender == Gender.Female else None)
                )
                if not g:
                    continue
                # If this species is already fully paired in ark, drop any of it
                if s in self.ark_inventory and len(self.ark_inventory[s]) >= 2:
                    return a
                # If we carry both genders of this species, drop one (prefer to keep the one that completes ark pair)
                if s in flock_inv and len(flock_inv[s]) >= 2:
                    # If ark has one gender, keep the missing one, drop the other
                    ark_genders = self.ark_inventory.get(s, set())
                    if len(ark_genders) == 1:
                        missing = "M" if "F" in ark_genders else "F"
                        if g != missing:
                            return a
                    else:
                        # Ark has none or both, drop any duplicate
                        return a
            except Exception:
                pass
        return None

    def _find_complement_in_sight(self) -> tuple[int, int] | None:
        """If we carry animals, look for complementary genders in sight.
        Return (cell_x, cell_y) to move to, or None."""
        if not getattr(self, "flock", None):
            return None
        # build set of species we carry with genders
        carry = {}
        for a in self.flock:
            try:
                s = str(a.species_id)
                carry.setdefault(s, set()).add(a.gender)
            except Exception:
                pass

        # prefer to find complements for carried species first
        for cv in self.sight:
            if not getattr(cv, "animals", None):
                continue
            for a in cv.animals:
                try:
                    s = str(a.species_id)
                except Exception:
                    continue
                genders_here = carry.get(s)
                if not genders_here:
                    continue
                # if we carry only one gender, look for the other
                if Gender.Male in genders_here and a.gender == Gender.Female:
                    return (cv.x, cv.y)
                if Gender.Female in genders_here and a.gender == Gender.Male:
                    return (cv.x, cv.y)

        # as fallback, look for species missing a gender on the ark (completion)
        for cv in self.sight:
            if not getattr(cv, "animals", None):
                continue
            for a in cv.animals:
                try:
                    s = str(a.species_id)
                except Exception:
                    continue
                has_m = s in self.ark_inventory and "M" in self.ark_inventory.get(
                    s, set()
                )
                has_f = s in self.ark_inventory and "F" in self.ark_inventory.get(
                    s, set()
                )
                if not (has_m and has_f):
                    return (cv.x, cv.y)
        return None

    def _animal_value(self, animal: Any) -> float:
        """Heuristic value: rarer species -> higher; completing ark pair gives bonus."""
        try:
            s = str(animal.species_id)
        except Exception:
            s = str(animal)
        # rarer species earlier in rarity_order
        rank = (
            self.rarity_order.index(s)
            if s in self.rarity_order
            else len(self.rarity_order)
        )
        base = max(0.1, (len(self.rarity_order) - rank))
        # completion bonus if ark missing one gender
        has_m = s in self.ark_inventory and "M" in self.ark_inventory.get(s, set())
        has_f = s in self.ark_inventory and "F" in self.ark_inventory.get(s, set())
        completion_bonus = 2.0 if not (has_m and has_f) else 0.0
        return base + completion_bonus

    # ---------- Sweep & Bounce Logic (No Jitter) ----------

    def _get_sweep_move(self) -> tuple[float, float]:
        # Move one unit in the sweep_angle direction (straight-line sweep)
        px, py = self.position
        dx = math.cos(self.sweep_angle)
        dy = math.sin(self.sweep_angle)

        target_x = px + dx
        target_y = py + dy

        # If the next step would go out of bounds, reflect the component and update angle
        reflected = False
        if not (0 <= target_x < c.X):
            dx = -dx
            reflected = True
        if not (0 <= target_y < c.Y):
            dy = -dy
            reflected = True

        if reflected:
            self.sweep_angle = math.atan2(dy, dx)
            target_x = px + dx
            target_y = py + dy

        # Zig-zag: if far from ark, add a lateral offset alternating each call
        dist_ark = distance(px, py, self.ark_position[0], self.ark_position[1])
        if dist_ark >= getattr(self, "zigzag_threshold", 80.0):
            # perpendicular vector
            pdx, pdy = -dy, dx
            # normalize
            plen = math.hypot(pdx, pdy)
            if plen > 0:
                pdx /= plen
                pdy /= plen
                phase = 1.0 if self.zigzag_phase else -1.0
                amp = getattr(self, "zigzag_amplitude", 0.8)
                target_x += pdx * amp * phase
                target_y += pdy * amp * phase
                # flip phase for next call
                self.zigzag_phase = not self.zigzag_phase

        if self.can_move_to(target_x, target_y):
            return target_x, target_y

        # fallback to random move if blocked
        return self._get_random_move()

    def _find_animals_in_corridor(
        self, lookahead: float = 2.0, corridor: float = 1.5
    ) -> tuple[int, int] | None:
        """Find a nearby cell within a forward corridor along sweep direction.
        Returns cell coords (x,y) or None."""
        px, py = self.position
        dx = math.cos(self.sweep_angle)
        dy = math.sin(self.sweep_angle)

        best = None
        best_score = float("inf")

        for cv in getattr(self, "sight", []):
            if not getattr(cv, "animals", None):
                continue
            # skip claimed cells
            claim = Player9.shared_claims.get((cv.x, cv.y))
            if claim and claim[0] != self.id:
                continue
            cx = cv.x + 0.5
            cy = cv.y + 0.5
            vx = cx - px
            vy = cy - py
            forward = vx * dx + vy * dy
            if forward < 0 or forward > lookahead:
                continue
            perp_sq = (vx * vx + vy * vy) - forward * forward
            perp = math.sqrt(max(0.0, perp_sq))
            if perp > corridor:
                continue
            # score: prefer small perp, then small forward
            score = perp * 10.0 + forward
            if score < best_score:
                best_score = score
                best = (cv.x, cv.y)

        return best

    def _find_nearby_animal_cell(self, radius: float = 1.6) -> tuple[int, int] | None:
        """Finds a nearby cell (within radius) that contains animals and is unclaimed."""
        px, py = self.position
        best = None
        best_d = float("inf")
        for cv in getattr(self, "sight", []):
            if not getattr(cv, "animals", None):
                continue
            # skip current cell
            if int(cv.x) == int(px) and int(cv.y) == int(py):
                continue
            claim = Player9.shared_claims.get((cv.x, cv.y))
            if claim and claim[0] != self.id:
                continue
            d = distance(px, py, cv.x, cv.y)
            if d <= radius and d < best_d:
                best_d = d
                best = (cv.x, cv.y)
        return best

    # ---------- MAIN HOOKS (Updated) ----------

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        """
        Called by the simulator for *both* Noah and Helpers.
        Noah broadcasts. Helpers sync.
        """
        if self.kind == Kind.Noah:
            # --- NOAH'S LOGIC ---
            target_species = self._find_rarest_needed_species()
            if target_species:
                msg = self.species_to_int.get(target_species, 0)
                return msg
            else:
                return 0  # 0 = "Get anything"

        else:
            # --- HELPER'S LOGIC ---
            self.position = snapshot.position
            self.flock = snapshot.flock
            self.sight = snapshot.sight
            self.is_raining = snapshot.is_raining
            # store last snapshot for roundtrip safety checks in get_action
            self._last_snapshot = snapshot

            # reset local_collects when at ark
            if int(self.position[0]) == int(self.ark_position[0]) and int(
                self.position[1]
            ) == int(self.ark_position[1]):
                self.local_collects = 0

            # Tick down shared claims TTL (class-level shared_claims)
            expired: list[tuple[int, int]] = []
            for k, v in list(Player9.shared_claims.items()):
                owner, ttl = v
                ttl -= 1
                if ttl <= 0:
                    expired.append(k)
                else:
                    Player9.shared_claims[k] = (owner, ttl)
            for k in expired:
                del Player9.shared_claims[k]
            # Update ark inventory from snapshot if present
            if (
                getattr(snapshot, "ark_view", None) is not None
                and snapshot.ark_view is not None
            ):
                self.ark_inventory = {}
                for a in snapshot.ark_view.animals:
                    try:
                        s = str(a.species_id)
                        g = (
                            "M"
                            if a.gender == Gender.Male
                            else ("F" if a.gender == Gender.Female else None)
                        )
                        if g is None:
                            continue
                        self.ark_inventory.setdefault(s, set()).add(g)
                    except Exception:
                        pass

            # Simple "hello" protocol
            if len(self.hellos_received) == 0:
                msg = 1 << (self.id % 8)
            else:
                msg = 0
                for hello in self.hellos_received:
                    msg |= hello
                self.hellos_received = []

            if not self.is_message_valid(msg):
                msg = msg & 0xFF

            return msg

    def get_action(self, messages: list[Message]) -> Action | None:
        """
        Called by the simulator for *both* Noah and Helpers.
        Noah does nothing. Helpers act.
        """

        if self.kind == Kind.Noah:
            return None  # Noah doesn't move or act

        # --- HELPER'S LOGIC ---

        # 1. Listen for Noah's broadcast
        for msg in messages:
            if msg.from_helper.kind == Kind.Noah:
                self.noah_target_species = self.int_to_species.get(msg.contents)
                break

        # 2. Handle "Hello" messages
        for msg in messages:
            if msg.from_helper.kind == Kind.Helper:
                if 1 << (msg.from_helper.id % 8) == msg.contents:
                    self.hellos_received.append(msg.contents)

        # 3. Decide on an Action

        # Priority 1: Safety / Flood Awareness / Full Inventory
        if self.is_raining:
            # Raining = flood is spreading → get to Ark ASAP
            return Move(*self.move_towards(*self.ark_position))

        # If the game exposes time until flood or similar:
        if hasattr(self, "time_remaining"):
            # If far away from the ark, start returning before the flood kills the helper
            dist_to_ark = distance(*self.position, *self.ark_position)
            if dist_to_ark > 40:
                return Move(*self.move_towards(*self.ark_position))

        # Priority 2: If raining or flock full, return to Ark; otherwise allow local collection
        flock_size = len(self.flock)
        if self.is_raining or flock_size >= self.FLOCK_CAPACITY:
            return Move(*self.move_towards(*self.ark_position))

        # If carrying animals, allow multiple local extra collects before returning.
        if flock_size > 0:
            # try nearby adjacent collects first (up to max allowed)
            if getattr(self, "local_collects", 0) < getattr(
                self, "max_local_collects", 2
            ):
                nearby = self._find_nearby_animal_cell(radius=1.6)
                if nearby:
                    nx, ny = nearby
                    Player9.shared_claims[(nx, ny)] = (self.id, Player9.CLAIM_TTL)
                    return Move(*self.move_towards(nx + 0.5, ny + 0.5))
            # otherwise return to ark
            return Move(*self.move_towards(*self.ark_position))

        # unstuck detection: if we've been on same cell with same flock repeatedly, try random move
        cx, cy = int(self.position[0]), int(self.position[1])
        cellview_current = None
        try:
            if self.sight.cell_is_in_sight(cx, cy):
                cellview_current = self.sight.get_cellview_at(cx, cy)
        except Exception:
            cellview_current = None

        if (
            self.last_cell == (cx, cy)
            and self.last_flock_size == flock_size
            and cellview_current
            and getattr(cellview_current, "animals", None)
        ):
            self.stuck_turns += 1
        else:
            self.stuck_turns = 0
        self.last_cell = (cx, cy)
        self.last_flock_size = flock_size

        if self.stuck_turns >= 3:
            rx, ry = self._get_random_move()
            return Move(rx, ry)

        # Drop unnecessary animals if flock is full
        if len(self.flock) >= self.FLOCK_CAPACITY:
            bad_animal = self._find_animal_to_drop()
            if bad_animal:
                return Release(bad_animal)

        # If we are on the Ark, try to collect animals from the ark cell first, then nearby cells
        at_ark = int(self.position[0]) == int(self.ark_position[0]) and int(
            self.position[1]
        ) == int(self.ark_position[1])
        if at_ark:
            # First, try to obtain a needed animal from the ark cell itself
            cx, cy = int(self.ark_position[0]), int(self.ark_position[1])
            if self.sight.cell_is_in_sight(cx, cy):
                ark_cellview = self.sight.get_cellview_at(cx, cy)
                if ark_cellview.animals:
                    animal_to_get = self._get_best_animal_on_cell(ark_cellview)
                    if animal_to_get:
                        return Obtain(animal_to_get)

            # If no animals in ark cell or none needed, look for nearby visible cells (distance <= 2.5) with animals (exclude ark cell)
            best = None
            best_d = float("inf")
            for cv in self.sight:
                if not getattr(cv, "animals", None):
                    continue
                if int(cv.x) == int(self.ark_position[0]) and int(cv.y) == int(
                    self.ark_position[1]
                ):
                    continue
                dx = (cv.x + 0.5) - self.ark_position[0]
                dy = (cv.y + 0.5) - self.ark_position[1]
                ad = math.hypot(dx, dy)
                if ad <= 2.5 and ad < best_d:
                    best = (cv.x, cv.y)
                    best_d = ad
            if best is not None:
                # move to nearest adjacent animal cell immediately
                tx, ty = best
                return Move(*self.move_towards(tx + 0.5, ty + 0.5))

        # Priority 3: Obtain one animal if on a cell with one (pick-and-return behavior)
        cellview = self._get_my_cell()
        # If empty, always pick one.
        if len(self.flock) == 0 and len(cellview.animals) > 0:
            animal_to_get = self._get_best_animal_on_cell(cellview)
            if animal_to_get:
                self.stay_turns = 0
                return Obtain(animal_to_get)
        # Conditional multi-pick: if we carry less than capacity, allow additional picks on this cell if
        # (a) another valid animal is present on this cell, or
        # (b) roundtrip safety check shows ample margin (>12 turns)
        if len(self.flock) < self.FLOCK_CAPACITY and len(cellview.animals) > 0:
            another = self._get_best_animal_on_cell(cellview)
            if another:
                cond_a = True
            else:
                cond_a = False
            cond_b = False
            if getattr(self, "_last_snapshot", None) is not None:
                try:
                    cond_b = self._roundtrip_safe(
                        self._last_snapshot, cellview.x, cellview.y, extra_margin=12
                    )
                except Exception:
                    cond_b = False
            if (
                (cond_a or cond_b)
                and another
                and getattr(self, "local_collects", 0)
                < getattr(self, "max_local_collects", 2)
            ):
                # mark we've done an extra local collect
                self.local_collects += 1
                return Obtain(another)

        # Priority 4: Chase the "best" animal in sight

        # If carrying animals, prefer complements/needed targets first
        if flock_size > 0:
            comp = self._find_complement_in_sight()
            if comp:
                tx, ty = comp
                # if on same cell, obtain will be handled via cell logic above
                return Move(*self.move_towards(tx + 0.5, ty + 0.5))

            # If there are nearby animal-containing cells (adjacent), go collect them first
            # but limit to a small number of extra local collects to avoid over-roaming
            if getattr(self, "local_collects", 0) < getattr(
                self, "max_local_collects", 1
            ):
                nearby = self._find_nearby_animal_cell(radius=1.6)
                if nearby:
                    nx, ny = nearby
                    Player9.shared_claims[(nx, ny)] = (self.id, Player9.CLAIM_TTL)
                    return Move(*self.move_towards(nx + 0.5, ny + 0.5))

        # Role-specific behaviors before general corridor/chase
        if getattr(self, "role", "sweeper") == "cluster":
            best = None
            best_d = float("inf")
            for cv in self.sight:
                if not getattr(cv, "animals", None):
                    continue
                if len(cv.animals) < 2:
                    continue
                claim = Player9.shared_claims.get((cv.x, cv.y))
                if claim and claim[0] != self.id:
                    continue
                d = distance(*self.position, cv.x, cv.y)
                if d < best_d:
                    best_d = d
                    best = (cv.x, cv.y)
            if best:
                Player9.shared_claims[(best[0], best[1])] = (self.id, Player9.CLAIM_TTL)
                return Move(*self.move_towards(best[0] + 0.5, best[1] + 0.5))

        if getattr(self, "role", "sweeper") == "ark_runner":
            best = None
            best_d = float("inf")
            for cv in self.sight:
                if not getattr(cv, "animals", None):
                    continue
                # prefer cells close to ark
                ad = distance(
                    self.ark_position[0], self.ark_position[1], cv.x + 0.5, cv.y + 0.5
                )
                if ad > getattr(self, "ark_radius", 8.0):
                    continue
                claim = Player9.shared_claims.get((cv.x, cv.y))
                if claim and claim[0] != self.id:
                    continue
                d = distance(*self.position, cv.x, cv.y) - (
                    getattr(self, "ark_bonus", 10.0) * max(0.0, (100.0 - ad) / 20.0)
                )
                if d < best_d:
                    best_d = d
                    best = (cv.x, cv.y)
            if best:
                Player9.shared_claims[(best[0], best[1])] = (self.id, Player9.CLAIM_TTL)
                return Move(*self.move_towards(best[0] + 0.5, best[1] + 0.5))

        # corridor grabbing: use per-helper corridor parameters
        corridor_target = self._find_animals_in_corridor(
            lookahead=self.corridor_lookahead, corridor=self.corridor_width
        )
        if corridor_target and not self.is_raining:
            tx, ty = corridor_target
            # claim this cell for a short time so others avoid it
            Player9.shared_claims[(tx, ty)] = (self.id, Player9.CLAIM_TTL)
            return Move(*self.move_towards(tx + 0.5, ty + 0.5))

        best_animal_pos = self._find_best_animal_to_chase()
        if best_animal_pos:
            bx, by = best_animal_pos
            # smart release: if flock is full, and a clearly better animal exists at target,
            # release the lowest-value carried animal to swap.
            if len(self.flock) >= self.FLOCK_CAPACITY:
                # find the candidate animal on that cell
                candidate = None
                for cv in self.sight:
                    if cv.x == bx and cv.y == by and getattr(cv, "animals", None):
                        candidate = self._get_best_animal_on_cell(cv)
                        break
                if candidate:
                    cand_val = self._animal_value(candidate)
                    # find lowest-value carried animal
                    min_val = float("inf")
                    min_animal = None
                    for a in self.flock:
                        v = self._animal_value(a)
                        if v < min_val:
                            min_val = v
                            min_animal = a
                    if min_animal and cand_val > min_val + 0.5:
                        return Release(min_animal)

            # claim the target and move towards it
            Player9.shared_claims[(bx, by)] = (self.id, Player9.CLAIM_TTL)
            return Move(*self.move_towards(bx + 0.5, by + 0.5))

        # Priority 5: No animals in sight, sweep the grid
        new_x, new_y = self._get_sweep_move()
        return Move(new_x, new_y)
