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
from typing import Set, Tuple, Optional, List, Dict
from operator import itemgetter

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
        super().__init__(id, ark_x, ark_y, kind, num_helpers, species_populations)

        self.species_stats = species_populations
        self.num_helpers = num_helpers

        if not hasattr(self, "id_to_species"):
            sorted_names = sorted(self.species_stats.keys())
            self.id_to_species: Dict[int, str] = {
                i: name for i, name in enumerate(sorted_names)
            }

        self.species_to_id: Dict[str, int] = {
            name: id_val for id_val, name in self.id_to_species.items()
        }

        self.ark_pos = (float(ark_x), float(ark_y))

        self.obtained_species: Set[SpeciesGender] = set()
        self.current_target_pos: Optional[Tuple[float, float]] = None
        self.previous_position: Tuple[float, float] = self.position
        self.animal_target_cell: Optional[CellView] = None

        self.grid_cell_size = 50.0
        self.grid_width = int(
            math.ceil((MAX_MAP_COORD - MIN_MAP_COORD + 1) / self.grid_cell_size)
        )
        self.grid_height = int(
            math.ceil((MAX_MAP_COORD - MIN_MAP_COORD + 1) / self.grid_cell_size)
        )

        num_active_helpers = max(1, num_helpers - 1)

        self.region_rows = int(math.sqrt(num_active_helpers))
        self.region_cols = int(math.ceil(num_active_helpers / self.region_rows))

        if self.id > 0:
            self.assigned_region_id = (self.id - 1) % (
                self.region_rows * self.region_cols
            )
        else:
            self.assigned_region_id = None
        if self.assigned_region_id is not None:
            region_row = self.assigned_region_id // self.region_cols
            region_col = self.assigned_region_id % self.region_cols

            base_width_in_cells = self.grid_width // self.region_cols
            base_height_in_cells = self.grid_height // self.region_rows

            extra_width_cells = self.grid_width % self.region_cols
            extra_height_cells = self.grid_height % self.region_rows

            if region_col < extra_width_cells:
                region_start_col = region_col * (base_width_in_cells + 1)
                region_width_in_cells = base_width_in_cells + 1
            else:
                region_start_col = (
                    extra_width_cells * (base_width_in_cells + 1)
                    + (region_col - extra_width_cells) * base_width_in_cells
                )
                region_width_in_cells = base_width_in_cells

            if region_row < extra_height_cells:
                region_start_row = region_row * (base_height_in_cells + 1)
                region_height_in_cells = base_height_in_cells + 1
            else:
                region_start_row = (
                    extra_height_cells * (base_height_in_cells + 1)
                    + (region_row - extra_height_cells) * base_height_in_cells
                )
                region_height_in_cells = base_height_in_cells

            self.region_min_x = float(
                MIN_MAP_COORD + region_start_col * self.grid_cell_size
            )
            self.region_max_x = float(
                MIN_MAP_COORD
                + (region_start_col + region_width_in_cells) * self.grid_cell_size
            )
            self.region_min_y = float(
                MIN_MAP_COORD + region_start_row * self.grid_cell_size
            )
            self.region_max_y = float(
                MIN_MAP_COORD
                + (region_start_row + region_height_in_cells) * self.grid_cell_size
            )

            self.region_center_x = (self.region_min_x + self.region_max_x) / 2
            self.region_center_y = (self.region_min_y + self.region_max_y) / 2

            region_center_dist = math.sqrt(
                (self.region_center_x - ark_x) ** 2
                + (self.region_center_y - ark_y) ** 2
            )

            # If region unreachable (>1000 units), skip region navigation
            if region_center_dist > 1000.0:
                print("WARNING: Region unreachable, skipping to exploration")
                self.has_reached_region = True
            else:
                self.has_reached_region = False
            self.saved_exploration_pos: Optional[Tuple[float, float]] = None
        else:
            self.region_min_x = MIN_MAP_COORD
            self.region_max_x = MAX_MAP_COORD
            self.region_min_y = MIN_MAP_COORD
            self.region_max_y = MAX_MAP_COORD
            self.region_center_x = 500.0
            self.region_center_y = 500.0
            self.has_reached_region = True
            self.saved_exploration_pos = None

        h = num_helpers
        if self.id > 0:
            self.base_angle = (2 * math.pi * (self.id - 1)) / (int(h) - 1)
        else:
            self.base_angle = 0
        self.is_exploring_fan_out = True

        self.ignore_list = []
        num_searching_helpers = max(1, num_helpers - 1)
        self.max_explore_dis = 100 + max(0, (5 - num_searching_helpers) * 40)
        self.max_explore_dis = min(400, self.max_explore_dis)

        self.visited_grid_cells: Dict[Tuple[int, int], int] = {}
        self.recent_positions: List[Tuple[float, float]] = []
        self.max_recent_positions = 20

        self.is_specialized = True
        self.specialization_limit = 0
        self.specialization_target_species: List[str] = []
        self.to_search_list: List[SpeciesGender] = []

        self._assign_specialization()

    def _assign_specialization(self):
        if self.id in [1, 2]:
            self.is_specialized = False
            self.specialization_limit = 0
            self.specialization_target_species = []
            return

        species_list = sorted(
            [(name, count) for name, count in self.species_stats.items()],
            key=itemgetter(1),
        )

        total_population = sum(count for _, count in species_list)

        # NEW CODE
        if species_list:
            smallest_count = species_list[0][1]  # First item (e.g., 20)
            biggest_count = species_list[-1][1]  # Last item (e.g., 200)

            # If smallest is <= half of the biggest, we stop specialization
            if smallest_count >= (biggest_count * 0.5):
                self.is_specialized = False
                self.specialization_limit = 0
                self.specialization_target_species = []
                return

        if total_population == 0:
            self.is_specialized = False
            self.specialization_limit = 0
            self.specialization_target_species = []
            return

        if len(species_list) > self.num_helpers * 50:
            self.is_specialized = False
            self.specialization_limit = 0
            self.specialization_target_species = []
            return

        specializations_map: Dict[int, List[str]] = {}
        population_percentages = [0.25, 0.10, 0.05, 0.02]
        specialization_limits = [1000, 2000, 3000, 4000]

        for i, percent in enumerate(population_percentages):
            target_population = total_population * percent
            current_cumulative_population = 0
            target_species_names = []

            for species_name, count in species_list:
                if current_cumulative_population < target_population:
                    target_species_names.append(species_name)
                    current_cumulative_population += count
                else:
                    break

            limit_id = specialization_limits[i]
            specializations_map[limit_id] = target_species_names

        num_specialized_helpers = self.num_helpers - 2
        group_id = self.id - 2
        group_percentages = [0.20, 0.20, 0.20, 0.40]

        group_sizes = []
        current_cumulative_size = 0

        for i in range(len(group_percentages)):
            size = math.ceil(num_specialized_helpers * group_percentages[i])
            if i == len(group_percentages) - 1:
                size = max(0, num_specialized_helpers - current_cumulative_size)
            current_cumulative_size += size
            group_sizes.append(size)

        cumulative_helper_count = 0
        assigned_limit = None

        for i, size in enumerate(group_sizes):
            start_id = cumulative_helper_count + 1
            end_id = cumulative_helper_count + size

            if start_id <= group_id <= end_id:
                assigned_limit = specialization_limits[i]
                break

            cumulative_helper_count += size

        if assigned_limit is not None and assigned_limit in specializations_map:
            self.is_specialized = True
            self.specialization_limit = assigned_limit
            self.specialization_target_species = specializations_map.get(
                assigned_limit, []
            )
        else:
            self.is_specialized = False
            self.specialization_limit = 0
            self.specialization_target_species = []

        self._update_to_search_list()

    def _update_to_search_list(self):
        final_search_list: List[SpeciesGender] = []

        if (
            self.is_specialized
            and hasattr(self, "specialization_target_species")
            and self.specialization_target_species
        ):
            for species_name in self.specialization_target_species:
                species_id = self.species_to_id.get(species_name)
                if species_id is None:
                    continue

                male_needed = (species_id, Gender.Male) not in self.obtained_species
                if male_needed:
                    final_search_list.append((species_id, Gender.Male))

                female_needed = (species_id, Gender.Female) not in self.obtained_species
                if female_needed:
                    final_search_list.append((species_id, Gender.Female))

        species_info: List[Tuple[int, int]] = []
        for name, count in self.species_stats.items():
            species_id = self.species_to_id[name]
            species_info.append((count, species_id))

        species_info.sort()

        for count, species_id in species_info:
            if len(final_search_list) >= 6:
                break

            if (species_id, Gender.Male) not in self.obtained_species and (
                species_id,
                Gender.Male,
            ) not in final_search_list:
                final_search_list.append((species_id, Gender.Male))

            if (species_id, Gender.Female) not in self.obtained_species and (
                species_id,
                Gender.Female,
            ) not in final_search_list:
                final_search_list.append((species_id, Gender.Female))

        self.to_search_list = final_search_list

    def _get_distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def _is_in_assigned_region(self, x: float, y: float) -> bool:
        if self.assigned_region_id is None:
            return True
        return (
            self.region_min_x <= x < self.region_max_x
            and self.region_min_y <= y < self.region_max_y
        )

    def _update_obtained_species_from_ark(self, ark_animals: Set):
        ark_set: Set[SpeciesGender] = set()
        for animal in ark_animals:
            if animal.gender != Gender.Unknown:
                ark_set.add((animal.species_id, animal.gender))
                self.is_exploring_fan_out = True
                self.base_angle += random()
                self.base_angle = self.base_angle % (2 * math.pi)

        self.ignore_list.clear()
        self.obtained_species.update(ark_set)

        is_returning_after_1000 = self.is_specialized and self.time_elapsed > 1000

        if is_returning_after_1000:
            print(
                f"Helper {self.id} is switching out of specialization mode after turn {self.time_elapsed}."
            )
            self.is_specialized = False
            self.specialization_limit = 0
            self.specialization_target_species = []
            self.to_search_list.clear()

        if self.is_specialized and len(self.to_search_list) < 6:
            self._update_to_search_list()

    def _is_species_needed(self, species_id: int, gender: Gender) -> bool:
        if species_id in self.ignore_list:
            return False

        if self.is_specialized:
            if gender != Gender.Unknown:
                if (species_id, gender) not in self.to_search_list:
                    return False
            else:
                is_target = any(s_id == species_id for s_id, _ in self.to_search_list)
                if not is_target:
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
        dx = target_pos[0] - current_pos[0]
        dy = target_pos[1] - current_pos[1]
        dist = self._get_distance(current_pos, target_pos)

        if dist < c.EPS:
            return Move(x=target_pos[0], y=target_pos[1])

        move_dist = min(dist, c.MAX_DISTANCE_KM)
        new_x = current_pos[0] + (dx / dist) * move_dist
        new_y = current_pos[1] + (dy / dist) * move_dist

        return Move(x=new_x, y=new_y)

    def _get_grid_cell(self, x: float, y: float) -> Tuple[int, int]:
        grid_x = int((x - MIN_MAP_COORD) / self.grid_cell_size)
        grid_y = int((y - MIN_MAP_COORD) / self.grid_cell_size)
        grid_x = max(0, min(self.grid_width - 1, grid_x))
        grid_y = max(0, min(self.grid_height - 1, grid_y))
        return (grid_x, grid_y)

    def _get_grid_center(self, grid_x: int, grid_y: int) -> Tuple[float, float]:
        center_x = MIN_MAP_COORD + (grid_x + 0.5) * self.grid_cell_size
        center_y = MIN_MAP_COORD + (grid_y + 0.5) * self.grid_cell_size
        return (center_x, center_y)

    def _update_visited_grid_cell(self, position: Tuple[float, float]):
        grid_x, grid_y = self._get_grid_cell(position[0], position[1])
        self.visited_grid_cells[(grid_x, grid_y)] = (
            self.visited_grid_cells.get((grid_x, grid_y), 0) + 1
        )

        self.recent_positions.append(position)
        if len(self.recent_positions) > self.max_recent_positions:
            self.recent_positions.pop(0)

    def _get_cell_visit_score(self, grid_x: int, grid_y: int) -> float:
        visit_count = self.visited_grid_cells.get((grid_x, grid_y), 0)
        if visit_count == 0:
            return 0.0
        return min(1.0, 0.3 + (visit_count - 1) * 0.15)

    def _get_distance_to_recent_positions(self, x: float, y: float) -> float:
        if not self.recent_positions:
            return 0.0

        min_dist = float("inf")
        for pos in self.recent_positions:
            dist = self._get_distance((x, y), pos)
            min_dist = min(min_dist, dist)

        return min_dist

    def _get_strategic_target(
        self, current_pos: Tuple[float, float]
    ) -> Tuple[float, float]:
        current_x, current_y = current_pos
        prev_x, prev_y = self.previous_position

        prev_dx = current_x - prev_x
        prev_dy = current_y - prev_y
        prev_mag = (
            math.sqrt(prev_dx**2 + prev_dy**2)
            if (prev_dx != 0 or prev_dy != 0)
            else 1.0
        )

        candidates: List[Tuple[int, int, float]] = []

        num_searching_helpers = max(1, self.num_helpers - 1)
        base_radius = 3
        search_radius = int(base_radius + max(0, (5 - num_searching_helpers) * 0.3))
        search_radius = max(3, min(6, search_radius))

        current_grid_x, current_grid_y = self._get_grid_cell(current_x, current_y)
        for dx in range(-search_radius, search_radius + 1):
            for dy in range(-search_radius, search_radius + 1):
                grid_x = current_grid_x + dx
                grid_y = current_grid_y + dy

                # Skip invalid grid cells
                if (
                    grid_x < 0
                    or grid_x >= self.grid_width
                    or grid_y < 0
                    or grid_y >= self.grid_height
                ):
                    continue

                # Get world coordinates of grid cell center
                cell_center_x, cell_center_y = self._get_grid_center(grid_x, grid_y)
                cell_pos = (cell_center_x, cell_center_y)

                # Check bounds and ark distance constraints
                if not (
                    MIN_MAP_COORD <= cell_center_x <= MAX_MAP_COORD
                    and MIN_MAP_COORD <= cell_center_y <= MAX_MAP_COORD
                ):
                    continue

                # Strict 1000 unit limit after turn 1000, slightly more lenient before
                max_allowed_distance = 950.0 if self.time_elapsed >= 1000 else 1000.0
                if self._get_distance(cell_pos, self.ark_pos) > max_allowed_distance:
                    continue

                # Calculate distance from current position
                dist_to_cell = self._get_distance(current_pos, cell_pos)

                # Skip cells that are too close (already explored)
                if dist_to_cell < 20.0:
                    continue

                # Calculate score components
                visit_score = self._get_cell_visit_score(
                    grid_x, grid_y
                )  # 0.0 = unvisited, 1.0 = heavily visited
                distance_to_recent = self._get_distance_to_recent_positions(
                    cell_center_x, cell_center_y
                )

                # Calculate distance from ark
                distance_from_ark = self._get_distance(cell_pos, self.ark_pos)

                # Prefer cells that are:
                # 1. Less visited (lower visit_score)
                # 2. Further from recently visited areas (higher distance_to_recent)
                # 3. At reasonable distance (not too close, not too far)
                # 4. Further from ark (especially when few helpers)
                # 5. Not backtracking (angle check)

                # Base score: inverse of visit frequency (unvisited = high score)
                base_score = 1.0 - visit_score

                # Distance bonus: prefer cells further from recent positions
                recent_bonus = min(1.0, distance_to_recent / 100.0)  # Normalize to 0-1

                # Distance penalty: prefer cells around TARGET_POINT_DISTANCE away
                ideal_distance = TARGET_POINT_DISTANCE
                distance_penalty = (
                    1.0 - abs(dist_to_cell - ideal_distance) / ideal_distance
                )
                distance_penalty = max(0.0, distance_penalty)  # Clamp to 0-1

                # Distance from ark bonus: encourage exploring further from ark
                # After turn 1000, use stricter limit to prevent going too far
                max_ark_distance = 950.0 if self.time_elapsed >= 1000 else 1000.0
                ark_distance_score = distance_from_ark / max_ark_distance

                # When there are fewer helpers, we need to explore further out
                # Adjust the weight based on number of helpers (excluding Noah)
                # After turn 1000, reduce the weight to discourage going too far
                num_searching_helpers = max(1, self.num_helpers - 1)  # Exclude Noah
                # With 2 helpers, weight is 0.5; with 10 helpers, weight is 0.1
                # This means fewer helpers = stronger push to explore far
                base_weight = max(0.1, 0.6 - (num_searching_helpers - 1) * 0.05)
                # After turn 1000, reduce weight by 50% to be more conservative
                if self.time_elapsed >= 1000:
                    base_weight *= 0.5
                ark_distance_weight = min(0.5, base_weight)  # Cap at 0.5

                # Combined score with adaptive ark distance weighting
                score = (
                    base_score * 0.4
                    + recent_bonus * 0.25
                    + distance_penalty * 0.15
                    + ark_distance_score * ark_distance_weight
                )

                # Check backtracking angle (if we have previous movement)
                if prev_mag > c.EPS:
                    new_dx = cell_center_x - current_x
                    new_dy = cell_center_y - current_y
                    new_mag = math.sqrt(new_dx**2 + new_dy**2)

                    if new_mag > c.EPS:
                        dot_product = prev_dx * new_dx + prev_dy * new_dy
                        cos_angle = dot_product / (prev_mag * new_mag)
                        cos_angle = max(-1.0, min(1.0, cos_angle))
                        angle_diff = math.acos(cos_angle)

                        # Penalize backtracking (160-200 degree angles)
                        if BACKTRACK_MIN_ANGLE <= angle_diff <= BACKTRACK_MAX_ANGLE:
                            score *= 0.3  # Heavy penalty for backtracking

                candidates.append((grid_x, grid_y, score))

        # If we found candidates, select the best one
        if candidates:
            # Sort by score (highest first)
            candidates.sort(key=lambda x: x[2], reverse=True)

            # Select from top candidates with some randomness for exploration
            # Take top 30% of candidates and randomly select from them
            top_count = max(1, int(len(candidates) * 0.3))
            top_candidates = candidates[:top_count]

            # Randomly select from top candidates
            selected = top_candidates[int(random() * len(top_candidates))]
            grid_x, grid_y, _ = selected

            return self._get_grid_center(grid_x, grid_y)

        # Fallback: if no good candidates found, use the old random method
        return self._get_new_random_target_fallback(current_pos)

    def _get_new_random_target_fallback(
        self, current_pos: Tuple[float, float]
    ) -> Tuple[float, float]:
        """Fallback to original random target selection if strategic search fails."""
        current_x, current_y = current_pos
        prev_x, prev_y = self.previous_position

        prev_dx = current_x - prev_x
        prev_dy = current_y - prev_y

        max_tries = 1000
        # After turn 1000, use stricter distance limit
        max_allowed_distance = 950.0 if self.time_elapsed >= 1000 else 1000.0
        for _ in range(max_tries):
            angle = random() * 2 * math.pi
            target_x = current_x + math.cos(angle) * TARGET_POINT_DISTANCE
            target_y = current_y + math.sin(angle) * TARGET_POINT_DISTANCE
            target_pos = (target_x, target_y)

            if self._get_distance(target_pos, self.ark_pos) > max_allowed_distance:
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
                return target_pos

            cos_angle = dot_product / (mag_prev * mag_new)
            cos_angle = max(-1.0, min(1.0, cos_angle))
            angle_diff = math.acos(cos_angle)

            if not (BACKTRACK_MIN_ANGLE <= angle_diff <= BACKTRACK_MAX_ANGLE):
                return target_pos

        # Last resort: return a position near current
        return (current_x + random() - 0.5, current_y + random() - 0.5)

    def _get_new_random_target(self, current_pos: Tuple[float, float]) -> Move:
        """Picks a new strategic target using grid-based exploration."""
        target_pos = self._get_strategic_target(current_pos)
        self.current_target_pos = target_pos
        return self._get_move_to_target(current_pos, target_pos)

    def _get_return_move(
        self, current_pos: Tuple[float, float], direct: bool = False
    ) -> Move:
        """Calculates a move to return to the Ark.

        Args:
            current_pos: Current position
            direct: If True, go straight to ark. If False, spiral/arc toward ark to explore.
        """
        # Save current position so we can resume exploration after dropoff
        # Only save if we're in our assigned region and haven't saved yet
        if (
            self.has_reached_region
            and self.saved_exploration_pos is None
            and self._is_in_assigned_region(current_pos[0], current_pos[1])
        ):
            self.saved_exploration_pos = current_pos

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

        # If specialized, prioritize targets on the specialized list
        if self.is_specialized and self.to_search_list:
            # Find the species ID that is highest priority in the to_search_list
            priority_species_id = None
            for species_id, _ in self.to_search_list:
                # Check if EITHER gender of this species is missing (which confirms it's a priority)
                if self._is_species_needed(species_id, Gender.Unknown):
                    priority_species_id = species_id
                    break

            if priority_species_id is not None:
                # Find the cell containing this priority species
                for cell_view in self.sight:
                    if not cell_view.helpers and not self.position_is_in_cell(
                        cell_view.x, cell_view.y
                    ):
                        for animal in cell_view.animals:
                            if animal.species_id == priority_species_id:
                                # We check _is_species_needed again to ensure it passes all filters
                                if self._is_species_needed(
                                    animal.species_id, Gender.Unknown
                                ):
                                    return cell_view

        # If not specialized, or no priority target found, revert to finding ANY needed animal
        for cell_view in self.sight:
            # Skip the helper's own cell (handled by immediate obtain logic below)
            if self.position_is_in_cell(cell_view.x, cell_view.y):
                continue

            # Avoid targeting cells that are already beyond the safe radius from the Ark.
            # After turn 1000, use stricter 950 unit limit
            max_safe_distance = 950.0 if self.time_elapsed >= 1000 else 1000.0
            cell_center = (cell_view.x + 0.5, cell_view.y + 0.5)
            if self._get_distance(cell_center, self.ark_pos) > max_safe_distance:
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

        # Update grid visit tracking
        self._update_visited_grid_cell(self.position)

        # Clear target if we were chasing and are now in the *old* target cell
        if self.animal_target_cell and self.position_is_in_cell(
            self.animal_target_cell.x, self.animal_target_cell.y
        ):
            self.animal_target_cell = None

        return 0

    def get_action(self, messages: list[Message]) -> Action | None:
        # --- TURN-BASED ACTION: Clear ignore_list every 50 turns ---
        if self.time_elapsed > 0 and self.time_elapsed % 50 == 0:
            self.ignore_list.clear()
        if self.time_elapsed % 1000 == 0:
            # After turn 1000, strictly enforce 1000 unit limit
            if self.time_elapsed >= 1000:
                # Cap at 950 to stay well within 1000 unit safety limit
                self.max_explore_dis = min(950, self.max_explore_dis)
            else:
                # Before turn 1000, can increase exploration distance
                num_searching_helpers = max(1, self.num_helpers - 1)
                increment = 100 + max(0, (5 - num_searching_helpers) * 20)
                self.max_explore_dis += increment
                # Cap at 900 to stay within 1000 unit safety limit
                self.max_explore_dis = min(900, self.max_explore_dis)

        # Additional safety: after turn 1000, always cap at 950
        if self.time_elapsed >= 1000:
            self.max_explore_dis = min(950, self.max_explore_dis)

        # --- PRINT STATEMENT FOR SPECIES STATS (Restored) ---
        if self.time_elapsed == 0:
            # Print specialization details
            if self.is_specialized:
                # The specialization limit is now the ID, not a population count
                limit_text = f"ID:{self.specialization_limit}"
                print(
                    f"Helper {self.id} is Specialized (Limit {limit_text}). Targets: {len(self.to_search_list)}"
                )
            else:
                print(f"Helper {self.id} is Normal.")
        # --- END PRINT STATEMENT ---

        # Noah doesn't act
        if self.kind == Kind.Noah:
            return None

        current_x, current_y = self.position
        current_pos = (current_x, current_y)

        # GREEDY MODE: If < 5 helpers and < 500 turns
        # greedy_mode = self.num_helpers < 5 and self.time_elapsed < 500
        greedy_mode = False

        # Check if we've reached our assigned region (do this every turn)
        if not self.has_reached_region and self.assigned_region_id is not None:
            if self._is_in_assigned_region(current_x, current_y):
                self.has_reached_region = True

        # Hard safety cap: if we're already beyond the allowed radius from
        # the Ark, abandon any active targets and return directly toward the Ark.
        # After turn 1000, use stricter 950 unit limit
        max_safe_distance = 950.0 if self.time_elapsed >= 1000 else 1000.0
        if self._get_distance(current_pos, self.ark_pos) > max_safe_distance:
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
        # This handles the immediate release of duplicates *after* they are obtained
        # and confirmed in the flock.
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
            # Add species to ignore_list so the helper doesn't try to pick up this species
            # again immediately in this cell.
            self.ignore_list.append(duplicate_to_release.species_id)
            self.animal_target_cell = None
            return Release(animal=duplicate_to_release)

        # --- NEXT PRIORITY: IMMEDIATE OBTAIN IN CURRENT CELL (With Duplicate Check Fix) ---
        # BUT ONLY if we've reached our assigned region!
        if len(self.flock) >= c.MAX_FLOCK_SIZE:
            # If flock is full, return to Ark
            return self._get_return_move(current_pos, direct=True)
        else:
            current_cell_x, current_cell_y = int(current_x), int(current_y)

            try:
                current_cell_view = self.sight.get_cellview_at(
                    current_cell_x, current_cell_y
                )
            except Exception:
                current_cell_view = None

            # Only collect animals if:
            # 1. We're in our assigned region, OR
            # 2. We're actively chasing an animal (animal_target_cell is set), OR
            # 3. We're in greedy mode (< 5 helpers, < 500 turns)
            can_collect = (
                self.has_reached_region
                or self.animal_target_cell is not None
                or greedy_mode
            )

            if current_cell_view and current_cell_view.animals and can_collect:
                animal_to_obtain = None

                # Iterate through all animals currently in the cell
                for animal in current_cell_view.animals:
                    # 1. Skip animals already in the helper's flock
                    if animal in self.flock:
                        continue

                    # 2. BUG FIX: Check if the animal is a duplicate on the Ark or in the current flock
                    # We can only confirm duplication if the gender is known (which it is, once in the cell)
                    if animal.gender != Gender.Unknown:
                        animal_key = (animal.species_id, animal.gender)

                        # Check against Ark (self.obtained_species)
                        # self.obtained_species already includes the flock contents from check_surroundings
                        is_duplicate_in_ark_or_flock = (
                            animal_key in self.obtained_species
                        )

                        if is_duplicate_in_ark_or_flock:
                            # If it's a known duplicate (we have this species/gender),
                            # add the species ID to the ignore list to prevent future chases of this species.
                            if animal.species_id not in self.ignore_list:
                                self.ignore_list.append(animal.species_id)

                            # Skip obtaining this duplicate animal
                            continue

                    # 3. If the animal is needed (passed duplicate check, or gender is unknown/needed)
                    # Use the comprehensive _is_species_needed check (which includes specialization and general Ark need)
                    if self._is_species_needed(animal.species_id, animal.gender):
                        # This is the first needed animal found in the cell. Obtain it.
                        animal_to_obtain = animal
                        break  # Found the target, exit the loop over animals

                if animal_to_obtain:
                    self.animal_target_cell = None
                    return Obtain(animal=animal_to_obtain)

                # If no animals were obtained (either due to duplicates or none needed), clear target
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
            # After turn 1000, use stricter 950 unit limit
            max_safe_distance = 950.0 if self.time_elapsed >= 1000 else 1000.0
            if self._get_distance(target_cell_center, self.ark_pos) > max_safe_distance:
                self.animal_target_cell = None
                self.current_target_pos = None
                return self._get_return_move(current_pos, direct=False)

            return self._get_move_to_target(current_pos, target_cell_center)

        # Scan for new animal target (if we've reached our assigned region or in greedy mode)
        if len(self.flock) < c.MAX_FLOCK_SIZE and (
            self.has_reached_region or greedy_mode
        ):
            # _find_needed_animal_in_sight() uses _is_species_needed with Gender.Unknown
            new_target_cell = self._find_needed_animal_in_sight()
            if new_target_cell:
                target_cell_center = (new_target_cell.x + 0.5, new_target_cell.y + 0.5)
                # Only commit to a chase target that keeps us within the safe radius
                # of the Ark. After turn 1000, use stricter 950 unit limit
                max_safe_distance = 950.0 if self.time_elapsed >= 1000 else 1000.0
                if (
                    self._get_distance(target_cell_center, self.ark_pos)
                    <= max_safe_distance
                ):
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
        # If less than 5 helpers, return with 2 animals instead of 3
        flock_threshold = 2 if self.num_helpers < 5 else 3
        if len(self.flock) >= flock_threshold:
            return self._get_return_move(current_pos)

        # Exploration Logic (Fan-out or Triangle)
        if (
            self.is_in_ark()
            or self.current_target_pos is None
            or self._get_distance(current_pos, self.current_target_pos)
            < c.MAX_DISTANCE_KM
        ):
            # If we have a saved exploration position and we're at the ark, resume from there
            if self.is_in_ark() and self.saved_exploration_pos is not None:
                resume_target = self.saved_exploration_pos
                self.current_target_pos = resume_target
                self.saved_exploration_pos = (
                    None  # Clear it so we don't keep going back
                )
                return self._get_move_to_target(current_pos, resume_target)

            # If we haven't reached our assigned region yet, head there first
            if not self.has_reached_region and self.assigned_region_id is not None:
                region_target = (self.region_center_x, self.region_center_y)
                self.current_target_pos = region_target
                return self._get_move_to_target(current_pos, region_target)

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
        # After turn 1000, use stricter 950 unit limit
        max_safe_distance = 950.0 if self.time_elapsed >= 1000 else 1000.0
        if (
            self.current_target_pos is not None
            and self._get_distance(self.current_target_pos, self.ark_pos)
            > max_safe_distance
        ):
            self.current_target_pos = None
            return self._get_return_move(current_pos, direct=False)

        return self._get_move_to_target(current_pos, self.current_target_pos)
