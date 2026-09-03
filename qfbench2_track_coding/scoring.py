"""Track 1 verifier and scorer.

Architecture
------------
Track 1 inherits the shared HierarchicalVerifier gate chain (g0-g2) from
qfbench2_common.verifier and provides a T1-specific g3 implementation plus a
pass@k scorer.

Two legacy QFBench verifier patterns are unified here:

Plain-pytest pattern (binary reward)
    The existing majority of QFBench tasks use pytest checks that exit 0 (pass)
    or non-zero (fail).  In T1 v2, the pytest result maps directly to
    g3_domain_semantics: pass → admissible (score computed), fail → inadmissible
    (score=None, label T1_INVARIANT_VIOLATION or T1_WRONG_NUMERIC).

DI-verifier pattern (multi-phase partial credit + root-cause labels)
    The legacy "DI verifier" assigned partial scores and emitted detailed labels
    (T1_CONVENTION_ERROR, T1_MISLABELING).  In T1 v2 the DI labels are
    preserved as diagnostics for the cross-track failure map, but partial credit
    is NOT used for leaderboard ranking.  The DI label pass runs AFTER g3
    clears (i.e., only on admissible attempts) and writes its labels to the
    failure-map JSONL without changing the reward.

Leaderboard ranking
    Official: mean pass@1 across the signed roster, ONE execution per task, fixed denominator,
    no confidence interval (ruled 2026-09-03). pass@3 and bootstrap CIs exist only in the
    offline Harbor development report (`qfbench2 track1 score-harbor-job`).
    LEADERBOARD_SORT = "desc" (higher is better).

Usage
-----
    from qfbench2_track_coding.scoring import build_verifier, LEADERBOARD_SORT
    from qfbench2_common.scoring.passk import suite_summary
    from qfbench2_common.scoring.bootstrap import bootstrap_ci

    verifier = build_verifier(ctx)
    verdict = verifier.run(ctx)
    # verdict.admissible, verdict.score (0.0 or 1.0), verdict.labels
"""

from __future__ import annotations

import json
import sys
import subprocess
import os
import pathlib
import re
from typing import Any

from qfbench2_common.contracts import OrganizerFault
from qfbench2_common.failure_labels import FailureLabel
from qfbench2_common.leakage import scan_canary
from qfbench2_common.manifest import verify_manifest
from qfbench2_common.scoring.passk import pass_at_k, suite_summary  # noqa: F401 (re-exported)
from qfbench2_common.scoring.bootstrap import bootstrap_ci  # noqa: F401 (re-exported)
from qfbench2_common.verifier import Gate, GateResult, HierarchicalVerifier

# ---------------------------------------------------------------------------
# Leaderboard direction
# ---------------------------------------------------------------------------

LEADERBOARD_SORT: str = "desc"  # higher pass@k = better rank

# ---------------------------------------------------------------------------
# Gate g0 — manifest integrity
# (Mirrors the shared gate logic documented in qfbench2_common.verifier.)
# Track 1 adds an interface_version check and image-hash logging.
# ---------------------------------------------------------------------------


def _g0_integrity(ctx: dict[str, Any]) -> GateResult:
    """Verify manifest checksums and interface_version == 2.0.

    ctx keys consumed:
        unit_dir  (str | pathlib.Path): path to the unit directory.
        image_hash (str, optional): sha256 of the submission image (logged).
    """
    unit_dir = pathlib.Path(ctx["unit_dir"])
    errs = verify_manifest(unit_dir)
    if errs:
        return GateResult(
            passed=False,
            label=FailureLabel.INTEGRITY_BAD_MANIFEST,
            detail={"manifest_errors": errs},
        )
    # Interface version check: card.toml schema_version must be "2.0".
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    card_path = unit_dir / "card.toml"
    if card_path.exists():
        card = tomllib.loads(card_path.read_text())
        sv = card.get("schema_version", "")
        if sv != "2.0":
            return GateResult(
                passed=False,
                label=FailureLabel.INTEGRITY_BAD_MANIFEST,
                detail={"error": f"schema_version='{sv}', expected '2.0'"},
            )
    return GateResult(passed=True, detail={"image_hash": ctx.get("image_hash", "")})


