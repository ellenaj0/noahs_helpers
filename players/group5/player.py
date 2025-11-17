from random import random
from core.action import Action, Move, Obtain, Release
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView
from core.animal import Gender
import core.constants as c
import math
from typing import Set, Tuple, Optional

# --- Constants for Player5 Logic ---
TURN_ADJUSTMENT_RAD = math.radians(0.5)
MAX_MAP_COORD = 999
MIN_MAP_COORD = 0
TARGET_POINT_DISTANCE = 150.0
BACKTRACK_MIN_ANGLE = math.radians(160)
BACKTRACK_MAX_ANGLE = math.radians(200)
NEAR_ARK_DISTANCE = 150.0
SpeciesGender = Tuple[int, Gender]


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return (abs(x1 - x2) ** 2 + abs(y1 - y2) ** 2) ** 0.5


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
        # Pass ALL arguments to the base class constructor
        super().__init__(id, ark_x, ark_y, kind, num_helpers, species_populations)

        # Explicitly save properties
        self.species_stats = species_populations
        self.num_helpers = num_helpers

        # --- Player 5 State Initialization ---
        self.ark_pos = (float(ark_x), float(ark_y))

        self.obtained_species: Set[SpeciesGender] = set()
        self.current_target_pos: Optional[Tuple[float, float]] = None
        self.previous_position: Tuple[float, float] = self.position
        self.animal_target_cell: Optional[CellView] = None

        h = num_helpers
        # calc fan-out angle and exclude noah since he stays on boat
        if self.id > 0:
            self.base_angle = (2 * math.pi * (self.id - 1)) / (int(h) - 1)
        else:
            self.base_angle = 0
        self.is_exploring_fan_out = True

        self.ignore_list = []  # List of species_ids where internal duplicates were found
        self.max_explore_dis = 100  # technically 200 at turn 1

    # --- Player5 Helper Methods ---

    def _get_distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """Calculates Euclidean distance between two points."""
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def _update_obtained_species_from_ark(self, ark_animals: Set):
        """
        Updates the set based on animals CONFIRMED to be on the Ark.
        """
        ark_set: Set[SpeciesGender] = set()
        for animal in ark_animals:
            if animal.gender != Gender.Unknown:
                ark_set.add((animal.species_id, animal.gender))
                self.is_exploring_fan_out = True
                self.base_angle += random()
                self.base_angle = self.base_angle % (2 * math.pi)

        self.ignore_list.clear()  # Clear ignore list upon full Ark sync
        self.obtained_species.update(ark_set)

    def _is_species_needed(self, species_id: int, gender: Gender) -> bool:
        """
        Checks if an animal is needed based on gender.
        """
        if species_id in self.ignore_list:
            return False
        if gender == Gender.Unknown:
            male_obtained = (species_id, Gender.Male) in self.obtained_species
            female_obtained = (species_id, Gender.Female) in self.obtained_species
            return not (male_obtained and female_obtained)
        else:
            return (species_id, gender) not in self.obtained_species

    def _get_move_to_target(
        self, current_pos: Tuple[float, float], target_pos: Tuple[float, float]
    ) -> Move:
        """Calculates a 1km move towards the target."""
        dx = target_pos[0] - current_pos[0]
        dy = target_pos[1] - current_pos[1]

        dist = self._get_distance(current_pos, target_pos)

        # if at target, just return target pos
        if dist < c.EPS:
            return Move(x=target_pos[0], y=target_pos[1])

        move_dist = min(dist, c.MAX_DISTANCE_KM)

        new_x = current_pos[0] + (dx / dist) * move_dist
        new_y = current_pos[1] + (dy / dist) * move_dist

        return Move(x=new_x, y=new_y)

    def _get_new_random_target(self, current_pos: Tuple[float, float]) -> Move:
        """Picks a new 150km point for the triangle exploration."""
        current_x, current_y = current_pos
        prev_x, prev_y = self.previous_position

        prev_dx = current_x - prev_x
        prev_dy = current_y - prev_y

        max_tries = 150
        for _ in range(max_tries):
            angle = random() * 2 * math.pi
            target_x = current_x + math.cos(angle) * TARGET_POINT_DISTANCE
            target_y = current_y + math.sin(angle) * TARGET_POINT_DISTANCE
            target_pos = (target_x, target_y)

            if self._get_distance(target_pos, self.ark_pos) > 1000.0:
                continue
            if not (
                MIN_MAP_COORD <= target_x <= MAX_MAP_COORD
                and MIN_MAP_COORD <= target_y <= MAX_MAP_COORD
            ):
                continue

            new_dx = target_x - current_x
            new_dy = target_y - current_y
            dot_product = prev_dx * new_dx + prev_dy * new_dy
            mag_prev = math.sqrt(prev_dx**2 + prev_dy**2)
            mag_new = math.sqrt(new_dx**2 + new_dy**2)

            if mag_prev < c.EPS or mag_new < c.EPS:
                self.current_target_pos = target_pos
                return self._get_move_to_target(current_pos, target_pos)

            cos_angle = dot_product / (mag_prev * mag_new)
            cos_angle = max(-1.0, min(1.0, cos_angle))
            angle_diff = math.acos(cos_angle)

            if not (BACKTRACK_MIN_ANGLE <= angle_diff <= BACKTRACK_MAX_ANGLE):
                self.current_target_pos = target_pos
                return self._get_move_to_target(current_pos, target_pos)

        if self.current_target_pos:
            return self._get_move_to_target(current_pos, self.current_target_pos)

        return Move(x=current_x + random() - 0.5, y=current_y + random() - 0.5)

    def _get_return_move(
        self, current_pos: Tuple[float, float], direct: bool = False
    ) -> Move:
        """Calculates a move to return to the Ark.

        Args:
            current_pos: Current position
            direct: If True, go straight to ark. If False, spiral/arc toward ark to explore.
        """
        current_dist_to_ark = self._get_distance(current_pos, self.ark_pos)

        if direct or current_dist_to_ark <= NEAR_ARK_DISTANCE:
            self.current_target_pos = self.ark_pos
            return self._get_move_to_target(current_pos, self.ark_pos)
        # spiral approach
        else:
            # calc angle from ark to current position
            dx = current_pos[0] - self.ark_pos[0]
            dy = current_pos[1] - self.ark_pos[1]
            current_angle = math.atan2(dy, dx)

            # add perpendicular offset to create arc offset based on helper ID for variety
            arc_offset = math.radians(30) * (1 if self.id % 2 == 0 else -1)
            spiral_angle = current_angle + arc_offset

            # move toward ark but offset to the side 90% of current distance in spiral direction
            target_dist = current_dist_to_ark * 0.9
            target_x = self.ark_pos[0] + math.cos(spiral_angle) * target_dist
            target_y = self.ark_pos[1] + math.sin(spiral_angle) * target_dist

            target_x = max(MIN_MAP_COORD, min(MAX_MAP_COORD, target_x))
            target_y = max(MIN_MAP_COORD, min(MAX_MAP_COORD, target_y))

            self.current_target_pos = (target_x, target_y)
            return self._get_move_to_target(current_pos, (target_x, target_y))

    def _find_needed_animal_in_sight(self) -> Optional[CellView]:
        """Scans sight for an animal that is NOT shepherded and is still needed."""
        for cell_view in self.sight:
            # Skip the helper's own cell (handled by immediate obtain logic below)
            if self.position_is_in_cell(cell_view.x, cell_view.y):
                continue

            # Avoid targeting cells that are already beyond the 1000-unit
            # safe radius from the Ark.
            cell_center = (cell_view.x + 0.5, cell_view.y + 0.5)
            if self._get_distance(cell_center, self.ark_pos) > 1000.0:
                continue

            if not cell_view.helpers:
                for animal in cell_view.animals:
                    # Check if EITHER gender is missing for the species
                    if self._is_species_needed(animal.species_id, Gender.Unknown):
                        return cell_view

        return None

    def position_is_in_cell(self, cell_x: int, cell_y: int) -> bool:
        """Checks if the helper's position is within the specified cell."""
        current_x, current_y = self.position
        return int(current_x) == cell_x and int(current_y) == cell_y

    def _get_turns_remaining_until_end(self) -> Optional[int]:
        """
        return turns remaining until simulation ends, or None if not raining yet
        """
        if not self.is_raining or self.rain_start_time is None:
            return None

        turns_since_rain = self.time_elapsed - self.rain_start_time

        return c.START_RAIN - turns_since_rain

    def _get_turns_to_reach_ark(
        self, from_pos: Optional[Tuple[float, float]] = None
    ) -> int:
        """
        calc min turns needed to reach ark from current or given position
        """
        pos = from_pos if from_pos else self.position
        distance = self._get_distance(pos, self.ark_pos)

        return int(math.ceil(distance / c.MAX_DISTANCE_KM))

    # --- Core Methods ---

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot):
        self.position = snapshot.position
        self.sight = snapshot.sight

        # track when rain starts
        if snapshot.is_raining and not self.is_raining:
            self.rain_start_time = snapshot.time_elapsed

        self.is_raining = snapshot.is_raining
        self.time_elapsed = snapshot.time_elapsed

        # track if at ark
        self.at_ark = snapshot.ark_view is not None

        # --- CRITICAL FIX 1: Update self.flock from the snapshot ---
        self.flock = snapshot.flock.copy()

        if self.kind != Kind.Noah:
            # Update based on confirmed Ark list (only when Ark view is available)
            if snapshot.ark_view:
                self._update_obtained_species_from_ark(snapshot.ark_view.animals)

            # CRITICAL FIX 2: Update obtained_species based on the fresh self.flock contents every turn
            for animal in self.flock:
                if animal.gender != Gender.Unknown:
                    self.obtained_species.add((animal.species_id, animal.gender))

        self.previous_position = self.position

        # Clear target if we were chasing and are now in the *old* target cell
        if self.animal_target_cell and self.position_is_in_cell(
            self.animal_target_cell.x, self.animal_target_cell.y
        ):
            self.animal_target_cell = None

        return 0

    def get_action(self, messages: list[Message]) -> Action | None:
        # --- TURN-BASED ACTION: Clear ignore_list every 250 turns ---
        if self.time_elapsed > 0 and self.time_elapsed % 250 == 0:
            self.ignore_list.clear()
        if self.time_elapsed % 1000 == 0:
            self.max_explore_dis += 100

        # Noah doesn't act
        if self.kind == Kind.Noah:
            return None

        current_x, current_y = self.position
        current_pos = (current_x, current_y)

        # Hard safety cap: if we're already beyond the 1000-unit radius from
        # the Ark, abandon any active targets and return directly toward the Ark.
        # If it is raining, must return immediately and DIRECTLY if cutting it close
        if self._get_distance(current_pos, self.ark_pos) > 1000.0:
            self.animal_target_cell = None
            self.current_target_pos = None
            return self._get_return_move(current_pos, direct=True)
        if self.is_raining:
            turns_remaining = self._get_turns_remaining_until_end()
            turns_needed = self._get_turns_to_reach_ark()

            if turns_remaining is not None:
                time_buffer = turns_remaining - turns_needed
                distance_to_ark = self._get_distance(current_pos, self.ark_pos)

                # must return immediately and DIRECTLY if cutting it close
                if time_buffer < 3:
                    return self._get_return_move(current_pos, direct=True)

        # --- HIGHEST PRIORITY: RELEASE INTERNAL FLOCK DUPLICATES ---
        flock_keys = [(a.species_id, a.gender) for a in self.flock]

        duplicate_to_release = next(
            (
                animal
                for animal in self.flock
                if flock_keys.count((animal.species_id, animal.gender)) > 1
            ),
            None,
        )

        if duplicate_to_release:
            self.ignore_list.append(duplicate_to_release.species_id)
            self.animal_target_cell = None
            return Release(animal=duplicate_to_release)

        # --- NEXT PRIORITY: IMMEDIATE OBTAIN IN CURRENT CELL ---
        if len(self.flock) >= c.MAX_FLOCK_SIZE:
            return self._get_return_move(current_pos, direct=True)
        else:
            current_cell_x, current_cell_y = int(current_x), int(current_y)

            try:
                current_cell_view = self.sight.get_cellview_at(
                    current_cell_x, current_cell_y
                )
            except Exception:
                current_cell_view = None

            if current_cell_view and current_cell_view.animals:
                # Filter out animals already in the helper's flock
                obtainable_animals = [
                    animal
                    for animal in current_cell_view.animals
                    if animal not in self.flock
                ]

                if obtainable_animals:
                    # Find the first obtainable animal in the current cell
                    animal_to_obtain = next(iter(obtainable_animals))
                    self.animal_target_cell = None
                    return Obtain(animal=animal_to_obtain)

                # If no animals are left after filtering, clear target
                else:
                    self.animal_target_cell = None

        # 1. Targeted Animal Collection Phase (Handles moving TO the target cell)

        if self.animal_target_cell:
            target_cell_x, target_cell_y = (
                self.animal_target_cell.x,
                self.animal_target_cell.y,
            )

            target_cell_center = (target_cell_x + 0.5, target_cell_y + 0.5)
            # If the chase target lies outside the allowed radius, abandon it
            # and head back toward the Ark instead.
            if self._get_distance(target_cell_center, self.ark_pos) > 1000.0:
                self.animal_target_cell = None
                self.current_target_pos = None
                return self._get_return_move(current_pos, direct=False)

            return self._get_move_to_target(current_pos, target_cell_center)

        # Scan for new animal target
        if len(self.flock) < c.MAX_FLOCK_SIZE:
            new_target_cell = self._find_needed_animal_in_sight()
            if new_target_cell:
                target_cell_center = (new_target_cell.x + 0.5, new_target_cell.y + 0.5)
                # Only commit to a chase target that keeps us within 1000 units
                # of the Ark.
                if self._get_distance(target_cell_center, self.ark_pos) <= 1000.0:
                    self.animal_target_cell = new_target_cell
                    return self._get_move_to_target(current_pos, target_cell_center)

        # 2. Movement Phase (Return or Explore)
        if self.is_raining:
            turns_remaining = self._get_turns_remaining_until_end()
            turns_needed = self._get_turns_to_reach_ark()

            if turns_remaining is not None:
                time_buffer = turns_remaining - turns_needed
                distance_to_ark = self._get_distance(current_pos, self.ark_pos)

                if distance_to_ark < 200 and time_buffer > 200:
                    # if flock is full, drop them off and go back out
                    if len(self.flock) >= 3:
                        return self._get_return_move(current_pos, direct=True)

                # medium distance with decent time
                elif distance_to_ark < 500 and time_buffer > 100:
                    # if actively chasing an animal and it's close, finish getting it
                    if self.animal_target_cell and len(self.flock) < c.MAX_FLOCK_SIZE:
                        target_dist = self._get_distance(
                            current_pos,
                            (
                                self.animal_target_cell.x + 0.5,
                                self.animal_target_cell.y + 0.5,
                            ),
                        )

                        if target_dist < 15:
                            # continue to animal targeting logic below
                            pass
                        else:
                            self.animal_target_cell = None
                            return self._get_return_move(current_pos, direct=False)
                    else:
                        # no active target. return using spiral path
                        return self._get_return_move(current_pos, direct=False)

                # far or no time, return immediately and directly
                else:
                    return self._get_return_move(current_pos, direct=True)

        # Loaded Return
        if len(self.flock) >= 3:
            return self._get_return_move(current_pos)

        # Exploration Logic (Fan-out or Triangle)
        if (
            self.is_in_ark()
            or self.current_target_pos is None
            or self._get_distance(current_pos, self.current_target_pos)
            < c.MAX_DISTANCE_KM
        ):
            if self.is_exploring_fan_out:
                angle = self.base_angle
                new_x = current_x + math.cos(angle) * c.MAX_DISTANCE_KM
                new_y = current_y + math.sin(angle) * c.MAX_DISTANCE_KM

                if (
                    not (
                        MIN_MAP_COORD <= new_x <= MAX_MAP_COORD
                        and MIN_MAP_COORD <= new_y <= MAX_MAP_COORD
                    )
                ) or self._get_distance(
                    (new_x, new_y), self.ark_pos
                ) > self.max_explore_dis:
                    self.is_exploring_fan_out = False
                    return self._get_new_random_target(current_pos)

                self.current_target_pos = (new_x, new_y)
                return Move(x=new_x, y=new_y)
            else:
                return self._get_new_random_target(current_pos)

        # Continue movement
        # If the currently set exploration target would place us outside the
        # allowed radius, abandon it and head back to the Ark.
        if (
            self.current_target_pos is not None
            and self._get_distance(self.current_target_pos, self.ark_pos) > 1000.0
        ):
            self.current_target_pos = None
            return self._get_return_move(current_pos, direct=False)

        return self._get_move_to_target(current_pos, self.current_target_pos)
