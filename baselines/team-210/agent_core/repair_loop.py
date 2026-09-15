"""Write, run, self-check, repair - under a clock.

FinanceZero makes one model call and stops. It does not run what it wrote, so a
program that raises, or one that runs and emits a negative gamma, scores exactly
the same as one that never compiled. Running the code is the cheapest gain
available here.

The second gain is the self-check. The reward is binary and the grader asserts
invariants, so a solution that executes cleanly and produces wrong-shaped output
still scores zero. Checking the contract before declaring success turns a silent
zero into another repair iteration.
"""

from __future__ import annotations

import re
import os
import pathlib
import time

from . import code_writer, consensus, examiner, explore, fc_gate, test_runner
from .contracts import Attempt, FailureKind, TaskSpec
from .deadline import Deadline
from invariant_library import universal

#: Independent candidates in the consensus vote. Two is the minimum that
#: yields a comparison; the vote runs only while the clock clearly affords a
#: full extra write-run-check, so a slow unit never pays for it. Dev knob
#: only (the eval room sets nothing, so the default IS the eval behaviour).
CANDIDATES = 2
#: Fraction of the budget that must remain for a second candidate to start:
#: the first solution already proved what a full attempt costs on this unit,
#: and the reconciliation round may need a third.
CONSENSUS_MIN_REMAINING = 0.35


def _candidates_wanted() -> int:
    try:
        return max(1, int(os.environ.get("T1_CANDIDATES", CANDIDATES)))
    except ValueError:
        return CANDIDATES


def _consensus_affordable(deadline: Deadline) -> bool:
    return (_candidates_wanted() >= 2 and deadline.can_afford()
            and deadline.remaining >= deadline.budget * CONSENSUS_MIN_REMAINING)

#: Base iteration allowance, extended up to the hard cap while the budget
#: clearly affords more rounds. Five was a constant from the no-model era;
#: with typical model runs using 100-300s of an 1800s card, extra rounds are
#: free realisation-of-mistake opportunities.
MAX_ITERATIONS = 5
MAX_ITERATIONS_HARD = 10
#: A timed-out attempt earns exactly one repair round with a "make it cheaper"
#: hint. Zero rounds threw away >1000s of budget on any task whose honest run
#: costs more than the old fixed cap; unlimited rounds would let a hopeless
#: task eat the clock.
MAX_TIMEOUT_REPAIRS = 1


def _source_frame(spec: TaskSpec):
    """The input table a row-key check compares against, when unambiguous.

    Only when the unit carries exactly one tabular data file: with several,
    guessing which one the identifier must survive from risks a self-check
    that is wrong in either direction. Lazy and forgiving - a failure to load
    input is never allowed to fail the *output*.
    """
    tabular = [f for f in spec.data_files
               if f.lower().endswith((".parquet", ".csv"))]
    if len(tabular) != 1:
        return None
    try:
        import pandas as pd
        path = pathlib.Path(spec.input_root) / tabular[0]
        if tabular[0].lower().endswith(".parquet"):
            return pd.read_parquet(path)
        return pd.read_csv(path)
    except Exception:
        return None


def _self_check(output_dir: pathlib.Path, contracts,
                spec: TaskSpec | None = None) -> tuple[FailureKind, str]:
    problems: list[str] = []
    source = _source_frame(spec) if (
        spec is not None and any(c.row_key for c in contracts)) else None
    for contract in contracts:
        violations = universal.check_contract(
            output_dir / contract.filename, contract,
            source_frame=source if contract.row_key else None)
        problems += [str(v) for v in violations]
    if not problems:
        return FailureKind.PASS, ""
    if any(p.startswith("file_exists") for p in problems):
        return FailureKind.MISSING_OUTPUT, "; ".join(problems[:8])
    if any(p.startswith(("columns_present", "readable")) for p in problems):
        return FailureKind.SCHEMA_MISMATCH, "; ".join(problems[:8])
    return FailureKind.INVARIANT_VIOLATION, "; ".join(problems[:8])