# ---------------------------------------------------------------------------
# Gate g1 — output schema
# T1 output schema: /output holds at least one deliverable; reward.json, if present, has reward ∈ {0.0, 1.0}.
# (Full per-task schema validation delegates to the task-specific checker.)
# ---------------------------------------------------------------------------


def _g1_schema(ctx: dict[str, Any]) -> GateResult:
    """Verify that the submission produced deliverables, and that a `reward.json`, IF present, is
    well-formed.

    `reward.json` is NOT required here any more. Measured 2026-09-02: it is written by the
    unit's `checks/test.sh`, and `checks/` is stripped from every mounted tree (it is Track 1's
    sealed grader), so no participant container can produce it. Requiring it here made every
    real Track 1 submission inadmissible at g1, before the grader ran -- indistinguishable from a
    genuinely failing one. The grader's checks run in `_g3_domain_semantics`
    (`_run_trusted_checks`), and admission comes from them alone; g1's job is the shape of what
    the submission wrote, which is: at least one regular file in the output directory.

    ctx keys consumed:
        output_dir (str | pathlib.Path): path to /output.
    """
    output_dir = pathlib.Path(ctx.get("output_dir", "/output"))
    if not output_dir.is_dir():
        return GateResult(
            passed=False,
            label=FailureLabel.SCHEMA_INVALID_OUTPUT,
            detail={"error": f"output directory not found at {output_dir}"},
        )
    deliverables = sorted(
        p.name
        for p in output_dir.iterdir()
        if p.is_file() and p.name not in ("reward.json", "pytest_report.json")
    )
    if not deliverables:
        return GateResult(
            passed=False,
            label=FailureLabel.SCHEMA_INVALID_OUTPUT,
            detail={
                "error": f"no deliverable in {output_dir}: the submission wrote nothing the "
                "unit's checks could examine"
            },
        )

    reward_path = output_dir / "reward.json"
    if reward_path.exists():
        try:
            payload = json.loads(reward_path.read_text())
        except json.JSONDecodeError as exc:
            return GateResult(
                passed=False,
                label=FailureLabel.SCHEMA_INVALID_OUTPUT,
                detail={"error": f"reward.json is not valid JSON: {exc}"},
            )
        reward = payload.get("reward") if isinstance(payload, dict) else None
        if reward not in (0, 1, 0.0, 1.0):
            return GateResult(
                passed=False,
                label=FailureLabel.SCHEMA_INVALID_OUTPUT,
                detail={
                    "error": f"reward.json carries reward={reward!r}; expected 0.0 or 1.0"
                },
            )

    return GateResult(passed=True, label=None, detail={"deliverables": deliverables})


# ---------------------------------------------------------------------------
# Gate g2 — cutoff / resource
# Checks: restricted-network compliance, wall-clock within card limit, canary not emitted.
# ---------------------------------------------------------------------------


def _g2_cutoff_resource(ctx: dict[str, Any]) -> GateResult:
    """Verify cutoff/resource constraints.

    ctx keys consumed:
        elapsed_sec      (float): wall-clock used by the agent container.
        agent_timeout_sec (float): from card.toml [agent].timeout_sec.
        output_dir       (str | pathlib.Path): to scan for canary.
        canary_registry  (set[str]): all known canary GUIDs (loaded from private registry).
        network          (str, optional): the card's [environment].network mode
                         ('restricted' for coding units; egress beyond the audited
                         proxy allowlist is impossible by construction and audited
                         via proxy logs).
    """
    elapsed = float(ctx.get("elapsed_sec", 0.0))
    timeout = float(ctx.get("agent_timeout_sec", 1800.0))
    if elapsed > timeout:
        return GateResult(
            passed=False,
            label=FailureLabel.RESOURCE_TIMEOUT,
            detail={"elapsed_sec": elapsed, "timeout_sec": timeout},
        )

    # Canary scan: search all text output for known GUIDs.
    output_dir = pathlib.Path(ctx.get("output_dir", "/output"))
    registry: set[str] = ctx.get("canary_registry", set())
    if registry:
        text_exts = {".py", ".json", ".txt", ".md", ".csv", ".log"}
        hits: list[str] = []
        for out_file in output_dir.rglob("*"):
            if out_file.is_file() and out_file.suffix in text_exts:
                content = out_file.read_text(errors="replace")
                hits.extend(scan_canary(content, registry))
        if hits:
            return GateResult(
                passed=False,
                label=FailureLabel.CONTAMINATION_CANARY,
                detail={"canary_guids_found": hits},
            )

    return GateResult(passed=True)


