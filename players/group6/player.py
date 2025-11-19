from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.action import Move, Obtain
from core.views.player_view import Kind
from core.animal import Animal
import math
from random import random, choice

helper_snapshots: dict[int, HelperSurroundingsSnapshot] = {}
# Track all animals that are currently in ANY helper's flock
animals_in_flocks: set[Animal] = set()
# Track animals being chased (animal -> helper_id)
animals_being_chased: dict[Animal, int] = {}

# global patrol strips for dynamic reassignment
_PATROL_STRIPS: list[dict] = []

# grid size used for amplitude caps / optional heuristics
GRID_WIDTH = 1000
GRID_HEIGHT = 1000


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

        # Coverage parameters
        self._patrol_spacing = 10  # skip spacing between rows

        # Initialize global patrol strips if first helper
        self._initialize_global_patrol_strips(num_helpers)

        # Assign this helper to a patrol strip
        strip_index = self._claim_patrol_strip(id, num_helpers)
        self._setup_patrol_parameters(id, strip_index)

    def _initialize_global_patrol_strips(self, num_helpers: int) -> None:
        """Create global patrol strips if not already initialized."""
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
        """Find and claim a patrol strip for this helper."""
        global _PATROL_STRIPS

        # Try to find strip already assigned to this ID
        for i, strip in enumerate(_PATROL_STRIPS):
            if strip["owner"] == helper_id:
                return i

        # Otherwise, claim strip based on ID
        strip_index = helper_id % len(_PATROL_STRIPS)
        _PATROL_STRIPS[strip_index]["owner"] = helper_id
        return strip_index

    def _setup_patrol_parameters(self, helper_id: int, strip_index: int) -> None:
        """Initialize patrol parameters for the assigned strip."""
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
        return 0

    def _update_snapshot(self, snapshot: HelperSurroundingsSnapshot) -> None:
        """Store the current snapshot and update position/flock."""
        self.position = snapshot.position
        self.flock = snapshot.flock
        helper_snapshots[self.id] = snapshot

    def _update_global_animal_tracking(self) -> None:
        """Update global tracking of animals in flocks and being chased."""
        global animals_in_flocks, animals_being_chased

        # Rebuild set of all animals currently in any flock
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

        if self._should_return_to_ark():
            return self._return_to_ark()

        # Try to obtain animal at current position
        obtain_action = self._try_obtain_at_current_position()
        if obtain_action:
            return obtain_action

        # Try to chase nearby animals
        chase_action = self._try_chase_nearby_animal()
        if chase_action:
            return chase_action

        # Default: patrol for animals
        return self._patrol_for_animals()

    def _should_return_to_ark(self) -> bool:
        """Check if helper should return to ark (rain or full flock)."""
        return helper_snapshots[self.id].is_raining or self.is_flock_full()

    def _return_to_ark(self) -> Move:
        """Return move action toward the ark."""
        if helper_snapshots[self.id].is_raining:
            print(f"[Helper {self.id}] Rain detected, returning to ark")
        else:
            print(
                f"[Helper {self.id}] Flock full ({len(self.flock)}/4), returning to ark"
            )
        return Move(*self.move_towards(*self.ark_position))

    def _try_obtain_at_current_position(self) -> Obtain | None:
        """Try to obtain an unclaimed animal at the current cell."""
        if self.is_flock_full():
            return None

        cur_x, cur_y = int(self.position[0]), int(self.position[1])
        cellview = helper_snapshots[self.id].sight.get_cellview_at(cur_x, cur_y)

        unclaimed_animals = self._get_unclaimed_animals(cellview.animals)
        if unclaimed_animals:
            random_animal = choice(tuple(unclaimed_animals))
            print(
                f"[Helper {self.id}] Attempting Obtain at ({cur_x}, {cur_y}), flock: {len(self.flock)}"
            )
            return Obtain(random_animal)

        return None

    def _get_unclaimed_animals(self, animals: set[Animal]) -> set[Animal]:
        """Filter animals to only those not in flocks and not being chased."""
        global animals_in_flocks, animals_being_chased
        free_animals = animals - animals_in_flocks
        return {a for a in free_animals if a not in animals_being_chased}

    def _try_chase_nearby_animal(self) -> Move | None:
        """Try to chase the closest unclaimed animal in sight."""
        candidates = self._find_chase_candidates()
        if not candidates:
            return None

        # Sort by distance and pick closest
        candidates.sort(key=lambda x: x[3])
        target_animal, tx, ty, _ = candidates[0]

        # Only claim if this helper is closest to the animal
        if self._is_closest_helper_to(tx, ty, candidates[0][3]):
            animals_being_chased[target_animal] = self.id
            print(f"[Helper {self.id}] Chasing free animal at ({tx}, {ty})")
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
        print(f"[Helper {self.id}] No animals visible, patrolling from {self.position}")
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
