from random import random

from core.action import Action, Move, Obtain, Release
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView
from core.animal import Animal, Gender

from .sector_manager import SectorManager


# Constants
TARGET_REACHED_DELTA = 5.0
RAIN_COUNTDOWN_START = 990
CHECKED_ANIMAL_RADIUS = 3
CHECKED_ANIMAL_EXPIRY_TURNS = 50
MAX_RECENT_UPDATES = 4
MAX_ENCODED_SPECIES_ID = 85  # Using mod 3 and // 3 since state_code 0 isn't sent
BASE_PICKUP_PROBABILITY_BOOST = 0.1
OPPOSITE_GENDER_IN_ARK_MULTIPLIER = 5.0
OPPOSITE_GENDER_IN_FLOCK_MULTIPLIER = 3.0
MIN_RARITY_FACTOR = 2.0
RELEASE_DISTANCE_FROM_ARK = 50.0
NO_ANIMAL_ADDED_RETURN_TURNS = 500


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculate Euclidean distance between two points."""
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


class Player8(Player):
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
        self.rain_countdown: int | None = None
        self.ark_view = None
        self.current_turn = 0

        # Sector management
        self.sector_manager = SectorManager(
            self.ark_position,
            self.kind,
            self.num_helpers,
            self.id,
        )
        # Track visited cells (cells that have been in sight)
        self.visited_cells: set[tuple[int, int]] = set()
        self.target_position = self.sector_manager.get_random_position_in_sector(
            self.visited_cells
        )

        # Internal ark state tracking: {species_id: (has_male, has_female)}
        self.ark_state: dict[int, tuple[bool, bool]] = {}
        self.recent_updates: list[tuple[int, int, int]] = []

        # Track animals we've checked for gender (to ignore in adjacent cells)
        self.checked_animals: dict[tuple[int, int, int], int] = {}

        # Track when last animal was added to flock
        self.last_animal_added_turn: int = 0
        self.prev_flock_size: int = 0

        # State for handling rare animal pickup when flock is full
        self.pending_obtain: Animal | None = None

    # Ark state tracking and messaging

    def _get_state_code(self, species_id: int) -> int:
        """Get state code for a species: 0=none, 1=male, 2=female, 3=both."""
        if species_id not in self.ark_state:
            return 0

        has_male, has_female = self.ark_state[species_id]
        if has_male and has_female:
            return 3
        elif has_male:
            return 1
        elif has_female:
            return 2
        return 0

    def _update_ark_state_from_view(self):
        """Update internal ark state from ark_view when at ark."""
        if self.ark_view is None:
            return

        for animal in self.ark_view.animals:
            sid = animal.species_id
            if sid not in self.ark_state:
                self.ark_state[sid] = (False, False)

            has_male, has_female = self.ark_state[sid]

            if animal.gender == Gender.Male:
                has_male = True
            elif animal.gender == Gender.Female:
                has_female = True

            self.ark_state[sid] = (has_male, has_female)

            # Add to recent updates
            state_code = self._get_state_code(sid)
            update = (sid, state_code, self.current_turn)
            if update not in self.recent_updates:
                self.recent_updates.append(update)
                if len(self.recent_updates) > MAX_RECENT_UPDATES:
                    self.recent_updates.pop(0)

    def _decode_state_code(self, state_code: int) -> tuple[bool, bool]:
        """Decode state code into (has_male, has_female)."""
        return (state_code in [1, 3], state_code in [2, 3])

    def _update_ark_state_from_msg(self, msg: int):
        """Update internal ark state from decoded message."""
        if msg == 0:
            return

        # Decode: state_code = (msg % 3) + 1, species_id = msg // 3
        state_code = (msg % 3) + 1  # Map 0-2 back to 1-3
        species_id = msg // 3

        # Decode state
        reported_male, reported_female = self._decode_state_code(state_code)

        # Initialize if needed
        if species_id not in self.ark_state:
            self.ark_state[species_id] = (False, False)

        current_male, current_female = self.ark_state[species_id]

        # Merge reported genders with current state
        current_male = current_male or reported_male
        current_female = current_female or reported_female

        self.ark_state[species_id] = (current_male, current_female)

        # Add to recent updates if we received new information
        if state_code > 0:
            # Get the state code after merging (might be different from reported)
            final_state_code = self._get_state_code(species_id)
            update = (species_id, final_state_code, self.current_turn)
            if update not in self.recent_updates:
                self.recent_updates.append(update)
                if len(self.recent_updates) > MAX_RECENT_UPDATES:
                    self.recent_updates.pop(0)

    def _encode_message(self) -> int:
        """Encode next update to broadcast."""
        if len(self.recent_updates) == 0:
            return 0

        # Cycle through recent updates
        species_id, state_code, _ = self.recent_updates[
            self.current_turn % len(self.recent_updates)
        ]

        # Encode: species_id * 3 + (state_code - 1)
        # Since state_code 0 is never sent, we only use 1-3, which we map to 0-2
        if species_id >= MAX_ENCODED_SPECIES_ID:
            return 0

        # Map state_code 1-3 to 0-2 for encoding
        encoded = species_id * 3 + (state_code - 1)
        if encoded > 255:  # Check if it fits in 1 byte
            return 0

        return encoded

    # Pickup and release logic

    def _get_my_cell(self) -> CellView:
        """Get the cell view for the current position."""
        xcell, ycell = tuple(map(int, self.position))
        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} failed to find own cell")

        return self.sight.get_cellview_at(xcell, ycell)

    def _species_has_both_genders_in_ark(self, species_id: int) -> bool:
        """Check if a species already has both male and female in the ark."""
        if species_id not in self.ark_state:
            return False
        has_male, has_female = self.ark_state[species_id]
        return has_male and has_female

    def _has_opposite_gender_in_ark(self, animal: Animal) -> bool:
        """Check if the opposite gender of this animal is in the ark."""
        if animal.species_id not in self.ark_state:
            return False

        has_male, has_female = self.ark_state[animal.species_id]
        if animal.gender == Gender.Male:
            return has_female
        elif animal.gender == Gender.Female:
            return has_male
        return False

    def _has_opposite_gender_in_flock(self, animal: Animal) -> bool:
        """Check if the opposite gender of this animal is in the flock."""
        for flock_animal in self.flock:
            if flock_animal.species_id == animal.species_id:
                if (
                    animal.gender == Gender.Male
                    and flock_animal.gender == Gender.Female
                ) or (
                    animal.gender == Gender.Female
                    and flock_animal.gender == Gender.Male
                ):
                    return True
        return False

    def _is_animal_no_longer_needed(self, animal: Animal) -> bool:
        """Check if an animal is no longer needed based on current ark state."""
        sid = animal.species_id

        # If species is complete, animal is not needed
        if self._species_has_both_genders_in_ark(sid):
            return True

        # Check if we already have this gender in the ark
        if sid in self.ark_state:
            has_male, has_female = self.ark_state[sid]
            if animal.gender == Gender.Male and has_male:
                return True
            if animal.gender == Gender.Female and has_female:
                return True

        return False

    def _find_animal_to_release(self) -> Animal | None:
        """Find an animal in the flock that should be released because it's no longer needed."""
        for animal in self.flock:
            if self._is_animal_no_longer_needed(animal):
                return animal
        return None

    def _was_animal_checked_nearby(
        self, x: int, y: int, species_id: int, radius: int = CHECKED_ANIMAL_RADIUS
    ) -> bool:
        """Check if we've recently checked this animal's gender in a nearby cell."""
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                # Check Manhattan distance
                if abs(dx) + abs(dy) > radius:
                    continue

                check_x = x + dx
                check_y = y + dy
                key = (check_x, check_y, species_id)

                if key in self.checked_animals:
                    visit_turn = self.checked_animals[key]
                    if (self.current_turn - visit_turn) < CHECKED_ANIMAL_EXPIRY_TURNS:
                        return True
        return False

    def _calculate_pickup_probability(self, animal: Animal) -> float:
        """Calculate probability of picking up an animal."""
        sid = animal.species_id

        # Base probability: inverse of population
        pop = self.species_populations.get(str(sid), 1)
        base_prob = 1.0 / (pop + 1) + BASE_PICKUP_PROBABILITY_BOOST

        # Check if already complete in ark
        if self._species_has_both_genders_in_ark(sid):
            return 0.0

        # Check if already in flock (same gender)
        for flock_animal in self.flock:
            if flock_animal.species_id == sid and flock_animal.gender == animal.gender:
                return 0.0

        # Check if opposite gender exists
        if self._has_opposite_gender_in_ark(animal):
            return base_prob * OPPOSITE_GENDER_IN_ARK_MULTIPLIER
        if self._has_opposite_gender_in_flock(animal):
            return base_prob * OPPOSITE_GENDER_IN_FLOCK_MULTIPLIER

        return base_prob

    def _is_animal_much_rarer(self, animal: Animal) -> bool:
        """Check if an animal is much rarer than animals in current flock."""
        if len(self.flock) == 0:
            return True

        animal_pop = self.species_populations.get(str(animal.species_id), 1)

        min_flock_pop = min(
            self.species_populations.get(str(flock_animal.species_id), 1)
            for flock_animal in self.flock
        )

        return animal_pop < min_flock_pop / MIN_RARITY_FACTOR

    def _has_other_helpers_in_cell(self, cellview: CellView) -> bool:
        """Check if there are other helpers in this cell."""
        return any(h.id != self.id for h in cellview.helpers)

    def _find_best_animal_to_pickup(self) -> Animal | None:
        """Find the best animal to pickup based on probabilities."""
        cellview = self._get_my_cell()
        if len(cellview.animals) == 0:
            return None

        # Ignore animals if another helper is in this cell (50% chance)
        if self._has_other_helpers_in_cell(cellview) and random() < 0.5:
            return None

        # Calculate probabilities for each animal
        candidates = []
        for animal in cellview.animals:
            prob = self._calculate_pickup_probability(animal)
            if prob > 0:
                candidates.append((animal, prob))

        if len(candidates) == 0:
            return None

        # Select based on probability (weighted random)
        total_prob = sum(prob for _, prob in candidates)
        if total_prob == 0:
            return None

        r = random() * total_prob
        cumsum = 0
        for animal, prob in candidates:
            cumsum += prob
            if r <= cumsum:
                return animal

        return candidates[0][0]

    def _find_best_animal_to_chase(self) -> tuple[int, int] | None:
        """Find best desirable animal to chase (highest probability)."""
        best_prob = 0.0
        best_pos = None

        for cellview in self.sight:
            if len(cellview.animals) == 0:
                continue

            if self._has_other_helpers_in_cell(cellview):
                continue

            # Filter for desirable animals
            for animal in cellview.animals:
                if self._species_has_both_genders_in_ark(animal.species_id):
                    continue

                prob = self._calculate_pickup_probability(animal)
                if prob == 0.0:
                    continue

                # Skip if we've checked this animal's gender in a nearby cell
                if animal.gender == Gender.Unknown:
                    if self._was_animal_checked_nearby(
                        cellview.x, cellview.y, animal.species_id
                    ):
                        continue

                if prob > best_prob:
                    best_prob = prob
                    best_pos = (cellview.x, cellview.y)

        return best_pos

    # Movement logic

    def _distance_from_ark(self) -> float:
        """Calculate distance from current position to ark."""
        return distance(*self.position, *self.ark_position)

    def _has_reached_target(self) -> bool:
        """Check if the player has reached the target position."""
        dist = distance(*self.position, *self.target_position)
        return dist <= TARGET_REACHED_DELTA

    def _update_rain_state(self, was_raining: bool):
        """Update rain countdown state."""
        if self.is_raining and not was_raining:
            self.rain_countdown = RAIN_COUNTDOWN_START

        if self.is_raining and self.rain_countdown is not None:
            self.rain_countdown -= 1

    def _mark_animals_as_checked(self):
        """Mark animals in current cell as checked for gender."""
        try:
            xcell, ycell = tuple(map(int, self.position))
            cellview = self._get_my_cell()
            for animal in cellview.animals:
                key = (xcell, ycell, animal.species_id)
                self.checked_animals[key] = self.current_turn
        except Exception:
            # If we can't get cell view, skip marking
            pass

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot):
        """Update state based on surroundings snapshot."""
        self.position = snapshot.position
        self.sight = snapshot.sight
        was_raining = self.is_raining
        self.is_raining = snapshot.is_raining
        self.current_turn = snapshot.time_elapsed

        # Check if flock size increased (animal was added)
        current_flock_size = len(self.flock)
        if current_flock_size > self.prev_flock_size:
            self.last_animal_added_turn = self.current_turn
        self.prev_flock_size = current_flock_size

        self._update_rain_state(was_raining)
        self._mark_animals_as_checked()

        # Track visited cells (cells in sight)
        if self.sight is not None:
            for cellview in self.sight:
                self.visited_cells.add((cellview.x, cellview.y))

        # Update ark state if at ark
        if snapshot.ark_view is not None:
            self.ark_view = snapshot.ark_view
            self._update_ark_state_from_view()
            # Reset counter when at ark (helps update status)
            self.last_animal_added_turn = self.current_turn

        return self._encode_message()

    def _should_head_back_to_ark(self) -> bool:
        """Determine if we should head back to ark due to rain."""
        if not self.is_raining:
            return False

        if self.rain_countdown is None:
            self.rain_countdown = RAIN_COUNTDOWN_START

        if self.rain_countdown <= 0:
            return True

        dist_from_ark = self._distance_from_ark()
        return dist_from_ark >= self.rain_countdown

    def _should_return_due_to_no_progress(self) -> bool:
        """Determine if we should return to ark due to no animal added in X turns."""
        if self.is_in_ark() or len(self.flock) < 3:
            return False  # Already at ark, reset counter
        turns_since_last_add = self.current_turn - self.last_animal_added_turn
        return turns_since_last_add >= NO_ANIMAL_ADDED_RETURN_TURNS

    def _handle_pending_obtain(self) -> Action | None:
        """Handle pending obtain action if applicable."""
        if self.pending_obtain is None:
            return None

        cellview = self._get_my_cell()
        if self.pending_obtain in cellview.animals:
            animal = self.pending_obtain
            self.pending_obtain = None
            return Obtain(animal)

        self.pending_obtain = None
        return None

    def _handle_full_flock(self) -> Action | None:
        """Handle actions when flock is full."""
        # Check pending obtain first
        action = self._handle_pending_obtain()
        if action is not None:
            return action

        # Check if there's a much rarer animal we should pickup
        best_animal = self._find_best_animal_to_pickup()
        if best_animal and self._is_animal_much_rarer(best_animal):
            # Release the least valuable animal first
            worst_animal = max(
                self.flock,
                key=lambda a: self.species_populations.get(str(a.species_id), 1),
            )
            self.pending_obtain = best_animal
            return Release(worst_animal)

        # Clear pending and head back to ark
        self.pending_obtain = None
        return Move(*self.move_towards(*self.ark_position))

    def _update_target_if_needed(self):
        """Update target position if we've reached it or are at ark."""
        if self.is_in_ark():
            self.target_position = self.sector_manager.get_random_position_in_sector(
                self.visited_cells
            )
        elif self._has_reached_target():
            self.target_position = self.sector_manager.get_random_position_in_sector(
                self.visited_cells
            )

    def get_action(self, messages: list[Message]) -> Action | None:
        """Get next action based on current state and messages."""
        # Decode messages and update ark state
        for msg in messages:
            self._update_ark_state_from_msg(msg.contents)

        # Noah shouldn't do anything
        if self.kind == Kind.Noah:
            return None

        # Handle rain: head back if needed
        if self._should_head_back_to_ark():
            return Move(*self.move_towards(*self.ark_position))

        # Return to ark if no animal added in X turns
        if self._should_return_due_to_no_progress():
            return Move(*self.move_towards(*self.ark_position))

        # Release an animal if it's no longer needed (only if far from ark)
        dist_from_ark = self._distance_from_ark()
        if dist_from_ark > RELEASE_DISTANCE_FROM_ARK:
            animal_to_release = self._find_animal_to_release()
            if animal_to_release is not None:
                return Release(animal_to_release)

        # Update target if needed
        self._update_target_if_needed()

        # Handle full flock
        if self.is_flock_full():
            return self._handle_full_flock()

        # Handle pending obtain
        action = self._handle_pending_obtain()
        if action is not None:
            return action

        # Try to pickup an animal if in same cell
        best_animal = self._find_best_animal_to_pickup()
        if best_animal:
            return Obtain(best_animal)

        # If I see any animals, chase the best one
        best_animal = self._find_best_animal_to_chase()
        if best_animal:
            return Move(*self.move_towards(*best_animal))

        # Move towards the sector target position
        return Move(*self.move_towards(*self.target_position))