# ---------------------------------------------------------------------------
# Gate g3 — domain semantics (T1-specific)
#
# This is where the two legacy verifier patterns are unified:
#
#   1. Pytest result (binary)  →  pass/fail admission.
#      If pytest exits non-zero, the attempt is inadmissible.
#      The failure label is assigned based on the pytest JSON report.
#
#   2. DI verifier (diagnostic)  →  labels only, no reward change.
#      After g3 clears (pytest passed), a lightweight DI pass reads the
#      pytest JSON report and assigns granular T1_* labels to partially
#      correct attempts.  These labels feed the failure-map JSONL but
#      do NOT change the score (which remains 1.0 for an admissible attempt).
#
# ---------------------------------------------------------------------------


def _classify_pytest_failure(report_path: pathlib.Path) -> FailureLabel:
    """Map pytest test names / nodeids to T1 failure labels.

    Heuristic used by the DI verifier to assign root-cause labels from
    pytest JSON report test outcome data.
    """
    if not report_path.exists():
        return FailureLabel.T1_WRONG_NUMERIC  # conservative default

    try:
        report = json.loads(report_path.read_text())
    except Exception:
        return FailureLabel.T1_WRONG_NUMERIC

    failed_tests: list[str] = []
    for test in report.get("tests", []):
        if test.get("outcome") in ("failed", "error"):
            failed_tests.append(test.get("nodeid", ""))

    # Map test name patterns to failure labels.
    # Order matters: more specific patterns take precedence.
    label_rules: list[tuple[str, FailureLabel]] = [
        ("parity", FailureLabel.T1_INVARIANT_VIOLATION),
        ("arbitrage", FailureLabel.T1_INVARIANT_VIOLATION),
        ("lower_bound", FailureLabel.T1_INVARIANT_VIOLATION),
        ("upper_bound", FailureLabel.T1_INVARIANT_VIOLATION),
        ("pde", FailureLabel.T1_INVARIANT_VIOLATION),
        ("gamma", FailureLabel.T1_INVARIANT_VIOLATION),
        ("vega", FailureLabel.T1_INVARIANT_VIOLATION),
        ("convention", FailureLabel.T1_CONVENTION_ERROR),
        ("sign", FailureLabel.T1_CONVENTION_ERROR),
        ("compounding", FailureLabel.T1_CONVENTION_ERROR),
        ("label", FailureLabel.T1_MISLABELING),
        ("column", FailureLabel.T1_MISLABELING),
        ("schema", FailureLabel.T1_MISLABELING),
    ]

    for test_id in failed_tests:
        test_lower = test_id.lower()
        for keyword, label in label_rules:
            if keyword in test_lower:
                return label

    return FailureLabel.T1_WRONG_NUMERIC  # default for unclassified numeric failures


# ---------------------------------------------------------------------------
# Trusted correctness: the grader runs the unit's own checks
# ---------------------------------------------------------------------------

#: Where a unit keeps the checks the GRADER owns. `test.sh` runs `test_outputs.py` against the
#: agent's deliverables and writes `reward.json` as its *output*. Nothing about the file on disk
#: distinguishes a grader-written reward.json from one the submission wrote itself, so admission
#: must come from running the checks, never from reading their supposed result.
_CHECKS_ENTRY = "test_outputs.py"

#: Bound on the "is the test runner installed at all" probe below.
_RUNNER_PROBE_TIMEOUT_SEC = 120.0

#: pytest exit codes that mean pytest itself never rendered a verdict on the submission:
#: 3 = internal error, 4 = usage error (a bad argv, a broken plugin, an unreadable ini). Neither
#: is reachable from anything a submission writes, so neither may be charged to one. 1 (tests
#: failed), 2 (collection interrupted) and 5 (nothing collected) deliberately stay with the
#: submission: a unit whose checks read the agent's deliverables at import time really can be
#: interrupted by a bad deliverable, and guessing "organizer" there would hand out free passes.
_HARNESS_FAULT_EXIT_CODES = frozenset({3, 4})