def solve(spec: TaskSpec, output_dir: pathlib.Path, work_dir: pathlib.Path,
          deadline: Deadline, *, prefer_model: bool = True,
          telemetry: list | None = None) -> list[Attempt]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    attempts: list[Attempt] = []
    error: str | None = None
    previous_source: str | None = None
    timeout_repairs = 0
    model_failures = 0
    template_tried = False
    previous_failure: str | None = None
    risk_round_used = False
    risk_snapshot: dict[str, bytes] = {}

    # Phase 0 - look before writing. The reading program's output becomes
    # the EVIDENCE block of every prompt below.
    if prefer_model and os.environ.get("T1_EXPLORE", "1") != "0":
        evidence, note = explore.run(spec, work_dir, deadline, telemetry)
        spec.evidence = evidence
        spec.notes.append(note)

    # Phase 1 - answer everything: the floor answer, never destroyed later.
    for index in range(MAX_ITERATIONS_HARD):
        if index >= MAX_ITERATIONS and deadline.remaining < deadline.budget * 0.5:
            # Extra rounds beyond the base five only while MOST of the
            # budget is still unspent - late extensions risk the reserve.
            break
        if not deadline.can_afford():
            attempts.append(Attempt(index, FailureKind.TIMEOUT,
                                    f"stopped early with {deadline.remaining:.0f}s "
                                    "left rather than risk being killed mid-write"))
            break

        # The model call costs wall clock too - up to 180s per iteration -
        # and an unmeasured cost made `predicted_attempt_cost` optimistic by
        # exactly that much, which is how a run gets killed at the cap.
        # After two failed model attempts, a template that matches the
        # contract gets one shot: a proven template must never lose forever
        # to a completion that keeps crashing.
        force_template = (
            not template_tried and model_failures >= 2
            and code_writer.match_template(spec, spec.contracts) is not None)

        write_started = time.monotonic()
        source, provenance = code_writer.write(
            spec, spec.contracts, str(output_dir), error, prefer_model,
            telemetry=telemetry, previous_source=previous_source,
            attempt_index=index, force_template=force_template)
        write_seconds = time.monotonic() - write_started
        if source is None:
            attempts.append(Attempt(index, FailureKind.MODEL_UNAVAILABLE,
                                    "no model and no template matched"))
            break
        if provenance == "template":
            template_tried = True

        # Byte-identical source will fail byte-identically. If a template is
        # still in reserve, spend the next iteration on it; otherwise stop.
        if source == previous_source:
            model_failures = max(model_failures, 2)
            if (not template_tried and code_writer.match_template(
                    spec, spec.contracts) is not None):
                attempts.append(Attempt(index, FailureKind.RUNTIME_ERROR,
                                        f"[{provenance}] regenerated source "
                                        "identical; switching to template",
                                        write_seconds))
                continue
            attempts.append(Attempt(index, FailureKind.RUNTIME_ERROR,
                                    f"[{provenance}] regenerated source is "
                                    "identical to the failed attempt; stopping",
                                    write_seconds))
            break
        previous_source = source

        script = work_dir / f"solution_{index}.py"
        script.write_text(source, encoding="utf-8")

        # The cap is the remaining budget, not an arbitrary constant: a fixed
        # 600s cap killed any honest 700s solution with >1000s still on the
        # clock. The floor may never punch through what is actually left.
        per_attempt = max(60.0, deadline.remaining - 30.0)
        per_attempt = min(per_attempt, max(5.0, deadline.remaining))
        try:
            kind, detail, seconds = test_runner.run_solution(
                script, work_dir, per_attempt, input_dir=spec.input_root)
        except TypeError:
            kind, detail, seconds = test_runner.run_solution(
                script, work_dir, per_attempt)
        deadline.record_attempt(write_seconds + seconds)

        if kind is FailureKind.PASS:
            kind, detail = _self_check(output_dir, spec.contracts, spec)
        elif kind in (FailureKind.RUNTIME_ERROR, FailureKind.TIMEOUT):
            # A generated program can write every real deliverable and then
            # die in its own assert or in post-processing.  The grader scores
            # the files, not the program's exit code, so re-read the output
            # before throwing that candidate away.  This is deliberately
            # limited to a complete contract audit: a partial or unreadable
            # tree remains a normal failure and gets a repair prompt.
            recovered_kind, _ = _self_check(
                output_dir, spec.contracts, spec)
            if recovered_kind is FailureKind.PASS:
                detail = (f"post-failure contract audit passed after "
                          f"{kind.value}: candidate kept as uncertain")
                kind = FailureKind.PASS

        attempts.append(Attempt(index, kind,
                                f"[{provenance}] {detail}"[:1500],
                                write_seconds + seconds))

        if kind is FailureKind.PASS:
            # Output-level evidence outranks code-shape evidence: when a
            # second independent candidate is affordable, the consensus vote
            # (below the loop) is the honesty driver. The calibrated shape
            # gate is the fallback for units too slow to afford a vote - a
            # nudge that buys ONE cross-check round, never a hard block.
            if (provenance == "model" and not risk_round_used
                    and not _consensus_affordable(deadline)
                    and deadline.can_afford()
                    and fc_gate.risk_of(source) >= fc_gate.RISK_THRESHOLD):
                risk_round_used = True
                # Snapshot the passing deliverables: if the cross-checked
                # rewrite lands worse, the audited-but-passing answer is
                # restored - the gate may spend budget, never destroy value.
                for contract in spec.contracts:
                    target = output_dir / contract.filename
                    if target.is_file():
                        risk_snapshot[contract.filename] = target.read_bytes()
                attempts[-1] = Attempt(index, FailureKind.INVARIANT_VIOLATION,
                                       "[fc-gate] self-check passed but the "
                                       "risk profile is high; demanding a "
                                       "cross-checked rewrite",
                                       attempts[-1].seconds)
                error = fc_gate.CROSS_CHECK_DEMAND
                continue
            break
        if kind is FailureKind.TIMEOUT:
            if timeout_repairs >= MAX_TIMEOUT_REPAIRS or not deadline.can_afford():
                break
            timeout_repairs += 1
            error = (f"timeout: the previous attempt exceeded {per_attempt:.0f}s. "
                     "Produce a substantially cheaper implementation - "
                     "vectorise, reduce grid/path counts to what the stated "
                     "tolerance needs, avoid per-row Python loops.")
            continue
        if not kind.repairable:
            break
        if provenance == "model":
            model_failures += 1
        # Two consecutive attempts failing on the byte-same complaint means
        # the feedback channel is exhausted: a third answer to the same
        # message will not differ. Measured on the 30x1 post-mortem - extra
        # iterations against a relational error were spent, not used.
        signature = f"{kind.value}:{detail[:200]}"
        if signature == previous_failure:
            # A template still in reserve outranks giving up (the exemplar
            # fails the model path identically twice before its template
            # rescue - stopping here would re-open that regression).
            if (not template_tried and code_writer.match_template(
                    spec, spec.contracts) is not None):
                model_failures = max(model_failures, 2)
            else:
                attempts.append(Attempt(index, kind,
                                        "same failure twice in a row; stopping "
                                        "rather than spending budget on a third",
                                        0.0))
                break
        previous_failure = signature
        error = f"{kind.value}: {detail}"
        if _unstated_assert(detail, spec.instruction):
            error += "\n" + SELF_ASSERT_HINT

    if (risk_snapshot and attempts
            and attempts[-1].kind is not FailureKind.PASS):
        for filename, payload in risk_snapshot.items():
            (output_dir / filename).write_bytes(payload)
        attempts.append(Attempt(len(attempts), FailureKind.PASS,
                                "[fc-gate] cross-checked rewrite did not "
                                "verify; restored the earlier passing answer",
                                0.0))

    # Phases 2-3 - self-triage, then spend what is left on the diagnosed
    # cause in leverage order. Each round re-triages; the floor answer is
    # replaced only by an answer that self-checks (and only earns a `pass`
    # claim with vote evidence).
    if prefer_model:
        attempts += _fix_list(spec, output_dir, work_dir, deadline,
                              attempts, previous_source, error, telemetry)
    return attempts


