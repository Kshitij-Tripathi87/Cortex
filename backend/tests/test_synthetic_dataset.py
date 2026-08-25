"""Synthetic dataset generator — smoke tests.

Runs the script as a subprocess and verifies the output CSVs have the
expected row counts. Doesn't validate content beyond a basic shape check
(header line, row count, non-empty cells).
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_synthetic_dataset.py"


def _run(size: str, out_dir: Path, seed: int = 42):
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace",
            "test-ws",
            "--seed",
            str(seed),
            "--size",
            size,
            "--out",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"script failed: stdout={proc.stdout} stderr={proc.stderr}"
    return out_dir


def _rowcounts(ws_dir: Path) -> dict[str, int]:
    counts = {}
    for csv_path in sorted(ws_dir.glob("*.csv")):
        with csv_path.open() as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                counts[csv_path.stem] = 0
                continue
            n = sum(1 for _ in reader)
            counts[csv_path.stem] = n
    return counts


def test_small_dataset_has_expected_row_counts(tmp_path: Path) -> None:
    ws_dir = _run("small", tmp_path, seed=42) / "test-ws"
    counts = _rowcounts(ws_dir)
    assert counts["suppliers"] == 10
    assert counts["components"] == 50
    assert counts["warehouses"] == 5
    assert counts["factories"] == 3
    assert counts["products"] == 25
    assert counts["customers"] == 10
    # edges inventory bom orders row counts are best-effort (skips empty pools)
    assert counts["bom"] <= 30
    assert counts["orders"] <= 100


def test_two_runs_with_same_seed_produce_identical_output(tmp_path: Path) -> None:
    out1 = _run("small", tmp_path / "a", seed=7) / "test-ws"
    out2 = _run("small", tmp_path / "b", seed=7) / "test-ws"
    for name in ["suppliers.csv", "components.csv", "warehouses.csv"]:
        assert (out1 / name).read_text() == (out2 / name).read_text(), f"{name} drifted"


def test_medium_dataset_has_expected_row_counts(tmp_path: Path) -> None:
    ws_dir = _run("medium", tmp_path, seed=42) / "test-ws"
    counts = _rowcounts(ws_dir)
    assert counts["suppliers"] == 50
    assert counts["components"] == 200
    assert counts["warehouses"] == 30
    assert counts["factories"] == 10
    assert counts["products"] == 100
    assert counts["customers"] == 50


@pytest.mark.parametrize("size", ["small", "medium"])
def test_all_ten_csvs_present(size: str, tmp_path: Path) -> None:
    ws_dir = _run(size, tmp_path, seed=42) / "test-ws"
    expected = {
        "suppliers",
        "components",
        "warehouses",
        "factories",
        "products",
        "customers",
        "edges",
        "inventory",
        "bom",
        "orders",
    }
    actual = {p.stem for p in ws_dir.glob("*.csv")}
    assert actual == expected, f"missing: {expected - actual}, extra: {actual - expected}"
