"""The examiner: a separate role whose only job is to prove the answer wrong.

The writer's own asserts are self-referential - a model asserting its own
formula passes its own bug (the false-confidence dossiers are full of it),
and two independent writers can share a misreading (v5b: 6 majority-
confirmed reconciliations, 0 graded pass). The examiner never repairs and
never sees the writer's prompt. It receives the task, the contract, the
evidence, the program and a numeric summary of what was written, and it
answers one question: is there a concrete reason this is wrong?

Its output is machine-readable so the loop can act on it: a verdict and a
list of findings, each with the instruction sentence or invariant it rests
on. A finding becomes the error of exactly one repair round; the examiner
runs at most once per unit.
"""

from __future__ import annotations

import json
import pathlib
import re
import textwrap

from . import code_writer, consensus
from .contracts import TaskSpec

SYSTEM = textwrap.dedent("""\
    You are an examiner grading a quantitative-finance program you did not
    write. Your job is to find a CONCRETE reason the delivered numbers are
    wrong. Check, in this order:
      1. Literal contract: files, keys/columns, order, dtypes, formats
         (fixed decimals, lowercase booleans), row counts, key survival.
      2. Every sentence in the task containing must / only / exactly / iff /
         before / after / positive / non-negative / "in this order", and
         every descriptive fact (frequency, cadence, "has upper tail
         dependence"): is each one satisfied by the numbers shown?
      3. Named methods: is the cited estimator/test implemented as its
         published definition, or as a lookalike?
      4. Units and scaling: annualisation, percent vs decimal, per-unit vs
         position, bump-size division, horizon scaling.
      5. Dimensional sanity and finance invariants (prices >= 0, ES >= VaR,
         discount factors in (0,1], durations >= 0, weights sum to 1).
      6. A simple special case or limit where the formula must reduce to a
         known value - does the program's logic reduce correctly?
      7. Hard-coding against the example or the sample rows.
    Reply with ONLY a JSON object:
      {"verdict": "ok" | "wrong",
       "findings": [{"where": "<file/quantity>",
                     "rule": "<the sentence, invariant or definition>",
                     "problem": "<what is violated, with numbers>",
                     "check": "<Python that PROVES it: read the deliverable(s)
                               from the directory in the environment variable
                               OUTPUT_DIR with json/pandas, recompute what the
                               rule requires from the delivered files and the
                               INPUT files, and `assert` the rule with a
                               message. Self-contained, no writes.>"}]}
    A finding without an executable `check` is discarded, and a check that
    passes when run means the finding was wrong - so do the arithmetic in
    the check, never in your head. Report a finding only when you can name
    the rule it violates. At most 5 findings.
    """)

MAX_FINDINGS = 5


def _numbers_summary(output_dir: pathlib.Path, spec: TaskSpec) -> str:
    fp = consensus.fingerprint(output_dir, spec.contracts)
    if not fp:
        return "(no numeric deliverable)"
    items = list(fp.items())[:60]
    return "\n".join(f"  {k} = {v:.6g}" for k, v in items)


def examine(spec: TaskSpec, output_dir: pathlib.Path, source: str,
            telemetry: list | None = None) -> tuple[str, list[dict]]:
    """Returns ('ok' | 'wrong' | 'unavailable', findings)."""
    if not code_writer.model_available():
        return "unavailable", []
    contract = "\n".join(
        f"  - {c.filename} ({c.fmt})"
        + (f": {', '.join(c.required_columns)}" if c.required_columns else "")
        for c in spec.contracts)
    user = (f"TASK\n{(spec.instruction or '').strip()[:9000]}\n\n"
            f"CONTRACT\n{contract}\n\n"
            + (f"EVIDENCE FROM THE INPUTS\n{spec.evidence[:3500]}\n\n"
               if spec.evidence else "")
            + f"DELIVERED NUMBERS (summary)\n{_numbers_summary(output_dir, spec)}\n\n"
            f"THE PROGRAM\n```python\n{source[:9000]}\n```\n\n"
            "Examine it now. JSON only.")
    reply = code_writer.complete(SYSTEM, user, telemetry=telemetry,
                                 variant=9, want_code=False)
    if not reply:
        return "unavailable", []
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        return "unavailable", []
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return "unavailable", []
    verdict = str(payload.get("verdict", "")).lower()
    findings = [f for f in payload.get("findings", []) if isinstance(f, dict)]
    findings = [f for f in findings
                if f.get("rule") and f.get("problem") and f.get("check")]
    if verdict == "wrong" and not findings:
        verdict = "ok"          # a verdict without an executable check is opinion
    return ("wrong" if verdict == "wrong" else "ok"), findings[:MAX_FINDINGS]


CHECK_TIMEOUT_SEC = 45.0


def verify(findings: list[dict], output_dir: pathlib.Path,
           work_dir: pathlib.Path, input_root: str = "") -> list[dict]:
    """Run each finding's check; keep only those whose assert FAILS.

    v6.1 gate-1: the examiner called correct answers wrong with invented
    arithmetic. Prose is not evidence; an executed assert is. A check that
    passes clears the finding; a check that crashes for any other reason
    (KeyError, NameError) proves nothing and is dropped too.
    """
    import os
    import subprocess
    import sys
    confirmed = []
    work_dir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(findings):
        script = work_dir / f"examiner_check_{i}.py"
        script.write_text(str(f["check"]), encoding="utf-8")
        env = dict(os.environ, OUTPUT_DIR=str(output_dir), INPUT_ROOT=input_root)
        try:
            proc = subprocess.run([sys.executable, str(script)], cwd=str(work_dir),
                                  capture_output=True, text=True,
                                  timeout=CHECK_TIMEOUT_SEC, env=env)
        except subprocess.TimeoutExpired:
            continue
        if proc.returncode != 0 and "AssertionError" in (proc.stderr or ""):
            tail = (proc.stderr or "").strip().splitlines()[-1][:300]
            confirmed.append({**f, "executed": tail})
    return confirmed


def as_error(findings: list[dict]) -> str:
    lines = ["examiner: the delivered answer violates stated rules:"]
    for f in findings:
        lines.append(f"- {f.get('where', '?')}: {f.get('problem', '')} "
                     f"[rule: {f.get('rule', '')}] -> fix: {f.get('fix', '')}")
    lines.append("Correct exactly these, keep everything else, and re-verify "
                 "each rule with an assert before writing.")
    return "\n".join(lines)
