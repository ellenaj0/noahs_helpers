from core.action import Action, Move, Obtain, Release
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.animal import Gender
from math import cos, sin, radians, hypot, ceil
import core.constants as c


class IndependentPlayer(Player):
    """
    Implementation of the Trivial Baseline Algorithm

    Strategy:
    - Divide 360 degrees around the ark into sectors (one per helper)
    - Each helper explores radially outward in their sector
    - Catch animals that ark doesn't have yet (known gender only)
    - Release animals that ark already has to free space
    - Return when carrying 2+ animals or flock is full
    - Choose next exploration angle to maximize coverage
    - Respect rain/time constraints for safe return
    """

    shared_ark_animals: set[tuple[int | str, Gender]] = set()
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
        # print(f"Independent Helper {id}")
        super().__init__(id, ark_x, ark_y, kind, num_helpers, species_populations)

        # State tracking
        self.state = (
            "exploring"  # "exploring", "returning", "hunting", "returning_to_discovery"
        )
        self.explored_angles = []  # List of angles we've explored
        self.current_target_angle = None  # Current exploration direction
        self.current_snapshot = None
        self.forced_return = False
        self.rain_start_turn: int | None = None

        # Animal hunting state
        self.discovery_position = None  # Position where we discovered the animal
        self.target_animal_cell = None  # Cell where the target animal was last seen
        self.target_species_id = None  # Species ID of target animal (to track it)
        self.previous_state = None  # State before hunting (to resume after catching)
        self.last_hunt_position = (
            None  # Last position where we hunted (to avoid re-hunting)
        )
        self.turns_since_last_hunt = 999  # Turns since last hunt

        # Sector assignment: divide 360 degrees among helpers (excluding Noah)
        # with soft weighting based on ark position
        # Noah is id=0, real helpers are id=1, 2, ..., num_helpers-1
        num_actual_helpers = num_helpers - 1

        # For Noah (id=0), no sector assignment needed
        if id == 0:
            self.sector_start = 0
            self.sector_end = 0
            self.current_target_angle = 0
            self.explored_angles = []
        else:
            # Calculate weighted sector sizes based on explorable area in each direction
            # First, calculate distance to boundary in each direction for each helper
            helper_weights = []

            for h_idx in range(num_actual_helpers):
                # Base angle for this helper (evenly distributed)
                base_angle = h_idx * 360.0 / num_actual_helpers
                angle_rad = radians(base_angle)

                # Calculate distance to boundary in this direction
                # Start from ark, go in direction until hitting world edge
                dx = cos(angle_rad)
                dy = sin(angle_rad)

                # Calculate max distance in this direction
                if dx > 0:
                    t_x = (c.X - 1 - ark_x) / dx
                elif dx < 0:
                    t_x = -ark_x / dx
                else:
                    t_x = float("inf")

                if dy > 0:
                    t_y = (c.Y - 1 - ark_y) / dy
                elif dy < 0:
                    t_y = -ark_y / dy
                else:
                    t_y = float("inf")

                max_distance = min(t_x, t_y, 1000)  # Cap at reasonable distance

                # Inverse weighting: larger explorable area → smaller sector angle
                # Logic: large areas need smaller angles to cover similar actual area
                # Use 1 / (distance^0.8) for soft inverse weighting
                weight = 1.0 / (max_distance**0.85)
                helper_weights.append(weight)

            # Normalize weights to sum to 360 degrees
            total_weight = sum(helper_weights)
            sector_sizes = [w / total_weight * 360.0 for w in helper_weights]

            # Calculate sector boundaries
            sector_boundaries = [0]
            for size in sector_sizes:
                sector_boundaries.append(sector_boundaries[-1] + size)

            # Assign sector to this helper
            helper_index = id - 1
            self.sector_start = sector_boundaries[helper_index]
            self.sector_end = sector_boundaries[helper_index + 1]

            # Initial heading: center of assigned sector
            self.current_target_angle = (self.sector_start + self.sector_end) / 2
            self.explored_angles.append(self.current_target_angle)

        # Track explored directions (both outbound and return paths)
        self.explored_return_angles = []  # Return path angles

        # Track what's on the ark
        self.ark_animals = set(
            type(self).shared_ark_animals
        )  # Set of (species_id, gender) tuples
        self.local_ark_version = type(self).shared_ark_version

        # Safety margin: return this many turns before the end
        self.safety_margin = 100

        # For Noah, just stay still
        if kind == Kind.Noah:
            self.state = "at_ark"

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        """Called before get_action to observe surroundings and broadcast message"""
        # Store snapshot for use in get_action
        self.current_snapshot = snapshot
        # Keep local position/flock in sync with simulator for helper logic
        self.position = snapshot.position
        self.flock = set(snapshot.flock)

        # Age the last hunt position
        self.turns_since_last_hunt += 1

        # Sync ark knowledge (locally and globally)
        self._sync_ark_information(snapshot)

        # Track when rain starts so we can compute exact remaining time
        if snapshot.is_raining and self.rain_start_turn is None:
            self.rain_start_turn = snapshot.time_elapsed

        # Check time constraints - use snapshot position, not self.position
        current_x, current_y = snapshot.position
        ark_x, ark_y = self.ark_position
        distance_to_ark = hypot(current_x - ark_x, current_y - ark_y)

        turns_to_return = ceil(distance_to_ark / c.MAX_DISTANCE_KM)
        available_turns = self._get_available_turns(snapshot)

        forced_due_time = (
            available_turns <= self.safety_margin
            or turns_to_return + self.safety_margin > available_turns
        )

        if forced_due_time:
            self.state = "returning"

        self.forced_return = forced_due_time

        # Return message (0 = no message used)
        return 0

    def get_action(self, messages: list[Message]) -> Action | None:
        """Decide what action to take this turn"""
        # Noah doesn't move
        if self.kind == Kind.Noah:
            return None

        if self.current_snapshot is None:
            return None

        snapshot = self.current_snapshot

        # Use snapshot position, not self.position (which is never updated)
        current_x, current_y = snapshot.position
        cell_x = int(current_x)
        cell_y = int(current_y)

        # Check if we're at the ark
        at_ark = (
            abs(current_x - self.ark_position[0]) <= c.EPS
            and abs(current_y - self.ark_position[1]) <= c.EPS
        )

        # Priority 1: Release animals that ark already has (to free space)
        if len(self.flock) > 0:
            for animal in list(self.flock):
                if animal.gender != Gender.Unknown:
                    if (animal.species_id, animal.gender) in self.ark_animals:
                        # Ark already has this species+gender, release it
                        return Release(animal)

        # Priority 2: Try to obtain animals if we're in a cell with animals
        # Skip if we're returning and already have flock (focus on getting back to ark)
        # ALSO skip if in returning_to_discovery state (focus on getting back to discovery position)
        should_skip_obtain = (
            self.state == "returning" and len(self.flock) > 0
        ) or self.state == "returning_to_discovery"

        if not self.is_flock_full() and not should_skip_obtain:
            # Check if we can see our current cell
            if snapshot.sight.cell_is_in_sight(cell_x, cell_y):
                try:
                    cell_view = snapshot.sight.get_cellview_at(cell_x, cell_y)

                    # Try to obtain animals that we need
                    for animal in cell_view.animals:
                        # Only obtain if:
                        # 1. Gender is known (we're in same cell, so it should be known)
                        # 2. Ark doesn't have this species+gender yet
                        # 3. Our flock doesn't have this species+gender yet (avoid duplicates)
                        # 4. We have space
                        # 5. Animal is not already in our flock (not shepherded)

                        # Check if flock already has this species+gender
                        flock_has_this = any(
                            a.species_id == animal.species_id
                            and a.gender == animal.gender
                            for a in self.flock
                        )

                        if (
                            animal.gender != Gender.Unknown
                            and (animal.species_id, animal.gender)
                            not in self.ark_animals
                            and not flock_has_this
                            and animal not in self.flock
                            and not self.is_flock_full()
                        ):
                            # Obtain the animal
                            # After obtaining, if we were hunting, return to discovery position
                            if self.state == "hunting":
                                self.state = "returning_to_discovery"
                            return Obtain(animal)
                except Exception:
                    # Cell not in sight, skip
                    pass

        # Check if we have 2 animals (half capacity) and should return
        if len(self.flock) >= 2:
            self.state = "returning"

        # Check if we're at the ark and returning
        if at_ark and self.state == "returning":
            # We just arrived at ark, animals are auto-unloaded
            # Ark updates the global list (handled in check_surroundings via ark_view)
            # The helper receives this updated information before its next exploration leg

            # Check if we've collected all animals (all species have both genders)
            all_species_complete = True
            for species_id in range(len(self.species_populations)):
                has_male = (species_id, Gender.Male) in self.ark_animals
                has_female = (species_id, Gender.Female) in self.ark_animals
                if not (has_male and has_female):
                    all_species_complete = False
                    break

            if all_species_complete:
                # All animals collected! Stay at ark
                self.state = "at_ark"
                self.forced_return = False
                return None

            # Still need more animals, continue exploring
            # Choose next exploration angle (maximally distant from all previously explored directions)
            self._choose_next_exploration_angle()
            self.forced_return = False
            self.state = "exploring"
            # Stay at ark this turn (will start exploring next turn)
            return None

        # Priority 3: Handle returning to discovery position after catching animal
        if self.state == "returning_to_discovery":
            if self.discovery_position is not None:
                disc_x, disc_y = self.discovery_position
                # Check if we've reached the discovery position
                distance_to_disc = hypot(current_x - disc_x, current_y - disc_y)
                if distance_to_disc <= c.EPS:
                    # Reached discovery position, clear hunting state first
                    self.discovery_position = None
                    self.target_animal_cell = None
                    saved_previous_state = self.previous_state
                    self.previous_state = None

                    # Decide next state:
                    # - If we have any animals, return to ark to unload
                    # - Otherwise resume previous state
                    if len(self.flock) > 0 or self.forced_return:
                        self.state = "returning"
                        # Immediately continue returning to avoid re-hunting same location
                        return self._return_to_ark(snapshot)
                    else:
                        # Resume previous state
                        resume_state = saved_previous_state or "exploring"
                        self.state = (
                            resume_state
                            if resume_state in ("exploring", "returning")
                            else "exploring"
                        )
                        # Immediately continue with resumed state
                        if self.state == "exploring":
                            return self._explore(snapshot)
                        elif self.state == "returning":
                            return self._return_to_ark(snapshot)
                else:
                    # Move towards discovery position
                    return self._move_towards_position(snapshot, disc_x, disc_y)
            else:
                # No discovery position, resume normal state
                self.state = self.previous_state if self.previous_state else "exploring"

        # Priority 4: ACTIVE HUNTING - Track and move towards target animal
        # Animals can move, so we need to update target position each turn
        if self.state == "hunting":
            if self.target_species_id is not None:
                # Try to find the target animal in sight and update its position
                target_found = False
                nearest_target = None
                nearest_distance = float("inf")

                for cell_view in snapshot.sight:
                    for animal in cell_view.animals:
                        # Look for animals of the target species that we need
                        if animal.species_id == self.target_species_id:
                            # Skip if already in our flock
                            if animal in self.flock:
                                continue

                            # Check if we still need this species/gender
                            if animal.gender != Gender.Unknown:
                                if (
                                    animal.species_id,
                                    animal.gender,
                                ) in self.ark_animals:
                                    continue  # Ark already has it

                            # This could be our target, find the nearest one
                            cell_x_a, cell_y_a = cell_view.x, cell_view.y
                            dist = hypot(
                                cell_x_a + 0.5 - current_x, cell_y_a + 0.5 - current_y
                            )
                            if dist < nearest_distance:
                                nearest_distance = dist
                                nearest_target = (cell_x_a, cell_y_a)
                                target_found = True

                if target_found and nearest_target:
                    # Update target to current position
                    self.target_animal_cell = nearest_target
                    target_x, target_y = nearest_target

                    # Check if we've reached the target cell
                    if cell_x == target_x and cell_y == target_y:
                        # At target cell - Priority 2 should have handled obtain
                        # If still hunting, animal moved away or can't be obtained
                        pass  # Will fall through and give up hunting below
                    else:
                        # Move towards current animal position
                        return self._move_towards_cell(
                            snapshot, self.target_animal_cell
                        )

                # If we can't see the target anymore or reached cell without obtaining
                # Give up hunting after reasonable attempts
                at_target_cell = (
                    self.target_animal_cell is not None
                    and cell_x == self.target_animal_cell[0]
                    and cell_y == self.target_animal_cell[1]
                )

                if not target_found or at_target_cell:
                    # Record this position to avoid re-hunting nearby soon
                    self.last_hunt_position = (current_x, current_y)
                    self.turns_since_last_hunt = 0

                    self.target_animal_cell = None
                    self.target_species_id = None
                    self.discovery_position = None
                    # Decide next state based on flock size
                    if len(self.flock) >= 2 or self.forced_return:
                        self.state = "returning"
                    else:
                        self.state = (
                            self.previous_state if self.previous_state else "exploring"
                        )
                    self.previous_state = None
                    # Fall through to continue with new state
            else:
                # Lost target species ID, resume previous state
                self.target_animal_cell = None
                self.discovery_position = None
                self.state = self.previous_state if self.previous_state else "exploring"
                self.previous_state = None

        # Priority 5: Search for animals in sight (only if not already hunting or returning to discovery)
        # According to algorithm: "On the return path, the helper continues applying
        # the same capture logic and will catch any missing-species animals"
        # This applies to exploring AND returning states (as long as we have space)
        if (
            self.state != "hunting"
            and self.state != "returning_to_discovery"
            and not self.is_flock_full()
        ):
            # Search for animals in sight that we need
            target_cell = self._find_nearest_needed_animal(snapshot)

            # Don't hunt if target is too close to where we recently hunted
            # (avoid getting stuck in hunt-fail-hunt loop at same location)
            if target_cell is not None and self.last_hunt_position is not None:
                if self.turns_since_last_hunt < 20:  # Within last 20 turns
                    last_x, last_y = self.last_hunt_position
                    target_x, target_y = target_cell
                    distance_to_last = hypot(target_x - last_x, target_y - last_y)
                    if distance_to_last < 10:  # Within 10 cells of last hunt location
                        target_cell = None  # Skip this hunt

            if target_cell is not None:
                # Found an animal! Determine which species we're hunting
                # Look at the target cell to find the species
                target_species = None
                try:
                    cell_view = snapshot.sight.get_cellview_at(
                        target_cell[0], target_cell[1]
                    )
                    # Find a needed animal in this cell
                    for animal in cell_view.animals:
                        if animal in self.flock:
                            continue
                        species_id = animal.species_id
                        has_male = (species_id, Gender.Male) in self.ark_animals
                        has_female = (species_id, Gender.Female) in self.ark_animals
                        if not (has_male and has_female):
                            target_species = species_id
                            break
                except Exception:
                    pass

                if target_species is not None:
                    # Found an animal! Start hunting (whether exploring or returning)
                    self.previous_state = (
                        self.state
                    )  # Save current state (exploring or returning)
                    self.discovery_position = (
                        current_x,
                        current_y,
                    )  # Record discovery position
                    self.target_animal_cell = target_cell  # Record target cell
                    self.target_species_id = target_species  # Record species to track
                    self.state = "hunting"
                    # Move towards the animal
                    return self._move_towards_cell(snapshot, target_cell)

        # Priority 6: If no animals in sight, continue exploring or returning
        if self.state == "exploring":
            return self._explore(snapshot)
        elif self.state == "returning":
            return self._return_to_ark(snapshot)

        return None

    def _explore(self, snapshot: HelperSurroundingsSnapshot) -> Action | None:
        """Explore outward along current heading"""
        # Check if we should return to ark (already checked in get_action, but double-check here)
        if len(self.flock) >= 2 or self.is_flock_full():
            self.state = "returning"
            return self._return_to_ark(snapshot)

        # Use snapshot position, not self.position
        current_x, current_y = snapshot.position

        # Safety check (should never be None after initialization)
        if self.current_target_angle is None:
            self.state = "returning"
            return self._return_to_ark(snapshot)

        # Calculate target position based on current angle
        # Move as far as we can in that direction
        distance = c.MAX_DISTANCE_KM * 0.99  # Conservative step

        target_x = current_x + distance * cos(radians(self.current_target_angle))
        target_y = current_y + distance * sin(radians(self.current_target_angle))

        # Check if we would hit the edge of the world
        target_x_clamped = max(0, min(c.X - 1, target_x))
        target_y_clamped = max(0, min(c.Y - 1, target_y))

        # If clamping changed our target significantly, we hit an edge - return to ark
        if (
            abs(target_x - target_x_clamped) > 0.1
            or abs(target_y - target_y_clamped) > 0.1
        ):
            self.state = "returning"
            return self._return_to_ark(snapshot)

        target_x = target_x_clamped
        target_y = target_y_clamped

        # Check distance constraints - ensure we can always return safely
        # According to algorithm: "A helper must never go beyond the distance that requires
        # more than the remaining time to return before the end of the simulation."
        ark_x, ark_y = self.ark_position
        distance_to_ark = hypot(target_x - ark_x, target_y - ark_y)
        turns_to_return_from_target = ceil(distance_to_ark / c.MAX_DISTANCE_KM)
        available_turns = self._get_available_turns(snapshot)
        remaining_after_move = max(0, available_turns - 1)

        if (
            remaining_after_move <= self.safety_margin
            or turns_to_return_from_target + self.safety_margin > remaining_after_move
        ):
            self.state = "returning"
            self.forced_return = True
            return self._return_to_ark(snapshot)

        # Use can_move_to with snapshot position - but we need to check manually
        # because can_move_to uses self.position which is outdated
        # Calculate distance using the same formula as can_move_to
        distance_to_target_sq = (
            abs(current_x - target_x) ** 2 + abs(current_y - target_y) ** 2
        )
        distance_check = distance_to_target_sq * 0.5 <= c.MAX_DISTANCE_KM

        if distance_check and 0 <= target_x < c.X and 0 <= target_y < c.Y:
            return Move(target_x, target_y)

        # If we can't move further (edge case), return to ark
        self.state = "returning"
        return self._return_to_ark(snapshot)

    def _return_to_ark(self, snapshot: HelperSurroundingsSnapshot) -> Action | None:
        """
        Move towards the ark with a clockwise offset to explore different areas.
        The offset angle increases with distance (farther = more offset, but stays close).
        """
        # Use snapshot position, not self.position
        current_x, current_y = snapshot.position
        ark_x, ark_y = self.ark_position

        # Calculate direction to ark
        dx = ark_x - current_x
        dy = ark_y - current_y
        dist = hypot(dx, dy)

        if dist == 0:
            # Already at ark
            return None

        # Move towards ark, but limit step size
        step_size = c.MAX_DISTANCE_KM * 0.99

        # Add clockwise offset to explore different areas on return
        # Only apply offset in the initial phase of return (far from ark)
        # Then switch to direct path to ensure efficient return
        if dist > 100:
            # Far from ark (>100km): apply clockwise offset to explore new areas
            # Offset formula: min(30°, distance / 15) gives ~1° per 15km, max 30°
            offset_radians = radians(min(30, dist / 15))

            # Rotate direction vector clockwise by offset_radians
            # Clockwise rotation: (x, y) -> (x*cos - y*sin, x*sin + y*cos) with negative angle
            cos_offset = cos(offset_radians)
            sin_offset = sin(offset_radians)

            # Apply rotation to direction vector (clockwise)
            dx_rotated = dx * cos_offset + dy * sin_offset
            dy_rotated = -dx * sin_offset + dy * cos_offset

            # Normalize and scale
            dist_rotated = hypot(dx_rotated, dy_rotated)
            scale = step_size / dist_rotated
            target_x = current_x + dx_rotated * scale
            target_y = current_y + dy_rotated * scale

            # Record return angle for next exploration planning
            from math import atan2, degrees

            return_angle = degrees(atan2(dy_rotated, dx_rotated))
            if return_angle < 0:
                return_angle += 360

            # Record this return angle
            if return_angle not in self.explored_return_angles:
                self.explored_return_angles.append(return_angle)
        else:
            # Close to ark (≤100km): go directly to ark for efficient return
            if dist <= step_size:
                target_x, target_y = ark_x, ark_y
            else:
                scale = step_size / dist
                target_x = current_x + dx * scale
                target_y = current_y + dy * scale

        # Check if we can move to target using the same distance formula as can_move_to
        distance_to_target_sq = (
            abs(current_x - target_x) ** 2 + abs(current_y - target_y) ** 2
        )
        distance_check = distance_to_target_sq * 0.5 <= c.MAX_DISTANCE_KM

        if distance_check and 0 <= target_x < c.X and 0 <= target_y < c.Y:
            return Move(target_x, target_y)

        return None

    def _move_towards_position(
        self, snapshot: HelperSurroundingsSnapshot, target_x: float, target_y: float
    ) -> Action | None:
        """
        Move towards a specific position (not a cell). Returns a Move action if possible, None otherwise.
        """
        current_x, current_y = snapshot.position

        # Calculate direction
        dx = target_x - current_x
        dy = target_y - current_y
        dist = hypot(dx, dy)

        if dist == 0:
            # Already at target position
            return None

        # Move towards target, but limit step size
        step_size = c.MAX_DISTANCE_KM * 0.99
        if dist <= step_size:
            target_move_x, target_move_y = target_x, target_y
        else:
            scale = step_size / dist
            target_move_x = current_x + dx * scale
            target_move_y = current_y + dy * scale

        # Check if we can move to target using the same distance formula as can_move_to
        distance_to_target_sq = (
            abs(current_x - target_move_x) ** 2 + abs(current_y - target_move_y) ** 2
        )
        distance_check = distance_to_target_sq * 0.5 <= c.MAX_DISTANCE_KM

        if distance_check and 0 <= target_move_x < c.X and 0 <= target_move_y < c.Y:
            return Move(target_move_x, target_move_y)

        return None

    def _choose_next_exploration_angle(self):
        """
        Choose the next angle to explore in our sector.
        Strategy: select the angle that maximizes the minimum distance to all "obstacles"
        (explored outbound angles, explored return angles, AND sector boundaries).

        Example: sector 0-90, explored outbound [0], return [10] -> choose ~50 (far from all)
        """
        num_samples = 72  # Sample more candidates for better coverage
        candidates = []

        # Generate candidates within sector (exclude endpoint to avoid overlap with next helper)
        sector_range = self.sector_end - self.sector_start

        for i in range(num_samples):
            # Distribute candidates evenly within sector
            # Use (i + 0.5) / num_samples to avoid including endpoints
            angle = self.sector_start + sector_range * (i + 0.5) / num_samples
            candidates.append(angle)

        # Find the candidate with maximum minimum distance to all obstacles
        best_angle = self.sector_start + sector_range / 2  # Default to middle
        best_min_dist = -1

        for candidate in candidates:
            # Calculate minimum distance to ALL obstacles
            min_dist = float("inf")

            # Distance to explored outbound angles
            for explored in self.explored_angles:
                # Calculate angular distance (accounting for wraparound)
                dist = abs(candidate - explored)
                if dist > 180:
                    dist = 360 - dist
                min_dist = min(min_dist, dist)

            # Distance to explored return angles
            for return_angle in self.explored_return_angles:
                # Calculate angular distance (accounting for wraparound)
                dist = abs(candidate - return_angle)
                if dist > 180:
                    dist = 360 - dist
                min_dist = min(min_dist, dist)

            # Distance to sector boundaries
            dist_to_start = abs(candidate - self.sector_start)
            dist_to_end = abs(candidate - self.sector_end)
            min_dist = min(min_dist, dist_to_start, dist_to_end)

            # Select candidate with maximum minimum distance (furthest from all obstacles)
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_angle = candidate

        self.current_target_angle = best_angle
        self.explored_angles.append(best_angle)

    def _find_nearest_needed_animal(
        self, snapshot: HelperSurroundingsSnapshot
    ) -> tuple[int, int] | None:
        """
        Search for animals in sight that we need (ark doesn't have yet).
        Returns the (x, y) cell coordinates of the nearest cell with needed animals, or None.
        Priority: cells with known-gender animals > cells with unknown-gender animals
        """
        current_x, current_y = snapshot.position
        current_cell_x = int(current_x)
        current_cell_y = int(current_y)

        best_cell_known = None  # Cell with known-gender animals we need
        best_distance_known = float("inf")
        best_cell_unknown = None  # Cell with unknown-gender animals (species we need)
        best_distance_unknown = float("inf")

        # Iterate through all cells in sight
        for cell_view in snapshot.sight:
            cell_x, cell_y = cell_view.x, cell_view.y
            is_current_cell = cell_x == current_cell_x and cell_y == current_cell_y

            # Check if there are other helpers in this cell
            # If yes, Unknown gender animals might be in their flocks
            has_other_helpers = any(h.id != self.id for h in cell_view.helpers)

            # Check if this cell has animals we need
            has_needed_known_animal = False
            has_needed_unknown_animal = False

            for animal in cell_view.animals:
                # Skip if already in our flock (already shepherded by us)
                if animal in self.flock:
                    continue

                species_id = animal.species_id
                has_male = (species_id, Gender.Male) in self.ark_animals
                has_female = (species_id, Gender.Female) in self.ark_animals

                # If ark doesn't have both genders, this species is needed
                if not (has_male and has_female):
                    # Gender is known if we're in the same cell
                    if animal.gender != Gender.Unknown:
                        # Known gender and needed - highest priority
                        if (species_id, animal.gender) not in self.ark_animals:
                            has_needed_known_animal = True
                    else:
                        # Unknown gender: from distance we can't tell gender
                        # Could be needed, or could be shepherded by another helper
                        if is_current_cell or has_other_helpers:
                            # In same cell or cell has other helpers - Unknown gender likely shepherded
                            # Skip to avoid hunting animals in other helpers' flocks
                            pass
                        else:
                            # Not in same cell and no other helpers - likely a free animal
                            # If species is not complete, consider hunting
                            if not (has_male and has_female):
                                has_needed_unknown_animal = True

            # Calculate distance to this cell
            cell_center_x = cell_x + 0.5
            cell_center_y = cell_y + 0.5
            distance = hypot(cell_center_x - current_x, cell_center_y - current_y)

            if has_needed_known_animal and distance < best_distance_known:
                best_distance_known = distance
                best_cell_known = (cell_x, cell_y)
            elif has_needed_unknown_animal and distance < best_distance_unknown:
                best_distance_unknown = distance
                best_cell_unknown = (cell_x, cell_y)

        # Prefer cells with known-gender animals
        if best_cell_known is not None:
            return best_cell_known
        elif best_cell_unknown is not None:
            # Only hunt unknown-gender animals if we have enough time
            # Near the deadline, focus on returning to ark instead of chasing unknowns
            available_turns = self._get_available_turns(snapshot)
            if available_turns > 200:  # Only hunt unknowns if we have plenty of time
                return best_cell_unknown

        return None

    def _move_towards_cell(
        self, snapshot: HelperSurroundingsSnapshot, target_cell: tuple[int, int]
    ) -> Action | None:
        """
        Move towards a target cell. Returns a Move action if possible, None otherwise.
        """
        current_x, current_y = snapshot.position
        target_x, target_y = target_cell

        # Move towards cell center
        cell_center_x = target_x + 0.5
        cell_center_y = target_y + 0.5

        # Calculate direction
        dx = cell_center_x - current_x
        dy = cell_center_y - current_y
        dist = hypot(dx, dy)

        if dist == 0:
            # Already at target cell
            return None

        # Move towards target, but limit step size
        step_size = c.MAX_DISTANCE_KM * 0.99
        if dist <= step_size:
            target_move_x, target_move_y = cell_center_x, cell_center_y
        else:
            scale = step_size / dist
            target_move_x = current_x + dx * scale
            target_move_y = current_y + dy * scale

        # Check if we can move to target using the same distance formula as can_move_to
        distance_to_target_sq = (
            abs(current_x - target_move_x) ** 2 + abs(current_y - target_move_y) ** 2
        )
        distance_check = distance_to_target_sq * 0.5 <= c.MAX_DISTANCE_KM

        if distance_check and 0 <= target_move_x < c.X and 0 <= target_move_y < c.Y:
            return Move(target_move_x, target_move_y)

        return None

    def _get_available_turns(self, snapshot: HelperSurroundingsSnapshot) -> int:
        """
        Conservative estimate of turns remaining before the flood deadline.
        Uses exact countdown once rain has started, otherwise assumes plenty of time.
        """
        if snapshot.is_raining and self.rain_start_turn is None:
            self.rain_start_turn = snapshot.time_elapsed

        if self.rain_start_turn is not None:
            # Rain has started - we know exactly how much time remains
            turns_since_rain = snapshot.time_elapsed - self.rain_start_turn
            return max(0, c.START_RAIN - turns_since_rain)

        # Rain has not started yet - we don't know when T is
        # Be optimistic and assume we have plenty of time to explore
        # Return a large number so helpers continue exploring
        return 10000  # Effectively infinite before rain starts

    def _sync_ark_information(self, snapshot: HelperSurroundingsSnapshot) -> None:
        """
        Keep every helper's view of ark inventory in sync by copying from the
        most recent helper that had direct visibility of the ark.
        """
        cls = type(self)

        if snapshot.ark_view is not None:
            ark_animals = {(a.species_id, a.gender) for a in snapshot.ark_view.animals}
            cls.shared_ark_animals = set(ark_animals)
            cls.shared_ark_version += 1
            self.ark_animals = set(ark_animals)
            self.local_ark_version = cls.shared_ark_version
            return

        if self.local_ark_version != cls.shared_ark_version:
            self.ark_animals = set(cls.shared_ark_animals)
            self.local_ark_version = cls.shared_ark_version
