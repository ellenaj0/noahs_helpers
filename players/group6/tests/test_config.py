"""Test configuration for performance benchmarks."""

import sys
import pathlib

# Add project root to path to import core modules
script_dir = pathlib.Path(__file__).parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))


# Test parameterizations
# Reduced upper bounds for faster benchmarking
HELPER_COUNTS = [2, 5, 10, 20]  # 50, 1000
SPECIES_COUNTS = [4, 8, 16, 32, 256]  # removed 128, 256, 512
ANIMAL_DENSITIES = [10, 50, 100, 200]  # 500, 2000
ARK_POSITIONS = [
    (0, 0),  # corner
    (500, 500),  # center
    (0, 500),  # edge
]

# Constants
SEED = 4444
# Benchmark time - enough for helpers to complete full cycles (explore → collect → return)
# Full simulation is 8064 turns, but for benchmarking we use 4000 to ensure helpers
# have time to return to ark (required for non-zero score)
BENCHMARK_TIME_T = 4000  # Allows helpers to complete collection cycles and return
TIME_T = BENCHMARK_TIME_T

# Fixed values for variation tests
FIXED_SPECIES = 16
FIXED_DENSITY = 100
FIXED_HELPERS = 10


def get_test_cases():
    """Generate test case configurations.

    Returns:
        list: List of dicts with keys: num_helpers, animals, ark, test_name
    """
    test_cases = []

    # Helper variation tests: vary helpers, fixed species (16) and density (100)
    for helpers in HELPER_COUNTS:
        animals = [FIXED_DENSITY] * FIXED_SPECIES
        test_cases.append(
            {
                "num_helpers": helpers,
                "animals": animals,
                "ark": (500, 500),
                "test_name": f"helpers_{helpers}_species_{FIXED_SPECIES}_density_{FIXED_DENSITY}_ark_500_500",
            }
        )

    # Species variation tests: vary species, fixed helpers (10) and density (100)
    for species in SPECIES_COUNTS:
        animals = [FIXED_DENSITY] * species
        test_cases.append(
            {
                "num_helpers": FIXED_HELPERS,
                "animals": animals,
                "ark": (500, 500),
                "test_name": f"helpers_{FIXED_HELPERS}_species_{species}_density_{FIXED_DENSITY}_ark_500_500",
            }
        )

    # Density variation tests: vary density, fixed helpers (10) and species (16)
    for density in ANIMAL_DENSITIES:
        animals = [density] * FIXED_SPECIES
        test_cases.append(
            {
                "num_helpers": FIXED_HELPERS,
                "animals": animals,
                "ark": (500, 500),
                "test_name": f"helpers_{FIXED_HELPERS}_species_{FIXED_SPECIES}_density_{density}_ark_500_500",
            }
        )

    # Edge cases
    # Minimal: 2 helpers, 4 species, low density
    test_cases.append(
        {
            "num_helpers": 2,
            "animals": [10] * 4,
            "ark": (500, 500),
            "test_name": "edge_minimal_helpers_2_species_4_density_10_ark_500_500",
        }
    )

    # Maximal: 50 helpers, 32 species, high density
    # Note: Reduced for faster benchmarking
    test_cases.append(
        {
            "num_helpers": 50,
            "animals": [500] * 32,
            "ark": (500, 500),
            "test_name": "edge_maximal_helpers_50_species_32_density_500_ark_500_500",
        }
    )

    # Ark position variations for key combinations
    for ark_pos in ARK_POSITIONS:
        if ark_pos != (500, 500):  # Already tested center
            test_cases.append(
                {
                    "num_helpers": FIXED_HELPERS,
                    "animals": [FIXED_DENSITY] * FIXED_SPECIES,
                    "ark": ark_pos,
                    "test_name": f"helpers_{FIXED_HELPERS}_species_{FIXED_SPECIES}_density_{FIXED_DENSITY}_ark_{ark_pos[0]}_{ark_pos[1]}",
                }
            )

    return test_cases