# ---------------------------------------------------------------------------
# Phase 2: triage.  Phase 3: the fix list.
# ---------------------------------------------------------------------------

#: Buckets, in the order the v5 leverage table ranks them.
CRASH, SELFCHECK, VOTE_PENDING, SECOND_CRASHED, DISAGREE, INCONCLUSIVE, \
    AGREE, EXAMINED, DONE = ("crash", "selfcheck", "vote_pending",
                             "second_crashed", "disagree", "inconclusive",
                             "agree", "examined", "done")
MAX_FIX_ROUNDS = 6
#: The crash bucket gets at most this many extra repairs beyond phase 1.
MAX_CRASH_ROUNDS = 2

CRASH_HINT = (
    "The program keeps crashing before it writes anything. Use ONLY the "
    "column names, keys, dtypes and paths shown in the EVIDENCE block; "
    "before every access that raised, print the object's keys/columns and "
    "guard the access. Return the complete program.")

#: A self-assert whose wording the instruction never uses is the model's own
#: hypothesis. Measured: 59% of assert failures, and they kill programs that
#: had already written correct deliverables (ohlc-realized-vol died on
#: "yz_efficiency should exceed 1" in 35 iterations across runs).
#: The word match is a SIGNAL, not a verdict: a stated identity can be
#: paraphrased. So the hint asks the model to decide, defaulting to the
#: warning form (a hypothesis assert can destroy a correct answer, while a
#: downgraded stated-identity assert only loses a check), and explicitly
#: protects a stated identity that happens to be worded differently.
SELF_ASSERT_HINT = (
    "The wording of that failing check does not appear in the task text. "
    "Decide which it is. If it is YOUR expectation - an estimator you think "
    "should dominate, an ordering or sign you consider natural - it is a "
    "hypothesis: keep the computation, replace the assert with a printed "
    "warning, and carry on. If the task really does require it in different "
    "words, keep the assert and fix the computation instead. Either way, "
    "write the deliverables BEFORE any verification block runs, so a check "
    "can never cost you a finished answer.")
