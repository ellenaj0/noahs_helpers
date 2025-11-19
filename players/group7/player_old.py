import math
from collections import deque
from core.action import Action, Move, Obtain, Release
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
import core.constants as c


class Player7(Player):
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
        self.my_territory = self.calculate_territory()
        self.priorities = self.calculate_species_priorities()
        self.phase = "explore"
        self.turn_count = 0
        self.is_raining = False
        self.known_animals = {}  # Track animals seen by self and others
        # Track ark contents by species and gender
        self.ark_status = {}
        self.last_snapshot = None  # Store last snapshot for get_action
        # Obtain retry control
        self._intend_obtain = False
        self._blocked_cells: dict[tuple[int, int], int] = {}
        # Rain tracking (helpers have 1008 turns after rain starts)
        self._rain_started_at: int | None = None
        # Sticky pursuit target (cell) chosen from 5km sight
        self._pursuit_target: tuple[int, int] | None = None
        self._pursuit_expires_at: int = 0
        self._pursuit_score: float = -1.0
        self._linger_until: int = 0
        # Oscillation dampers
        self._recent_cells: deque[tuple[int, int]] = deque(maxlen=8)
        self._pursuit_lock_until: int = 0
        self._pursuit_last_dist: float | None = None
        self._pursuit_stuck_count: int = 0

    def calculate_territory(self):
        """Divide the map into territories for each helper"""
        grid_size = 1000
        num_per_side = max(1, int(math.sqrt(self.num_helpers)))
        sector_size = grid_size / num_per_side

        sector_x = (self.id % num_per_side) * sector_size
        sector_y = (self.id // num_per_side) * sector_size

        return {
            "min_x": int(sector_x),
            "max_x": int(min(sector_x + sector_size, grid_size - 1)),
            "min_y": int(sector_y),
            "max_y": int(min(sector_y + sector_size, grid_size - 1)),
            "center_x": int(sector_x + sector_size / 2),
            "center_y": int(sector_y + sector_size / 2),
        }

    def calculate_species_priorities(self):
        """Map species_id (int) -> priority (rarer = higher)."""
        if not self.species_populations:
            return {}

        max_pop = max(self.species_populations.values())
        priorities: dict[int, float] = {}

        # species_populations keys are letters 'a', 'b', ... map to ids 0,1,...
        for letter, population in self.species_populations.items():
            species_id = ord(letter) - ord("a")
            # Avoid div by zero; if population is 0, treat as very high
            priorities[species_id] = (
                (max_pop / population) if population > 0 else (max_pop * 10.0)
            )

        return priorities

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        """Check surroundings and encode a message"""
        self.last_snapshot = snapshot  # Store for use in get_action
        self.update_state(snapshot)
        return self.encode_message()

    def update_state(self, snapshot: HelperSurroundingsSnapshot):
        """Update internal state based on surroundings"""
        self.turn_count += 1

        # Update is_raining from snapshot
        self.is_raining = snapshot.is_raining
        if self.is_raining and self._rain_started_at is None:
            # Use global time elapsed for precise return window tracking
            self._rain_started_at = snapshot.time_elapsed

        # Keep our internal state in sync with the engine
        # Position and flock in the Engine are held on PlayerInfo;
        # snapshots provide the authoritative values each turn.
        self.position = snapshot.position
        self._recent_cells.append((int(self.position[0]), int(self.position[1])))
        prev_size = len(self.flock)
        # Use a copy to avoid accidental mutation across frames
        self.flock = snapshot.flock.copy()

        # Expire blocked cells
        to_delete = [
            cell for cell, exp in self._blocked_cells.items() if exp <= self.turn_count
        ]
        for cell in to_delete:
            del self._blocked_cells[cell]

        # If we intended to obtain last turn but flock size didn't grow,
        # likely tried to obtain a shepherded animal; block this cell briefly.
        if self._intend_obtain and len(self.flock) <= prev_size:
            cx, cy = int(self.position[0]), int(self.position[1])
            self._blocked_cells[(cx, cy)] = self.turn_count + 5
        # If we successfully obtained (flock grew), linger here to harvest
        if self._intend_obtain and len(self.flock) > prev_size:
            self._linger_until = self.turn_count + 2
        self._intend_obtain = False

        # Update ark status if we can see it
        if snapshot.ark_view:
            self.update_ark_status(snapshot.ark_view.animals)

        # Update known animals in sight
        # Sight is an iterable of CellView objects, each with animals
        if snapshot.sight:
            for cell_view in snapshot.sight:
                for animal in cell_view.animals:
                    # Animals are in cells at (cell_view.x, cell_view.y)
                    key = (cell_view.x, cell_view.y, animal.species_id)
                    self.known_animals[key] = {
                        "species_id": animal.species_id,
                        "gender": animal.gender,
                        "position": (cell_view.x, cell_view.y),
                        "turn_seen": self.turn_count,
                    }

    def update_ark_status(self, ark_animals):
        """Update what species/genders are already on the ark"""
        from core.animal import Gender

        self.ark_status = {}
        for animal in ark_animals:
            if animal.species_id not in self.ark_status:
                self.ark_status[animal.species_id] = {
                    Gender.Male: False,
                    Gender.Female: False,
                }
            if animal.gender != Gender.Unknown:
                self.ark_status[animal.species_id][animal.gender] = True

    def encode_message(self) -> int:
        """Encode important information into 1 byte (8 bits)"""
        from core.animal import Gender
        # Simple encoding scheme:
        # Bits 0-4: Species ID (up to 32 species)
        # Bit 5: Gender (0=Male, 1=Female)
        # Bit 6: Has animal (1) or just spotted (0)
        # Bit 7: High priority flag

        if not self.flock:
            return 0  # No important message

        # Encode the highest priority animal in our flock
        highest_priority_animal = max(
            self.flock, key=lambda a: self.get_animal_value(a.species_id, a.gender)
        )

        species_id = highest_priority_animal.species_id

        message = species_id & 0x1F  # 5 bits for species
        if highest_priority_animal.gender == Gender.Female:
            message |= 1 << 5
        message |= 1 << 6  # We have the animal
        message |= (1 << 7) if self.priorities.get(species_id, 0) > 1.5 else 0

        return message

    def get_action(self, messages: list[Message]) -> Action | None:
        """Decide the next action based on current state"""
        # Noah doesn't move or take actions
        if self.kind == Kind.Noah:
            return None

        self.process_messages(messages)

        # Phase 1: Return to ark if raining or time to return
        if self.phase == "return" or self.should_return_to_ark():
            self.phase = "return"
            if self.at_ark():
                return None  # We're already at the ark
            return self.move_towards_ark()

        # Phase 2: Return to ark if flock is full or should offload
        if len(self.flock) >= 4 or (len(self.flock) > 0 and self.should_offload()):
            if self.at_ark():
                return None  # Unload happens automatically
            return self.move_towards_ark()

        # Phase 3a: Try to obtain animals in current cell first, and linger
        # a couple turns after success to keep harvesting.
        if self._linger_until > self.turn_count:
            target = self.find_best_animal_in_cell(self.last_snapshot)
            if target:
                self._intend_obtain = True
                return Obtain(target)

        # Phase 3b: Evaluate visible completer vs current cell value
        comp_info = self._find_visible_completer_outside_cell_info()
        current_best = self._best_value_in_current_cell(self.last_snapshot)
        if comp_info is not None:
            comp_pos, comp_val, _comp_dist = comp_info
            # Only chase if significantly better than staying
            if comp_val > current_best * 1.5:
                if self.is_flock_full():
                    to_release = self._choose_lowest_value_in_flock()
                    if to_release is not None:
                        return Release(to_release)
                return self.move_towards_position(comp_pos)

        # Phase 3c: Try to obtain animals in current cell
        target = self.find_best_animal_in_cell(self.last_snapshot)
        if target:
            # If flock full, see if target completes a species and is worth
            # releasing our lowest value animal to make space.
            if self.is_flock_full():
                to_release = self._choose_release_for_target(target)
                if to_release is not None:
                    return Release(to_release)
                # else we cannot/should not release; fall through to movement
            else:
                self._intend_obtain = True
                return Obtain(target)

        # Phase 4: Move toward highest value target animal
        target_animal = self.find_highest_value_target()
        if target_animal:
            return self.move_towards_position(target_animal["position"])

        # Phase 4b: Pursue best cell in 5km sight (sticky for a few turns)
        move = self._pursue_best_cell()
        if move is not None:
            return move

        # Phase 5: Explore territory (even if at ark with empty flock)
        return self.explore_territory()

    def process_messages(self, messages: list[Message]):
        """Process messages from other helpers"""
        # Decode message (currently not used, but available for coordination)
        pass

    def should_return_to_ark(self) -> bool:
        """Determine if it's time to return to the ark"""
        # If raining, we have c.START_RAIN turns to get back
        if self.is_raining and self._rain_started_at is not None:
            # Rough ETA in turns using 0.99 step scaled as 1.0
            eta = int(math.ceil(self.distance_to_ark() / c.MAX_DISTANCE_KM))
            turns_since_rain = self.last_snapshot.time_elapsed - self._rain_started_at
            time_left = c.START_RAIN - turns_since_rain
            # 20% safety buffer
            return eta * 1.2 >= time_left

        # Fallback: very conservative late-game return
        distance = self.distance_to_ark()
        if self.turn_count > 1000 and distance > 200:
            return True

        return False

    def should_offload(self) -> bool:
        """Determine if we should return to ark to offload"""
        if len(self.flock) >= 4:
            return True

        # If we have high-value animals and flock is 75% full
        if len(self.flock) >= 3:
            high_value_count = sum(
                1
                for animal in self.flock
                if self.get_animal_value(animal.species_id, animal.gender) >= 90
            )
            return high_value_count >= 2

        return False

    def find_best_animal_in_cell(self, snapshot: HelperSurroundingsSnapshot | None):
        """Find the best animal to obtain in our current cell"""
        if not snapshot or not snapshot.sight:
            return None

        # Get the cell we're currently in
        current_x = int(snapshot.position[0])
        current_y = int(snapshot.position[1])

        # If this cell is blocked (recent failed obtains), skip obtaining here
        expiry = self._blocked_cells.get((current_x, current_y))
        if expiry is not None and expiry > self.turn_count:
            return None

        # Find animals at our current cell
        animals_at_position = []
        for cell_view in snapshot.sight:
            if cell_view.x == current_x and cell_view.y == current_y:
                animals_at_position = list(cell_view.animals)
                break

        if not animals_at_position:
            return None

        # Find the best animal in cell; prefer completers
        best_animal = None
        best_value = -1
        best_completer = None
        best_completer_value = -1

        for animal in animals_at_position:
            # Skip if we already have this animal in our flock
            if animal in self.flock:
                continue

            value = self.get_animal_value(animal.species_id, animal.gender)
            # Check if animal would complete a species on the ark
            if self._would_complete_species(animal.species_id, animal.gender):
                if value > best_completer_value:
                    best_completer_value = value
                    best_completer = animal
            if value > best_value:
                best_value = value
                best_animal = animal

        return best_completer or best_animal

    def _would_complete_species(self, species_id: int, gender) -> bool:
        from core.animal import Gender

        info = self.ark_status.get(
            species_id, {Gender.Male: False, Gender.Female: False}
        )
        if gender == Gender.Male:
            return info[Gender.Female] and not info[Gender.Male]
        if gender == Gender.Female:
            return info[Gender.Male] and not info[Gender.Female]
        return False

    def _choose_release_for_target(self, target) -> object | None:
        """If target is high-value (esp. completer) and flock full,
        pick the lowest-value animal to release if beneficial.
        Returns the Animal to release or None.
        """
        # Only consider releasing if the target is a completer
        if not self._would_complete_species(target.species_id, target.gender):
            return None

        # Find lowest-value animal in our flock
        lowest = None
        lowest_val = float("inf")
        for a in self.flock:
            val = self.get_animal_value(a.species_id, a.gender)
            if val < lowest_val:
                lowest_val = val
                lowest = a

        target_val = self.get_animal_value(target.species_id, target.gender)
        if lowest is not None and target_val > lowest_val:
            return lowest
        return None

    def _choose_lowest_value_in_flock(self):
        """Return lowest value animal in flock (or None if flock empty)."""
        lowest = None
        lowest_val = float("inf")
        for a in self.flock:
            val = self.get_animal_value(a.species_id, a.gender)
            if val < lowest_val:
                lowest_val = val
                lowest = a
        return lowest

    def _find_visible_completer_outside_cell_info(
        self,
    ) -> tuple[tuple[int, int], float, float] | None:
        """Find a non-current cell in sight that has a completer.

        Returns (position, value, distance) or None.
        """
        snap = self.last_snapshot
        if not snap or not snap.sight:
            return None

        curr_x, curr_y = int(self.position[0]), int(self.position[1])
        best_pos = None
        best_val = -1.0
        best_dist = float("inf")
        for cell_view in snap.sight:
            if (cell_view.x, cell_view.y) == (curr_x, curr_y):
                continue
            # Skip blocked cells
            expiry = self._blocked_cells.get((cell_view.x, cell_view.y))
            if expiry is not None and expiry > self.turn_count:
                continue

            cell_best_val = -1.0
            for a in cell_view.animals:
                if self._would_complete_species(a.species_id, a.gender):
                    v = self.get_animal_value(a.species_id, a.gender)
                    if v > cell_best_val:
                        cell_best_val = v
            if cell_best_val < 0:
                continue

            dx = cell_view.x - self.position[0]
            dy = cell_view.y - self.position[1]
            dist = math.hypot(dx, dy)
            if dist < best_dist or (dist == best_dist and cell_best_val > best_val):
                best_dist = dist
                best_pos = (cell_view.x, cell_view.y)
                best_val = cell_best_val

        if best_pos is None:
            return None
        return (best_pos, best_val, best_dist)

    def _best_value_in_current_cell(
        self, snapshot: HelperSurroundingsSnapshot | None
    ) -> float:
        if not snapshot or not snapshot.sight:
            return 0.0
        cx, cy = int(self.position[0]), int(self.position[1])
        best = 0.0
        for cell_view in snapshot.sight:
            if (cell_view.x, cell_view.y) != (cx, cy):
                continue
            for a in cell_view.animals:
                best = max(best, self.get_animal_value(a.species_id, a.gender))
            break
        return best

    def find_highest_value_target(self):
        """Find a good target not in our current or blocked cell.

        Score target by value and proximity to encourage movement.
        """
        from math import hypot

        best_target = None
        best_score = -1.0

        curr_x = int(self.position[0])
        curr_y = int(self.position[1])

        for _, animal_info in self.known_animals.items():
            # discard stale info
            if self.turn_count - animal_info["turn_seen"] > 50:
                continue

            tx, ty = animal_info["position"]

            # skip current cell and temporarily blocked cells
            if (tx, ty) == (curr_x, curr_y):
                continue
            expiry = self._blocked_cells.get((tx, ty))
            if expiry is not None and expiry > self.turn_count:
                continue

            value = self.get_animal_value(
                animal_info["species_id"], animal_info.get("gender")
            )

            # prefer closer high-value targets; avoid div by zero
            dx = tx - self.position[0]
            dy = ty - self.position[1]
            dist = max(1.0, hypot(dx, dy))
            score = value / dist

            if score > best_score:
                best_score = score
                best_target = animal_info

        return best_target

    def _pursue_best_cell(self) -> Move | None:
        """Pick/continue a best cell within 5km by value/effort.

        Short-lived sticky target to avoid thrashing between cells.
        """
        snap = self.last_snapshot
        if not snap or not snap.sight:
            return None

        curr = (int(self.position[0]), int(self.position[1]))

        # If we have a valid, not-blocked pursuit target, continue toward it
        if (
            self._pursuit_target is not None
            and self._pursuit_expires_at > self.turn_count
            and self._blocked_cells.get(self._pursuit_target, 0) <= self.turn_count
        ):
            # If reached the target cell, clear pursuit
            if self._pursuit_target == curr:
                self._pursuit_target = None
                self._pursuit_last_dist = None
                self._pursuit_stuck_count = 0
            else:
                # Stuck detection: ensure distance decreases over time
                tx, ty = self._pursuit_target
                dx = tx - self.position[0]
                dy = ty - self.position[1]
                dist = max(0.0, math.hypot(dx, dy))
                if (
                    self._pursuit_last_dist is not None
                    and dist >= self._pursuit_last_dist - 1e-6
                ):
                    self._pursuit_stuck_count += 1
                else:
                    self._pursuit_stuck_count = 0
                self._pursuit_last_dist = dist

                # If stuck for 3 turns, block and drop this target
                if self._pursuit_stuck_count >= 3:
                    self._blocked_cells[self._pursuit_target] = self.turn_count + 5
                    self._pursuit_target = None
                    self._pursuit_last_dist = None
                    self._pursuit_stuck_count = 0
                else:
                    return self.move_towards_position(self._pursuit_target)

        # Compute best cell from current sight
        best_cell = None
        best_score = -1.0

        for cell_view in snap.sight:
            tx, ty = cell_view.x, cell_view.y

            # Skip current cell; handled by obtain logic
            if (tx, ty) == curr:
                continue
            # Skip temporarily blocked cells
            expiry = self._blocked_cells.get((tx, ty))
            if expiry is not None and expiry > self.turn_count:
                continue

            # Sum value of animals in that cell
            cell_value = 0.0
            for a in cell_view.animals:
                cell_value += self.get_animal_value(a.species_id, a.gender)

            if cell_value <= 0:
                continue

            dx = tx - self.position[0]
            dy = ty - self.position[1]
            dist = max(1.0, math.hypot(dx, dy))
            score = cell_value / dist

            # Avoid revisiting very recent cells unless much better
            if (tx, ty) in self._recent_cells and best_score >= 0:
                if score <= best_score * 1.3:
                    continue

            if score > best_score:
                best_score = score
                best_cell = (tx, ty)

        if best_cell is None:
            return None

        # Set sticky pursuit and apply lock/hysteresis to avoid flips
        if (
            self._pursuit_target is not None
            and self._pursuit_expires_at > self.turn_count
            and (
                self.turn_count < self._pursuit_lock_until
                or best_score < self._pursuit_score * 1.5
            )
        ):
            return self.move_towards_position(self._pursuit_target)

        self._pursuit_target = best_cell
        self._pursuit_score = best_score
        sticky = int(max(5, min(20, best_score if best_score > 0 else 5)))
        self._pursuit_expires_at = self.turn_count + sticky
        self._pursuit_lock_until = self.turn_count + 4
        # Initialize distance tracking for stuck detection
        dx = best_cell[0] - self.position[0]
        dy = best_cell[1] - self.position[1]
        self._pursuit_last_dist = max(0.0, math.hypot(dx, dy))
        self._pursuit_stuck_count = 0

        return self.move_towards_position(best_cell)

    def get_animal_value(self, species_id: int, gender) -> float:
        """Calculate value of animal based on ark status and rarity"""
        from core.animal import Gender

        base_priority = self.priorities.get(species_id, 1.0)

        # Check ark status
        ark_info = self.ark_status.get(
            species_id, {Gender.Male: False, Gender.Female: False}
        )

        if not gender or gender == Gender.Unknown:
            # Don't know gender yet, assume average value
            return base_priority * 50

        has_male = ark_info[Gender.Male]
        has_female = ark_info[Gender.Female]

        # Maximum value: completing a species (100 points)
        if (gender == Gender.Male and has_female and not has_male) or (
            gender == Gender.Female and has_male and not has_female
        ):
            return base_priority * 100

        # High value: first animal of species
        if not has_male and not has_female:
            return base_priority * 80

        # Low value: duplicate gender or already complete
        return base_priority * 10

    def move_towards_ark(self) -> Move:
        """Move toward the ark"""
        # Use base class move_towards which handles 1km constraint
        new_x, new_y = self.move_towards(self.ark_position[0], self.ark_position[1])
        return Move(new_x, new_y)

    def move_towards_position(self, target_position: tuple[float, float]) -> Move:
        """Move toward a target position"""
        # Use base class move_towards which handles 1km constraint
        new_x, new_y = self.move_towards(target_position[0], target_position[1])
        return Move(new_x, new_y)

    def explore_territory(self) -> Move:
        """Boustrophedon (lawnmower) sweep within assigned territory."""
        t = self.my_territory
        min_x, max_x = t["min_x"], t["max_x"]
        min_y, max_y = t["min_y"], t["max_y"]
        cx, cy = t["center_x"], t["center_y"]

        # If we're out of our sector, head to center first
        if (
            self.position[0] < min_x
            or self.position[0] > max_x
            or self.position[1] < min_y
            or self.position[1] > max_y
        ):
            return self.move_towards_position((cx, cy))

        width = max(1, max_x - min_x)
        height = max(1, max_y - min_y)

        # Row step ~ sight diameter so we scan with overlap
        row_step = max(1, c.MAX_SIGHT_KM * 2 - 1)
        row_count = max(1, height // row_step)

        # Determine which row we're on based on turns
        row = (self.turn_count // (width + 1)) % row_count
        y_target = min_y + min(row * row_step, height - 1)

        # Alternate direction each row
        left_to_right = row % 2 == 0
        x_progress = self.turn_count % (width + 1)
        x_target = min_x + x_progress if left_to_right else max_x - x_progress

        # Clamp inside bounds
        x_target = min(max(x_target, min_x), max_x)
        y_target = min(max(y_target, min_y), max_y)

        return self.move_towards_position((x_target, y_target))

    def at_ark(self) -> bool:
        """Check if we're at the ark"""
        return (
            abs(self.position[0] - self.ark_position[0]) < 0.5
            and abs(self.position[1] - self.ark_position[1]) < 0.5
        )

    def distance_to_ark(self) -> float:
        """Calculate distance to the ark"""
        dx = self.ark_position[0] - self.position[0]
        dy = self.ark_position[1] - self.position[1]
        return math.sqrt(dx**2 + dy**2)
