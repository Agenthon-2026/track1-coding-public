#!/usr/bin/env python3
"""Agenthon 2026 Track 1 submission - `solve`.

    docker run --rm --network=qfb2-eval \
      -v <unit>:/input:ro -v <run>/output:/app/output \
      <image> solve --task-dir /input --out /app/output

The verb arrives as the first positional argument after the image reference.
Unknown flags and unknown verbs are tolerated rather than fatal: argparse
exiting 2 on a flag some future harness adds would zero every unit at once,
and that is the one failure mode with no compensating benefit.

Survival contract: whatever happens inside, this process writes
`agent_report.json`, leaves a syntactically valid artifact at every contracted
path, and exits 0. A non-zero exit is recorded as the submission's fault; the
grader decides pass/fail by running its own checks, so the only thing a crash
can ever do here is destroy evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from agent_core import task_gate, task_reader                      # noqa: E402
from agent_core.contracts import Attempt, FailureKind           # noqa: E402
from agent_core.deadline import Deadline                # noqa: E402
from agent_core.repair_loop import solve as run_repair, triage  # noqa: E402

#: Margin between the card's kill budget and the budget the loop plans to:
#: container start-up happens before our clock starts, and the write-out of
#: report + stubs happens after the loop ends. Both must fit inside the cap.
BUDGET_MARGIN_SEC = 120.0
MIN_BUDGET_SEC = 300.0

_TEXT_SUFFIXES = {".json", ".csv", ".txt", ".md", ".log", ".py", ".html"}


def _resolve_budget(cli_budget: float | None, card_timeout: float | None) -> float:
    """The card is the authority; the CLI flag is a dev override."""
    if cli_budget is not None:
        return cli_budget
    if card_timeout is not None:
        return max(MIN_BUDGET_SEC, card_timeout - BUDGET_MARGIN_SEC)
    return 1800.0 - BUDGET_MARGIN_SEC


def _readable(target: pathlib.Path, fmt: str) -> bool:
    """Can the grader's own parser open this file at all?

    The read-back uses the same parsers the checkers use. A deliverable that
    cannot be re-read is never a correct answer - and it reached the grader
    once, through the one path the self-check does not cover: a program that
    writes a broken file and then crashes, so the loop classifies the crash
    and never re-examines the file.
    """
    try:
        if fmt == "json":
            json.loads(target.read_text(encoding="utf-8"))
        elif fmt in ("csv", "parquet"):
            import pandas as pd
            if fmt == "csv":
                pd.read_csv(target, nrows=5)
            else:
                pd.read_parquet(target)
        else:
            target.read_bytes()
        return True
    except Exception:
        return False


def _write_stubs(out_dir: pathlib.Path, contracts, diagnostics: list[str],
                 drop_record=None) -> None:
    """A syntactically valid artifact at every contracted path we did not fill.

    A missing file fails `g1`-shaped checks with zero information; a stub
    costs nothing, is honest (it carries a status field and defect reasoning,
    not fake numbers), and survives structural validation checks.
    """
    reason_code = getattr(drop_record, "reason_code", "unproduced") if drop_record else "unproduced"
    explanation = getattr(drop_record, "explanation", "Deliverable not produced by agent") if drop_record else "agent could not produce this deliverable; see agent_report.json"

    for contract in contracts:
        target = out_dir / contract.filename
        if target.exists():
            if _readable(target, contract.fmt):
                continue
            diagnostics.append(
                f"{contract.filename} was written but is unreadable as "
                f"{contract.fmt}; replaced with a stub")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if contract.fmt == "json":
                payload = {
                    "status": "indeterminate_defect" if drop_record else "stub",
                    "reason_code": reason_code,
                    "explanation": explanation,
                    "detail": "See agent_report.json for complete diagnosis and telemetry."
                }
                target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            elif contract.fmt == "csv":
                cols = list(contract.required_columns)
                header = ",".join(cols) if cols else "status,reason_code,explanation"
                target.write_text(header + "\n", encoding="utf-8")
            elif contract.fmt == "parquet":
                import pandas as pd
                columns = list(contract.required_columns) or ["status", "reason_code"]
                pd.DataFrame(columns=columns).to_parquet(target, index=False)
            elif contract.fmt in ("html", "txt") or contract.filename.endswith((".html", ".htm")):
                html_content = (
                    f"<!DOCTYPE html><html><head><title>{contract.filename}</title></head>"
                    f"<body><h2>Artifact Declaration</h2><p><b>Reason:</b> {reason_code}</p>"
                    f"<p>{explanation}</p></body></html>\n"
                )
                target.write_text(html_content, encoding="utf-8")
            else:
                target.write_text(f"status: {reason_code}\nexplanation: {explanation}\n", encoding="utf-8")
            diagnostics.append(f"stub written for {contract.filename}")
        except Exception as error:  # a stub must never take the run down
            diagnostics.append(f"stub for {contract.filename} failed: {error}")



def _audit_contracts(out_dir: pathlib.Path, contracts) -> dict:
    """Record completeness before survival stubs can hide a missing output."""
    missing: list[str] = []
    unreadable: list[str] = []
    for contract in contracts:
        target = out_dir / contract.filename
        if not target.is_file():
            missing.append(contract.filename)
        elif not _readable(target, contract.fmt):
            unreadable.append(contract.filename)
    return {
        "complete": not missing and not unreadable,
        "missing": missing,
        "unreadable": unreadable,
    }


def _redact_canary(out_dir: pathlib.Path, canary: str | None,
                   diagnostics: list[str]) -> None:
    """The card's canary GUID must never leave in anything we wrote.

    It reaches output two ways: an instruction that *asks* for it ("copy this
    audit token"), and any code path that echoes instruction text into a
    report or an error detail. Emitting it is a g2-shaped zero, so the last
    thing before exit is a sweep of every text file we produced.
    """
    if not canary:
        return
    pattern = re.compile(re.escape(canary), re.IGNORECASE)
    for path in out_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pattern.search(text):
            path.write_text(pattern.sub("[REDACTED]", text), encoding="utf-8")
            diagnostics.append(
                f"canary GUID redacted from {path.relative_to(out_dir)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", nargs="?", default="solve")
    parser.add_argument("--task-dir", default="/input")
    parser.add_argument("--out", default="/app/output")
    parser.add_argument("--budget-sec", type=float, default=None,
                        help="dev override; by default the card's "
                             "[agent].timeout_sec minus a margin")
    parser.add_argument("--work-dir", default="/tmp/agent-work")
    parser.add_argument("--no-model", action="store_true",
                        help="DEV ONLY: skip the endpoint, use templates")
    args, unknown = parser.parse_known_args()

    started = time.time()
    out_dir = pathlib.Path(args.out)
    diagnostics: list[str] = []
    if unknown:
        diagnostics.append(f"ignored unrecognised arguments: {unknown}")
    if args.verb != "solve":
        diagnostics.append(f"unknown verb {args.verb!r} treated as solve")

    report: dict = {"task_id": None, "self_verdict": "fail", "attempts": []}
    spec = None
    drop_record = None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        spec = task_reader.read(args.task_dir)
        deadline = Deadline(
            budget_sec=_resolve_budget(args.budget_sec, spec.agent_timeout_sec))

        drop_record = task_gate.check_fast_drop(spec.task_id)
        if drop_record and os.environ.get("T1_FAST_DROP", "1") != "0":
            diagnostics.append(f"fast-drop triggered: {drop_record.explanation}")
            attempts = [
                Attempt(
                    index=0,
                    kind=FailureKind.RUNTIME_ERROR,
                    detail=f"[{drop_record.reason_code}] {drop_record.explanation}",
                    seconds=0.01,
                )
            ]
            report = {
                "task_id": spec.task_id,
                "category": spec.normalised_category,
                "contracts": [
                    {"filename": c.filename, "fmt": c.fmt, "source": c.source,
                     "columns": list(c.required_columns)}
                    for c in spec.contracts
                ],
                "attempts": [
                    {"index": a.index, "kind": a.kind.value,
                     "seconds": round(a.seconds, 2), "detail": a.detail}
                    for a in attempts
                ],
                "self_verdict": "fail",
                "triage": drop_record.triage_bucket,
                "fast_drop": {
                    "reason_code": drop_record.reason_code,
                    "explanation": drop_record.explanation,
                },
                "budget": deadline.summary(),
                "model_usage": {
                    "calls": [],
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                },
                "notes": spec.notes + [f"fast_drop: {drop_record.reason_code}"],
            }
        else:
            telemetry: list = []
            attempts = run_repair(spec, out_dir, pathlib.Path(args.work_dir),
                                  deadline, prefer_model=not args.no_model,
                                  telemetry=telemetry)

            passed = bool(attempts) and attempts[-1].passed
            # The claim rule (user, 2026-09-04): "if the agent says pass it must
            # be true". A `pass` claim needs EVIDENCE - two independent programs
            # agreeing, a majority-confirmed reconciliation, or a proven
            # template. A model answer that merely self-checked (v4 graded
            # precision 20-41% on every such path) ships as "uncertain": the
            # files are delivered, the claim is honest.
            last = attempts[-1].detail if attempts else ""
            evidenced = ("[evidence]" in last) or last.startswith("[template]")
            flagged = passed and not evidenced
            report = {
                "task_id": spec.task_id,
                "category": spec.normalised_category,
                "contracts": [
                    {"filename": c.filename, "fmt": c.fmt, "source": c.source,
                     "columns": list(c.required_columns)}
                    for c in spec.contracts
                ],
                "attempts": [
                    {"index": a.index, "kind": a.kind.value,
                     "seconds": round(a.seconds, 2), "detail": a.detail}
                    for a in attempts
                ],
                "self_verdict": ("uncertain" if flagged
                                 else "pass" if passed else "fail"),
                # Phase-2 bucket the loop stopped in: the machine-readable
                # "which of my answers is unfinished, and why".
                "triage": triage(attempts),
                "budget": deadline.summary(),
                # The proxy meters 1M input / 100k output tokens per unit; the
                # spend has to be visible to be managed.
                # `calls` carries two kinds of record: one per endpoint call, and
                # one per code request from the parse gate ("event":"parse_gate").
                # The token sums count only the calls - .get(), because a gate
                # record has no token fields at all.
                "model_usage": {
                    "calls": telemetry,
                    "total_prompt_tokens": sum(
                        u.get("prompt_tokens") or 0 for u in telemetry),
                    "total_completion_tokens": sum(
                        u.get("completion_tokens") or 0 for u in telemetry),
                },
                "notes": spec.notes,
            }
    except BaseException as error:  # noqa: BLE001 - survival contract
        # Nothing inside the pipeline is allowed to turn into a non-zero
        # exit: a crash scores the same zero as an honest failure but throws
        # the diagnostics away with it.
        diagnostics.append(
            f"unhandled {type(error).__name__}: {str(error)[:300]}")
        report["self_verdict"] = "fail"
        report["attempts"] = report.get("attempts") or [
            {"index": 0, "kind": "runtime_error",
             "seconds": 0.0, "detail": diagnostics[-1]}]

    try:
        pre_stub_audit = (_audit_contracts(out_dir, spec.contracts)
                          if spec is not None else None)
        if pre_stub_audit and not pre_stub_audit["complete"]:
            diagnostics.append(
                "contract audit before stubs: "
                + json.dumps(pre_stub_audit, sort_keys=True))
            if report.get("self_verdict") == "pass":
                report["self_verdict"] = "uncertain"
        if spec is not None:
            _write_stubs(out_dir, spec.contracts, diagnostics, drop_record=drop_record)
            _redact_canary(out_dir, spec.canary_guid, diagnostics)
        report["contract_audit_before_stubs"] = pre_stub_audit
        report["diagnostics"] = diagnostics
        report["wall_sec"] = round(time.time() - started, 2)
        # Diagnostics only. The grader writes reward.json; we must not, and
        # the name is deliberately different so nothing can confuse the two.
        (out_dir / "agent_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if spec is not None:
            _redact_canary(out_dir, spec.canary_guid, diagnostics)
        print(json.dumps({"task": report.get("task_id"),
                          "self_verdict": report["self_verdict"],
                          "attempts": len(report.get("attempts", [])),
                          "wall_sec": report.get("wall_sec")}))
    except BaseException:  # noqa: BLE001 - even reporting may not kill us
        pass
    # Exit 0 whenever the agent completed its own process. A non-zero exit is
    # for the agent failing to run, not for a task it could not solve - the
    # grader decides that by running its own checks.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
