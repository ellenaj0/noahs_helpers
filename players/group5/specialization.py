"""Specialization logic for Player5 strategy."""
import math
from typing import List, Dict, Optional, Set, Tuple
from operator import itemgetter
from core.animal import Gender
from .constants import SpeciesGender


def create_specialization_groups(
    species_list: List[Tuple[str, int]], total_population: int
) -> Dict[int, List[str]]:
    """Create nested rarity groups for specialization."""
    specializations_map: Dict[int, List[str]] = {}
    # Adjusted percentages - focus more on moderately rare, less on ultra-rare
    population_percentages = [0.30, 0.15, 0.08, 0.03]
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

        specializations_map[specialization_limits[i]] = target_species_names

    return specializations_map


def determine_helper_group(helper_id: int, num_helpers: int) -> Optional[int]:
    """Determine which specialization group this helper belongs to."""
    num_specialized_helpers = num_helpers - 2
    group_id = helper_id - 2

    # Rebalanced: more helpers on moderately rare (30/30), fewer on ultra-rare (15)
    group_percentages = [0.30, 0.30, 0.25, 0.15]
    specialization_limits = [1000, 2000, 3000, 4000]

    # Calculate group sizes
    group_sizes = []
    current_cumulative_size = 0

    for i in range(len(group_percentages)):
        size = math.ceil(num_specialized_helpers * group_percentages[i])

        if i == len(group_percentages) - 1:
            size = max(0, num_specialized_helpers - current_cumulative_size)

        current_cumulative_size += size
        group_sizes.append(size)

    # Find which group this helper belongs to
    cumulative_helper_count = 0
    for i, size in enumerate(group_sizes):
        start_id = cumulative_helper_count + 1
        end_id = cumulative_helper_count + size

        if start_id <= group_id <= end_id:
            return specialization_limits[i]

        cumulative_helper_count += size

    return None


def assign_specialization(
    helper_id: int,
    num_helpers: int,
    species_stats: Dict[str, int],
    species_to_id: Dict[str, int]
) -> Tuple[bool, int, List[str]]:
    """
    Assign helper specialization based on nested subsets of rarest species.

    Returns: (is_specialized, specialization_limit, specialization_target_species)
    """
    # Helpers 1 and 2 use normal behavior
    if helper_id in [1, 2]:
        return False, 0, []

    # Calculate species list sorted by rarity
    species_list = sorted(
        [(name, count) for name, count in species_stats.items() if count >= 6],
        key=itemgetter(1)
    )

    total_population = sum(count for _, count in species_list)
    if total_population == 0:
        return False, 0, []

    # Define rarity groupings
    specializations_map = create_specialization_groups(species_list, total_population)

    # Assign helper to appropriate group
    assigned_limit = determine_helper_group(helper_id, num_helpers)

    # Apply specialization
    if assigned_limit and assigned_limit in specializations_map:
        return True, assigned_limit, specializations_map[assigned_limit]
    else:
        return False, 0, []


def add_needed_genders(
    species_names: List[str],
    species_to_id: Dict[str, int],
    obtained_species: Set[SpeciesGender],
    current_list: List[SpeciesGender]
) -> List[SpeciesGender]:
    """Add needed genders for given species to the list."""
    result = current_list.copy()

    for species_name in species_names:
        species_id = species_to_id.get(species_name)
        if species_id is None:
            continue

        for gender in [Gender.Male, Gender.Female]:
            if (species_id, gender) not in obtained_species:
                result.append((species_id, gender))

    return result


def update_to_search_list(
    is_specialized: bool,
    specialization_target_species: List[str],
    species_stats: Dict[str, int],
    species_to_id: Dict[str, int],
    obtained_species: Set[SpeciesGender],
    helper_id: int = 0,
    num_helpers: int = 1
) -> Tuple[List[SpeciesGender], List[str]]:
    """
    Update search list for dedicated species hunting.

    Each helper hunts their assigned species until collected,
    then automatically moves to next rarest needed species.

    Returns: (search_list, updated_specialization_target_species)
    """
    final_search_list: List[SpeciesGender] = []

    # Get all species sorted by rarity
    species_list = sorted(
        [(name, count) for name, count in species_stats.items() if count >= 6],
        key=itemgetter(1)
    )

    if not is_specialized or helper_id <= 2:
        # Generalist helpers: search for rarest overall
        species_info = sorted(
            [(count, species_to_id[name]) for name, count in species_stats.items()]
        )

        for count, species_id in species_info:
            if len(final_search_list) >= 6:
                break

            if (species_id, Gender.Male) not in obtained_species and \
               (species_id, Gender.Male) not in final_search_list:
                final_search_list.append((species_id, Gender.Male))

            if (species_id, Gender.Female) not in obtained_species and \
               (species_id, Gender.Male) not in final_search_list:
                final_search_list.append((species_id, Gender.Female))

        return final_search_list, specialization_target_species

    # SPECIALIZED HELPERS: Dedicated species hunting
    # Check if current assigned species is complete
    current_species_complete = True
    for species_name in specialization_target_species:
        species_id = species_to_id.get(species_name)
        if species_id is not None:
            male_has = (species_id, Gender.Male) in obtained_species
            female_has = (species_id, Gender.Female) in obtained_species
            if not (male_has and female_has):
                current_species_complete = False
                break

    # If current species complete, assign next rarest needed species
    new_target_species = specialization_target_species
    if current_species_complete:
        # Find next rarest species that still needs collection
        for species_name, count in species_list:
            species_id = species_to_id.get(species_name)
            if species_id is None:
                continue

            male_has = (species_id, Gender.Male) in obtained_species
            female_has = (species_id, Gender.Female) in obtained_species

            if not (male_has and female_has):
                # Found a species that needs collection
                new_target_species = [species_name]
                print(f"Helper {helper_id} reassigned to species: {species_name}")
                break

    # Build search list for assigned species
    for species_name in new_target_species:
        species_id = species_to_id.get(species_name)
        if species_id is None:
            continue

        if (species_id, Gender.Male) not in obtained_species:
            final_search_list.append((species_id, Gender.Male))
        if (species_id, Gender.Female) not in obtained_species:
            final_search_list.append((species_id, Gender.Female))

    return final_search_list, new_target_species


def is_species_needed(
    species_id: int,
    gender: Gender,
    ignore_list: List[int],
    is_specialized: bool,
    to_search_list: List[SpeciesGender],
    obtained_species: Set[SpeciesGender]
) -> bool:
    """Check if an animal is needed based on gender and specialization."""
    if species_id in ignore_list:
        return False

    # Check against ark first
    if gender == Gender.Unknown:
        male_obtained = (species_id, Gender.Male) in obtained_species
        female_obtained = (species_id, Gender.Female) in obtained_species
        is_needed = not (male_obtained and female_obtained)
    else:
        is_needed = (species_id, gender) not in obtained_species

    if not is_needed:
        return False

    # Specialization preference (but not strict filter)
    # Specialized helpers PREFER their targets but can take others if available
    if is_specialized and to_search_list:
        if gender != Gender.Unknown:
            # Strong preference for specialized targets
            return (species_id, gender) in to_search_list
        else:
            # If gender unknown, prefer specialized species
            is_target = any(s_id == species_id for s_id, _ in to_search_list)
            return is_target

    # Non-specialized or no specific targets: take anything needed
    return True
