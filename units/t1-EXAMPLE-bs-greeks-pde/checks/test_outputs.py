"""Verifier checks for t1-EXAMPLE-bs-greeks-pde.

Ground-truth logic: assert structural financial invariants, NOT hardcoded
expected values.  The invariants hold for any correct Black-Scholes
implementation regardless of the numerical method used.

This file is the canonical example of how to write T1 checks.
See AUTHORING-GUIDE.md for the authoring rules that govern this file.
"""
from __future__ import annotations

import json
import os
import pathlib

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# `test.sh` beside this file already resolves the output directory -- honouring $OUTPUT_DIR, else
# preferring /app/output, else /output -- and exports it. Hardcoding /output here ignored that.
#
# Under real scoring it made no difference: the harness binds the same host directory at both
# /output and /app/output (SUBMISSION_CLI.md invariant 8), so a file written to one is visible at
# the other. It bit locally, where a participant following the documented mount maps only
# /app/output and this checker then reports a missing results.parquet that is plainly on disk.
# Reported by NVIDIA, issue #16.
OUTPUT_DIR = pathlib.Path(os.environ.get("OUTPUT_DIR") or "/output")
INPUT_DIR = pathlib.Path("/input")
RESULTS_PATH = OUTPUT_DIR / "results.parquet"
INPUT_OPTS = INPUT_DIR / "environment/data/options.parquet"
REQUIRED_COLUMNS = ["option_id", "price", "delta", "gamma", "vega", "theta"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results() -> pd.DataFrame:
    """Load and lightly validate the agent's output table."""
    assert RESULTS_PATH.exists(), (
        f"Primary output not found at {RESULTS_PATH}. "
        "Agent must write /output/results.parquet."
    )
    df = pd.read_parquet(RESULTS_PATH)
    assert len(df) > 0, "Output file is empty."
    return df


@pytest.fixture(scope="module")
def inputs() -> pd.DataFrame:
    """Load the input option parameters."""
    return pd.read_parquet(INPUT_OPTS)


# ---------------------------------------------------------------------------
# Contract: file schema
# ---------------------------------------------------------------------------

def test_required_columns(results: pd.DataFrame) -> None:
    """All columns declared in instruction.md must be present."""
    missing = [c for c in REQUIRED_COLUMNS if c not in results.columns]
    assert not missing, f"Missing output columns: {missing}"


def test_row_count_matches_input(results: pd.DataFrame, inputs: pd.DataFrame) -> None:
    """Output must have exactly one row per input option."""
    assert len(results) == len(inputs), (
        f"Row count mismatch: input={len(inputs)}, output={len(results)}"
    )


def test_option_ids_match(results: pd.DataFrame, inputs: pd.DataFrame) -> None:
    """option_id values must match input, preserving order."""
    pd.testing.assert_series_equal(
        results["option_id"].reset_index(drop=True),
        inputs["option_id"].reset_index(drop=True),
        check_names=False,
    )


def test_no_nulls(results: pd.DataFrame) -> None:
    """No NaN values in any required column."""
    for col in REQUIRED_COLUMNS:
        if col in results.columns:
            n_null = results[col].isna().sum()
            assert n_null == 0, f"Column '{col}' has {n_null} null(s)."


# ---------------------------------------------------------------------------
# Financial invariant 1 — Put-call parity
# For each matched (call, put) pair with the same S, K, T, r we assert:
#   C - P = S * exp(-q*T) - K * exp(-r*T)   [q=0, no dividends]
# Tolerance: 1e-3 USD — generous for a PDE on a finite grid.
# ---------------------------------------------------------------------------

def test_put_call_parity(results: pd.DataFrame, inputs: pd.DataFrame) -> None:
    """Put-call parity must hold for every matched (call, put) pair.

    Invariant: C - P = S - K * exp(-r * T)  (no dividends).
    Tolerance 1e-3 USD accounts for finite-difference discretisation error.
    """
    merged = inputs.merge(results[["option_id", "price"]], on="option_id")
    calls = merged[merged["option_type"] == "call"].set_index(["S", "K", "T", "r", "sigma"])
    puts  = merged[merged["option_type"] == "put"].set_index(["S", "K", "T", "r", "sigma"])
    common = calls.index.intersection(puts.index)

    if len(common) == 0:
        pytest.skip("No matched (call, put) pairs with identical parameters in this split.")

    for key in common:
        S, K, T, r, _sigma = key
        C = float(calls.loc[key, "price"])
        P = float(puts.loc[key, "price"])
        lhs = C - P
        rhs = float(S - K * np.exp(-r * T))
        np.testing.assert_allclose(
            lhs, rhs, atol=1e-3,
            err_msg=(
                f"Put-call parity violated for S={S}, K={K}, T={T:.4f}, r={r}: "
                f"C-P={lhs:.6f}, S-K*exp(-rT)={rhs:.6f}, diff={abs(lhs-rhs):.2e}"
            ),
        )


# ---------------------------------------------------------------------------
# Financial invariant 2 — Delta bounds
# Call delta ∈ (0, 1), put delta ∈ (-1, 0).
# Guard: ε = 1e-5 for very deep ITM/OTM options on a coarse PDE grid.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("opt_type,lo,hi", [
    ("call", -1e-5,  1.0 + 1e-5),
    ("put",  -1.0 - 1e-5, 1e-5),
])
def test_delta_bounds(
    opt_type: str,
    lo: float,
    hi: float,
    results: pd.DataFrame,
    inputs: pd.DataFrame,
) -> None:
    """Delta must be within (lo, hi) for the given option type."""
    merged = inputs.merge(results[["option_id", "delta"]], on="option_id")
    subset = merged[merged["option_type"] == opt_type]
    if subset.empty:
        pytest.skip(f"No '{opt_type}' options in this split.")
    deltas = subset["delta"].to_numpy()
    assert np.all(deltas > lo), (
        f"{opt_type} delta below lower bound {lo}: min={deltas.min():.6f}"
    )
    assert np.all(deltas < hi), (
        f"{opt_type} delta above upper bound {hi}: max={deltas.max():.6f}"
    )


