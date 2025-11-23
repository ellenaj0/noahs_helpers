"""Format and display benchmark results."""

import csv
import pathlib
from typing import List, Dict, Any


def format_table(results: List[Dict[str, Any]]) -> str:
    """Format results as a table string.

    Args:
        results: List of result dictionaries

    Returns:
        Formatted table string
    """
    if not results:
        return "No results to display."

    # Define column headers and widths
    headers = [
        "Test Name",
        "Helpers",
        "Species",
        "Total Animals",
        "Density",
        "Ark Pos",
        "Score",
        "Time (s)",
    ]
    col_widths = [
        max(len(str(h)), max((len(str(r.get(k, ""))) for r in results), default=0))
        for h, k in zip(
            headers,
            [
                "test_name",
                "num_helpers",
                "num_species",
                "total_animals",
                "density",
                "ark_pos",
                "score",
                "execution_time",
            ],
        )
    ]
    col_widths[0] = min(col_widths[0], 50)  # Limit test name width

    # Create header row
    header_row = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    separator = "-" * len(header_row)

    # Create data rows
    rows = [header_row, separator]
    for result in results:
        test_name = result.get("test_name", "")[:50]  # Truncate if too long
        row = " | ".join(
            [
                str(test_name).ljust(col_widths[0]),
                str(result.get("num_helpers", "")).ljust(col_widths[1]),
                str(result.get("num_species", "")).ljust(col_widths[2]),
                str(result.get("total_animals", "")).ljust(col_widths[3]),
                str(result.get("density", "")).ljust(col_widths[4]),
                str(result.get("ark_pos", "")).ljust(col_widths[5]),
                str(result.get("score", "")).ljust(col_widths[6]),
                f"{result.get('execution_time', 0):.2f}".ljust(col_widths[7]),
            ]
        )
        rows.append(row)

    return "\n".join(rows)


def save_csv(results: List[Dict[str, Any]], output_path: pathlib.Path):
    """Save results to CSV file.

    Args:
        results: List of result dictionaries
        output_path: Path to output CSV file
    """
    if not results:
        return

    fieldnames = [
        "test_name",
        "num_helpers",
        "num_species",
        "total_animals",
        "density",
        "ark_pos",
        "score",
        "execution_time",
        "status",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow({k: result.get(k, "") for k in fieldnames})


def display_results(results: List[Dict[str, Any]], output_csv: pathlib.Path = None):
    """Display and optionally save results.

    Args:
        results: List of result dictionaries
        output_csv: Optional path to save CSV file
    """
    # Sort by score (descending)
    results_sorted = sorted(results, key=lambda x: x.get("score", 0), reverse=True)

    # Display table
    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS")
    print("=" * 80)
    print(format_table(results_sorted))
    print("=" * 80)

    # Summary statistics
    if results:
        scores = [r.get("score", 0) for r in results if r.get("status") == "success"]
        if scores:
            print("\nSummary:")
            print(f"  Total tests: {len(results)}")
            print(
                f"  Successful: {sum(1 for r in results if r.get('status') == 'success')}"
            )
            print(
                f"  Failed: {sum(1 for r in results if r.get('status') != 'success')}"
            )
            print(f"  Average score: {sum(scores) / len(scores):.2f}")
            print(f"  Best score: {max(scores)}")
            print(f"  Worst score: {min(scores)}")

    # Save to CSV if requested
    if output_csv:
        save_csv(results_sorted, output_csv)
        print(f"\nResults saved to: {output_csv}")
