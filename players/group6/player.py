from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.action import Move, Obtain
from core.views.player_view import Kind
from core.animal import Animal, Gender
import math
from random import random

helper_snapshots: dict[int, HelperSurroundingsSnapshot] = {}
animals_in_flocks: set[Animal] = set()
animals_being_chased: dict[Animal, int] = {}

_PATROL_STRIPS: list[dict] = []

GRID_WIDTH = 1000
GRID_HEIGHT = 1000

# Debug flag: set to True to enable debug print output
DEBUG = False
# communication globals
ark_species_status: dict[int, dict] = {}  # species_id -> {male: bool, female: bool}
reported_animals: dict[
    tuple[int, int], list[tuple[int, int]]
] = {}  # (x,y) -> [(species_id, turn_seen)]
last_noah_broadcast_turn: int = -1

# signal encoding constants
SIGNAL_ANIMAL_SIGHTING = 1
SIGNAL_ARK_STATUS = 2


class Player6(Player):
    def __init__(
        self,
        id: int,
        ark_x: int,
        ark_y: int,
        kind: Kind,
        num_helpers,
        species_populations: dict[str, int],
    ):
        super().__init__(id, ark_x, ark_y, kind, num_helpers, species_populations)

        # store species populations for priority calculations
        self._species_populations = species_populations
        # sreate mapping from species_id to population count
        self._species_id_populations: dict[int, int] = {}
        for species_name, pop in species_populations.items():
            # extract species_id from species name
            if isinstance(species_name, int):
                species_id = species_name
            elif len(species_name) == 1 and species_name.isalpha():
                species_id = ord(species_name.lower()) - ord("a")
            elif "_" in species_name:
                species_id = int(species_name.split("_")[-1])
            else:
                try:
                    species_id = int(species_name)
                except ValueError:
                    # fallback: use hash or skip
                    continue
            self._species_id_populations[species_id] = pop

        # initialize ark status tracking
        global ark_species_status
        if kind == Kind.Noah:
            for species_id in self._species_id_populations.keys():
                ark_species_status[species_id] = {"male": False, "female": False}

        if kind == Kind.Helper:
            self._patrol_spacing = 10
            self._initialize_global_patrol_strips(num_helpers)
            strip_index = self._claim_patrol_strip(id, num_helpers)
            self._setup_patrol_parameters(id, strip_index)

    def _initialize_global_patrol_strips(self, num_helpers: int) -> None:
        global _PATROL_STRIPS
        if len(_PATROL_STRIPS) > 0:
            return

        cols_per_helper = max(1, int(math.ceil(GRID_WIDTH / max(1, num_helpers))))
        num_strips = int(math.ceil(GRID_WIDTH / cols_per_helper))

        for si in range(num_strips):
            x_min = int(si * cols_per_helper)
            x_max = int(min(GRID_WIDTH - 1, (si + 1) * cols_per_helper - 1))
            owner = si if si < num_helpers else None
            _PATROL_STRIPS.append(
                {"x_min": x_min, "x_max": x_max, "owner": owner, "done": False}
            )

    def _claim_patrol_strip(self, helper_id: int, num_helpers: int) -> int:
        global _PATROL_STRIPS
        for i, strip in enumerate(_PATROL_STRIPS):
            if strip["owner"] == helper_id:
                return i
        strip_index = helper_id % len(_PATROL_STRIPS)
        _PATROL_STRIPS[strip_index]["owner"] = helper_id
        return strip_index

    def _setup_patrol_parameters(self, helper_id: int, strip_index: int) -> None:
        strip = _PATROL_STRIPS[strip_index]
        self._patrol_strip_index = strip_index
        self._patrol_x_min = strip["x_min"]
        self._patrol_x_max = strip["x_max"]
        self._patrol_row = (helper_id * self._patrol_spacing) % GRID_HEIGHT
        self._patrol_row_step = self._patrol_spacing
        self._patrol_dir = helper_id % 2 == 0
        self._patrol_active = True

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        self._update_snapshot(snapshot)
        self._update_global_animal_tracking()

        if self.kind == Kind.Noah:
            return self._noah_broadcast()
        else:
            return self._helper_broadcast()

    def _update_snapshot(self, snapshot: HelperSurroundingsSnapshot) -> None:
        self.position = snapshot.position
        self.flock = snapshot.flock
        helper_snapshots[self.id] = snapshot

        # Update ark status if we're at the ark
        if self.kind == Kind.Helper and self._at_ark():
            self._update_ark_status_from_ark(snapshot)

    def _at_ark(self) -> bool:
        """Check if helper is currently at the ark."""
        return (int(self.position[0]), int(self.position[1])) == self.ark_position

    def _update_ark_status_from_ark(self, snapshot: HelperSurroundingsSnapshot) -> None:
        """Update global ark status when helper visits the ark."""
        global ark_species_status
        ark_animals = snapshot.sight.get_cellview_at(*self.ark_position).animals

        for animal in ark_animals:
            if animal.species_id not in ark_species_status:
                ark_species_status[animal.species_id] = {"male": False, "female": False}

            if animal.gender == Gender.Male:
                ark_species_status[animal.species_id]["male"] = True
            elif animal.gender == Gender.Female:
                ark_species_status[animal.species_id]["female"] = True

    def _noah_broadcast(self) -> int:
        """noah broadcasts high-priority species that still need collection."""
        global last_noah_broadcast_turn, ark_species_status

        # Update ark status
        if self.id in helper_snapshots and hasattr(helper_snapshots[self.id], "sight"):
            ark_animals = (
                helper_snapshots[self.id]
                .sight.get_cellview_at(*self.ark_position)
                .animals
            )
            for animal in ark_animals:
                if animal.species_id not in ark_species_status:
                    ark_species_status[animal.species_id] = {
                        "male": False,
                        "female": False,
                    }

                if animal.gender == Gender.Male:
                    ark_species_status[animal.species_id]["male"] = True
                elif animal.gender == Gender.Female:
                    ark_species_status[animal.species_id]["female"] = True

        # Broadcast every 10 turns
        if self.id in helper_snapshots:
            current_turn = helper_snapshots[self.id].time_elapsed
        else:
            return 0

        if current_turn - last_noah_broadcast_turn < 10:
            return 0

        last_noah_broadcast_turn = current_turn

        # Find rarest incomplete species
        incomplete_species = []
        for species_id, population in self._species_id_populations.items():
            status = ark_species_status.get(
                species_id, {"male": False, "female": False}
            )
            if not (status["male"] and status["female"]):
                incomplete_species.append((population, species_id))

        if not incomplete_species:
            return 0

        # Broadcast the rarest incomplete species (lowest population count)
        incomplete_species.sort()
        rarest_species_id = incomplete_species[0][1]

        # Encode: signal type (2 bits) + species_id (6 bits)
        # This allows up to 64 different species
        signal = (SIGNAL_ARK_STATUS << 6) | (rarest_species_id & 0x3F)
        return signal

    def _helper_broadcast(self) -> int:
        """helper broadcasts which species they're currently pursuing or carrying."""
        snapshot = helper_snapshots[self.id]

        # Priority 1: If we have animals in flock, broadcast the rarest one
        if len(self.flock) > 0:
            rarest_in_flock = min(
                self.flock, key=lambda a: self._get_species_priority(a.species_id)
            )
            # Signal: "I'm carrying species X"
            signal = (SIGNAL_ANIMAL_SIGHTING << 6) | (rarest_in_flock.species_id & 0x3F)
            return signal

        # Priority 2: If we're chasing something, broadcast what we're chasing
        for animal, chaser_id in animals_being_chased.items():
            if chaser_id == self.id:
                signal = (SIGNAL_ANIMAL_SIGHTING << 6) | (animal.species_id & 0x3F)
                return signal

        # priority 3: broadcast the most valuable unclaimed animal we can see
        best_animal = None
        best_priority = float("inf")

        for cellview in snapshot.sight:
            for animal in cellview.animals:
                # Skip if already claimed
                if animal in animals_in_flocks or animal in animals_being_chased:
                    continue

                priority = self._get_species_priority(animal.species_id)
                if priority < best_priority:
                    best_priority = priority
                    best_animal = animal

        if best_animal is not None:
            signal = (SIGNAL_ANIMAL_SIGHTING << 6) | (best_animal.species_id & 0x3F)
            return signal

        # Nothing to report
        return 0

    def _get_species_priority(self, species_id: int) -> float:
        """Calculate priority for a species (lower = higher priority)."""
        global ark_species_status

        population = self._species_id_populations.get(species_id, 10)
        status = ark_species_status.get(species_id, {"male": False, "female": False})

        # Highest priority: rare species not yet on ark
        if not status["male"] and not status["female"]:
            priority = population * 0.1
        # Medium priority: incomplete species (need one gender)
        elif not (status["male"] and status["female"]):
            priority = population * 0.5
        # Low priority: complete species
        else:
            priority = population * 10

        # Extra boost if Noah is broadcasting this as priority
        if (
            hasattr(self, "_noah_priority_species")
            and self._noah_priority_species == species_id
        ):
            priority *= 0.5  # Make it even more attractive

        # Slight penalty if other nearby helpers are already pursuing this species
        if hasattr(self, "_other_helpers_pursuing"):
            pursuing_count = sum(
                1
                for s_id in self._other_helpers_pursuing.values()
                if s_id == species_id
            )
            if pursuing_count > 0:
                priority *= 1.0 + 0.2 * pursuing_count

        return priority

    def _update_global_animal_tracking(self) -> None:
        global animals_in_flocks, animals_being_chased
        animals_in_flocks = set()
        for helper_snapshot in helper_snapshots.values():
            animals_in_flocks.update(helper_snapshot.flock)

        # Remove chase assignments for animals now in flocks
        animals_being_chased = {
            animal: helper_id
            for animal, helper_id in animals_being_chased.items()
            if animal not in animals_in_flocks
        }

    def _get_random_move(self) -> tuple[float, float]:
        old_x, old_y = self.position
        dx, dy = random() - 0.5, random() - 0.5

        while not (self.can_move_to(old_x + dx, old_y + dy)):
            dx, dy = random() - 0.5, random() - 0.5

        return old_x + dx, old_y + dy

    def get_action(self, messages) -> Move | Obtain | None:
        if self.kind == Kind.Noah:
            return None

        # Process incoming messages
        self._process_messages(messages)

        if self._should_return_to_ark():
            return self._return_to_ark()

        obtain_action = self._try_obtain_at_current_position()
        if obtain_action:
            return obtain_action

        # Try to chase nearby animals
        chase_action = self._try_chase_nearby_animal()
        if chase_action:
            return chase_action

        return self._patrol_for_animals()

    def _process_messages(self, messages) -> None:
        """Process communication signals from other helpers and Noah."""
        # Track which species other helpers are working on
        if not hasattr(self, "_other_helpers_pursuing"):
            self._other_helpers_pursuing = {}

        for message in messages:
            sender_id = message.from_helper.id
            signal = message.contents

            # Decode signal type (top 2 bits)
            signal_type = signal >> 6
            payload = signal & 0x3F  # Bottom 6 bits

            if signal_type == SIGNAL_ARK_STATUS:
                # Noah is broadcasting a priority species
                priority_species_id = payload
                # Store this as a temporary boost for decision-making
                if not hasattr(self, "_noah_priority_species"):
                    self._noah_priority_species = None
                self._noah_priority_species = priority_species_id

            elif signal_type == SIGNAL_ANIMAL_SIGHTING:
                # Another helper is pursuing/carrying this species
                species_id = payload
                self._other_helpers_pursuing[sender_id] = species_id

    def _should_return_to_ark(self) -> bool:
        return helper_snapshots[self.id].is_raining or self.is_flock_full()

    def _return_to_ark(self) -> Move:
        """Return move action toward the ark."""
        if DEBUG:
            if helper_snapshots[self.id].is_raining:
                print(f"[Helper {self.id}] Rain detected, returning to ark")
            else:
                print(
                    f"[Helper {self.id}] Flock full ({len(self.flock)}/4), returning to ark"
                )
        return Move(*self.move_towards(*self.ark_position))

    def _try_obtain_at_current_position(self) -> Obtain | None:
        if self.is_flock_full():
            return None

        cur_x, cur_y = int(self.position[0]), int(self.position[1])
        cellview = helper_snapshots[self.id].sight.get_cellview_at(cur_x, cur_y)

        unclaimed_animals = self._get_unclaimed_animals(cellview.animals)
        if not unclaimed_animals:
            return None

        # Prioritize by species rarity
        best_animal = min(
            unclaimed_animals, key=lambda a: self._get_species_priority(a.species_id)
        )
        if DEBUG:
            print(
                f"[Helper {self.id}] Obtaining species_{best_animal.species_id} at ({cur_x}, {cur_y}), flock: {len(self.flock)}"
            )
        return Obtain(best_animal)

    def _get_unclaimed_animals(self, animals: set[Animal]) -> set[Animal]:
        global animals_in_flocks, animals_being_chased
        free_animals = animals - animals_in_flocks
        return {a for a in free_animals if a not in animals_being_chased}

    def _try_chase_nearby_animal(self) -> Move | None:
        """Try to chase the closest unclaimed animal in sight."""
        candidates = self._find_chase_candidates()
        if not candidates:
            return None

        # Sort by priority (rarity) first, then distance
        candidates.sort(
            key=lambda x: (self._get_species_priority(x[0].species_id), x[3])
        )
        target_animal, tx, ty, dist = candidates[0]

        if self._is_closest_helper_to(tx, ty, dist):
            animals_being_chased[target_animal] = self.id
            if DEBUG:
                print(
                    f"[Helper {self.id}] Chasing species_{target_animal.species_id} at ({tx}, {ty})"
                )
            return Move(*self.move_towards(tx, ty))

        return None

    def _find_chase_candidates(self) -> list[tuple[Animal, int, int, float]]:
        """Find all unclaimed animals in sight with their positions and distances."""
        candidates = []
        for cellview in helper_snapshots[self.id].sight:
            unclaimed_animals = self._get_unclaimed_animals(cellview.animals)
            if unclaimed_animals:
                dist = math.sqrt(
                    (cellview.x - self.position[0]) ** 2
                    + (cellview.y - self.position[1]) ** 2
                )
                for animal in unclaimed_animals:
                    candidates.append((animal, cellview.x, cellview.y, dist))
        return candidates

    def _is_closest_helper_to(self, x: int, y: int, my_distance: float) -> bool:
        """Check if this helper is the closest to the given position."""
        for other_id, other_snapshot in helper_snapshots.items():
            if other_id == self.id:
                continue

            other_dist = math.sqrt(
                (x - other_snapshot.position[0]) ** 2
                + (y - other_snapshot.position[1]) ** 2
            )

            # Another helper is closer, or same distance but lower ID
            if other_dist < my_distance or (
                other_dist == my_distance and other_id < self.id
            ):
                return False
        return True

    def _patrol_for_animals(self) -> Move:
        """Move to patrol the grid searching for animals."""
        if DEBUG:
            print(
                f"[Helper {self.id}] No animals visible, patrolling from {self.position}"
            )
        target = self._get_patrol_target()
        if target:
            return Move(*self.move_towards(*target))
        return Move(*self._get_random_move())

    def move_in_dir(self) -> tuple[float, float] | None:
        """Compute a target location for patrol movement.

        Returns:
            tuple[float, float] | None: target coordinates, or None if no target
        """
        return self._get_patrol_target()

    def _get_patrol_target(self) -> tuple[float, float] | None:
        """Get the next target position for boustrophedon patrol pattern."""
        if not getattr(self, "_patrol_active", False):
            return None

        cur_x = int(round(self.position[0]))
        cur_y = int(round(self.position[1]))

        # Move back to assigned strip if outside
        if cur_x < self._patrol_x_min:
            return (float(self._patrol_x_min), float(cur_y))
        if cur_x > self._patrol_x_max:
            return (float(self._patrol_x_max), float(cur_y))

        # Calculate row target
        row_y = int(max(0, min(GRID_HEIGHT - 1, self._patrol_row)))
        end_x = self._patrol_x_max if self._patrol_dir else self._patrol_x_min

        # Check if at end of current row - advance to next
        if cur_x == end_x and cur_y == row_y:
            self._advance_to_next_patrol_row()
            # Recalculate after potential reassignment
            if not self._patrol_active:
                return None
            row_y = int(max(0, min(GRID_HEIGHT - 1, self._patrol_row)))
            end_x = self._patrol_x_max if self._patrol_dir else self._patrol_x_min

        return (float(end_x), float(row_y))

    def _advance_to_next_patrol_row(self) -> None:
        """Advance patrol to next row, or reassign to new strip if finished."""
        next_row = self._patrol_row + self._patrol_row_step

        if next_row >= GRID_HEIGHT:
            self._finish_current_strip()
            self._try_reassign_to_unfinished_strip()
        else:
            self._patrol_row = next_row
            self._patrol_dir = not self._patrol_dir

    def _finish_current_strip(self) -> None:
        """Mark current patrol strip as completed."""
        global _PATROL_STRIPS
        _PATROL_STRIPS[self._patrol_strip_index]["done"] = True
        _PATROL_STRIPS[self._patrol_strip_index]["owner"] = None

    def _try_reassign_to_unfinished_strip(self) -> None:
        """Try to claim an unfinished patrol strip, or deactivate if none available."""
        global _PATROL_STRIPS

        for i, strip in enumerate(_PATROL_STRIPS):
            if not strip["done"] and strip["owner"] is None:
                self._assign_to_strip(i)
                return

        # No strips left - deactivate patrol
        self._patrol_active = False

    def _assign_to_strip(self, strip_index: int) -> None:
        """Assign this helper to a specific patrol strip."""
        global _PATROL_STRIPS
        strip = _PATROL_STRIPS[strip_index]

        strip["owner"] = self.id
        self._patrol_strip_index = strip_index
        self._patrol_x_min = strip["x_min"]
        self._patrol_x_max = strip["x_max"]
        self._patrol_row = 0
        self._patrol_dir = strip_index % 2 == 0
        self._patrol_active = True


"""Comments2:
    - priority score, check for needed animals
    - noah speaks every 10 turns, saying who’s rare and incomplete
    - helpers:
        - rarest in flock
        - if chasing an animal
        - rarest unclaimed, not gotten animal
        - ^ called every turn
        -  update status of ark once there as well
"""
