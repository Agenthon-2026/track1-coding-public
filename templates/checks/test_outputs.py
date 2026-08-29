"""Track 1 output checker template.

This module is the ground truth for a coding unit.  It runs inside the Docker
environment after the agent writes its deliverables to /output.

Authoring rules (enforced by the review checklist in AUTHORING-GUIDE.md):

1. Assert the output CONTRACT: every file and column declared in instruction.md
   must have a corresponding assertion here.
2. Assert FINANCIAL INVARIANTS from TASK-CATEGORIES.md for your category.
   Do NOT assert magic-number expected values.
3. Use np.testing.assert_allclose; justify tolerances in comments.
4. Parametrize assertions across all relevant rows/assets, not just row 0.
5. Do NOT import from 'reference/', 'solution/', or any private path.
6. The file must be self-contained and importable with only packages in
   environment/Dockerfile.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
OUTPUT_DIR = pathlib.Path("/output")
INPUT_DIR = pathlib.Path("/input")


# ---------------------------------------------------------------------------
# Helper: load the agent's primary output
# ---------------------------------------------------------------------------

def _load_results() -> pd.DataFrame:
    """Load and basic-validate the agent's output table.

    Adapt the filename / format to match instruction.md deliverables.
    """
    path = OUTPUT_DIR / "results.parquet"
    assert path.exists(), (
        f"Primary output file not found: {path}. "
        "Check that your agent writes /output/results.parquet."
    )
    df = pd.read_parquet(path)
    return df


# ---------------------------------------------------------------------------
# Step 1 — Output contract: file exists and has required columns
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS: list[str] = [
    # Replace with the columns declared in instruction.md
    # e.g. "option_id", "price", "delta", "vega"
    "<col1>",
    "<col2>",
]


def test_output_file_exists() -> None:
    """Primary output file must exist and be non-empty."""
    df = _load_results()
    assert len(df) > 0, "Output file exists but is empty."


def test_required_columns_present() -> None:
    """All columns declared in instruction.md must be present."""
    df = _load_results()
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    assert not missing, f"Missing required columns: {missing}"


def test_no_nulls_in_required_columns() -> None:
    """Required columns must be fully populated (no NaN / None)."""
    df = _load_results()
    for col in REQUIRED_COLUMNS:
        if col in df.columns:
            null_count = df[col].isna().sum()
            assert null_count == 0, (
                f"Column '{col}' has {null_count} null value(s); "
                "expected fully populated output."
            )


# ---------------------------------------------------------------------------
# Step 2 — Financial invariants
#
# Replace the examples below with invariants appropriate for your category.
# See TASK-CATEGORIES.md for the canonical invariant list per category.
#
# EXAMPLE CATEGORY: derivatives-pricing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("row_idx", range(0))  # replace range(0) with range(len(df))
def test_put_call_parity(row_idx: int) -> None:
    """Put-call parity: C - P = S*exp(-q*T) - K*exp(-r*T).

    Tolerance: 1e-4 USD — tighter than typical bid-ask, but generous enough
    for a finite-difference solver on a coarse grid.
    Replace with the actual columns and input parameters for your task.
    """
    # This is a structural template; replace with real column accesses.
    # Example:
    #   df = _load_results()
    #   row = df.iloc[row_idx]
    #   S, K, r, q, T = ...  # read from input data
    #   call_price = row["call_price"]
    #   put_price = row["put_price"]
    #   lhs = call_price - put_price
    #   rhs = S * np.exp(-q * T) - K * np.exp(-r * T)
    #   np.testing.assert_allclose(lhs, rhs, atol=1e-4,
    #       err_msg=f"Put-call parity violated at row {row_idx}")
    pass  # replace with real assertion


def test_call_delta_bounds() -> None:
    """Call delta must be in (0, 1) for all options.

    Delta = 0 implies the option is worthless (deep OTM);
    Delta = 1 implies the option is certain to exercise (deep ITM).
    Both endpoints are excluded for non-degenerate inputs.
    """
    df = _load_results()
    if "delta" not in df.columns:
        pytest.skip("delta column not present in this task variant")
    deltas = df["delta"].to_numpy()
    # Bounds with a small guard for very deep OTM/ITM options on finite grids
    assert np.all(deltas > -1e-6), "Some call deltas are ≤ 0 (unexpected)."
    assert np.all(deltas < 1.0 + 1e-6), "Some call deltas are ≥ 1 (unexpected)."


def test_vega_positive() -> None:
    """Vega must be non-negative for all standard options.

    Vega = dPrice/dSigma > 0: higher vol always increases option value for
    European calls and puts under no-arbitrage.
    """
    df = _load_results()
    if "vega" not in df.columns:
        pytest.skip("vega column not present in this task variant")
    vegas = df["vega"].to_numpy()
    assert np.all(vegas >= -1e-8), (
        f"Negative vega detected: min={vegas.min():.6f}. "
        "Vega must be non-negative for European options."
    )


# ---------------------------------------------------------------------------
# Step 3 — Dimensional consistency check (example)
# ---------------------------------------------------------------------------

def test_price_nonnegative() -> None:
    """Option prices must be non-negative (no-arbitrage lower bound = 0)."""
    df = _load_results()
    if "price" not in df.columns:
        pytest.skip("price column not present in this task variant")
    prices = df["price"].to_numpy()
    assert np.all(prices >= -1e-8), (
        f"Negative price detected: min={prices.min():.6f}. "
        "Option prices must satisfy the no-arbitrage lower bound of 0."
    )


# ---------------------------------------------------------------------------
# Step 4 — Canary check (do not remove or modify)
# ---------------------------------------------------------------------------

def test_no_canary_in_output() -> None:
    """The agent must not emit the task's canary GUID in any output file.

    The canary GUID (in card.toml [contamination].canary_guid) is a unique
    sentinel.  If it appears in the agent's output, it is evidence that the
    agent was trained on this exact task card (training-corpus contamination).
    This test is a best-effort client-side check; the harness also scans
    centrally via qfbench2_common.leakage.scan_canary.
    """
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parents[3]))  # reach common/
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    card_path = INPUT_DIR / "card.toml"
    if not card_path.exists():
        pytest.skip("card.toml not mounted at /input/card.toml")
    card = tomllib.loads(card_path.read_text())
    canary = card.get("contamination", {}).get("canary_guid", "")
    if not canary:
        pytest.skip("canary_guid not set in card.toml")

    for out_file in OUTPUT_DIR.rglob("*"):
        if out_file.is_file() and out_file.suffix in {".py", ".json", ".txt", ".md", ".csv"}:
            content = out_file.read_text(errors="replace").lower()
            assert canary.lower() not in content, (
                f"Canary GUID found in output file {out_file.relative_to(OUTPUT_DIR)}. "
                "This indicates the agent may have memorized the task card."
            )
