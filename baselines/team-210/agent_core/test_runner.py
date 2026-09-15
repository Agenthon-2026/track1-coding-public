"""Run a generated solution and classify what happened.

Classification is the product here, not the stdout. The repair loop can only act
on a FailureKind, and the local matrix is only useful if the kinds are distinct.
Reading a traceback into the right bucket is what makes the difference between
"try again" and "stop, this cannot be fixed from here".
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import time

from .contracts import FailureKind

#: A module the image does not carry cannot be installed at runtime - the eval
#: network reaches the model endpoint and nothing else. Retrying is pure waste.
_IMPORT = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
_TRACEBACK_LAST = re.compile(r"^([A-Za-z_.]*Error|[A-Za-z_.]*Exception): (.*)$", re.M)


def run_solution(script: pathlib.Path, cwd: pathlib.Path,
                 timeout_sec: float,
                 input_dir: pathlib.Path | str | None = None) -> tuple[FailureKind, str, float]:
    started = time.monotonic()
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    parts = [str(cwd)]
    if input_dir:
        parts.append(str(input_dir))
    parts.append("/input")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return FailureKind.TIMEOUT, f"exceeded {timeout_sec:.0f}s", time.monotonic() - started

    seconds = time.monotonic() - started
    if proc.returncode == 0:
        return FailureKind.PASS, proc.stdout[-2000:], seconds

    combined = (proc.stderr or "") + (proc.stdout or "")
    missing = _IMPORT.search(combined)
    if missing:
        return (FailureKind.IMPORT_ERROR,
                f"missing module {missing.group(1)!r} - not installable at runtime",
                seconds)

    # The one-line summary routes the classification; the tail is what the
    # repair prompt actually needs - a bare "KeyError: 'x'" without the
    # frames around it sent the model hunting in the wrong function.
    last = _TRACEBACK_LAST.findall(combined)
    summary = f"{last[-1][0]}: {last[-1][1]}" if last else "non-zero exit"
    detail = f"{summary}\n--- traceback tail ---\n{combined[-1000:]}"
    return FailureKind.RUNTIME_ERROR, detail, seconds


# `run_unit_checks` - the dev-only runner for the grader's own checks - used
# to live here and therefore shipped inside the submission image: dead code
# that executes `checks/test.sh`, which is the first thing an auditor of the
# "never depend on checks/ at runtime" rule goes looking for. It now lives in
# `dev_tools/checks_dev.py`, which is not COPY'd into the image.
