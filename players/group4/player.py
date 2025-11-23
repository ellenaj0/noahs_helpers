from __future__ import annotations
import math
import random
from typing import Optional

from core.action import Action, Move, Obtain, Release
from core.animal import Animal, Gender
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.cell_view import CellView
from core.views.player_view import Kind

import core.constants as c


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x1 - x2, y1 - y2)


class Player4(Player):
    """Helper implementation that patrols safe regions and coordinates via messages."""

    SAFE_MANHATTAN_LIMIT = c.START_RAIN  # can get back to ark before deadline

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
        """Initialize long-lived state about assignments, priorities, and movement.

        All helpers share the same logic, but each helper caches its assigned region,
        rarity priority table, and local tracking structures (blocked cells, pending
        obtains, etc.) so we can respond deterministically to arena updates.
        """

        # Runtime state refreshed every turn from the arena snapshot.
        self.turn = 0
        self.is_raining = False
        self.sight = None
        self.ark_view = None

        # Helpers are numbered after Noah (id 0), so compute per-helper indices.
        self.helper_index = self.id - 1 if self.kind == Kind.Helper else None
        self.helper_count = max(1, self.num_helpers - 1) if self.num_helpers else 1
        self.region_index = (
            (self.helper_index if self.helper_index is not None else 0)
            if self.kind == Kind.Helper
            else None
        )

        self.assignment_broadcasted = False

        # Movement targets live inside the global safe area and a per-helper slice.
        self.safe_bounds = self._compute_safe_bounds()
        self.region_bounds = self._compute_region_bounds()
        self.patrol_target: Optional[tuple[float, float]] = None
        self.tracking_cell: Optional[tuple[int, int]] = None

        # Pre-compute rarity ranks so greedy selection remains deterministic.
        self.species_priority = self._build_species_priority(species_populations)
        max_pop = (
            max((priority[0] for priority in self.species_priority.values()), default=0)
            + 100
        )
        self.default_priority = (max_pop, 999)
        self.rare_cutoff = (
            min(
                (priority[0] for priority in self.species_priority.values()),
                default=0,
            )
            + 1
        )

        self.species_on_ark: dict[int, set[Gender]] = {}
        self.known_assignments: dict[int, int] = {}
        self.helpers_returning: set[int] = set()
        self.pending_obtain: Optional[Animal] = None
        self.unavailable_animals: set[Animal] = set()
        # Cells that we want to skip until a certain turn because they were contested.
        self.blocked_cells: dict[tuple[int, int], int] = {}
        # Track which species we've already broadcast to avoid redundant messages
        self.broadcasted_species: set[int] = set()
        # Rotating index for broadcasting species on ark
        self.species_broadcast_index = 0

    # === Territory & Priority Helpers ===

    def _build_species_priority(
        self, species_populations: dict[str, int]
    ) -> dict[int, tuple[int, int]]:
        """Convert species population map into sortable priority tuples."""
        priority: dict[int, tuple[int, int]] = {}
        for letter, population in species_populations.items():
            sid = ord(letter) - ord("a")
            priority[sid] = (population, sid)
        return priority

    def _compute_safe_bounds(self) -> tuple[float, float, float, float]:
        """Return the axis-aligned bounding box that fits inside the safe 1008 steps."""
        ax, ay = self.ark_position
        return (
            max(0.0, ax - self.SAFE_MANHATTAN_LIMIT),
            min(float(c.X - 1), ax + self.SAFE_MANHATTAN_LIMIT),
            max(0.0, ay - self.SAFE_MANHATTAN_LIMIT),
            min(float(c.Y - 1), ay + self.SAFE_MANHATTAN_LIMIT),
        )

    def _compute_region_bounds(self) -> Optional[tuple[float, float, float, float]]:
        """Split the safe diamond into square-ish grids and return this helper's slice."""
        if self.kind != Kind.Helper or self.region_index is None:
            return None

        cols = math.ceil(math.sqrt(self.helper_count))
        rows = math.ceil(self.helper_count / cols)
        region_width = (self.safe_bounds[1] - self.safe_bounds[0]) / max(cols, 1)
        region_height = (self.safe_bounds[3] - self.safe_bounds[2]) / max(rows, 1)

        row = self.region_index // cols
        col = self.region_index % cols

        min_x = self.safe_bounds[0] + col * region_width
        max_x = min(self.safe_bounds[0] + (col + 1) * region_width, self.safe_bounds[1])
        min_y = self.safe_bounds[2] + row * region_height
        max_y = min(
            self.safe_bounds[2] + (row + 1) * region_height, self.safe_bounds[3]
        )

        return (min_x, max_x, min_y, max_y)

    def _is_point_safe(self, x: float, y: float) -> bool:
        """Check Manhattan distance constraint back to the Ark."""
        ax, ay = self.ark_position
        return abs(x - ax) + abs(y - ay) <= self.SAFE_MANHATTAN_LIMIT

    # === Messaging & Snapshot Handling ===

    # region snapshot / messaging

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        """Refresh local state from the engine snapshot and decide what to broadcast."""
        self.turn = snapshot.time_elapsed
        self.is_raining = snapshot.is_raining
        self.position = snapshot.position
        self.flock = snapshot.flock
        self.sight = snapshot.sight
        self.ark_view = snapshot.ark_view

        if snapshot.ark_view:
            self._update_ark_species(snapshot.ark_view)

        self._handle_pending_obtain()

        return self._compose_message()

    def _handle_pending_obtain(self) -> None:
        """Detect whether the animal we attempted to obtain actually joined the flock."""
        if self.pending_obtain is None:
            return

        if self.pending_obtain in self.flock:
            self.unavailable_animals.discard(self.pending_obtain)
        else:
            self.unavailable_animals.add(self.pending_obtain)
            position_cell = (int(self.position[0]), int(self.position[1]))
            self.blocked_cells[position_cell] = self.turn + 5
            self.tracking_cell = None
            self.patrol_target = None

        self.pending_obtain = None

    def _update_ark_species(self, ark_view) -> None:
        """Refresh complete Ark species status when at the Ark, ensuring latest information."""
        # When at the Ark, do a complete refresh from the actual Ark view
        # This ensures helpers get the latest status regardless of missed messages
        if self.is_in_ark():
            # Rebuild species_on_ark from scratch based on current Ark state
            self.species_on_ark = {}
            for animal in ark_view.animals:
                if animal.gender == Gender.Unknown:
                    continue
                if animal.species_id not in self.species_on_ark:
                    self.species_on_ark[animal.species_id] = set()
                self.species_on_ark[animal.species_id].add(animal.gender)
            # Reset broadcast tracking so we can broadcast what we see
            # This allows helpers to share the latest complete species
            self.broadcasted_species.clear()
            self.species_broadcast_index = 0
        else:
            # When not at Ark, just update incrementally (from messages or partial views)
            for animal in ark_view.animals:
                if animal.gender == Gender.Unknown:
                    continue
                if animal.species_id not in self.species_on_ark:
                    self.species_on_ark[animal.species_id] = set()
                self.species_on_ark[animal.species_id].add(animal.gender)

    def _is_species_complete_on_ark(self, species_id: int) -> bool:
        """Check if a species has both genders on the Ark."""
        genders = self.species_on_ark.get(species_id, set())
        return Gender.Male in genders and Gender.Female in genders

    def _is_gender_on_ark(self, species_id: int, gender: Gender) -> bool:
        """Check if a specific gender of a species is already on the Ark."""
        if gender == Gender.Unknown:
            return False  # Unknown gender doesn't count as redundant
        genders = self.species_on_ark.get(species_id, set())
        return gender in genders

    def _has_nearby_helpers(self) -> bool:
        """Check if there are other helpers within 5km sight radius."""
        if self.sight is None:
            return False

        for cellview in self.sight:
            # Check if there are any helpers in this cell that aren't us
            if any(helper.id != self.id for helper in cellview.helpers):
                return True

        return False

    def _get_next_species_to_broadcast(self) -> Optional[int]:
        """Get the next species to broadcast that is complete on Ark but not yet broadcast."""
        if not self.ark_view:
            return None

        # Find all complete species that haven't been broadcast yet
        complete_species = [
            sid
            for sid in self.species_on_ark.keys()
            if self._is_species_complete_on_ark(sid)
            and sid not in self.broadcasted_species
        ]

        if not complete_species:
            return None

        # Rotate through species to broadcast them all over time
        # Use turn number to cycle through, ensuring we eventually broadcast all
        if self.species_broadcast_index >= len(complete_species):
            self.species_broadcast_index = 0

        if complete_species:
            species = complete_species[
                self.species_broadcast_index % len(complete_species)
            ]
            self.species_broadcast_index = (self.species_broadcast_index + 1) % max(
                len(complete_species), 1
            )
            return species

        return None

    def _compose_message(self) -> int:
        """Send assignments first, then species-on-ark when at Ark or randomly when helpers nearby."""
        if self.kind != Kind.Helper:
            return 0

        # First message: broadcast region assignment
        if not self.assignment_broadcasted and self.region_index is not None:
            msg = 0x80 | (self.region_index & 0x3F)
            self.assignment_broadcasted = True
            return msg if self.is_message_valid(msg) else (msg & 0xFF)

        # When at the Ark, broadcast species that are complete (both genders present)
        if self.is_in_ark() and self.ark_view:
            species_to_broadcast = self._get_next_species_to_broadcast()
            if species_to_broadcast is not None:
                # Message format: 0x80 | 0x40 | species_id (bits 0-5)
                msg = 0x80 | 0x40 | (species_to_broadcast & 0x3F)
                self.broadcasted_species.add(species_to_broadcast)
                return msg if self.is_message_valid(msg) else (msg & 0xFF)

        # Randomly broadcast species-on-ark info when other helpers are nearby (15% chance)
        # This helps spread information even when helpers are far from the Ark
        if self._has_nearby_helpers() and self.species_on_ark:
            # 15% chance to broadcast a complete species
            if random.random() < 0.15:
                # Find any complete species to broadcast (not just unbroadcast ones)
                complete_species = [
                    sid
                    for sid in self.species_on_ark.keys()
                    if self._is_species_complete_on_ark(sid)
                ]
                if complete_species:
                    # Randomly pick one to broadcast
                    species_to_broadcast = random.choice(complete_species)
                    # Message format: 0x80 | 0x40 | species_id (bits 0-5)
                    msg = 0x80 | 0x40 | (species_to_broadcast & 0x3F)
                    return msg if self.is_message_valid(msg) else (msg & 0xFF)

        # Regular status message: returning flag + flock size
        msg = 0
        if self._should_return_to_ark():
            msg |= 0x40

        msg |= min(len(self.flock), 0x07)

        return msg if self.is_message_valid(msg) else (msg & 0xFF)

    def _process_messages(self, messages: list[Message]) -> None:
        """Decode broadcasts from neighbors and keep track of their assignments/state."""
        for msg in messages:
            # High bit indicates assignment or species-on-ark message
            if msg.contents & 0x80:
                # Bit 6 distinguishes: 0 = assignment, 1 = species-on-ark
                if msg.contents & 0x40:
                    # Species-on-ark message: mark this species as complete
                    species_id = msg.contents & 0x3F
                    # Mark both genders as present since it's complete
                    if species_id not in self.species_on_ark:
                        self.species_on_ark[species_id] = set()
                    self.species_on_ark[species_id].add(Gender.Male)
                    self.species_on_ark[species_id].add(Gender.Female)
                else:
                    # Assignment message
                    self.known_assignments[msg.from_helper.id] = msg.contents & 0x3F
            # Otherwise only the "heading home" bit matters for congestion tracking.
            elif msg.contents & 0x40:
                self.helpers_returning.add(msg.from_helper.id)

    def _release_complete_species_animals(self) -> Optional[Action]:
        """Release animals that are redundant: complete species or duplicate genders on Ark."""
        if not self.flock:
            return None

        # Find animals that are redundant:
        # 1. Species already complete on the Ark (both genders present)
        # 2. Animal's gender already on the Ark (even if species not complete)
        animals_to_release = []
        for animal in self.flock:
            # Check if species is complete
            if self._is_species_complete_on_ark(animal.species_id):
                animals_to_release.append(animal)
            # Check if this specific gender is already on the Ark
            elif self._is_gender_on_ark(animal.species_id, animal.gender):
                animals_to_release.append(animal)

        if not animals_to_release:
            return None

        # Release the worst-scoring animal from redundant animals
        # This frees up space for more valuable animals
        worst_animal = max(animals_to_release, key=lambda a: self._score_animal(a))
        return Release(worst_animal)

    # === Perception, Scoring & Target Selection ===

    # region helper lookups

    def _get_my_cell(self) -> CellView:
        """Return the precise cell view that matches our floating-point coordinates."""
        xcell, ycell = tuple(map(int, self.position))
        if self.sight is None or not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} cannot determine its current cell")

        return self.sight.get_cellview_at(xcell, ycell)

    def _distance_from_ark(self) -> float:
        """Euclidean distance to Ark, helpful for conservative returns."""
        return _distance(*self.position, *self.ark_position)

    def _flock_species_count(self, species_id: int) -> int:
        """Count how many animals in our flock already belong to the given species."""
        return sum(1 for animal in self.flock if animal.species_id == species_id)

    def _species_priority(self, species_id: int) -> tuple[int, int]:
        """Look up rarity tuple or fall back to the default high score."""
        return self.species_priority.get(species_id, self.default_priority)

    def _score_animal(
        self, animal: Animal, assume_unknown_desired: bool = False
    ) -> tuple[int, int, int, int, int, int]:
        """
        Lower scores are better.
        New scoring strongly incentivizes completing species pairs.
        """
        population, sid = self._species_priority(animal.species_id)

        genders_on_ark = self.species_on_ark.get(animal.species_id, set())
        flock_genders = {
            a.gender for a in self.flock if a.species_id == animal.species_id
        }

        # ---- NEW LOGIC: strong bonus for pairing genders ----
        pairing_bonus = 0
        if animal.gender != Gender.Unknown:
            # If Ark has one gender, we want the other very badly
            if len(genders_on_ark) == 1 and animal.gender not in genders_on_ark:
                pairing_bonus -= 3  # big positive incentive

            # If flock has one gender, chase completing that pair too
            if len(flock_genders) == 1 and animal.gender not in flock_genders:
                pairing_bonus -= 2

        # Fallback: unknown gender sometimes acceptable
        if animal.gender == Gender.Unknown and assume_unknown_desired:
            pairing_bonus -= 1

        # Duplicates still penalized
        duplicate_species_penalty = (
            1 if animal.species_id in genders_on_ark.union(flock_genders) else 0
        )
        unknown_penalty = 1 if animal.gender == Gender.Unknown else 0
        duplicates = self._flock_species_count(animal.species_id)

        # Score tuple: lexicographic ordering minimizes this
        return (
            duplicate_species_penalty,  # avoid waste
            population,  # prioritize rare
            -pairing_bonus,  # 🔥 prefer completing pairs first
            duplicates,  # fewer extras
            unknown_penalty,  # gender clarity better
            sid,
        )

    def _best_animal_in_cell(
        self, cellview: CellView, assume_unknown: bool = False
    ) -> tuple[Animal, tuple[int, int, int, int, int, int]] | tuple[None, None]:
        """Return the highest ranked animal in a cell along with its score tuple."""
        best_animal: Optional[Animal] = None
        best_score: Optional[tuple[int, int, int, int, int, int]] = None
        for animal in cellview.animals:
            # Ignore anything already collected or temporarily blocked.
            if animal in self.flock:
                continue
            if animal in self.unavailable_animals:
                continue
            # Skip animals from species that are already complete on the Ark
            if self._is_species_complete_on_ark(animal.species_id):
                continue
            # Skip animals whose gender is already on the Ark (avoid duplicates)
            if self._is_gender_on_ark(animal.species_id, animal.gender):
                continue
            score = self._score_animal(animal, assume_unknown_desired=assume_unknown)
            if best_animal is None or best_score is None or (score < best_score):
                best_animal = animal
                best_score = score

        if best_animal is not None and best_score is not None:
            return (best_animal, best_score)
        return (None, None)

    def _purge_blocked_cells(self) -> None:
        """Remove stale entries so we eventually reconsider cells after timeout."""
        expired = [
            cell for cell, expiry in self.blocked_cells.items() if expiry <= self.turn
        ]
        for cell in expired:
            del self.blocked_cells[cell]

    def _should_return_to_ark(self) -> bool:
        """Decide when to abandon exploration and head back to the Ark."""
        if self.is_flock_full():
            return True
        if self.kind != Kind.Helper:
            return False

        unique_species = {animal.species_id for animal in self.flock}

        if self.is_raining:
            return True

        if len(unique_species) >= 4:
            return True

        if self.is_flock_full() and len(unique_species) == c.MAX_FLOCK_SIZE:
            return True

        return False

    def _pick_new_patrol_target(self) -> None:
        """Select a random waypoint within our assigned region or the safe bounds."""
        if not self.region_bounds:
            self.patrol_target = self._random_point_in_safe_area()
            return

        min_x, max_x, min_y, max_y = self.region_bounds
        for _ in range(10):
            x = random.uniform(min_x, max_x)
            y = random.uniform(min_y, max_y)
            if self._is_point_safe(x, y):
                self.patrol_target = (x, y)
                return

        self.patrol_target = self._random_point_in_safe_area()

    def _random_point_in_safe_area(self) -> tuple[float, float]:
        """Sample a safe coordinate when the region produces no usable destinations."""
        min_x, max_x, min_y, max_y = self.safe_bounds
        for _ in range(20):
            x = random.uniform(min_x, max_x)
            y = random.uniform(min_y, max_y)
            if self._is_point_safe(x, y):
                return (x, y)

        return self.ark_position

    def _update_tracking_cell(self) -> None:
        """Find the best visible cell to chase next, respecting blocked cells."""
        if self.sight is None:
            return

        self._purge_blocked_cells()

        best_cell = None
        best_score = None
        for cellview in self.sight:
            if not cellview.animals:
                continue
            if not self._is_point_safe(cellview.x, cellview.y):
                continue
            if any(helper.id != self.id for helper in cellview.helpers):
                continue

            if (cellview.x, cellview.y) in self.blocked_cells:
                continue
            best_animal, score = self._best_animal_in_cell(
                cellview, assume_unknown=True
            )
            if best_animal is None or score is None:
                continue
            dist = _distance(*self.position, cellview.x, cellview.y)
            # Prefer better animal scores, then the closest option as a tiebreaker.
            candidate_score = (*score, dist)
            if best_cell is None or best_score is None or candidate_score < best_score:
                best_cell = (cellview.x, cellview.y)
                best_score = candidate_score

        if best_cell:
            self.tracking_cell = best_cell

    def _tracking_target_active(self) -> bool:
        """Validate current tracking cell and discard it when conditions change."""
        if not self.tracking_cell:
            return False

        tx, ty = self.tracking_cell
        expiry = self.blocked_cells.get((tx, ty))
        if expiry is not None:
            if expiry > self.turn:
                self.tracking_cell = None
                return False
            del self.blocked_cells[(tx, ty)]

        if not self._is_point_safe(tx, ty):
            self.tracking_cell = None
            return False

        if self.sight and self.sight.cell_is_in_sight(tx, ty):
            cell = self.sight.get_cellview_at(tx, ty)
            if any(helper.id != self.id for helper in cell.helpers):
                self.blocked_cells[(tx, ty)] = self.turn + 5
                self.tracking_cell = None
                return False

            if not cell.animals:
                self.tracking_cell = None
                return False

        return True

    # === Action Selection & Movement ===

    def get_action(self, messages: list[Message]) -> Action | None:
        """Main decision tree: release, obtain, chase, or roam."""
        self._process_messages(messages)

        if self.kind == Kind.Noah:
            return None

        # First priority: release animals from species already complete on the Ark
        # This frees up space immediately when we learn a species is complete
        release_complete_action = self._release_complete_species_animals()
        if release_complete_action:
            return release_complete_action

        my_cell = self._get_my_cell()
        self._prune_unavailable_animals(my_cell)

        if self._should_return_to_ark():
            self.tracking_cell = None
            self.patrol_target = None
            return Move(*self.move_towards(*self.ark_position))

        # When full, eject the least valuable passenger if something better is here.
        release_action = self._maybe_release_for_priority(my_cell)
        if release_action:
            return release_action

        obtain_candidate = self._select_animal_here(my_cell)
        if obtain_candidate:
            self.pending_obtain = obtain_candidate
            return Obtain(obtain_candidate)

        # Otherwise, keep patrolling—either chase a seen cell or wander the region.
        self._update_tracking_cell()
        move_target = self._select_move_target()

        next_pos = self.move_towards(*move_target)
        if _distance(*next_pos, *self.position) < 0.05:
            next_pos = self._random_safe_step()

        return Move(*next_pos)

    def _select_animal_here(self, cellview: CellView) -> Optional[Animal]:
        # If we've already failed an obtain in this cell, DO NOT try again
        cell_coords = (cellview.x, cellview.y)
        if cell_coords in self.blocked_cells:
            return None

        if self.is_flock_full():
            return None

        animal, _ = self._best_animal_in_cell(cellview)
        return animal

    def _prune_unavailable_animals(self, cellview: CellView) -> None:
        """Drop unavailable animals that left the cell so we can reconsider later."""
        if not self.unavailable_animals:
            return
        self.unavailable_animals.intersection_update(cellview.animals)

    def _maybe_release_for_priority(self, cellview: CellView) -> Optional[Action]:
        """Free flock space when a rarer animal is available in the current cell."""
        if not self.is_flock_full():
            return None

        candidate, candidate_score = self._best_animal_in_cell(cellview)
        if candidate is None or candidate_score is None:
            return None

        worst_animal = max(self.flock, key=lambda a: self._score_animal(a))
        if self._score_animal(worst_animal) > candidate_score:
            return Release(worst_animal)

        return None

    def _select_move_target(self) -> tuple[float, float]:
        """Decide which coordinate to move towards this turn."""
        if self._tracking_target_active() and self.tracking_cell:
            return (float(self.tracking_cell[0]), float(self.tracking_cell[1]))

        if (
            self.patrol_target is None
            or _distance(*self.position, *self.patrol_target) < 0.5
        ):
            self._pick_new_patrol_target()

        if self.tracking_cell:
            return (float(self.tracking_cell[0]), float(self.tracking_cell[1]))

        if self.patrol_target:
            return self.patrol_target

        return self.ark_position

    def _random_safe_step(self) -> tuple[float, float]:
        """Fallback jitter to keep helpers moving even when stuck."""
        if self.kind == Kind.Noah:
            return self.position

        # Random-walk inside the legal move radius to shake free from impasses.
        for _ in range(20):
            angle = random.uniform(0, math.tau)
            distance = random.uniform(0.4, c.MAX_DISTANCE_KM * 0.95)
            dx = math.cos(angle) * distance
            dy = math.sin(angle) * distance
            candidate = (self.position[0] + dx, self.position[1] + dy)
            if self.can_move_to(*candidate):
                return candidate

        return self.move_towards(*(self._random_point_in_safe_area()))
