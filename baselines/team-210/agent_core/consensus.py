"""Agreement between independently produced deliverables.

The model-agnostic honesty driver. A self-check proves an answer has the
right SHAPE; it cannot prove the numbers are right, and the false-confidence
cases are exactly answers with the right shape and wrong numbers. Two
solutions written independently (different seed, a nudge towards a different
computational route) that land on the SAME numbers are far less likely to
share a mistake than one solution asserting its own formula. Disagreement is
the evidence that a reconciliation round needs - evidence from the output,
not from the shape of the code, so it holds for any model the organizers
plug in, deterministic or not. A model that varies between runs is a *gift*
here: its variance is free diversity for the vote.

Fingerprints are flat {label: number} maps; anything non-numeric is ignored,
and a unit with no numeric deliverable simply cannot be compared (reported
as such - never as agreement).
"""

from __future__ import annotations

import json
import math
import pathlib

from .contracts import OutputContract

#: Independent methods legitimately differ by discretisation / Monte Carlo
#: noise; a real bug differs by orders of magnitude or a sign. 2% relative is
#: wide enough to forgive a method change and narrow enough to catch a
#: wrong formula, which is what the contrast set shows dishonest passes are.
RTOL = 2e-2
ATOL = 1e-6
#: Table columns are summarised, not compared row by row: statistics are
#: order-insensitive, which matters because two candidates may sort
#: differently while both being right.
_TABLE_STATS = ("mean", "min", "max")
MAX_ITEMS = 400


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        try:
            out = float(value)
        except ValueError:
            return None
        return out if math.isfinite(out) else None
    return None


def _flatten_json(node, prefix: str, out: dict) -> None:
    if len(out) >= MAX_ITEMS:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            _flatten_json(value, f"{prefix}.{key}" if prefix else str(key), out)
    elif isinstance(node, list):
        for i, value in enumerate(node[:50]):
            _flatten_json(value, f"{prefix}[{i}]", out)
    else:
        number = _num(node)
        if number is not None:
            out[prefix] = number


def _table_fingerprint(path: pathlib.Path, prefix: str, out: dict) -> None:
    try:
        import pandas as pd
        frame = (pd.read_parquet(path) if path.suffix.lower() == ".parquet"
                 else pd.read_csv(path))
    except Exception:
        return
    out[f"{prefix}:rows"] = float(len(frame))
    numeric = frame.select_dtypes(include="number")
    for column in list(numeric.columns)[:60]:
        series = numeric[column].dropna()
        if series.empty:
            continue
        for stat in _TABLE_STATS:
            value = _num(getattr(series, stat)())
            if value is not None:
                out[f"{prefix}:{column}.{stat}"] = value


def fingerprint(output_dir: pathlib.Path,
                contracts: tuple[OutputContract, ...]) -> dict[str, float]:
    out: dict[str, float] = {}
    for contract in contracts:
        path = output_dir / contract.filename
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                _flatten_json(json.loads(path.read_text(encoding="utf-8")),
                              contract.filename, out)
            except Exception:
                continue
        elif suffix in (".parquet", ".csv"):
            _table_fingerprint(path, contract.filename, out)
    return out


def compare(a: dict[str, float], b: dict[str, float],
            rtol: float = RTOL, atol: float = ATOL
            ) -> tuple[bool | None, list[str]]:
    """(agree, mismatches). `agree` is None when nothing numeric is shared."""
    shared = sorted(set(a) & set(b))
    if not shared:
        return None, []
    mismatches: list[str] = []
    for key in shared:
        x, y = a[key], b[key]
        if abs(x - y) > atol + rtol * max(abs(x), abs(y)):
            mismatches.append(f"{key}: {x:.6g} vs {y:.6g}")
    for key in sorted(set(a) ^ set(b)):
        mismatches.append(f"{key}: present in one candidate only")
    return not mismatches, mismatches[:40]


def snapshot(output_dir: pathlib.Path,
             contracts: tuple[OutputContract, ...]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for contract in contracts:
        path = output_dir / contract.filename
        if path.is_file():
            files[contract.filename] = path.read_bytes()
    return files


def restore(output_dir: pathlib.Path, files: dict[str, bytes]) -> None:
    for name, payload in files.items():
        target = output_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


INDEPENDENT_HINT = (
    "INDEPENDENT ATTEMPT {variant}: write a fresh, complete solution to the "
    "task WITHOUT reference to any earlier program. Where a materially "
    "different but equally valid computational route exists (closed form vs "
    "numerical, matrix vs iterative, library vs manual), prefer the one you "
    "would NOT reach for first - two independent answers will be compared "
    "quantity by quantity.")

RECONCILE_DEMAND = (
    "cross-validation: two independently written solutions both passed the "
    "local checks but DISAGREE on these quantities:\n{mismatches}\n\n"
    "At least one is wrong. Do not pick a side by preference: determine "
    "which is right with an explicit third computation (a hand-checkable "
    "special case, a known identity, a limit, a library reference), assert "
    "the winner reproduces it within tolerance, and then rewrite the "
    "deliverables from the verified computation. The second program was:\n"
    "```python\n{other}\n```")
