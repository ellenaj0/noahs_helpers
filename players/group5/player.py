from random import random, choice
from core.action import Action, Move, Obtain, Release
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView
from core.animal import Gender
import core.constants as c
import math
from typing import Set, Tuple, List, Optional

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
        self.base_angle = (2 * math.pi * (self.id - 1)) / int(h)
        self.is_exploring_fan_out = True

        # hopefully this is temporary...
        self.time_elapsed = 0
        self.ignore_list = []

    # --- Player5 Helper Methods ---

    def _get_distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """Calculates Euclidean distance between two points."""
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def _update_obtained_species(self, ark_animals: Set):
        """
        Updates the set of species/genders already saved on the Ark.
        This updates the list based on the Ark's view, ensuring external knowledge is captured.
        """
        # Create a set of newly observed species/genders from the Ark's current view
        ark_set: Set[SpeciesGender] = set()
        for animal in ark_animals:
            if animal.gender != Gender.Unknown:
                ark_set.add((animal.species_id, animal.gender))

        print(sorted(ark_set, key=lambda x: x[0]))
        print("------")
        # Merge Ark's list into helper's memory
        self.ignore_list.clear()
        self.obtained_species.update(ark_set)

    def _is_species_needed(self, species_id: int, gender: Gender) -> bool:
        """
        Checks if an animal is needed based on gender.
        Needed if the species/gender pair is NOT in self.obtained_species.
        """
        if species_id in self.ignore_list:
            return False
        if gender == Gender.Unknown:
            # Needed if AT LEAST ONE gender is missing (NOT both obtained)
            male_obtained = (species_id, Gender.Male) in self.obtained_species
            female_obtained = (species_id, Gender.Female) in self.obtained_species
            return not (male_obtained and female_obtained)
        else:
            # Needed if the specific known gender is missing
            return (species_id, gender) not in self.obtained_species

    def _get_move_to_target(
        self, current_pos: Tuple[float, float], target_pos: Tuple[float, float]
    ) -> Move:
        """Calculates a 1km move towards the target."""
        dx = target_pos[0] - current_pos[0]
        dy = target_pos[1] - current_pos[1]

        dist = self._get_distance(current_pos, target_pos)

        if dist < c.EPS:
            return self._get_new_random_target(current_pos)

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

        max_tries = 20
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

    def _get_return_move(self, current_pos: Tuple[float, float]) -> Move:
        """Calculates a move to return to the Ark (indirectly if far, directly if near)."""
        current_dist_to_ark = self._get_distance(current_pos, self.ark_pos)

        if current_dist_to_ark <= NEAR_ARK_DISTANCE:
            self.current_target_pos = self.ark_pos
            return self._get_move_to_target(current_pos, self.ark_pos)
        else:
            max_tries = 20
            for _ in range(max_tries):
                target_x = random() * (MAX_MAP_COORD - MIN_MAP_COORD) + MIN_MAP_COORD
                target_y = random() * (MAX_MAP_COORD - MIN_MAP_COORD) + MIN_MAP_COORD
                target_pos = (target_x, target_y)

                dist_target_to_ark = self._get_distance(target_pos, self.ark_pos)
                if dist_target_to_ark < current_dist_to_ark:
                    self.current_target_pos = target_pos
                    return self._get_move_to_target(current_pos, target_pos)

            self.current_target_pos = self.ark_pos
            return self._get_move_to_target(current_pos, self.ark_pos)

    def _find_needed_animal_in_sight(self) -> Optional[CellView]:
        """Scans sight for an animal that is NOT shepherded and is still needed."""
        for cell_view in self.sight:
            # Skip the helper's own cell (handled by immediate obtain logic below)
            if self.position_is_in_cell(cell_view.x, cell_view.y):
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

    # --- Core Methods ---

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot):
        self.position = snapshot.position
        self.sight = snapshot.sight
        self.is_raining = snapshot.is_raining

        if self.kind != Kind.Noah and snapshot.ark_view:
            self._update_obtained_species(snapshot.ark_view.animals)

        self.previous_position = self.position

        # Clear target if we were chasing and are now in the *old* target cell (it should be caught or moved)
        if self.animal_target_cell and self.position_is_in_cell(
            self.animal_target_cell.x, self.animal_target_cell.y
        ):
            self.animal_target_cell = None

        return 0

    # we really don't need this if the simulator works as intended... or im just dumb
    def _add_flock_to_obtained_species(self):
        """Adds all animals currently in the helper's flock to the obtained_species set."""
        for animal in self.flock:
            # Animals in the flock should always have a known gender
            if animal.gender != Gender.Unknown:
                self.obtained_species.add((animal.species_id, animal.gender))

    def get_action(self, messages: list[Message]) -> Action | None:
        self.time_elapsed += 1
        # Noah doesn't act
        if self.kind == Kind.Noah:
            return None

        current_x, current_y = self.position
        current_pos = (current_x, current_y)

        self._add_flock_to_obtained_species()

        flock_keys = [(a.species_id, a.gender) for a in self.flock]

        # Find the first animal 'a' in the flock whose (species_id, gender) key count is > 1.
        # If found, set the action to Release(animal=a).

        if self.time_elapsed % 250 == 0:
            # Assumes self.ignore_list is a set[int]
            self.ignore_list.clear()

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
            return Release(animal=duplicate_to_release)
        """
        if len(self.flock) >= 4:
            for animal in list(self.flock):
                species_id = animal.species_id
                
                male_obtained = (species_id, Gender.Male) in self.obtained_species
                female_obtained = (species_id, Gender.Female) in self.obtained_species
                
                if male_obtained and female_obtained:
                    self.animal_target_cell = None
                    return Release(animal=animal) 
        print(self.obtained_species)
        print(self.flock)
        print(self.id)
        print(self.ignore_list)
        print("------")"""

        # --- NEXT PRIORITY: IMMEDIATE OBTAIN IN CURRENT CELL (AND UPDATE STATE) ---
        if len(self.flock) < c.MAX_FLOCK_SIZE:
            current_cell_x, current_cell_y = int(current_x), int(current_y)

            try:
                current_cell_view = self.sight.get_cellview_at(
                    current_cell_x, current_cell_y
                )
            except Exception:
                current_cell_view = None

            if current_cell_view and current_cell_view.animals:
                # Find the first obtainable animal in the current cell
                animal_to_obtain = next(iter(current_cell_view.animals))

                is_needed = self._is_species_needed(
                    animal_to_obtain.species_id, animal_to_obtain.gender
                )

                # if is_needed:
                # FIX: Update the helper's memory immediately upon successful capture request
                # self.obtained_species.add((animal_to_obtain.species_id, animal_to_obtain.gender))
                # if is_needed: #I hate evenrything
                self.animal_target_cell = None
                return Obtain(animal=animal_to_obtain)

                # If it's a duplicate, we don't obtain it, but we still clear the chase target
                self.animal_target_cell = None

        # 1. Targeted Animal Collection Phase (Handles moving TO the target cell)

        if self.animal_target_cell:
            target_cell_x, target_cell_y = (
                self.animal_target_cell.x,
                self.animal_target_cell.y,
            )

            # This handles the movement toward the target cell center
            target_cell_center = (target_cell_x + 0.5, target_cell_y + 0.5)
            return self._get_move_to_target(current_pos, target_cell_center)

        # Scan for new animal target
        if len(self.flock) < c.MAX_FLOCK_SIZE:
            new_target_cell = self._find_needed_animal_in_sight()
            if new_target_cell:
                self.animal_target_cell = new_target_cell
                target_cell_center = (new_target_cell.x + 0.5, new_target_cell.y + 0.5)
                return self._get_move_to_target(current_pos, target_cell_center)

        # 2. Movement Phase (Return or Explore)

        # Emergency Rain Return
        if self.is_raining and self.time_elapsed >= self.time - c.START_RAIN:
            return self._get_return_move(current_pos)

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
                ) or self._get_distance((new_x, new_y), self.ark_pos) > 1000.0:
                    self.is_exploring_fan_out = False
                    return self._get_new_random_target(current_pos)

                self.current_target_pos = (new_x, new_y)
                return Move(x=new_x, y=new_y)
            else:
                return self._get_new_random_target(current_pos)

        # Continue movement
        return self._get_move_to_target(current_pos, self.current_target_pos)
