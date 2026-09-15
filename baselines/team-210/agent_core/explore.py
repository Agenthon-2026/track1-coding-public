"""Phase 0 of the classroom loop: look before writing.

Sixty percent of v5's failures were programs that never ran to the end -
KeyError on a column that does not exist, tz-naive against tz-aware,
NameError on a config key the model assumed. Every one is a guess about
the inputs. This phase asks the model for a READING program only: open
every input at its exact path and print what is actually there. The run's
stdout becomes the EVIDENCE block of every later prompt; the model then
writes against facts it printed itself, which the trails show it trusts
over any summary we hand it.

Cheap by construction: one completion, one short run, one repair at most,
capped at a small share of the budget. Anything that goes wrong here is
itself the first lesson (a wrong path, an unreadable format) and is worth
more than the seconds it cost.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap
import time

from . import code_writer
from .contracts import TaskSpec
from .deadline import Deadline

#: Share of the budget phase 0 may use, and the hard cap on one run.
BUDGET_SHARE = 0.08
RUN_CAP_SEC = 90.0
#: The explorer is not worth starting on tiny budgets: the reading program
#: plus its run would eat what the solution needs.
MIN_BUDGET_SEC = 300.0
STDOUT_CAP = 7000

SYSTEM = textwrap.dedent("""\
    You write a short Python program that ONLY READS inputs and PRINTS what
    is in them. It computes nothing and writes no files. Rules:
      * Open every input at the exact absolute path given.
      * For each table (csv/parquet): print columns with dtypes, shape, the
        index / date column's first and last values and inferred frequency,
        the first 3 rows, describe() of numeric columns (rounded), unique
        counts of any id-like column, and any timezone information.
      * For each JSON: print every key with its value type; print scalar
        values in full; for lists print length and the first element.
      * For text files: print the first 5 lines.
      * Wrap each file in try/except and print the exception if it fails -
        never let one file stop the others.
      * Keep total output under about 150 lines: truncate long prints.
      * Import only numpy, pandas, pyarrow, json, pathlib. No fences, no
        commentary: Python source only.
    """)


def _user(spec: TaskSpec) -> str:
    files = "\n".join(f"  - {spec.input_root}/{f}" for f in spec.data_files)
    return (f"INPUT FILES (read with EXACTLY these paths):\n{files}\n\n"
            f"TASK EXCERPT (for orientation only; do not solve it):\n"
            f"{(spec.instruction or '')[:1500]}\n\n"
            "Write the reading program now.")


def _run(source: str, work_dir: pathlib.Path, cap: float) -> tuple[bool, str]:
    script = work_dir / "explore.py"
    script.write_text(source, encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, str(script)], cwd=str(work_dir),
                              capture_output=True, text=True, timeout=cap)
    except subprocess.TimeoutExpired:
        return False, f"reading program exceeded {cap:.0f}s"
    out = (proc.stdout or "")[:STDOUT_CAP]
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1200:]
        return False, out + "\n--- reading program crashed ---\n" + tail
    return True, out


def run(spec: TaskSpec, work_dir: pathlib.Path, deadline: Deadline,
        telemetry: list | None = None) -> tuple[str, str]:
    """Returns (evidence, note). Evidence may be partial; never raises."""
    if not code_writer.model_available():
        return "", "explore skipped: no model"
    if deadline.budget < MIN_BUDGET_SEC:
        return "", "explore skipped: budget too small"
    if not spec.data_files:
        return "", "explore skipped: no input files"
    work_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    allowance = deadline.budget * BUDGET_SHARE
    cap = min(RUN_CAP_SEC, max(20.0, allowance / 2))

    source = code_writer.complete(SYSTEM, _user(spec), telemetry=telemetry,
                                  variant=7, want_code=True)
    if not source:
        return "", "explore skipped: no reading program"
    ok, out = _run(source, work_dir, cap)
    if not ok and time.monotonic() - started < allowance:
        # One repair: the crash text is the most specific evidence there is
        # about the inputs (wrong path, encoding, format).
        fix = code_writer.complete(
            SYSTEM, _user(spec) + "\n\nYOUR PREVIOUS READING PROGRAM FAILED "
            "WITH:\n" + out[-1500:] + "\n\nReturn the complete corrected "
            "reading program.", telemetry=telemetry, variant=8, want_code=True)
        if fix:
            ok2, out2 = _run(fix, work_dir, cap)
            if ok2 or len(out2) > len(out):
                ok, out = ok2, out2
    spent = time.monotonic() - started
    deadline.record_attempt(spent)
    note = (f"explore: {'ok' if ok else 'partial'} in {spent:.0f}s, "
            f"{len(out)} chars of evidence")
    return out.strip(), note