def _require_test_runner() -> None:
    """Refuse to score at all when the SCORER's own interpreter cannot import pytest.

    `_run_trusted_checks` shells out to ``{sys.executable} -m pytest``. Until 2026-08-29 nothing
    declared that: `pyproject.toml` listed `qfbench2-common` and nothing else, and
    `qfbench2-common` carries pytest only in its `dev` extra. Measured in a clean venv holding
    exactly this package's declared dependencies, on unit
    `t1-option-put-call-parity-forward-audit` with a submission whose four deliverables pass that
    unit's own checks: g3 returned ``passed=False``, ``trusted_checks="ran"``,
    ``pytest_returncode=1``. `python -m pytest` with no pytest installed exits **1** -- which is
    also pytest's "tests failed" code -- so a correct submission was scored zero *and* told its
    answer was wrong, with nothing in the verdict naming the real cause. Every Track 1 submission
    would have gone that way on launch day.

    A missing test runner is organizer material. `OrganizerFault` is the contract's channel for
    that: it produces no participant score, and per the frozen C1 `organizer_failure` policy the
    scope is `abort_whole_evaluation`, so no partial leaderboard of zeros is published.

    The probe is a separate one-line subprocess rather than an `importlib` check in this process
    because ``sys.executable`` is what will actually run the checks, and it is the exit code of
    *that* interpreter, not this one's import table, that decides the verdict.

    Raises:
        OrganizerFault: pytest is not importable by the interpreter that runs the checks.
    """
    try:
        probe = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", "import pytest"],
            capture_output=True,
            text=True,
            timeout=_RUNNER_PROBE_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OrganizerFault(
            f"the Track 1 scorer could not start a test runner with {sys.executable}: {exc}"
        ) from exc
    if probe.returncode != 0:
        raise OrganizerFault(
            "the Track 1 scorer runs every unit's grader-owned checks with "
            f"'{sys.executable} -m pytest', and pytest is not importable there. This is an "
            "organizer-side environment fault, never a submission error: install this "
            "package's declared dependencies into the scoring environment."
        )


def _run_trusted_checks(
    unit_dir: pathlib.Path, output_dir: pathlib.Path, timeout_sec: float = 900.0
) -> tuple[bool, dict[str, Any]]:
    """Run the unit's grader-owned checks against the submission's output.

    Returns ``(passed, detail)``. **A run that cannot happen is not a pass.** If the checks are
    absent, unreadable, error out or time out, this returns ``False`` with a reason — a correctness
    gate that cannot execute must fail closed, never report green (global rule 7).

    Failing closed is right only when the fault could be the submission's. When the fault is
    provably ours — no test runner in the scoring environment, or pytest exiting on its own
    internal/usage error — a ``False`` here would be charged to the participant as
    ``T1_WRONG_NUMERIC``. Those two cases raise `OrganizerFault` instead, which scores nobody.

    Raises:
        OrganizerFault: the scoring environment has no importable pytest, or pytest exited with
            an internal (3) or usage (4) error without judging the submission.
    """
    checks = pathlib.Path(unit_dir) / "checks" / _CHECKS_ENTRY
    if not checks.is_file():
        return False, {"trusted_checks": "absent", "path": str(checks)}

    # Can these checks actually be pointed at THIS output directory?
    #
    # In production the checks run inside the unit's container, where the agent's output really is
    # at the path they name, so a hardcoded `/app/output` is correct there. Run anywhere else, a
    # hardcoded path means the checks read an empty or absent directory and fail for a reason that
    # has nothing to do with the submission. Measured across the public units: 39 of 87 resolve
    # OUTPUT_DIR from the environment and 48 do not.
    #
    # Reporting "failed" in that situation would be a lie in the safe direction, which is still a
    # lie -- and it would make a correct submission look wrong. So this refuses to render a verdict
    # it cannot support, and says which case it is.
    source = checks.read_text(errors="replace")
    redirectable = bool(re.search(r"OUTPUT_DIR[^\n]*(environ|getenv)", source))
    reads_here = pathlib.Path(str(output_dir)).resolve() == pathlib.Path("/app/output")
    if not redirectable and not reads_here:
        return False, {
            "trusted_checks": "not_redirectable",
            "detail": (
                "this unit's checks resolve their output path statically, so they can only be "
                "trusted inside the evaluation container where that path is the agent's output"
            ),
        }

    # Before anything is read as a verdict: can the runner run at all? A scoring environment
    # without pytest cannot judge this submission, and must say so as an organizer fault rather
    # than returning a "failed" that is indistinguishable from a wrong answer.
    _require_test_runner()

    env = {**os.environ, "OUTPUT_DIR": str(output_dir), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                "-m",
                "pytest",
                str(checks),
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
            cwd=str(unit_dir),
        )
    except subprocess.TimeoutExpired:
        return False, {"trusted_checks": "timeout", "timeout_sec": timeout_sec}
    except OSError as exc:
        return False, {"trusted_checks": "could_not_run", "error": str(exc)}
    if proc.returncode in _HARNESS_FAULT_EXIT_CODES:
        # pytest reached an internal or usage error: it never judged the submission. Deliberately
        # no unit path and no captured output in the message -- a sealed unit id must not travel
        # into an operator log on an abort path. The exit code is the diagnosis.
        raise OrganizerFault(
            f"the Track 1 scorer's pytest invocation exited {proc.returncode} "
            "(pytest internal/usage error) before judging the submission; this is an "
            "organizer-side harness fault, never a submission error"
        )
    # pytest: 0 = all passed. 5 = no tests collected, which is not evidence of correctness.
    return proc.returncode == 0, {
        "trusted_checks": "ran",
        "pytest_returncode": proc.returncode,
        "tail": (proc.stdout or proc.stderr or "")[-400:],
    }


