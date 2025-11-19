"""Run benchmarks in parallel."""

import sys
import pathlib
import random
import time
from multiprocessing import Pool
from typing import Dict, Any

# Try to import tqdm for progress bar (optional dependency)
try:
    from tqdm import tqdm

    # Check if we're in a TTY (tqdm works best in interactive terminals)
    # Note: sys is imported at the top of the file
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

    # Create a dummy tqdm that just passes through the iterable
    def tqdm(iterable=None, **kwargs):
        return iterable if iterable is not None else iter([])


# Add parent directories to path to import modules
script_dir = pathlib.Path(__file__).parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(script_dir.parent))

from core.runner import ArkRunner  # noqa: E402
from players.group6.player import Player6  # noqa: E402
from test_config import SEED, TIME_T  # noqa: E402


def run_single_benchmark(map_path: pathlib.Path) -> Dict[str, Any]:
    """Run a single benchmark test.

    Args:
        map_path: Path to the JSON map file

    Returns:
        Dictionary with test results
    """
    # Load map configuration
    with open(map_path, "r") as f:
        import json

        map_data = json.load(f)

    num_helpers = map_data["num_helpers"]
    animals = map_data["animals"]
    ark = tuple(map_data["ark"])

    # Calculate total animals to detect extreme cases
    total_animals = sum(animals)
    num_species = len(animals)

    # Safety check: Skip extremely large test cases that are likely to hang
    # These should have been removed by regenerate-maps, but check anyway
    if total_animals > 100000 or num_species > 512:
        return {
            "test_name": map_path.stem,
            "num_helpers": num_helpers,
            "num_species": num_species,
            "total_animals": total_animals,
            "density": animals[0] if animals else 0,
            "ark_pos": f"{ark[0]},{ark[1]}",
            "score": 0,
            "execution_time": 0,
            "status": "skipped: extreme test case (too many animals/species). Run --regenerate-maps to fix.",
        }

    # Set random seed for reproducibility
    random.seed(SEED)

    # Create runner and run simulation
    try:
        runner = ArkRunner(Player6, num_helpers, animals, TIME_T, ark)
        start_time = time.time()
        score, times = runner.run()
        execution_time = time.time() - start_time

        # Calculate statistics
        density = animals[0] if animals else 0  # Assume same density per species

        return {
            "test_name": map_path.stem,
            "num_helpers": num_helpers,
            "num_species": num_species,
            "total_animals": total_animals,
            "density": density,
            "ark_pos": f"{ark[0]},{ark[1]}",
            "score": score,
            "execution_time": execution_time,
            "status": "success",
        }
    except Exception as e:
        return {
            "test_name": map_path.stem,
            "num_helpers": num_helpers,
            "num_species": num_species,
            "total_animals": total_animals,
            "density": animals[0] if animals else 0,
            "ark_pos": f"{ark[0]},{ark[1]}",
            "score": 0,
            "execution_time": 0,
            "status": f"error: {str(e)}",
        }


def run_benchmarks_parallel(maps_dir: pathlib.Path, num_workers: int = None) -> list:
    """Run all benchmarks in parallel.

    Args:
        maps_dir: Directory containing map JSON files
        num_workers: Number of parallel workers (None = CPU count)

    Returns:
        List of result dictionaries
    """
    import multiprocessing

    # Find all map files
    map_files = sorted(maps_dir.glob("*.json"))

    if not map_files:
        print(f"No map files found in {maps_dir}")
        return []

    # Use all CPUs if not specified
    if num_workers is None:
        num_workers = multiprocessing.cpu_count()

    print(
        f"Running {len(map_files)} benchmarks using {num_workers} workers...",
        flush=True,
    )
    start_time = time.time()

    if TQDM_AVAILABLE:
        # Check if stdout is a TTY (tqdm works best in interactive terminals)
        use_tqdm = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else True

        if use_tqdm:
            # Use a manual progress bar approach that works better with multiprocessing
            with Pool(processes=num_workers) as pool:
                # Create progress bar
                pbar = tqdm(
                    total=len(map_files),
                    desc="Running benchmarks",
                    unit="test",
                    ncols=100,
                    mininterval=0.5,
                    maxinterval=2.0,
                    file=sys.stdout,
                )

                # Use imap_unordered and manually update progress bar
                results = []
                iterator = pool.imap_unordered(run_single_benchmark, map_files)
                try:
                    for result in iterator:
                        results.append(result)
                        pbar.update(1)
                finally:
                    pbar.close()
        else:
            # Not a TTY, fall back to simple progress updates
            with Pool(processes=num_workers) as pool:
                results = []
                for i, result in enumerate(
                    pool.imap_unordered(run_single_benchmark, map_files), 1
                ):
                    results.append(result)
                    elapsed = time.time() - start_time
                    print(
                        f"  Completed {i}/{len(map_files)} [{elapsed:.1f}s elapsed]",
                        flush=True,
                    )
    else:
        # tqdm not available, use simple progress updates
        with Pool(processes=num_workers) as pool:
            results = []
            for i, result in enumerate(
                pool.imap_unordered(run_single_benchmark, map_files), 1
            ):
                results.append(result)
                elapsed = time.time() - start_time
                print(
                    f"  Completed {i}/{len(map_files)} [{elapsed:.1f}s elapsed]",
                    flush=True,
                )

    total_time = time.time() - start_time
    print(
        f"✓ All benchmarks complete in {total_time:.1f}s ({total_time / 60:.1f} min)",
        flush=True,
    )

    return results