_ASSERT_RE = re.compile(r"AssertionError:?\s*([^\n|]{0,180})")
_ASSERT_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")


def _unstated_assert(detail: str, instruction: str) -> bool:
    """Does the failing assert's wording appear in the task text at all?"""
    match = _ASSERT_RE.search(detail or "")
    if not match:
        return False
    text = (instruction or "").lower()
    words = {w.lower() for w in _ASSERT_WORD.findall(match.group(1))}
    words -= {"must", "should", "value", "values", "expected", "error",
              "assert", "check", "result", "results", "than", "with"}
    if not words:
        return False
    return len({w for w in words if w in text}) < 2


def triage(attempts: list[Attempt]) -> str:
    """Which bucket of the leverage table the unit is in right now."""
    if not attempts:
        return CRASH
    last = attempts[-1]
    trail = " ".join(a.detail for a in attempts)
    if not last.passed:
        if last.kind in (FailureKind.RUNTIME_ERROR, FailureKind.IMPORT_ERROR,
                         FailureKind.TIMEOUT, FailureKind.MODEL_UNAVAILABLE):
            return CRASH
        return SELFCHECK
    if "[examiner]" in last.detail:
        return EXAMINED
    if last.detail.startswith("[template]"):
        return DONE          # a proven template is its own evidence
    if "[consensus]" not in trail:
        return VOTE_PENDING
    if "[evidence]" in last.detail:
        return AGREE
    if "second candidate unusable" in trail and "DISAGREE" not in trail:
        return SECOND_CRASHED
    if "DISAGREE" in trail:
        return DISAGREE
    return INCONCLUSIVE