def _g3_domain_semantics(ctx: dict[str, Any]) -> GateResult:
    """Run pytest checks + financial invariants; assign T1 failure labels.

    ctx keys consumed:
        output_dir  (str | pathlib.Path): /output (reward.json lives here).
        checks_dir  (str | pathlib.Path, optional): path to checks/test_outputs.py.
            If provided, pytest is re-run by the harness rather than relying on
            a pre-written reward.json (used for the sealed final scorer).
        di_label_only (bool, optional): if True, only assign DI labels without
            changing the admission decision (used as the diagnostic overlay pass).
    """
    output_dir = pathlib.Path(ctx.get("output_dir", "/output"))
    di_label_only: bool = bool(ctx.get("di_label_only", False))

    # --- The submission's CLAIM, if it made one. `reward.json` is written by `checks/test.sh`
    # under Harbor; under this harness `checks/` is stripped from the mounted tree, so a
    # participant container normally cannot write it, and its absence means nothing. Present
    # and unparseable is still refused: a malformed claim is a malformed output.
    reward_path = output_dir / "reward.json"
    report_path = output_dir / "pytest_report.json"

    reward: float | None = None
    payload: dict[str, Any] = {}
    if reward_path.exists():
        try:
            payload = json.loads(reward_path.read_text())
            reward = float(payload.get("reward", 0.0))
        except Exception as exc:
            return GateResult(
                passed=False,
                label=FailureLabel.T1_WRONG_NUMERIC,
                detail={"error": f"reward.json parse error: {exc}"},
            )

    # --- DI label overlay (diagnostic pass, admissible attempts only) ---
    # Classifies root-cause even when reward=1.0 to capture partially-correct
    # admissible solutions (e.g., correct price but sign-flipped theta).
    di_label: FailureLabel | None = None
    if reward is not None and reward < 1.0:
        di_label = _classify_pytest_failure(report_path)
    elif di_label_only:
        # For admissible attempts: run classification on any non-fatal warnings
        # in the pytest report (outcome="passed" with warnings may still
        # signal a T1_CONVENTION_ERROR via xfail or custom marks).
        di_label = _classify_pytest_failure(report_path)

    if di_label_only:
        # DI overlay: do not gate, just annotate.  Always "passes" this phase.
        return GateResult(
            passed=True,
            label=di_label,
            detail={"di_label": di_label.value if di_label else None, "reward": reward},
        )

    # --- Binary admission decision: the GRADER's checks, never the submission's claim ---
    #
    # `reward.json` is written by the submission's own container when it can (Harbor); under
    # this harness it usually cannot, and g1 no longer requires it. Either way it cannot decide
    # correctness: measured
    # 2026-08-28, an output directory containing nothing but `{"reward": 1.0}` -- no solution,
    # no deliverable, nothing executed -- was admitted with score 1.0, identical to a genuinely
    # correct submission. Admission now comes from running the unit's own `checks/` against the
    # deliverables, which is what `test.sh` was always meant to do and what nothing here did.
    unit_dir = pathlib.Path(ctx.get("unit_dir", "."))
    trusted_ok, trusted = _run_trusted_checks(unit_dir, output_dir)

    if not trusted_ok and trusted.get("trusted_checks") != "ran":
        # The checks could not be executed. That is not evidence of correctness and must not be
        # scored as though it were (global rule 7: a gate that cannot run fails, never passes).
        return GateResult(
            passed=False,
            label=FailureLabel.T1_WRONG_NUMERIC,
            detail={
                "error": "trusted checks did not execute",
                "claimed_reward": reward,
                **trusted,
            },
        )

    if trusted_ok and reward is not None and reward < 1.0:
        # The submission under-reported itself. Harmless, but worth recording.
        trusted["claim_disagreement"] = "checks passed, submission reported failure"

    return GateResult(
        passed=trusted_ok,
        label=di_label if not trusted_ok else None,
        detail={
            "claimed_reward": reward,
            "claimed_pytest_exit_code": payload.get("pytest_exit_code"),
            **trusted,
        },
    )


