"""Solve only the public Black-Scholes exemplar through the submission CLI.

This is a transport example, not a benchmark baseline. It deliberately handles one public task so
participants can test qfbench2 execution, verification, and image packaging before adding an LLM.
"""

from __future__ import annotations

import argparse
import math
import pathlib
from collections.abc import Sequence

import numpy as np
import pandas as pd

EXEMPLAR_ID = "t1-EXAMPLE-bs-greeks-pde"


def _normal_cdf(values: np.ndarray) -> np.ndarray:
    erf = np.vectorize(math.erf, otypes=[float])
    return 0.5 * (1.0 + erf(values / math.sqrt(2.0)))


def _input_path(task_dir: pathlib.Path) -> pathlib.Path:
    candidates = (
        task_dir / "environment/data/options.parquet",
        task_dir / "data/options.parquet",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "options.parquet was not found in the mounted exemplar task"
    )


def solve(task_dir: str | pathlib.Path, out: str | pathlib.Path) -> pathlib.Path:
    """Write a valid results.parquet for the one public exemplar."""

    task = pathlib.Path(task_dir)
    if task.name not in {EXEMPLAR_ID, "app", "input"}:
        raise ValueError(
            f"the example agent supports only {EXEMPLAR_ID}, got {task.name!r}"
        )

    options = pd.read_parquet(_input_path(task))
    spot = options["S"].to_numpy(dtype=float)
    strike = options["K"].to_numpy(dtype=float)
    maturity = options["T"].to_numpy(dtype=float)
    rate = options["r"].to_numpy(dtype=float)
    volatility = options["sigma"].to_numpy(dtype=float)
    option_type = options["option_type"].astype(str).to_numpy()

    sqrt_t = np.sqrt(maturity)
    d1 = (np.log(spot / strike) + (rate + 0.5 * volatility**2) * maturity) / (
        volatility * sqrt_t
    )
    d2 = d1 - volatility * sqrt_t
    discount = np.exp(-rate * maturity)
    density = np.exp(-0.5 * d1**2) / np.sqrt(2.0 * np.pi)
    is_call = option_type == "call"

    cdf_d1 = _normal_cdf(d1)
    cdf_d2 = _normal_cdf(d2)
    cdf_minus_d1 = _normal_cdf(-d1)
    cdf_minus_d2 = _normal_cdf(-d2)
    call_price = spot * cdf_d1 - strike * discount * cdf_d2
    put_price = strike * discount * cdf_minus_d2 - spot * cdf_minus_d1
    call_theta = (
        -spot * density * volatility / (2.0 * sqrt_t)
        - rate * strike * discount * cdf_d2
    )
    put_theta = (
        -spot * density * volatility / (2.0 * sqrt_t)
        + rate * strike * discount * cdf_minus_d2
    )

    result = pd.DataFrame(
        {
            "option_id": options["option_id"],
            "price": np.where(is_call, call_price, put_price),
            "delta": np.where(is_call, cdf_d1, cdf_d1 - 1.0),
            "gamma": density / (spot * volatility * sqrt_t),
            "vega": spot * density * sqrt_t,
            "theta": np.where(is_call, call_theta, put_theta) / 365.0,
        }
    )
    output = pathlib.Path(out)
    output.mkdir(parents=True, exist_ok=True)
    target = output / "results.parquet"
    result.to_parquet(target, index=False)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Track 1 exemplar agent")
    parser.add_argument("verb", choices=["solve"])
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    solve(args.task_dir, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