def _fix_list(spec: TaskSpec, output_dir: pathlib.Path, work_dir: pathlib.Path,
              deadline: Deadline, attempts: list[Attempt],
              last_source: str | None, last_error: str | None,
              telemetry) -> list[Attempt]:
    out: list[Attempt] = []
    crash_rounds = 0
    examined = False
    voted = False
    source = last_source
    error = last_error
    for _ in range(MAX_FIX_ROUNDS):
        if not deadline.can_afford():
            break
        bucket = triage(attempts + out)
        index = len(attempts) + len(out)
        if bucket in (CRASH, SELFCHECK):
            if bucket == CRASH and crash_rounds >= MAX_CRASH_ROUNDS:
                break
            if bucket == CRASH:
                crash_rounds += 1
            hint = CRASH_HINT if bucket == CRASH else ""
            fixed, kind, detail, seconds, tree = _candidate(
                spec, output_dir, work_dir, deadline, variant=0,
                error=f"{error or ''}\n{hint}".strip(), previous_source=source,
                prefer_model=True, telemetry=telemetry, index=index)
            if fixed is None:
                break
            source = fixed
            if kind is FailureKind.PASS:
                _restore_tree(output_dir, tree)   # the floor becomes this answer
                out.append(Attempt(index, FailureKind.PASS,
                                   f"[model][fix:{bucket}] repaired", seconds))
            else:
                error = f"{kind.value}: {detail}"
                out.append(Attempt(index, kind,
                                   f"[model][fix:{bucket}] {detail}"[:1500], seconds))
            continue
        if bucket == VOTE_PENDING and not voted:
            voted = True
            if source and _consensus_affordable(deadline):
                out += _cross_validate(spec, output_dir, work_dir, deadline,
                                       source, True, telemetry, start_index=index)
                continue
            # No budget for a vote: the answer stays; the verdict will say so.
            out.append(Attempt(index, FailureKind.PASS,
                               "[consensus] no vote (disabled or unaffordable); "
                               "first answer stands (flagged)", 0.0))
            continue
        if bucket in (AGREE, SECOND_CRASHED, DISAGREE, INCONCLUSIVE,
                      VOTE_PENDING) and not examined and source:
            # The examiner: one adversarial audit, then at most one repair
            # driven by its findings. Runs on evidenced answers too - two
            # writers can share a misreading (v5b: 6 majority installs, 0
            # graded pass).
            examined = True
            verdict, findings = examiner.examine(spec, output_dir, source,
                                                 telemetry)
            if verdict == "unavailable":
                break            # no examiner, no verdict change
            # Only an EXECUTED failing check is a finding. v6.1 gate-1: the
            # examiner's prose called two correct answers wrong (invented
            # arithmetic) and the claim rate fell to 1 of 26.
            confirmed = (examiner.verify(findings, output_dir, work_dir,
                                         spec.input_root)
                         if verdict == "wrong" else [])
            if not confirmed:
                note = ("no rule violation found" if verdict == "ok" else
                        f"{len(findings)} finding(s) not confirmed by execution")
                out.append(Attempt(index, FailureKind.PASS,
                                   f"[examiner] ok: {note}"
                                   + ("[evidence]" if bucket == AGREE
                                      else " (flagged)"), 0.0))
                break
            findings = confirmed
            # ADVISORY ONLY. Gate-1 run 1 of v6: the examiner's installed
            # rewrites graded 3 of 8, and three of the failures were stable
            # units that were RIGHT before the "fix" - the same shape as
            # v4's reconciliation. A model rewrite is a fresh guess; the
            # examiner's value is its verdict (5 of 5 "ok" graded pass),
            # so its findings downgrade the claim and are recorded, and the
            # floor answer stays untouched.
            out.append(Attempt(index, FailureKind.PASS,
                               "[examiner] wrong (executed checks failed): "
                               + "; ".join(f"{f.get('where', '?')}: {f.get('executed', '')}"
                                           for f in findings)[:600]
                               + " - answer kept (flagged)", 0.0))
            break
        break
    return out


