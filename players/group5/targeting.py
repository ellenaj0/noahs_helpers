"""Animal targeting and ark management for Player5."""
import math
from random import random
from typing import Optional, Set, Tuple, List
from core.animal import Gender
from core.views.cell_view import CellView
from core.sight import Sight
from .constants import SpeciesGender


def update_obtained_species_from_ark(
    ark_animals: Set,
    obtained_species: Set[SpeciesGender],
    is_specialized: bool,
    time_elapsed: int,
    helper_id: int,
    base_angle: float
) -> Tuple[Set[SpeciesGender], bool, float]:
    """
    Update obtained species based on confirmed Ark animals.

    Returns: (updated_obtained_species, new_is_exploring_fan_out, new_base_angle)
    """
    ark_set: Set[SpeciesGender] = set()
    new_base_angle = base_angle
    new_is_exploring_fan_out = False

    for animal in ark_animals:
        if animal.gender != Gender.Unknown:
            ark_set.add((animal.species_id, animal.gender))
            new_is_exploring_fan_out = True
            new_base_angle = (base_angle + random()) % (2 * math.pi)

    updated_obtained = obtained_species.copy()
    updated_obtained.update(ark_set)

    # Handle specialization switching after turn 1000
    if is_specialized and time_elapsed > 1000:
        print(f"Helper {helper_id} switching out of specialization after turn {time_elapsed}")

    return updated_obtained, new_is_exploring_fan_out, new_base_angle


def find_needed_animal_in_sight(
    sight: Sight,
    is_specialized: bool,
    to_search_list: List[SpeciesGender],
    is_species_needed_func,
    position: Tuple[float, float],
    ark_pos: Tuple[float, float],
    safe_radius: float
) -> Optional[CellView]:
    """
    Scan sight for needed, unshepherded animals.

    Prioritizes specialized targets if applicable.
    """
    # Prioritize specialized targets
    if is_specialized and to_search_list:
        priority_species_id = next(
            (species_id for species_id, _ in to_search_list
             if is_species_needed_func(species_id, Gender.Unknown)),
            None
        )

        if priority_species_id is not None:
            target_cell = find_cell_with_species(
                sight, priority_species_id, is_species_needed_func,
                position, ark_pos, safe_radius
            )
            if target_cell:
                return target_cell

    # Find any needed animal (uses the is_species_needed_func which has all the checks)
    return find_cell_with_needed_animal(
        sight, is_species_needed_func, position, ark_pos, safe_radius
    )


def find_cell_with_species(
    sight: Sight,
    species_id: int,
    is_species_needed_func,
    position: Tuple[float, float],
    ark_pos: Tuple[float, float],
    safe_radius: float
) -> Optional[CellView]:
    """Find a cell containing the specified species."""
    for cell_view in sight:
        if is_valid_target_cell(cell_view, position, ark_pos, safe_radius):
            for animal in cell_view.animals:
                if animal.species_id == species_id and \
                   is_species_needed_func(animal.species_id, Gender.Unknown):
                    return cell_view
    return None


def find_cell_with_needed_animal(
    sight: Sight,
    is_species_needed_func,
    position: Tuple[float, float],
    ark_pos: Tuple[float, float],
    safe_radius: float
) -> Optional[CellView]:
    """Find any cell with a needed animal."""
    for cell_view in sight:
        if is_valid_target_cell(cell_view, position, ark_pos, safe_radius):
            for animal in cell_view.animals:
                if is_species_needed_func(animal.species_id, Gender.Unknown):
                    return cell_view
    return None


def is_valid_target_cell(
    cell_view: CellView,
    position: Tuple[float, float],
    ark_pos: Tuple[float, float],
    safe_radius: float
) -> bool:
    """Check if a cell is valid for targeting."""
    from .movement import get_distance, is_within_safe_radius

    # Check if in current cell
    current_x, current_y = int(position[0]), int(position[1])
    if current_x == cell_view.x and current_y == cell_view.y:
        return False

    if cell_view.helpers:
        return False

    cell_center = (cell_view.x + 0.5, cell_view.y + 0.5)
    return is_within_safe_radius(cell_center, ark_pos, safe_radius)