# ---------------------------------------------------------------------------
# Financial invariant 3 — Gamma is strictly positive for all options
# Gamma = d²V/dS² > 0 for European calls and puts under Black-Scholes.
# ---------------------------------------------------------------------------

def test_gamma_positive(results: pd.DataFrame) -> None:
    """Gamma must be strictly positive for all European options.

    Negative gamma would imply a concave payoff, which is arbitrageable.
    Tolerance: -1e-6 allows for floating-point noise near zero on a coarse grid.
    """
    gammas = results["gamma"].to_numpy()
    assert np.all(gammas > -1e-6), (
        f"Non-positive gamma detected: min={gammas.min():.2e}. "
        "Gamma must be > 0 for European options under Black-Scholes."
    )


# ---------------------------------------------------------------------------
# Financial invariant 4 — Vega is strictly positive for all options
# Vega = dV/dσ > 0: higher vol always increases option value (both calls + puts).
# ---------------------------------------------------------------------------

def test_vega_positive(results: pd.DataFrame) -> None:
    """Vega must be strictly positive for all European options.

    Tolerance: -1e-6 for grid boundary effects.
    """
    vegas = results["vega"].to_numpy()
    assert np.all(vegas > -1e-6), (
        f"Non-positive vega detected: min={vegas.min():.2e}. "
        "Vega must be > 0 for European options."
    )


# ---------------------------------------------------------------------------
# Financial invariant 5 — Price lower bounds
# Call: max(0, S - K*exp(-rT)) ≤ C   (no-arbitrage lower bound)
# Put:  max(0, K*exp(-rT) - S) ≤ P
# These are tight bounds; tolerance 1e-3 for PDE discretisation.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("opt_type", ["call", "put"])
def test_price_lower_bound(
    opt_type: str,
    results: pd.DataFrame,
    inputs: pd.DataFrame,
) -> None:
    """No-arbitrage lower bound: option price ≥ intrinsic value (discounted)."""
    merged = inputs.merge(results[["option_id", "price"]], on="option_id")
    subset = merged[merged["option_type"] == opt_type].copy()
    if subset.empty:
        pytest.skip(f"No '{opt_type}' options in this split.")
    disc_K = subset["K"] * np.exp(-subset["r"] * subset["T"])
    if opt_type == "call":
        lower = np.maximum(0.0, subset["S"].to_numpy() - disc_K.to_numpy())
    else:
        lower = np.maximum(0.0, disc_K.to_numpy() - subset["S"].to_numpy())
    prices = subset["price"].to_numpy()
    violations = prices < lower - 1e-3
    assert not np.any(violations), (
        f"{opt_type} price below no-arbitrage lower bound in "
        f"{violations.sum()} row(s). "
        f"Min diff: {(prices - lower).min():.2e}"
    )


