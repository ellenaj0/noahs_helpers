# Group 6 Performance Test Suite

This directory contains the performance benchmarking test suite for the Group 6 player implementation.

**⚠️ Note**: Benchmarks use 4000 turns (not full 8064) for speed. This ensures helpers have time to return to ark (required for scoring). Use `--test-time 8064` for full simulation accuracy.

## Structure

- `benchmark.py` - Main entry point for running benchmarks
- `test_config.py` - Test parameterizations and configuration
- `generate_test_maps.py` - Generates JSON map files for test cases
- `run_benchmarks.py` - Runs benchmarks in parallel
- `format_results.py` - Formats and displays results
- `run_with_gui.py` - Run individual tests with GUI visualization
- `test_maps/` - Directory containing generated map JSON files
- `benchmark_results/` - Directory containing timestamped benchmark result files

## Usage

### Run all benchmarks:
```bash
cd players/group6/tests
python benchmark.py
```

### Run quick subset (helper variation only):
```bash
python benchmark.py --quick
```

### Regenerate maps:
```bash
python benchmark.py --regenerate-maps
```

### Verbose output:
```bash
python benchmark.py --verbose
```

### Specify number of workers:
```bash
python benchmark.py --workers 4
```

### Custom simulation time:
```bash
# Faster testing (2000 turns - may not allow all helpers to return)
python benchmark.py --quick --test-time 2000

# Full simulation (8064 turns)
python benchmark.py --quick --test-time 8064
```

### Run a test with GUI (visual verification):
```bash
# Run a specific test case with GUI
python run_with_gui.py helpers_10_species_16_density_100_ark_500_500

# Or with custom time/seed
python run_with_gui.py helpers_10_species_16_density_100_ark_500_500 --test-time 500 --seed 4444

# List available test maps
python run_with_gui.py --help
```

## Test Cases

The test suite covers:
- **Helper variation**: [2, 5, 10, 20, 50] helpers
- **Species variation**: [4, 8, 12, 16, 20, 32, 64] species
- **Density variation**: [10, 50, 100, 500] animals per species
- **Ark positions**: Corner, center, and edge positions
- **Edge cases**: Minimal and maximal resource configurations

All tests use:
- Constant seed (4444) for reproducibility
- 4000 turns by default (customizable with `--test-time`)
- Parallel execution using all CPU cores

### Performance
- **Quick mode** (~8 tests): ~15-20 minutes with 8 workers (4000 turns per test)
- **Full suite** (~20 tests): ~40-50 minutes (estimated)
- Note: With 4000 turns, helpers have time to complete collection cycles and return to ark

## Results

Results are displayed in a formatted table and automatically saved to the `benchmark_results/` directory with a timestamped filename that includes:
- Date and time: `YYYY-MM-DD_HH-MM-SS` format
- Git commit hash: Short 8-character hash
- Branch name: Current git branch (sanitized)

**Filename format**: `results_<date>_<time>_<commit>_<branch>.csv`

**Example**: `results_2024-01-15_14-30-00_509b8e27_benchmarks.csv`

This allows you to:
- Track performance changes over time
- Compare results across different commits
- Organize results by branch
- Keep a complete history of benchmark runs

Results are automatically organized in the `benchmark_results/` folder, making it easy to compare performance across different code versions and branches.

