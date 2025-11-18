"""Player5: Advanced strategy with specialization and efficient exploration."""
import math
from typing import Set, Tuple, Optional, List, Dict

from core.action import Action, Move, Obtain, Release
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView
from core.animal import Gender
import core.constants as c

from .constants import SpeciesGender, SAFE_RADIUS_FROM_ARK, MIN_MAP_COORD, MAX_MAP_COORD
from . import specialization as spec
from . import movement as mov
from . import targeting as targ


class Player5(Player):
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

        # Store basic info
        self.species_stats = species_populations
        self.num_helpers = num_helpers

        # Initialize species mapping
        self._initialize_species_mapping()

        # Initialize state
        self.ark_pos = (float(ark_x), float(ark_y))
        self.obtained_species: Set[SpeciesGender] = set()
        self.current_target_pos: Optional[Tuple[float, float]] = None
        self.previous_position: Tuple[float, float] = self.position
        self.animal_target_cell: Optional[CellView] = None
        self.ignore_list: List[int] = []

        # Initialize exploration angle
        if self.id > 0:
            self.base_angle = (2 * math.pi * (self.id - 1)) / (int(num_helpers) - 1)
        else:
            self.base_angle = 0
        self.is_exploring_fan_out = True

        # Initialize specialization using function
        (
            self.is_specialized,
            self.specialization_limit,
            self.specialization_target_species
        ) = spec.assign_specialization(
            self.id, self.num_helpers, self.species_stats, self.species_to_id
        )
        (
            self.to_search_list,
            self.specialization_target_species
        ) = spec.update_to_search_list(
            self.is_specialized,
            self.specialization_target_species,
            self.species_stats,
            self.species_to_id,
            self.obtained_species,
            self.id,
            self.num_helpers
        )

    def _initialize_species_mapping(self):
        """Initialize bidirectional species ID-name mapping."""
        if not hasattr(self, 'id_to_species'):
            sorted_names = sorted(self.species_stats.keys())
            self.id_to_species: Dict[int, str] = {
                i: name for i, name in enumerate(sorted_names)
            }

        self.species_to_id: Dict[str, int] = {
            name: id_val for id_val, name in self.id_to_species.items()
        }

    # Utility methods
    def _get_turns_remaining_until_end(self) -> Optional[int]:
        """Return turns remaining until simulation ends, or None if not raining."""
        if not self.is_raining or self.rain_start_time is None:
            return None

        turns_since_rain = self.time_elapsed - self.rain_start_time
        return c.START_RAIN - turns_since_rain

    def _get_turns_to_reach_ark(
        self, from_pos: Optional[Tuple[float, float]] = None
    ) -> int:
        """Calculate minimum turns needed to reach ark from position."""
        pos = from_pos if from_pos else self.position
        distance = mov.get_distance(pos, self.ark_pos)
        return int(math.ceil(distance / c.MAX_DISTANCE_KM))

    # Core methods
    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot):
        """Update helper state based on current surroundings."""
        self.position = snapshot.position
        self.sight = snapshot.sight

        # Track rain start
        if snapshot.is_raining and not self.is_raining:
            self.rain_start_time = snapshot.time_elapsed

        self.is_raining = snapshot.is_raining
        self.time_elapsed = snapshot.time_elapsed
        self.at_ark = snapshot.ark_view is not None
        self.flock = snapshot.flock.copy()

        if self.kind != Kind.Noah:
            # Update from ark when visible
            if snapshot.ark_view:
                (
                    self.obtained_species,
                    self.is_exploring_fan_out,
                    self.base_angle
                ) = targ.update_obtained_species_from_ark(
                    snapshot.ark_view.animals,
                    self.obtained_species,
                    self.is_specialized,
                    self.time_elapsed,
                    self.id,
                    self.base_angle
                )

                # Handle specialization switching and replenish
                if self.is_specialized and self.time_elapsed > 1000:
                    self.is_specialized = False
                    self.specialization_limit = 0
                    self.specialization_target_species = []
                    self.to_search_list.clear()
                elif self.is_specialized:
                    print(f"Replenish search list for Player: {self.id}")
                    (
                        self.to_search_list,
                        self.specialization_target_species
                    ) = spec.update_to_search_list(
                        self.is_specialized,
                        self.specialization_target_species,
                        self.species_stats,
                        self.species_to_id,
                        self.obtained_species,
                        self.id,
                        self.num_helpers
                    )

            # Update from current flock
            for animal in self.flock:
                if animal.gender != Gender.Unknown:
                    self.obtained_species.add((animal.species_id, animal.gender))

        self.previous_position = self.position

        # Clear target if reached
        if self.animal_target_cell:
            current_x, current_y = int(self.position[0]), int(self.position[1])
            if current_x == self.animal_target_cell.x and current_y == self.animal_target_cell.y:
                self.animal_target_cell = None

        return 0

    def get_action(self, messages: list[Message]) -> Action | None:
        """Determine next action based on current state."""
        # Periodic maintenance
        if self.time_elapsed > 0 and self.time_elapsed % 250 == 0:
            self.ignore_list.clear()

        # Debug output at start
        if self.time_elapsed == 0:
            if self.is_specialized:
                print(f"Helper {self.id} is Specialized (Limit ID:{self.specialization_limit}). "
                      f"Targets: {len(self.to_search_list)}")
            else:
                print(f"Helper {self.id} is Normal.")

        # Noah doesn't act
        if self.kind == Kind.Noah:
            return None

        current_pos = self.position

        # Emergency return if beyond safe radius
        if not mov.is_within_safe_radius(current_pos, self.ark_pos, SAFE_RADIUS_FROM_ARK):
            self.animal_target_cell = None
            self.current_target_pos = None
            move, self.current_target_pos = mov.get_return_move(
                current_pos, self.ark_pos, self.id, direct=True
            )
            return move

        # Handle critical rain urgency
        if self.is_raining:
            action = self._handle_rain_urgency(current_pos)
            if action:
                return action

        # Release internal flock duplicates
        duplicate = self._find_duplicate_in_flock()
        if duplicate:
            self.ignore_list.append(duplicate.species_id)
            self.animal_target_cell = None
            return Release(animal=duplicate)

        # Return if flock is full
        if len(self.flock) >= c.MAX_FLOCK_SIZE:
            move, self.current_target_pos = mov.get_return_move(
                current_pos, self.ark_pos, self.id, direct=True
            )
            return move

        # Try to obtain animals in current cell
        action = self._try_obtain_in_current_cell()
        if action:
            return action

        # Move to targeted animal cell
        if self.animal_target_cell:
            return self._handle_animal_chase(current_pos)

        # Find new animal target
        if len(self.flock) < c.MAX_FLOCK_SIZE:
            new_target_cell = targ.find_needed_animal_in_sight(
                self.sight,
                self.is_specialized,
                self.to_search_list,
                lambda sid, g: spec.is_species_needed(
                    sid, g, self.ignore_list, self.is_specialized,
                    self.to_search_list, self.obtained_species
                ),
                self.position,
                self.ark_pos,
                SAFE_RADIUS_FROM_ARK
            )
            if new_target_cell:
                target_cell_center = (new_target_cell.x + 0.5, new_target_cell.y + 0.5)

                if mov.is_within_safe_radius(target_cell_center, self.ark_pos, SAFE_RADIUS_FROM_ARK):
                    self.animal_target_cell = new_target_cell
                    return mov.get_move_to_target(current_pos, target_cell_center)

        # Handle rain movement logic
        if self.is_raining:
            action = self._handle_rain_movement(current_pos)
            if action:
                return action

        # Return when loaded
        if len(self.flock) >= 3:
            move, self.current_target_pos = mov.get_return_move(
                current_pos, self.ark_pos, self.id, direct=False
            )
            return move

        # Exploration logic
        return self._handle_exploration(current_pos)

    def _find_duplicate_in_flock(self):
        """Find and return a duplicate animal in flock, if any."""
        flock_keys = [(a.species_id, a.gender) for a in self.flock]
        return next(
            (a for a in self.flock if flock_keys.count((a.species_id, a.gender)) > 1),
            None
        )

    def _try_obtain_in_current_cell(self) -> Optional[Obtain]:
        """Try to obtain a needed animal in the current cell."""
        current_cell_x, current_cell_y = int(self.position[0]), int(self.position[1])

        try:
            current_cell_view = self.sight.get_cellview_at(current_cell_x, current_cell_y)
        except Exception:
            return None

        if not current_cell_view or not current_cell_view.animals:
            return None

        for animal in current_cell_view.animals:
            if animal in self.flock:
                continue

            # Check for duplicates
            if animal.gender != Gender.Unknown:
                animal_key = (animal.species_id, animal.gender)

                if animal_key in self.obtained_species:
                    if animal.species_id not in self.ignore_list:
                        self.ignore_list.append(animal.species_id)
                    continue

            # Check if needed
            if spec.is_species_needed(
                animal.species_id, animal.gender, self.ignore_list,
                self.is_specialized, self.to_search_list, self.obtained_species
            ):
                self.animal_target_cell = None
                return Obtain(animal=animal)

        # No animals obtained, clear target
        self.animal_target_cell = None
        return None

    def _handle_animal_chase(self, current_pos: Tuple[float, float]) -> Move:
        """Handle movement towards targeted animal cell."""
        target_cell_center = (
            self.animal_target_cell.x + 0.5,
            self.animal_target_cell.y + 0.5
        )

        if not mov.is_within_safe_radius(target_cell_center, self.ark_pos, SAFE_RADIUS_FROM_ARK):
            self.animal_target_cell = None
            self.current_target_pos = None
            move, self.current_target_pos = mov.get_return_move(
                current_pos, self.ark_pos, self.id, direct=False
            )
            return move

        return mov.get_move_to_target(current_pos, target_cell_center)

    def _handle_rain_urgency(self, current_pos: Tuple[float, float]) -> Optional[Move]:
        """Handle critical rain situations requiring immediate return."""
        turns_remaining = self._get_turns_remaining_until_end()
        if turns_remaining is None:
            return None

        turns_needed = self._get_turns_to_reach_ark()
        time_buffer = turns_remaining - turns_needed

        if time_buffer < 3:
            move, self.current_target_pos = mov.get_return_move(
                current_pos, self.ark_pos, self.id, direct=True
            )
            return move

        return None

    def _handle_rain_movement(self, current_pos: Tuple[float, float]) -> Optional[Move]:
        """Handle non-critical rain movement decisions."""
        turns_remaining = self._get_turns_remaining_until_end()
        if turns_remaining is None:
            return None

        turns_needed = self._get_turns_to_reach_ark()
        time_buffer = turns_remaining - turns_needed
        distance_to_ark = mov.get_distance(current_pos, self.ark_pos)

        # Close to ark with time to spare
        if distance_to_ark < 200 and time_buffer > 200:
            if len(self.flock) >= 3:
                move, self.current_target_pos = mov.get_return_move(
                    current_pos, self.ark_pos, self.id, direct=True
                )
                return move

        # Medium distance with decent time
        elif distance_to_ark < 500 and time_buffer > 100:
            if self.animal_target_cell and len(self.flock) < c.MAX_FLOCK_SIZE:
                target_dist = mov.get_distance(
                    current_pos,
                    (self.animal_target_cell.x + 0.5, self.animal_target_cell.y + 0.5)
                )

                if target_dist >= 15:
                    self.animal_target_cell = None
                    move, self.current_target_pos = mov.get_return_move(
                        current_pos, self.ark_pos, self.id, direct=False
                    )
                    return move
            else:
                move, self.current_target_pos = mov.get_return_move(
                    current_pos, self.ark_pos, self.id, direct=False
                )
                return move

        # Far or no time
        else:
            move, self.current_target_pos = mov.get_return_move(
                current_pos, self.ark_pos, self.id, direct=True
            )
            return move

        return None

    def _handle_exploration(self, current_pos: Tuple[float, float]) -> Move:
        """Handle exploration movement logic."""
        if (self.is_in_ark() or
            self.current_target_pos is None or
            mov.get_distance(current_pos, self.current_target_pos) < c.MAX_DISTANCE_KM):

            if self.is_exploring_fan_out:
                return self._handle_fan_out_exploration(current_pos)
            else:
                move, self.current_target_pos = mov.get_new_random_target(
                    current_pos, self.previous_position, self.ark_pos,
                    SAFE_RADIUS_FROM_ARK, self.current_target_pos
                )
                return move

        # Continue to current target (with safety check)
        if self.current_target_pos and not mov.is_within_safe_radius(
            self.current_target_pos, self.ark_pos, SAFE_RADIUS_FROM_ARK
        ):
            self.current_target_pos = None
            move, self.current_target_pos = mov.get_return_move(
                current_pos, self.ark_pos, self.id, direct=False
            )
            return move

        return mov.get_move_to_target(current_pos, self.current_target_pos)

    def _handle_fan_out_exploration(self, current_pos: Tuple[float, float]) -> Move:
        """Handle fan-out exploration pattern."""
        angle = self.base_angle
        new_x = current_pos[0] + math.cos(angle) * c.MAX_DISTANCE_KM
        new_y = current_pos[1] + math.sin(angle) * c.MAX_DISTANCE_KM

        # Check if next position is valid (within map bounds and safe radius)
        if (not mov.is_within_map_bounds(new_x, new_y) or
            not mov.is_within_safe_radius((new_x, new_y), self.ark_pos, SAFE_RADIUS_FROM_ARK)):
            self.is_exploring_fan_out = False
            move, self.current_target_pos = mov.get_new_random_target(
                current_pos, self.previous_position, self.ark_pos,
                SAFE_RADIUS_FROM_ARK, self.current_target_pos
            )
            return move

        self.current_target_pos = (new_x, new_y)
        return Move(x=new_x, y=new_y)
