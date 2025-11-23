#!/usr/bin/env python3
"""Run a benchmark test case with the GUI for visual verification."""

import argparse
import json
import pathlib
import random
import sys

# Add project root to path
script_dir = pathlib.Path(__file__).parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

from core.runner import ArkRunner  # noqa: E402
from players.group6.player import Player6  # noqa: E402
from test_config import SEED, TIME_T  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Run a benchmark test case with GUI visualization"
    )
    parser.add_argument(
        "map_file",
        type=str,
        help="Name of the map file (e.g., 'helpers_10_species_16_density_100_ark_500_500') or full path",
    )
    parser.add_argument(
        "--test-time",
        type=int,
        default=None,
        help=f"Override simulation time (default: {TIME_T} from test_config, ensures helpers return to ark)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=f"Override random seed (default: {SEED} from test_config)",
    )

    args = parser.parse_args()

    # Find the map file
    maps_dir = script_dir / "test_maps"
    map_path = None

    # Try as filename first
    if not args.map_file.endswith(".json"):
        map_path = maps_dir / f"{args.map_file}.json"
    else:
        map_path = maps_dir / args.map_file

    # If not found, try as full path
    if not map_path.exists():
        map_path = pathlib.Path(args.map_file)
        if not map_path.exists():
            print(f"Error: Map file not found: {args.map_file}")
            print(f"Available maps in {maps_dir}:")
            for f in sorted(maps_dir.glob("*.json")):
                print(f"  - {f.stem}")
            return 1

    # Load map configuration
    with open(map_path, "r") as f:
        map_data = json.load(f)

    num_helpers = map_data["num_helpers"]
    animals = map_data["animals"]
    ark = tuple(map_data["ark"])
    test_time = args.test_time if args.test_time is not None else TIME_T
    seed = args.seed if args.seed is not None else SEED

    print("=" * 70)
    print("Running Benchmark Test with GUI")
    print("=" * 70)
    print(f"Map file: {map_path.name}")
    print(f"Helpers: {num_helpers}")
    print(f"Species: {len(animals)}")
    print(f"Total animals: {sum(animals)}")
    print(f"Ark position: {ark}")
    print(f"Simulation time: {test_time} turns")
    print(f"Seed: {seed}")
    print("=" * 70)
    print()
    print("Starting GUI... (close window when done to see final score)")
    print()

    # Set random seed
    random.seed(seed)

    # Create runner and run with GUI
    runner = ArkRunner(Player6, num_helpers, animals, test_time, ark)
    score, times = runner.run_gui()

    # Print results
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"SCORE={score}")
    if len(times):
        print(f"TOTAL_TURN_TIME={sum(times):.4f}s")
        print(f"TURNS_PER_SECOND={1 / (sum(times) / len(times)):.0f}")
    else:
        print("TOTAL_TURN_TIME=-1")
        print("TURNS_PER_SECOND=-1")
    print("=" * 70)
    print()
    print(f"Compare this score ({score}) with the benchmark result for:")
    print(f"  {map_path.stem}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
