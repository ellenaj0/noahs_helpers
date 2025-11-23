from __future__ import annotations

import math
from math import ceil, hypot
from random import random
from typing import Any

import core.constants as c
from core.action import Action, Move, Obtain, Release
from core.animal import Gender
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculates Euclidean distance."""
    return (abs(x1 - x2) ** 2 + abs(y1 - y2) ** 2) ** 0.5


class Player9(Player):
    """
    Greedy "Cluster-Feed" Strategy with Helper Coordination (v18.4 - Greedy Tweaks):

    - NOAH:
        - Broadcasts the rarest still-needed species (no male+female pair yet).

    - HELPERS:
        - Sync ark contents when anyone sees the ark.
        - Maintain priority:
            1) Species still needed (no full pair), ordered by rarity.
            2) Then other species.
        - Use messages for spatial coordination:
            * Each helper broadcasts the coarse grid sector it is currently in.
            * Helpers prefer to chase animals in sectors not already claimed
              by other helpers.

        - Inventory behavior (now greedier):
            * While carrying animals (but not full), try to fill flock,
              as long as there is enough time to get home (dynamic margin).
            * After returning and unloading, immediately look for nearby
              animals in sight and go for them if any exist.
            * Never leave a good animal on the current cell unused.
            * If no needed species on a cell, grab ANY animal you can.

        - Movement:
            * All moves go through `_get_safe_move_action`.
            * If a move is blocked, fall back to random/scatter moves.
            * When at the Ark and there is time left, try to
              step away (never get stuck sitting on the Ark).
            * Anti-ping-pong logic to sweep away from un-obtainable animals.
            * Smart "wait at ark" logic to prevent wasted steps when
              time is low.
    """

    FLOCK_CAPACITY = 4

    # Coarse sectors for coordination
    SECTORS_X = 10
    SECTORS_Y = 10

    # Shared ark state
    shared_ark_animals: set[tuple[str, Gender]] = set()
    shared_ark_version: int = 0

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
        self.rain_start_turn: int | None = None
        self.forced_return = False
        self.current_snapshot: HelperSurroundingsSnapshot | None = None

        self.ark_inventory: dict[str, set[str]] = {}
        self.ark_animals = set(type(self).shared_ark_animals)
        self.local_ark_version = type(self).shared_ark_version

        # Noah broadcast target
        self.noah_target_species: str | None = None

        # Sector we think we’re in
        self.current_sector: int | None = None

        # Rarity info
        self_species_populations = self.species_populations
        self.rarity_order = sorted(
            self_species_populations.keys(),
            key=lambda s: self_species_populations.get(s, 0),
        )
        self.rarity_map = {species: i for i, species in enumerate(self.rarity_order)}

        # Encoding for species <-> int (for Noah messages)
        self.int_to_species: dict[int, str] = {
            i + 1: species for i, species in enumerate(self.rarity_order)
        }
        self.species_to_int: dict[str, int] = {
            species: i for i, species in self.int_to_species.items()
        }

        # Recomputed after ark sync
        self.personal_priority_species: list[str] = list(self.rarity_order)

        # Simple stuck detection for "spam OBTAIN on same cell" cases
        self.last_cell: tuple[int, int] | None = None
        self.last_flock_size: int = 0
        self.stuck_turns: int = 0

        # Deterministic sweep angle assignment
        if num_helpers > 0:
            idx = id % num_helpers
            self.sweep_angle = 2.0 * math.pi * idx / num_helpers
        else:
            self.sweep_angle = 0.0

        if self.kind == Kind.Noah:
            print("I am Noah. I will coordinate.")
        else:
            print(f"I am Helper {self.id}. My sweep angle is {self.sweep_angle:.2f}")

    # ---------- Sector Helpers for Coordination ----------

    def _sector_for_position(self, x: float, y: float) -> int:
        """Map a continuous position to a coarse sector index (0..SECTORS_X*SECTORS_Y-1)."""
        sx = 0 if c.X <= 0 else int(self.SECTORS_X * x / c.X)
        sy = 0 if c.Y <= 0 else int(self.SECTORS_Y * y / c.Y)

        sx = max(0, min(self.SECTORS_X - 1, sx))
        sy = max(0, min(self.SECTORS_Y - 1, sy))

        return sy * self.SECTORS_X + sx

    def _sector_for_cell(self, cell_x: int, cell_y: int) -> int:
        """Map a grid cell center to a sector index."""
        return self._sector_for_position(cell_x + 0.5, cell_y + 0.5)

    # ---------- Core Helper Functions ----------

    def _get_my_cell(self, snapshot: HelperSurroundingsSnapshot) -> Any | None:
        xcell, ycell = tuple(map(int, self.position))
        if not snapshot.sight.cell_is_in_sight(xcell, ycell):
            return None
        try:
            return snapshot.sight.get_cellview_at(xcell, ycell)
        except Exception:
            return None

    def _is_at_ark(self, snapshot: HelperSurroundingsSnapshot) -> bool:
        current_x, current_y = snapshot.position
        ark_x, ark_y = self.ark_position
        return int(current_x) == int(ark_x) and int(current_y) == int(ark_y)

    def _get_species_rarity(self, species_id: Any) -> float:
        return self.rarity_map.get(str(species_id), float("inf"))

    def _species_has_pair(self, species_id_str: str) -> bool:
        has_male = (species_id_str, Gender.Male) in self.ark_animals
        has_female = (species_id_str, Gender.Female) in self.ark_animals
        return has_male and has_female

    def _is_species_needed(self, species_id: Any) -> bool:
        species_id_str = str(species_id)
        return not self._species_has_pair(species_id_str)

    # ---------- Coordination & Strategy Logic ----------

    def _recompute_personal_priority(self) -> None:
        needed = [s for s in self.rarity_order if self._is_species_needed(s)]
        not_needed = [s for s in self.rarity_order if s not in needed]
        self.personal_priority_species = needed + not_needed

    def _find_rarest_needed_species(self) -> str | None:
        for species in self.rarity_order:
            if self._is_species_needed(species):
                return species
        return None

    # 🟢 GREEDIER VERSION
    def _get_best_animal_on_cell(self, cellview: Any) -> Any | None:
        """
        GREEDY:
        1) Prefer any needed species on this cell.
        2) If none are needed, grab the first obtainable animal (any species).
        """
        if not cellview or not cellview.animals:
            return None

        # First pass: needed animals
        for animal in cellview.animals:
            if animal.gender == Gender.Unknown:
                continue
            if animal in self.flock:
                continue
            species_id_str = str(animal.species_id)
            if self._is_species_needed(species_id_str):
                return animal

        # Second pass: ANY obtainable animal
        for animal in cellview.animals:
            if animal.gender == Gender.Unknown:
                continue
            if animal in self.flock:
                continue
            return animal

        return None

    # 🟢 GREEDIER VERSION
    def _find_best_animal_to_chase(
        self,
        snapshot: HelperSurroundingsSnapshot,
        avoid_sectors: set[int] | None = None,
    ) -> tuple[int, int] | None:
        """
        GREEDY:
        Ignore Noah target + rarity.
        Just:
          - Pick the closest cell with animals.
          - If possible, prefer cells in sectors NOT in avoid_sectors.
        """
        avoid_sectors = avoid_sectors or set()

        my_x, my_y = int(self.position[0]), int(self.position[1])

        best_non_avoid = None
        best_non_avoid_dist = float("inf")

        best_any = None
        best_any_dist = float("inf")

        for cellview in snapshot.sight:
            if not cellview.animals:
                continue

            # Skip our own cell; our own cell is handled earlier.
            if cellview.x == my_x and cellview.y == my_y:
                continue

            dist = distance(*self.position, cellview.x + 0.5, cellview.y + 0.5)
            cell_sector = self._sector_for_cell(cellview.x, cellview.y)
            in_avoid = cell_sector in avoid_sectors

            # Track best overall
            if dist < best_any_dist:
                best_any_dist = dist
                best_any = (cellview.x, cellview.y)

            # Track best NOT in avoid set
            if not in_avoid and dist < best_non_avoid_dist:
                best_non_avoid_dist = dist
                best_non_avoid = (cellview.x, cellview.y)

        # If we found something outside avoid sectors, use that; otherwise, fall back.
        return best_non_avoid or best_any

    def _get_smart_release(self, cellview: Any) -> Action | None:
        """
        If flock is full, see if we can swap a "bad" animal for a better one on this cell.
        """
        if not self.is_flock_full() or not cellview or not cellview.animals:
            return None

        best_on_cell = self._get_best_animal_on_cell(cellview)
        if not best_on_cell:
            return None

        best_species_str = str(best_on_cell.species_id)
        best_needed = self._is_species_needed(best_species_str)
        best_rarity = self._get_species_rarity(best_species_str)

        if not best_needed:
            return None

        worst_in_flock = None
        worst_key = (-1, -1.0)  # (needed_flag, rarity)

        for animal in self.flock:
            species_str = str(animal.species_id)
            needed = self._is_species_needed(species_str)
            rarity = self._get_species_rarity(species_str)
            needed_flag = 0 if needed else 1
            key = (needed_flag, rarity)
            if key > worst_key:
                worst_key = key
                worst_in_flock = animal

        if worst_in_flock:
            worst_species_str = str(worst_in_flock.species_id)
            worst_needed = self._is_species_needed(worst_species_str)
            worst_rarity = self._get_species_rarity(worst_species_str)

            if (not worst_needed) or (worst_rarity > best_rarity):
                print(
                    f"Helper {self.id} releasing {worst_in_flock.species_id} "
                    f"for better needed {best_on_cell.species_id}"
                )
                return Release(worst_in_flock)

        return None

    # ---------- Movement & Safety ----------

    def _get_random_move(self) -> Action | None:
        """
        Robust "un-stuck" move.
        Tries 10 random moves, then center, then (if not at ark) ark, then waits (None).
        """
        old_x, old_y = self.position
        ark_x, ark_y = self.ark_position

        for _ in range(10):
            dx, dy = random() - 0.5, random() - 0.5
            new_x, new_y = old_x + dx, old_y + dy
            if (new_x, new_y) != (old_x, old_y) and self.can_move_to(new_x, new_y):
                return Move(new_x, new_y)

        cx, cy = self.move_towards(500.0, 500.0)
        if (cx, cy) != (old_x, old_y) and self.can_move_to(cx, cy):
            return Move(cx, cy)

        # --- FIX: Do not try to move to ark if already on ark cell ---
        is_on_ark_cell = int(old_x) == int(ark_x) and int(old_y) == int(ark_y)
        if not is_on_ark_cell:
            ax, ay = self.move_towards(ark_x, ark_y)
            if (ax, ay) != (old_x, old_y) and self.can_move_to(ax, ay):
                return Move(ax, ay)
        # --- END FIX ---

        return None

    def _get_safe_move_action(self, target_x: float, target_y: float) -> Action | None:
        new_x, new_y = self.move_towards(target_x, target_y)

        new_x = max(0, min(c.X - 1, new_x))
        new_y = max(0, min(c.Y - 1, new_y))

        if self.can_move_to(new_x, new_y):
            return Move(new_x, new_y)
        else:
            return self._get_random_move()

    def _move_to_ark(self) -> Action | None:
        return self._get_safe_move_action(*self.ark_position)

    def _move_to_cell(self, cell_x: int, cell_y: int) -> Action | None:
        return self._get_safe_move_action(cell_x + 0.5, cell_y + 0.5)

    def _get_sweep_move(self) -> Action | None:
        current_x, current_y = self.position

        dx = math.cos(self.sweep_angle) * c.MAX_DISTANCE_KM * 0.99
        dy = math.sin(self.sweep_angle) * c.MAX_DISTANCE_KM * 0.99

        target_x = current_x + dx
        target_y = current_y + dy

        if not (0 <= target_x < c.X):
            self.sweep_angle = math.pi - self.sweep_angle
        if not (0 <= target_y < c.Y):
            self.sweep_angle = -self.sweep_angle

        dx = math.cos(self.sweep_angle) * c.MAX_DISTANCE_KM * 0.99
        dy = math.sin(self.sweep_angle) * c.MAX_DISTANCE_KM * 0.99

        target_x = current_x + dx
        target_y = current_y + dy

        target_x = max(0, min(c.X - 1, target_x))
        target_y = max(0, min(c.Y - 1, target_y))

        if self.can_move_to(target_x, target_y):
            return Move(target_x, target_y)

        return self._get_random_move()

    # ---------- Time & Ark Sync ----------

    def _get_available_turns(self, snapshot: HelperSurroundingsSnapshot) -> int:
        if snapshot.is_raining and self.rain_start_turn is None:
            self.rain_start_turn = snapshot.time_elapsed

        if self.rain_start_turn is not None:
            turns_since_rain = snapshot.time_elapsed - self.rain_start_turn
            return max(0, c.START_RAIN - turns_since_rain)

        return max(0, c.MIN_T - snapshot.time_elapsed)

    def _roundtrip_safe(
        self,
        snapshot: HelperSurroundingsSnapshot,
        cell_x: int,
        cell_y: int,
        extra_margin: int = 3,
    ) -> bool:
        """
        Returns True if we can go from Ark to (cell_x, cell_y) and back
        before the flood, with an extra safety margin.
        """
        dx = (cell_x + 0.5) - self.ark_position[0]
        dy = (cell_y + 0.5) - self.ark_position[1]
        dist = hypot(dx, dy)

        turns_out = ceil(dist / c.MAX_DISTANCE_KM)
        available_turns = self._get_available_turns(snapshot)

        return 2 * turns_out + extra_margin <= available_turns

    def _sync_ark_information(self, snapshot: HelperSurroundingsSnapshot) -> None:
        cls = type(self)

        if snapshot.ark_view is not None:
            ark_animals = {
                (str(a.species_id), a.gender) for a in snapshot.ark_view.animals
            }
            cls.shared_ark_animals = set(ark_animals)
            cls.shared_ark_version += 1
            self.ark_animals = set(ark_animals)
            self.local_ark_version = cls.shared_ark_version
            self._recompute_personal_priority()
            return

        if self.local_ark_version != cls.shared_ark_version:
            self.ark_animals = set(cls.shared_ark_animals)
            self.local_ark_version = cls.shared_ark_version
            self._recompute_personal_priority()

    # ---------- MAIN HOOKS ----------

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        """
        Observe surroundings and broadcast a message.

        - Noah: broadcast rarest-needed species (encoded as int).
        - Helpers: broadcast their current sector index + 1 (0 reserved).
        """
        self.position = snapshot.position
        self.flock = set(snapshot.flock)
        self.current_snapshot = snapshot

        self.current_sector = self._sector_for_position(
            snapshot.position[0], snapshot.position[1]
        )

        self._sync_ark_information(snapshot)

        # Noah: species recommendation
        if self.kind == Kind.Noah:
            target_species = self._find_rarest_needed_species()
            if target_species:
                msg = self.species_to_int.get(target_species, 0)
                return msg
            return 0

        # Helpers: rain / time
        self.is_raining = snapshot.is_raining
        if self.is_raining and self.rain_start_turn is None:
            self.rain_start_turn = snapshot.time_elapsed

        distance_to_ark = hypot(
            self.position[0] - self.ark_position[0],
            self.position[1] - self.ark_position[1],
        )
        turns_to_return = ceil(distance_to_ark / c.MAX_DISTANCE_KM)
        available_turns = self._get_available_turns(snapshot)

        self.forced_return = turns_to_return + 10 > available_turns

        # --- FIX: Make ForcedReturn consistent with AtArk ---
        if self._is_at_ark(snapshot):
            self.forced_return = False
        # --- END FIX ---

        # Helpers broadcast their sector + 1 (0 reserved)
        return (self.current_sector + 1) if self.current_sector is not None else 0

    def get_action(self, messages: list[Message]) -> Action | None:
        if self.kind == Kind.Noah:
            return None

        snapshot = self.current_snapshot
        if not snapshot:
            return None

        # Ensure stuck-tracking fields exist (in case __init__ wasn't patched)
        if not hasattr(self, "last_cell"):
            self.last_cell: tuple[int, int] | None = None
            self.last_flock_size: int = 0
            self.stuck_turns: int = 0

        # --- Logging setup ---
        my_id = f"H{self.id} [T{snapshot.time_elapsed}]"
        flock_size = len(self.flock)
        pos = f"({self.position[0]:.1f}, {self.position[1]:.1f})"
        print(f"--- {my_id}: STATE ---")
        print(
            f"{my_id}: Pos={pos} | Flock={flock_size}/{self.FLOCK_CAPACITY} | ForcedReturn={self.forced_return}"
        )

        # --- Message decoding ---
        occupied_sectors: set[int] = set()
        for msg in messages:
            if msg.from_helper.kind == Kind.Noah:
                self.noah_target_species = self.int_to_species.get(msg.contents)
            else:
                sector_code = msg.contents
                if sector_code > 0:
                    sector_id = sector_code - 1
                    occupied_sectors.add(sector_id)

        if self.current_sector is not None and self.current_sector in occupied_sectors:
            occupied_sectors.discard(self.current_sector)

        print(
            f"{my_id}: NoahTarget={self.noah_target_species} | OccupiedSectors={occupied_sectors}"
        )

        cellview = self._get_my_cell(snapshot)
        at_ark = self._is_at_ark(snapshot)
        print(f"{my_id}: AtArk={at_ark}")

        # --- Stuck detection (only when NOT at ark) ---
        xcell, ycell = int(self.position[0]), int(self.position[1])
        if (
            not at_ark
            and self.last_cell == (xcell, ycell)
            and self.last_flock_size == flock_size
            and cellview
            and cellview.animals
        ):
            self.stuck_turns += 1
        else:
            if not at_ark:
                self.stuck_turns = 0  # reset when moving or changing flock off-ark

        self.last_cell = (xcell, ycell)
        self.last_flock_size = flock_size

        print(f"{my_id}: StuckTurns={self.stuck_turns}")

        CONSIDER_STUCK_AFTER = 3
        cell_is_stuck = (self.stuck_turns >= CONSIDER_STUCK_AFTER) and (not at_ark)

        # ============================================================
        # 1. AT ARK LOGIC
        # ============================================================
        if at_ark:
            print(f"{my_id}: LOGIC: AT_ARK block.")
            self.forced_return = False

            # Being on the ark is not "stuck" for hunting purposes
            self.stuck_turns = 0

            # IMPORTANT: animals visible on the ark cell are ark animals.
            # We must NOT try to Obtain them or we will spam Obtain forever.
            # So: NEVER Obtain on the ark cell.

            # If time is very low, just stay safely on the ark.
            available_turns = self._get_available_turns(snapshot)
            if available_turns <= 5:
                print(f"{my_id}: AT_ARK: Time low. WAITING on ark.")
                return None

            # Otherwise, look for nearby wild targets to chase.
            print(f"{my_id}: AT_ARK: Looking for nearby targets (greedy).")
            best_animal_pos = self._find_best_animal_to_chase(
                snapshot, avoid_sectors=occupied_sectors
            )
            if best_animal_pos:
                print(f"{my_id}: AT_ARK: Found target at {best_animal_pos}. MOVING.")
                return self._move_to_cell(*best_animal_pos)

            # If no target in sight, optionally wander away if there is enough time.
            MIN_TIME_TO_LEAVE_ARK = 12  # (10 for margin + 2 for buffer)
            print(
                f"{my_id}: AT_ARK: No targets. Turns left: {available_turns}. Need > {MIN_TIME_TO_LEAVE_ARK} to wander."
            )
            if available_turns > MIN_TIME_TO_LEAVE_ARK:
                sweep_move = self._get_sweep_move()
                if sweep_move is not None:
                    print(f"{my_id}: AT_ARK: Sweeping away.")
                    return sweep_move
                rand_move = self._get_random_move()
                if rand_move is not None:
                    print(f"{my_id}: AT_ARK: Random move away.")
                    return rand_move
                print(f"{my_id}: AT_ARK: All moves failed. WAITING.")
            else:
                print(f"{my_id}: AT_ARK: Not enough time to move. WAITING.")
            return None

        # ============================================================
        # 2. NOT AT ARK
        # ============================================================
        print(f"{my_id}: LOGIC: NOT_AT_ARK. Checking current cell.")
        animals_on_cell = bool(cellview and cellview.animals)
        best_to_obtain = None

        # 2a) Safety: forced return overrides everything
        if self.forced_return:
            print(f"{my_id}: NOT_AT_ARK: FORCED RETURN. Moving to Ark.")
            return self._move_to_ark()

        # 2b) FLOCK FULL: maybe swap, then bank
        if self.is_flock_full():
            print(
                f"{my_id}: NOT_AT_ARK: Flock is full. Checking for swap, then returning."
            )
            release_action = self._get_smart_release(cellview)
            if release_action:
                print(f"{my_id}: NOT_AT_ARK: Swapping animal. RELEASING.")
                return release_action
            return self._move_to_ark()

        # 2c) CARRYING SOME ANIMALS (1–3): be score-greedy but allow small cluster grabs
        if flock_size > 0:
            available_turns = self._get_available_turns(snapshot)

            # Free extra grab on current cell (if not stuck)
            if animals_on_cell and not cell_is_stuck:
                best_to_obtain = self._get_best_animal_on_cell(cellview)
                if best_to_obtain:
                    print(
                        f"{my_id}: NOT_AT_ARK: Carrying {flock_size}, free animal on cell. OBTAINING."
                    )
                    return Obtain(best_to_obtain)

            # Try to chase a *very* nearby target if:
            # - within a small radius
            # - plenty of time left
            CLUSTER_RADIUS = 20.0  # tighter radius for "extra greed"
            MIN_TURNS_FOR_EXTRA = 15

            best_animal_pos = self._find_best_animal_to_chase(
                snapshot, avoid_sectors=occupied_sectors
            )
            if best_animal_pos:
                tx, ty = best_animal_pos
                dist = distance(self.position[0], self.position[1], tx + 0.5, ty + 0.5)
                print(
                    f"{my_id}: NOT_AT_ARK: Carrying {flock_size}, nearby target at {best_animal_pos} (dist={dist:.1f}, avail={available_turns})."
                )

                if dist <= CLUSTER_RADIUS and available_turns > MIN_TURNS_FOR_EXTRA:
                    print(
                        f"{my_id}: NOT_AT_ARK: Extra cluster is close and time is safe. CHASING before banking."
                    )
                    return self._move_to_cell(tx, ty)

            # Otherwise, just bank the score.
            print(
                f"{my_id}: NOT_AT_ARK: Carrying {flock_size}. No safe close cluster. RETURNING TO ARK."
            )
            return self._move_to_ark()

        # 2d) EMPTY FLOCK: try to obtain on our cell, unless it's a "stuck" cell.
        if animals_on_cell and not cell_is_stuck:
            best_to_obtain = self._get_best_animal_on_cell(cellview)
            if best_to_obtain:
                print(
                    f"{my_id}: NOT_AT_ARK: EMPTY + found {best_to_obtain.species_id} on my cell. OBTAINING."
                )
                return Obtain(best_to_obtain)

        # 2e) If animals here but we consider this cell stuck → sweep away
        if animals_on_cell and cell_is_stuck:
            print(f"{my_id}: NOT_AT_ARK: Animals here but STUCK. SWEEPING away.")
            return self._get_sweep_move()

        # ============================================================
        # 3. HUNTING LOGIC (ONLY WHEN EMPTY & not stuck)
        # ============================================================
        print(f"{my_id}: LOGIC: HUNT while empty. Looking for targets.")
        best_animal_pos = self._find_best_animal_to_chase(
            snapshot, avoid_sectors=occupied_sectors
        )

        if best_animal_pos:
            print(f"{my_id}: HUNT: Chasing target at {best_animal_pos}. MOVING.")
            return self._move_to_cell(*best_animal_pos)

        # No target in sight: sweep to find something.
        print(f"{my_id}: HUNT: No targets in sight. SWEEPING.")
        return self._get_sweep_move()
