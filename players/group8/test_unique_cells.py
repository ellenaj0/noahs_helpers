#!/usr/bin/env python3
"""
Script to test how many unique cells each helper visits on average across multiple seeds.
Uses t1.json config and runs for 2016 turns.
"""

import random
import pathlib
import argparse
from collections import defaultdict
from typing import Dict, Set

from core.runner import ArkRunner
from core.args import MapArgs, PLAYERS
from core.engine import Engine
from core.views.player_view import Kind


def load_map_config(map_path: str) -> MapArgs:
    """Load map configuration from JSON file."""
    map_file = pathlib.Path(map_path).resolve()
    if not map_file.is_file():
        raise FileNotFoundError(f'Map file "{map_file}" not found')

    return MapArgs.read(map_file)


def track_unique_cells(
    engine: Engine, num_turns: int
) -> Dict[int, Set[tuple[int, int]]]:
    """
    Run the simulation and track unique cells visited by each helper.
    Returns a dictionary mapping helper_id -> set of (x, y) cell coordinates visited.
    """
    # Initialize tracking: helper_id -> set of visited cells
    visited_cells: Dict[int, Set[tuple[int, int]]] = defaultdict(set)

    # Track initial positions
    for hi in engine.info_helpers.keys():
        if hi.kind != Kind.Noah:  # Skip Noah (id 0, kind Noah)
            x_cell = int(hi.x)
            y_cell = int(hi.y)
            visited_cells[hi.id].add((x_cell, y_cell))

    # Run simulation for specified number of turns
    while engine.time_elapsed < num_turns:
        engine.run_turn()

        # Track cells visited after each turn
        for hi in engine.info_helpers.keys():
            if hi.kind != Kind.Noah:  # Skip Noah
                x_cell = int(hi.x)
                y_cell = int(hi.y)
                visited_cells[hi.id].add((x_cell, y_cell))

    return visited_cells


def run_single_test(
    player_class, map_args: MapArgs, seed: int, num_turns: int = 2016
) -> tuple[Dict[int, int], int]:
    """
    Run a single test with a given seed.
    Returns a tuple of:
    - dictionary mapping helper_id -> number of unique cells visited
    - final score
    """
    random.seed(seed)

    runner = ArkRunner(
        player_class=player_class,
        num_helpers=map_args.num_helpers,
        animals=map_args.animals,
        time=num_turns,
        ark_pos=map_args.ark,
    )

    engine = runner.setup_engine()
    visited_cells = track_unique_cells(engine, num_turns)

    # Get the final score
    score, _ = engine.get_results()

    # Convert to counts
    helper_cells = {helper_id: len(cells) for helper_id, cells in visited_cells.items()}
    return helper_cells, score


def main():
    parser = argparse.ArgumentParser(
        description="Test how many unique cells each helper visits across multiple seeds"
    )
    parser.add_argument(
        "--player",
        type=str,
        choices=list(PLAYERS.keys()),
        help="Which player to test (1-10 or r for random). If not specified, tests all players.",
    )
    parser.add_argument(
        "--map",
        type=str,
        default="maps/template/t1.json",
        help="Path to map configuration JSON file (default: maps/template/t1.json)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=2016,
        help="Number of turns to run (default: 2016)",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=10,
        help="Number of different seeds to test (default: 10)",
    )
    parser.add_argument(
        "--start-seed",
        type=int,
        default=1,
        help="Starting seed value (default: 1)",
    )

    args = parser.parse_args()

    # Configuration
    map_path = args.map
    num_turns = args.turns
    num_seeds = args.seeds
    start_seed = args.start_seed

    # Load map configuration
    print(f"Loading map configuration from {map_path}...")
    map_args = load_map_config(map_path)
    print(f"  num_helpers: {map_args.num_helpers}")
    print(f"  animals: {len(map_args.animals)} species")
    print(f"  ark position: {map_args.ark}")
    print()

    # Determine which players to test
    players_to_test = {}
    if args.player:
        if args.player not in PLAYERS:
            print(f"Error: Player '{args.player}' not found")
            return
        players_to_test[args.player] = PLAYERS[args.player]
    else:
        # Test all players except random by default
        players_to_test = {name: cls for name, cls in PLAYERS.items() if name != "r"}

    # Test player types
    results_by_player: Dict[str, Dict[int, list[int]]] = {}
    scores_by_player: Dict[str, list[int]] = {}

    for player_name, player_class in players_to_test.items():
        print(f"Testing player {player_name}...")
        results_by_helper: Dict[int, list[int]] = defaultdict(list)
        scores: list[int] = []

        # Run multiple seeds
        for seed in range(start_seed, start_seed + num_seeds):
            print(f"  Seed {seed}...", end=" ", flush=True)
            try:
                helper_cells, score = run_single_test(
                    player_class, map_args, seed, num_turns
                )
                for helper_id, num_cells in helper_cells.items():
                    results_by_helper[helper_id].append(num_cells)
                scores.append(score)
                print(f"✓ (score: {score})")
            except Exception as e:
                print(f"✗ Error: {e}")

        results_by_player[player_name] = results_by_helper
        scores_by_player[player_name] = scores
        print()

    # Print results
    print("=" * 80)
    print("RESULTS: Scores and Unique Cells Visited per Helper")
    print("=" * 80)
    print(f"Config: {map_path}")
    print(f"Turns: {num_turns}")
    print(
        f"Seeds tested: {num_seeds} (seeds {start_seed} to {start_seed + num_seeds - 1})"
    )
    print()

    for player_name, results_by_helper in results_by_player.items():
        print(f"Player {player_name}:")
        print("-" * 80)

        # Print score statistics
        scores = scores_by_player[player_name]
        if scores:
            avg_score = sum(scores) / len(scores)
            min_score = min(scores)
            max_score = max(scores)
            print(
                f"  Score: avg={avg_score:7.2f}, min={min_score:5d}, max={max_score:5d}"
            )
            print()

        # Calculate statistics for each helper
        helper_stats = []
        for helper_id in sorted(results_by_helper.keys()):
            cells_visited = results_by_helper[helper_id]
            if cells_visited:
                avg = sum(cells_visited) / len(cells_visited)
                min_cells = min(cells_visited)
                max_cells = max(cells_visited)
                helper_stats.append((helper_id, avg, min_cells, max_cells))

        # Print per-helper stats
        for helper_id, avg, min_cells, max_cells in helper_stats:
            print(
                f"  Helper {helper_id:2d}: avg={avg:7.2f}, min={min_cells:5d}, max={max_cells:5d}"
            )

        # Calculate overall average across all helpers
        if helper_stats:
            all_avgs = [avg for _, avg, _, _ in helper_stats]
            overall_avg = sum(all_avgs) / len(all_avgs)
            print(f"  Overall average: {overall_avg:.2f} unique cells per helper")

        print()


if __name__ == "__main__":
    main()
