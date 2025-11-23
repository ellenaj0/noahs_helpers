#!/usr/bin/env python3
"""Main benchmark script for Group 6 player performance testing."""

import argparse
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime

from generate_test_maps import generate_maps
from run_benchmarks import run_benchmarks_parallel
from format_results import display_results
from test_config import get_test_cases


def get_git_metadata():
    """Get git commit hash and branch name using subprocess.

    Returns:
        tuple: (commit_hash, branch_name) with fallback to ("unknown", "unknown")
    """
    commit_hash = "unknown"
    branch_name = "unknown"

    try:
        # Get commit hash (short, 8 characters)
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        commit_hash = result.stdout.strip()
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        pass

    try:
        # Get branch name
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        branch_name = result.stdout.strip()
        # Sanitize branch name: replace special chars with underscores, lowercase
        branch_name = (
            branch_name.lower().replace("/", "_").replace("\\", "_").replace("-", "_")
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        pass

    return commit_hash, branch_name


def generate_result_filename(
    results_dir: pathlib.Path, commit_hash: str, branch_name: str
) -> pathlib.Path:
    """Generate a timestamped result filename with git metadata.

    Args:
        results_dir: Directory to save results in
        commit_hash: Git commit hash (8 chars)
        branch_name: Git branch name (sanitized)

    Returns:
        Path to the result file
    """
    # Generate datetime string: YYYY-MM-DD_HH-MM-SS
    now = datetime.now()
    datetime_str = now.strftime("%Y-%m-%d_%H-%M-%S")

    # Format: results_<date>_<time>_<commit>_<branch>.csv
    filename = f"results_{datetime_str}_{commit_hash}_{branch_name}.csv"
    return results_dir / filename


def main():
    parser = argparse.ArgumentParser(
        description="Run performance benchmarks for Group 6 player"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only a subset of tests (helper variation only)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed progress",
    )
    parser.add_argument(
        "--regenerate-maps",
        action="store_true",
        help="Force regeneration of map files",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: all CPUs)",
    )
    parser.add_argument(
        "--test-time",
        type=int,
        default=None,
        help="Override simulation time (turns). Default is 4000 for benchmarks, full game is 8064",
    )

    args = parser.parse_args()

    # Override TIME_T if specified
    if args.test_time:
        import test_config

        test_config.TIME_T = args.test_time
        if args.verbose:
            print(f"Using custom simulation time: {args.test_time} turns")

    # Get script directory
    script_dir = pathlib.Path(__file__).parent
    maps_dir = script_dir / "test_maps"
    results_dir = script_dir / "benchmark_results"
    old_results_csv = script_dir / "benchmark_results.csv"

    # Create results directory if it doesn't exist
    results_dir.mkdir(exist_ok=True)

    # Migrate existing results CSV if it exists
    if old_results_csv.exists():
        commit_hash, branch_name = get_git_metadata()
        migrated_filename = generate_result_filename(
            results_dir, commit_hash, branch_name
        )
        shutil.copy2(old_results_csv, migrated_filename)
        old_results_csv.unlink()  # Remove old file
        if args.verbose:
            print(f"Migrated existing results to: {migrated_filename.name}")

    # Get git metadata and generate result filename for new run
    commit_hash, branch_name = get_git_metadata()
    results_csv = generate_result_filename(results_dir, commit_hash, branch_name)

    if args.verbose:
        print(f"Results will be saved to: {results_csv.name}")
        print(f"  Commit: {commit_hash}, Branch: {branch_name}")

    # Generate maps if needed
    if (
        args.regenerate_maps
        or not maps_dir.exists()
        or not list(maps_dir.glob("*.json"))
    ):
        if args.verbose:
            print("Generating test maps...")
        generate_maps(maps_dir)
        if args.verbose:
            print(f"Generated {len(get_test_cases())} test maps")
    else:
        if args.verbose:
            print(f"Using existing maps in {maps_dir}")
            print("  (use --regenerate-maps to rebuild if test config changed)")

    # Filter maps for quick mode
    if args.quick:
        if args.verbose:
            print("Quick mode: Running only helper variation tests...")
        # Filter to only helper variation maps
        all_maps = list(maps_dir.glob("*.json"))
        filtered_maps = [
            m
            for m in all_maps
            if m.stem.startswith("helpers_")
            and "species_16_density_100" in m.stem
            and "edge_" not in m.stem
        ]
        # Temporarily create a filtered directory
        temp_maps_dir = maps_dir / ".quick_temp"
        temp_maps_dir.mkdir(exist_ok=True)
        for m in filtered_maps:
            shutil.copy2(m, temp_maps_dir / m.name)

        try:
            results = run_benchmarks_parallel(temp_maps_dir, num_workers=args.workers)
        finally:
            # Clean up temp directory
            if temp_maps_dir.exists():
                shutil.rmtree(temp_maps_dir)
    else:
        results = run_benchmarks_parallel(maps_dir, num_workers=args.workers)

    # Display and save results
    display_results(results, output_csv=results_csv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