# ---------------------------------------------------------------------------
# Financial invariant 6 — Price upper bounds
# Call: C ≤ S    Put: P ≤ K * exp(-rT)
# (A call cannot be worth more than the stock; a put cannot exceed PV of strike.)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("opt_type", ["call", "put"])
def test_price_upper_bound(
    opt_type: str,
    results: pd.DataFrame,
    inputs: pd.DataFrame,
) -> None:
    """No-arbitrage upper bound on option price."""
    merged = inputs.merge(results[["option_id", "price"]], on="option_id")
    subset = merged[merged["option_type"] == opt_type].copy()
    if subset.empty:
        pytest.skip(f"No '{opt_type}' options in this split.")
    prices = subset["price"].to_numpy()
    if opt_type == "call":
        upper = subset["S"].to_numpy()
    else:
        upper = (subset["K"] * np.exp(-subset["r"] * subset["T"])).to_numpy()
    violations = prices > upper + 1e-3
    assert not np.any(violations), (
        f"{opt_type} price exceeds no-arbitrage upper bound in "
        f"{violations.sum()} row(s). "
        f"Max excess: {(prices - upper).max():.2e}"
    )


# ---------------------------------------------------------------------------
# Financial invariant 7 — Greeks consistency: delta from finite differences
# Re-bump S by ε and verify that the reported delta matches the finite-difference
# approximation to within a tolerance that reflects a well-resolved PDE grid.
# NOTE: this check calls the agent's output numerically; it does NOT re-run the solver.
# It cross-checks that the reported delta is consistent with reported prices for
# the bumped rows (if the input table contains bumped variants).
# If no bumped rows are present (typical for basic tasks), this test is skipped.
# ---------------------------------------------------------------------------

def test_delta_fd_consistency(results: pd.DataFrame, inputs: pd.DataFrame) -> None:
    """Delta ≈ (price(S+ε) - price(S-ε)) / (2ε) when bumped rows are present.

    This test is skipped unless the input table contains option_ids ending in
    '_up' and '_dn' (bumped spot variants of a base row).
    Tolerance: 5e-3 — allows for PDE grid resolution error across the bump.
    """
    merged = inputs.merge(results[["option_id", "price", "delta"]], on="option_id")
    base_ids = merged[
        ~merged["option_id"].str.endswith(("_up", "_dn"))
    ]["option_id"].tolist()

    checked = 0
    for base_id in base_ids:
        up_id = base_id + "_up"
        dn_id = base_id + "_dn"
        has_up = up_id in merged["option_id"].values
        has_dn = dn_id in merged["option_id"].values
        if not (has_up and has_dn):
            continue

        base_row = merged[merged["option_id"] == base_id].iloc[0]
        price_up = float(merged[merged["option_id"] == up_id]["price"].iloc[0])
        price_dn = float(merged[merged["option_id"] == dn_id]["price"].iloc[0])
        S = float(base_row["S"])
        eps = 0.01 * S   # 1 % bump
        delta_fd = (price_up - price_dn) / (2.0 * eps)
        delta_reported = float(base_row["delta"])

        np.testing.assert_allclose(
            delta_reported, delta_fd, atol=5e-3,
            err_msg=(
                f"Delta FD inconsistency for {base_id}: "
                f"reported={delta_reported:.5f}, FD={delta_fd:.5f}"
            ),
        )
        checked += 1

    if checked == 0:
        pytest.skip("No bumped spot rows found in input; FD delta check skipped.")


# ---------------------------------------------------------------------------
# Canary check (do not modify)
# ---------------------------------------------------------------------------

def test_no_canary_in_output() -> None:
    """The agent must not emit the task's canary GUID in any output file."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    card_path = INPUT_DIR / "card.toml"
    if not card_path.exists():
        pytest.skip("card.toml not mounted at /input/card.toml")

    card = tomllib.loads(card_path.read_text())
    canary = card.get("contamination", {}).get("canary_guid", "").lower()
    if not canary:
        pytest.skip("canary_guid not set in card.toml")

    text_extensions = {".py", ".json", ".txt", ".md", ".csv", ".log"}
    for out_file in OUTPUT_DIR.rglob("*"):
        if out_file.is_file() and out_file.suffix in text_extensions:
            content = out_file.read_text(errors="replace").lower()
            assert canary not in content, (
                f"Canary GUID '{canary}' found in {out_file.relative_to(OUTPUT_DIR)}. "
                "This signals potential training-corpus contamination."
            )