def _snapshot_tree(root: pathlib.Path) -> dict[str, bytes]:
    """Every file under the output root - not just the contract files.

    The v3 sweep destroyed graded-1.0 answers: a second candidate crashed
    after overwriting deliverables the contract extractor had not listed,
    and a contract-only restore left those overwritten. The vote may only
    ever touch the real output through a whole-tree restore.
    """
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _restore_tree(root: pathlib.Path, files: dict[str, bytes]) -> None:
    for p in list(root.rglob("*")):
        if p.is_file() and str(p.relative_to(root)) not in files:
            p.unlink()
    for name, payload in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _candidate(spec: TaskSpec, output_dir: pathlib.Path,
               work_dir: pathlib.Path, deadline: Deadline, *, variant: int,
               error: str | None, previous_source: str | None,
               prefer_model: bool, telemetry, index: int
               ) -> tuple[str | None, FailureKind, str, float, dict[str, bytes]]:
    """One independent write-run-check, with the real output dir restored
    afterwards no matter what. Returns (source, kind, detail, secs, tree)
    where `tree` is what the candidate wrote (whole output tree)."""
    before = _snapshot_tree(output_dir)
    started = time.monotonic()
    source, provenance = code_writer.write(
        spec, spec.contracts, str(output_dir), error, prefer_model,
        telemetry=telemetry, previous_source=previous_source,
        attempt_index=index, variant=variant)
    write_seconds = time.monotonic() - started
    if source is None or provenance != "model":
        return (None, FailureKind.MODEL_UNAVAILABLE, "no independent candidate",
                write_seconds, {})
    script = work_dir / f"candidate_{variant}.py"
    script.write_text(source, encoding="utf-8")
    per_attempt = max(30.0, deadline.remaining - 30.0)
    try:
        try:
            kind, detail, seconds = test_runner.run_solution(
                script, work_dir, per_attempt, input_dir=spec.input_root)
        except TypeError:
            kind, detail, seconds = test_runner.run_solution(
                script, work_dir, per_attempt)
        if kind is FailureKind.PASS:
            kind, detail = _self_check(output_dir, spec.contracts, spec)
        produced = _snapshot_tree(output_dir)
    finally:
        _restore_tree(output_dir, before)
    deadline.record_attempt(write_seconds + seconds)
    return source, kind, detail, write_seconds + seconds, produced


