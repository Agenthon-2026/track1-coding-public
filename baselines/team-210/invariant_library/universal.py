"""The invariants that generalise, and only those.

The masterplan called for ten category modules. Mining the 87 public checkers
says that is the wrong shape: 1931 *distinct* test-function names across 2252
assertions - about 22 bespoke assertions per unit - and the twenty most common
finance invariants together account for roughly 100 of the 1638 semantic ones.
The vocabulary does not repeat, so a domain library cannot pre-cover the hidden
tasks.

What does repeat is thin and structural: does the file exist, does it have the
right columns, did every input row survive, are quantities that must be positive
positive, is anything NaN. 614 of the 2252 assertions (27%) are of that kind, and
unlike the rest they transfer to a task nobody has seen.

So this module stays small on purpose. A category module earns its place only
when the local failure matrix shows a category failing repeatedly for a finance
reason rather than a contract one.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

try:
    import numpy as np
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - present in the sandbox image
    np = None
    pd = None


@dataclass(frozen=True)
class Violation:
    check: str
    detail: str

    def __str__(self) -> str:
        return f"{self.check}: {self.detail}"


def file_exists(path) -> list[Violation]:
    import pathlib
    p = pathlib.Path(path)
    if not p.is_file():
        return [Violation("file_exists", f"nothing at {p}")]
    if p.stat().st_size == 0:
        return [Violation("file_exists", f"{p} is empty")]
    return []


def columns_present(frame, required: tuple[str, ...]) -> list[Violation]:
    if not required:
        return []
    missing = [c for c in required if c not in frame.columns]
    if missing:
        return [Violation("columns_present", f"missing {missing}; "
                                             f"have {list(frame.columns)}")]
    return []


def row_count_matches(frame, expected: int) -> list[Violation]:
    if len(frame) != expected:
        return [Violation("row_count", f"{len(frame)} rows, expected {expected}")]
    return []


def row_key_preserved(frame, source_frame, key: str) -> list[Violation]:
    """Every identifier in the input must appear exactly once in the output.

    `test_option_ids_match` and its many spellings are among the few semantic
    checks that do recur, because almost every table task carries an identifier.
    """
    if key not in frame.columns:
        return [Violation("row_key", f"output has no column {key!r}")]
    if key not in source_frame.columns:
        return []
    out, src = list(frame[key]), list(source_frame[key])
    if len(set(out)) != len(out):
        return [Violation("row_key", f"{key} is not unique in the output")]
    missing = set(src) - set(out)
    extra = set(out) - set(src)
    problems = []
    if missing:
        problems.append(f"{len(missing)} input ids absent from output")
    if extra:
        problems.append(f"{len(extra)} output ids not in input")
    return [Violation("row_key", "; ".join(problems))] if problems else []


def no_nulls(frame, columns: tuple[str, ...] = ()) -> list[Violation]:
    """A required column that is ENTIRELY null was never computed.

    Partial nulls are not a violation: graders accepted them on units where
    they are the honest answer (an open position has no realised pnl, a
    tenor with no market quote has no yield), and blocking on them cost two
    graded-passing units in the v2/v3 sweeps - the self-check must never be
    stricter than the grader.
    """
    cols = columns or tuple(frame.columns)
    out = []
    for c in cols:
        if c not in frame.columns or len(frame) == 0:
            continue
        if bool(frame[c].isnull().all()):
            out.append(Violation("no_nulls", f"column {c!r} is entirely null"))
    return out


def all_finite(frame, columns: tuple[str, ...] = ()) -> list[Violation]:
    """NaN is caught by no_nulls; this catches +/-inf, which passes isnull().

    Vectorised through numpy, not per-element `.apply` with an isinstance
    filter: a float32 inf is an `np.float32`, not a `float`, so the old
    element-wise check waved it through - the exact value class this check
    exists for - and was slow on large frames besides.
    """
    if pd is None or np is None:
        return []
    cols = columns or tuple(frame.select_dtypes("number").columns)
    out = []
    for c in cols:
        if c not in frame.columns:
            continue
        try:
            values = frame[c].to_numpy(dtype="float64", copy=False)
        except (TypeError, ValueError):
            continue  # non-numeric column; finiteness does not apply
        bad = int(np.isinf(values).sum())
        if bad:
            out.append(Violation("all_finite", f"column {c!r} has {bad} non-finite"))
    return out


def sign(frame, column: str, *, positive: bool, tolerance: float) -> list[Violation]:
    """A quantity that must not change sign, checked at the grader's tolerance.

    The tolerance argument is mandatory and has no default on purpose. Writing
    `> 0` where the grader writes `> -1e-6` rejects correct answers: in the
    worked exemplar, twelve of ninety-eight rows sit exactly on a bound because
    a deep in-the-money option days from expiry has N(d1) == 1.0 in floating
    point. A self-check stricter than the grader burns iterations; one looser
    lets failures through.
    """
    if column not in frame.columns:
        return [Violation("sign", f"no column {column!r}")]
    values = frame[column]
    bad = (values < -tolerance) if positive else (values > tolerance)
    count = int(bad.sum())
    if count:
        worst = float(values[bad].min() if positive else values[bad].max())
        direction = "positive" if positive else "negative"
        return [Violation("sign", f"{column!r}: {count} value(s) not {direction} "
                                  f"within {tolerance:g}, worst {worst:g}")]
    return []


def within(frame, column: str, low: float, high: float,
           tolerance: float) -> list[Violation]:
    if column not in frame.columns:
        return [Violation("within", f"no column {column!r}")]
    values = frame[column]
    bad = (values < low - tolerance) | (values > high + tolerance)
    count = int(bad.sum())
    if count:
        return [Violation("within", f"{column!r}: {count} value(s) outside "
                                    f"[{low:g}, {high:g}] +/- {tolerance:g}")]
    return []


def rank_valid(frame, column: str) -> list[Violation]:
    """A column named like a rank must BE a rank: integers 1..N, complete,
    no duplicates.

    Evidence: 4 held-out units failed `test_rank_is_descending_and_complete`
    with rankings that had gaps or repeats - the single most repeated
    assertion failure in the 30x1 post-mortem, and it needs no finance at
    all, only reading the contract to the end.
    """
    if column not in frame.columns:
        return []
    values = frame[column]
    problems = []
    try:
        as_int = values.astype("int64")
    except (ValueError, TypeError):
        return [Violation("rank_valid", f"{column!r} is not integer-like")]
    if (as_int != values).any():
        problems.append("non-integer ranks")
    expected = set(range(1, len(frame) + 1))
    got = set(int(v) for v in as_int)
    if got != expected:
        missing = sorted(expected - got)[:5]
        dupes = len(frame) - len(got)
        problems.append(f"not a complete 1..{len(frame)} ranking"
                        + (f"; missing {missing}" if missing else "")
                        + (f"; {dupes} duplicate(s)" if dupes else ""))
    return [Violation("rank_valid", f"{column!r}: " + "; ".join(problems))] \
        if problems else []


#: Column names that promise a ranking.
_RANKISH = ("rank", "ranking")


#: Column names whose values cannot be negative in any finance convention.
_NONNEGATIVE = ("price", "premium", "vol", "variance", "std", "stdev",
                "sigma", "prob", "probability", "count", "notional",
                "volume", "duration", "half_life")
#: ...and names for which negative values are the normal case, even when a
#: non-negative token is embedded (log_price, pnl_vol_ratio, return_std).
_SIGNED = ("return", "pnl", "p&l", "log", "diff", "change", "delta", "spread",
           "z_", "zscore", "score", "sens", "beta", "alpha", "skew",
           "excess", "error", "residual", "drift", "theta", "rho", "carry")


def _nonnegative_name(column: str) -> bool:
    name = column.lower()
    if any(s in name for s in _SIGNED):
        return False
    return any(t in name for t in _NONNEGATIVE)


def plausible_values(frame) -> list[Violation]:
    """Degenerate numerics: shapes that are never a computed answer.

    From the v3 false-confidence dossier, four graded-0 units passed every
    contract check with numbers that no finance could produce: european
    option prices of exactly 0.0 (american-fd), knock-out prices of -200
    (digital-barrier), a local-vol column that is entirely NaN (dupire), a
    tail index of 2.9 where the data admit < 1 (smith - NOT caught here:
    range knowledge is domain-specific and belongs in the playbook). Three
    shapes are domain-free: a numeric column entirely null, a numeric
    column entirely zero, and negatives in a column whose name says it is
    a price / vol / variance / probability. Each here points at >= 1
    graded failure and at no graded pass in v1-v3.
    """
    if pd is None:
        return []
    out = []
    numeric = frame.select_dtypes(include="number")
    if len(frame) == 0:
        return out
    for column in numeric.columns:
        series = numeric[column]
        if bool(series.isnull().all()):
            out.append(Violation("degenerate", f"column {column!r} is entirely null"))
            continue
        values = series.dropna()
        if len(values) >= 3 and bool((values == 0).all()):
            out.append(Violation("degenerate", f"column {column!r} is entirely zero"))
        elif _nonnegative_name(str(column)) and bool((values < 0).any()):
            # Relative, not absolute: a quadrature price of -7e-4 next to
            # prices of order 1e2 is integration noise the grader itself
            # expects (stochvol-implied-surface); the absolute rule killed
            # a correct candidate. A real sign bug is a large negative.
            scale = float(values.abs().max()) or 1.0
            bad = values[values < -1e-3 * scale]
            if len(bad):
                out.append(Violation("degenerate",
                                     f"column {column!r} has {len(bad)} negative "
                                     "value(s) beyond 0.1% of its scale but its "
                                     "name says it cannot be negative"))
    return out


def check_contract(path, contract, source_frame=None) -> list[Violation]:
    """Everything derivable from the OutputContract alone.

    This is what the agent runs before declaring success, and it is deliberately
    the same set of questions the recurring 27% of grader assertions ask.
    """
    problems = file_exists(path)
    if problems or pd is None:
        return problems

    import pathlib
    p = pathlib.Path(path)

    # JSON never goes through pandas. `pd.read_json` on a dict of scalars -
    # the single most common deliverable shape, {"sharpe": 1.2, ...} - raises
    # "If using all scalar values, you must pass an index", so the self-check
    # declared a *correct* answer unreadable and the repair loop then spent
    # every remaining iteration mangling it. JSON is validated as JSON: the
    # required "columns" are required keys.
    if contract.fmt == "json":
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            return [Violation("readable", f"{p.name} is not valid JSON: {error}")]
        return problems + _check_json_payload(payload, contract)

    try:
        if contract.fmt == "parquet":
            frame = pd.read_parquet(p)
        elif contract.fmt == "csv":
            frame = pd.read_csv(p)
        else:
            return []
    except Exception as error:
        return [Violation("readable", f"{p.name} could not be parsed: {error}")]

    problems += columns_present(frame, contract.required_columns)
    problems += no_nulls(frame, contract.required_columns)
    problems += all_finite(frame, contract.required_columns)
    problems += plausible_values(frame)
    for column in contract.required_columns:
        if any(k in column.lower() for k in _RANKISH):
            problems += rank_valid(frame, column)
    if source_frame is not None and contract.row_key:
        problems += row_key_preserved(frame, source_frame, contract.row_key)
    return problems


def _check_json_payload(payload, contract) -> list[Violation]:
    """Key presence and finiteness for a JSON deliverable, pandas-free."""
    required = tuple(contract.required_columns)
    problems: list[Violation] = []

    if isinstance(payload, dict):
        records = [payload]
    elif isinstance(payload, list):
        records = [r for r in payload if isinstance(r, dict)]
        if required and not records:
            return [Violation("columns_present",
                              f"array holds no objects carrying {list(required)}")]
    else:
        return []  # a bare scalar or string is a valid JSON deliverable shape

    if required:
        missing = [k for k in required if any(k not in r for r in records)]
        if missing:
            have = sorted({k for r in records for k in r})
            problems.append(Violation("columns_present",
                                      f"missing {missing}; have {have}"))

    for record in records:
        numerics = {}
        for key, value in record.items():
            if isinstance(value, float) and not math.isfinite(value):
                problems.append(Violation("all_finite",
                                          f"key {key!r} is non-finite"))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numerics[key] = float(value)
                if value < 0 and _nonnegative_name(str(key)):
                    problems.append(Violation(
                        "degenerate", f"key {key!r} = {value} but its name "
                        "says it cannot be negative"))
        # american-fd: every headline number was 0.0 and the self-check
        # passed. A record whose numerics are ALL zero was not computed.
        if len(numerics) >= 3 and all(v == 0.0 for v in numerics.values()):
            problems.append(Violation("degenerate",
                                      "every numeric value in the record is 0"))
    return problems
