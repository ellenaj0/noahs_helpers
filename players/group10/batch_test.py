#!/usr/bin/env python3
import csv
import datetime as dt
import os
import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional

RESULTS_FILE = "./players/group10/ark_results.csv"

os.chdir("../..")


@dataclass(frozen=True)
class ExperimentConfig:
    player: str
    num_helpers: int
    animals: str  # space-separated ints, as in the shell script
    ark_x: int
    ark_y: int
    time: int
    seed: int
    gui: bool = False  # batch mode: default to no GUI


def build_command(cfg: ExperimentConfig) -> List[str]:
    """Build the uv/main.py command for a given config."""
    cmd = [
        "uv",
        "run",
        "main.py",
        "--player",
        cfg.player,
        "--num_helpers",
        str(cfg.num_helpers),
        "--animals",
        *cfg.animals.split(),
        "--ark",
        str(cfg.ark_x),
        str(cfg.ark_y),
        "-T",
        str(cfg.time),
        "--seed",
        str(cfg.seed),
    ]
    if cfg.gui:
        cmd.append("--gui")
    return cmd


def extract_metric(output: str) -> Optional[float]:
    """
    Extract a numeric metric from the simulator output.

    """
    patterns = [
        r"SCORE=\s*([0-9]+)",
    ]
    # print(output)
    for pat in patterns:
        m = re.search(pat, output)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def load_previous_results(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def save_results(path: str, rows: List[dict]) -> None:
    file_exists = os.path.exists(path)
    fieldnames = [
        "timestamp",
        "player",
        "num_helpers",
        "animals",
        "ark_x",
        "ark_y",
        "time",
        "seed",
        "gui",
        "metric",
        "success",
    ]
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)


def compare_with_previous(
    cfg: ExperimentConfig,
    metric: Optional[float],
    previous_rows: List[dict],
) -> None:
    """
    Compare the new metric with previous results for the same config.
    Prints a short summary.
    """

    # Identify "same config" rows by matching key fields
    def same_config(row: dict) -> bool:
        return (
            row.get("player") == cfg.player
            and int(row.get("num_helpers", -1)) == cfg.num_helpers
            and row.get("animals") == cfg.animals
            and int(row.get("ark_x", -1)) == cfg.ark_x
            and int(row.get("ark_y", -1)) == cfg.ark_y
            and int(row.get("time", -1)) == cfg.time
        )

    same_cfg_rows = [r for r in previous_rows if same_config(r)]

    if not same_cfg_rows:
        print("  No previous results for this config.")
        return

    prev_metrics = []
    for r in same_cfg_rows:
        try:
            if r.get("metric"):
                prev_metrics.append(float(r["metric"]))
        except ValueError:
            continue

    if not prev_metrics:
        print("  Previous results found, but they had no valid metric.")
        return

    best_prev = max(prev_metrics)
    if metric is None:
        print(
            f"  Previous best metric for this config: {best_prev:.3f} (new metric unavailable)"
        )
        return

    diff = metric - best_prev
    trend = "IMPROVED" if diff > 0 else ("TIED" if diff == 0 else "WORSE")
    print(
        f"  Previous best: {best_prev:.3f}, new: {metric:.3f} ({trend}, Δ={diff:+.3f})"
    )


def main():
    # Define a variety of experiment settings.
    # You can tweak this list however you like.
    base_player = "10"

    animals_sets = [
        "2 4 6 8 10 12 14 16 18 20 20 20 20",
        "10 20 40 60 80 100 120 140 160 180",
        "4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 100",
    ]

    num_helpers_list = [5, 20, 40]
    ark_positions = [(500, 500), (900, 900)]
    time_limit = 4000

    experiments: List[ExperimentConfig] = []

    for animals in animals_sets:
        for num_helpers in num_helpers_list:
            for ark_x, ark_y in ark_positions:
                experiments.append(
                    ExperimentConfig(
                        player=base_player,
                        num_helpers=num_helpers,
                        animals=animals,
                        ark_x=ark_x,
                        ark_y=ark_y,
                        time=time_limit,
                        seed=4444,
                        gui=False,
                    )
                )

    print(f"Planned experiments: {len(experiments)}")

    previous = load_previous_results(RESULTS_FILE)
    new_rows: List[dict] = []

    for i, cfg in enumerate(experiments, start=1):
        print(
            f"\n=== Experiment {i}/{len(experiments)} ===\n"
            f"  player={cfg.player}, helpers={cfg.num_helpers}, "
            f"animals={cfg.animals}, ark=({cfg.ark_x},{cfg.ark_y}), "
            f"T={cfg.time}, seed={cfg.seed}"
        )

        cmd = build_command(cfg)
        print("  Running:", " ".join(cmd))

        proc = subprocess.run(cmd, capture_output=True, text=True)

        success = proc.returncode == 0
        if not success:
            print("  Simulation FAILED with return code:", proc.returncode)
            print("  stderr:\n", proc.stderr)

        metric = extract_metric(proc.stdout)
        if metric is not None:
            print(f"  Extracted metric: {metric:.3f}")
        else:
            print("  Could not extract metric from output; storing as empty.")

        compare_with_previous(cfg, metric, previous)

        row = {
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "player": cfg.player,
            "num_helpers": cfg.num_helpers,
            "animals": cfg.animals,
            "ark_x": cfg.ark_x,
            "ark_y": cfg.ark_y,
            "time": cfg.time,
            "seed": cfg.seed,
            "gui": int(cfg.gui),
            "metric": "" if metric is None else metric,
            "success": int(success),
        }
        new_rows.append(row)

    if new_rows:
        save_results(RESULTS_FILE, new_rows)
        print(f"\nSaved {len(new_rows)} new result rows to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