def _cross_validate(spec: TaskSpec, output_dir: pathlib.Path,
                    work_dir: pathlib.Path, deadline: Deadline,
                    first_source: str, prefer_model: bool, telemetry,
                    start_index: int) -> list[Attempt]:
    """Vote between the passing answer and an independent second candidate.

    Agree: the first answer stands, now with output-level evidence.
    Disagree: one reconciliation round with the discrepancy spelled out;
    its answer stands if it verifies, else the first answer is restored.
    The first answer is never destroyed - the vote spends budget, not value.
    """
    # Every candidate runs against the real output dir (the instruction may
    # name it absolutely) but `_candidate` restores the whole tree after
    # each one: the first answer is on disk, untouched, at every return
    # below except the one that explicitly installs a reconciled winner.
    first_print = consensus.fingerprint(output_dir, spec.contracts)
    out: list[Attempt] = []
    if not first_print:
        out.append(Attempt(start_index, FailureKind.PASS,
                           "[consensus] no numeric deliverable to compare; "
                           "first answer stands (flagged)", 0.0))
        return out

    source_b, kind, detail, seconds, tree_b = _candidate(
        spec, output_dir, work_dir, deadline, variant=1, error=None,
        previous_source=None, prefer_model=prefer_model, telemetry=telemetry,
        index=start_index)
    if (kind is not FailureKind.PASS and kind.repairable and source_b
            and source_b != first_source and deadline.can_afford()):
        # v3 sweep: 37 of 62 votes died because the second candidate
        # crashed on its first run - no evidence either way, and that path
        # graded at 41% precision. One repair round, exactly as the main
        # loop would grant, turns most of those into a real comparison.
        out.append(Attempt(start_index, kind,
                           f"[consensus] second candidate failed once "
                           f"({detail[:200]}); one repair round", seconds))
        source_b, kind, detail, more, tree_b = _candidate(
            spec, output_dir, work_dir, deadline, variant=1,
            error=f"{kind.value}: {detail}", previous_source=source_b,
            prefer_model=prefer_model, telemetry=telemetry,
            index=start_index + 1)
        seconds += more
    if kind is not FailureKind.PASS or source_b == first_source:
        why = ("identical to the first" if source_b == first_source
               else f"{kind.value}: {detail[:300]}")
        out.append(Attempt(start_index, FailureKind.PASS,
                           f"[consensus] second candidate unusable ({why}); "
                           "first answer stands (flagged)", seconds))
        return out

    second_print = _fingerprint_tree(tree_b, work_dir / "vote_b", spec)
    agree, mismatches = consensus.compare(first_print, second_print)
    if agree is None:
        out.append(Attempt(start_index, FailureKind.PASS,
                           "[consensus] nothing comparable; first answer "
                           "stands (flagged)", seconds))
        return out
    if agree:
        # The one path that earns a `pass` claim: two independently written
        # programs landing on the same numbers (v3/v4 graded precision 70%
        # vs 9-25% on every other path).
        out.append(Attempt(start_index, FailureKind.PASS,
                           f"[consensus][evidence] independent candidates agree "
                           f"on {len(first_print)} quantities; first answer "
                           "stands", seconds))
        return out

    out.append(Attempt(start_index, FailureKind.INVARIANT_VIOLATION,
                       "[consensus] independent candidates DISAGREE: "
                       + "; ".join(mismatches[:6]), seconds))
    if not deadline.can_afford():
        out.append(Attempt(start_index + 1, FailureKind.PASS,
                           "[consensus] no budget to reconcile; first answer "
                           "stands (flagged)", 0.0))
        return out

    demand = consensus.RECONCILE_DEMAND.format(
        mismatches="\n".join(mismatches[:20]), other=source_b[:3500])
    source_c, kind, detail, seconds, tree_c = _candidate(
        spec, output_dir, work_dir, deadline, variant=2, error=demand,
        previous_source=first_source, prefer_model=prefer_model,
        telemetry=telemetry, index=start_index + 1)
    if kind is FailureKind.PASS:
        third_print = _fingerprint_tree(tree_c, work_dir / "vote_c", spec)
        with_first, _ = consensus.compare(first_print, third_print)
        with_second, _ = consensus.compare(second_print, third_print)
        if with_first or with_second:
            # A majority: the third computation confirms one of the two.
            # Installing the confirmed one (the third's tree) is the
            # adjudicated answer with evidence behind it.
            _restore_tree(output_dir, tree_c)
            out.append(Attempt(start_index + 1, FailureKind.PASS,
                               "[consensus][evidence] reconciled answer "
                               "verified; sides with the "
                               f"{'first' if with_first else 'second'} "
                               "candidate", seconds))
            return out
        # v4 sweep: 12 of 14 "reconciled" installs agreed with NOBODY and
        # graded 0 - a third different answer is not adjudication, it is a
        # third guess. The first answer stays; the claim is uncertain.
        out.append(Attempt(start_index + 1, FailureKind.PASS,
                           "[consensus] reconciled answer agrees with neither "
                           "candidate; first answer stands (flagged)", seconds))
        return out
    out.append(Attempt(start_index + 1, FailureKind.PASS,
                       f"[consensus] reconciliation failed ({kind.value}); "
                       "first answer stands (flagged)", seconds))
    return out


def _fingerprint_tree(tree: dict[str, bytes], scratch: pathlib.Path,
                      spec: TaskSpec) -> dict[str, float]:
    """Fingerprint a candidate's output tree without touching the real one."""
    scratch.mkdir(parents=True, exist_ok=True)
    _restore_tree(scratch, tree)
    return consensus.fingerprint(scratch, spec.contracts)