# ---------------------------------------------------------------------------
# Scorer: converts admissible attempt result to score dict
# ---------------------------------------------------------------------------


def _t1_scorer(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return score=1.0 for an admissible attempt (passed all gates).

    Pass@k is computed in aggregate over multiple attempts; per-attempt
    the score is binary (0.0 inadmissible, 1.0 admissible).
    The sealed final scorer aggregates [T, n_attempts] into pass@k.
    """
    return {"score": 1.0, "metric": "pass@k", "k_values": [1, 3]}


# ---------------------------------------------------------------------------
# Public factory: build_verifier
# ---------------------------------------------------------------------------


def build_verifier(ctx: dict[str, Any]) -> HierarchicalVerifier:
    """Construct the T1 HierarchicalVerifier for one evaluation attempt.

    Gate order (matches the published contract in qfbench2_common.verifier):
        g0_integrity         manifest checksums OK, schema_version == "2.0"
        g1_schema            the submission wrote deliverables; reward.json, if any, well-formed
        g2_cutoff_resource   timeout, canary, restricted-network compliance
        g3_domain_semantics  pytest passes AND financial invariants hold

    Args:
        ctx: evaluation context dict.  Required keys depend on which gates run;
             see each gate function's docstring.  Typical keys:
             - unit_dir (str | Path): the unit directory.
             - output_dir (str | Path): the /output directory.
             - elapsed_sec (float): agent wall-clock time.
             - agent_timeout_sec (float): from card.toml.
             - canary_registry (set[str]): from private canary_registry.json.
             - image_hash (str): sha256 of submission image.

    Returns:
        HierarchicalVerifier ready to call .run(ctx).

    Example::

        from qfbench2_track_coding.scoring import build_verifier
        verifier = build_verifier({
            "unit_dir": "/task/units/t1-deriv-bs",
            "output_dir": "/run/output",
            "elapsed_sec": 423.1,
            "agent_timeout_sec": 1800.0,
            "canary_registry": {"f47ac10b-58cc-..."},
            "image_hash": "sha256:abc123...",
        })
        verdict = verifier.run(ctx)
        # verdict.admissible  bool
        # verdict.score       1.0 or None
        # verdict.labels      list[FailureLabel]
    """
    # Annotated with the toolkit's own `Gate` alias rather than left to inference. `list` is
    # invariant, so an inferred `list[tuple[str, Callable[[dict[str, Any]], GateResult]]]` is not
    # the `list[tuple[str, Gate]]` HierarchicalVerifier declares, and `mypy --strict` -- a required
    # CI check -- rejected this call. Naming the published type is the fix; silencing the check
    # with an ignore would have left the next signature drift invisible.
    gates: list[tuple[str, Gate]] = [
        ("g0_integrity", _g0_integrity),
        ("g1_schema", _g1_schema),
        ("g2_cutoff_resource", _g2_cutoff_resource),
        ("g3_domain_semantics", _g3_domain_semantics),
    ]
    return HierarchicalVerifier(gates=gates, scorer=_t1_scorer)
