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

import ast
import contextlib
import json
import sys
import subprocess
import os
import pathlib
import re
import tempfile
import xml.etree.ElementTree as ET
import shutil
import stat
from collections.abc import Iterator
from typing import Any

from qfbench2_common.contracts import OrganizerFault
from qfbench2_common.failure_labels import FailureLabel
from qfbench2_common.leakage import scan_tree
from qfbench2_common.manifest import verify_manifest
from qfbench2_common.scoring.passk import pass_at_k, suite_summary  # noqa: F401 (re-exported)
from qfbench2_common.scoring.bootstrap import bootstrap_ci  # noqa: F401 (re-exported)
from qfbench2_common.verifier import Gate, GateResult, HierarchicalVerifier

#: The scorer version, SHARED BY ALL FOUR TRACKS and bumped together (owner ruling 2026-09-11).
#:
#: Before this the four packages declared 2.0.0, 2.1.0, 0.1.0 and 3.0.0 -- numbers with no
#: relationship to each other, to the toolkit, or to anything a participant could see, and three of
#: the four exposed no version at all. A participant asking which scorer produced their number had
#: nothing to resolve. 3.1.0 was chosen because nothing may appear to go backwards: Track 4 was
#: already at 3.0.0, so a lower shared number would have been a downgrade for it.
#:
#: `pyproject.toml` must agree with this, and a test in this repository asserts it -- the Track 2
#: package previously said 2.1.0 there and 2.0.0 here, so even a participant who found a version
#: could not trust it.
SCORER_VERSION = "3.1.0"


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

    # Canary scan: every regular file under the output tree, at any depth.
    #
    # This used to walk the tree itself, read only files whose suffix was in a six-entry allowlist
    # (.py .json .txt .md .csv .log), and call the withdrawn `scan_canary` per file. Two defects in
    # one loop: `scan_canary` is a raising stub under frozen ruling R-8, so the gate CRASHED the
    # moment a registry was supplied; and the extension allowlist meant a contaminated agent that
    # wrote its memory to any other name was never scanned at all.
    #
    # `scan_tree` reads every regular file regardless of name or extension, matches byte-wise and
    # case-folded so a canary is found in binary output as readily as in text, and raises
    # `LeakageScanIncomplete` (an OrganizerFault) rather than reporting `clean` when it cannot
    # finish -- a scan that could not complete must never look like a scan that found nothing.
    #
    # It returns a verdict carrying a COUNT of distinct registry entries observed, never the
    # matched GUIDs themselves, so a hit cannot tell an adversary which canary they tripped.
    output_dir = pathlib.Path(ctx.get("output_dir", "/output"))
    registry: set[str] = ctx.get("canary_registry", set())
    if registry:
        verdict = scan_tree(output_dir, registry)
        if verdict.canary_verdict == "hit":
            # COUNT only, never the matched GUIDs. The old detail returned the canaries that were
            # hit, which hands a contaminated submitter the exact strings to strip on the next
            # attempt -- and the registry is private material besides. `hit_count` is the number of
            # DISTINCT registry entries observed, so repeating one canary a thousand times cannot
            # be made to read differently from writing it once.
            return GateResult(
                passed=False,
                label=FailureLabel.CONTAMINATION_CANARY,
                detail={
                    "canary_hit_count": verdict.hit_count,
                    "scanned_file_count": verdict.scanned_file_count,
                },
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

#: The container paths the harness binds to the run's output directory, in the order they are
#: tried. Keep in sync with `tests/test_output_dir_contract.py::BOUND_OUTPUT_PATHS` and
#: SUBMISSION_CLI.md invariant 8. A unit's checks may name either statically; the scorer presents
#: the submission's output there for the duration of that unit's checks (see
#: `_present_output_at`). On the platform the first one already exists, empty, when the scorer
#: starts: it is the scoring container's own output root, bound there by the worker. Module-level
#: so tests can point it at a temporary tree -- creating a real `/app/output` needs root, which
#: CI does not have.
_PRESENTABLE_OUTPUT_PATHS: tuple[str, ...] = ("/app/output", "/output")

#: Does `checks/test_outputs.py` resolve its output path from the environment? Both operand orders
#: are real: `pathlib.Path(os.environ.get("OUTPUT_DIR") or "/app/output")` puts OUTPUT_DIR after
#: `environ`, `d = os.environ.get("OUTPUT_DIR", "/app/output")` puts it after too -- but the first
#: form the scorer shipped with, `OUTPUT_DIR[^\n]*(environ|getenv)`, matched only a name-first
#: line (`OUTPUT_DIR = os.environ[...]`) and classified a value-first line as hardcoded. Both
#: spellings exist in authored units; both are redirectable.
_REDIRECTABLE_RE = re.compile(
    r"(?:environ|getenv)[^\n]*OUTPUT_DIR|OUTPUT_DIR[^\n]*(?:environ|getenv)"
)


def _static_output_paths(source: str) -> list[str]:
    """The bound container paths a checks file names literally, in `_PRESENTABLE_OUTPUT_PATHS`
    order. The lookbehind is load-bearing (it is the one `tests/test_output_dir_contract.py`
    documents): without it `/output` matches INSIDE `/app/output` and a relative `./output`."""
    found: list[str] = []
    for path in _PRESENTABLE_OUTPUT_PATHS:
        if re.search(rf"(?<![.\w]){re.escape(path)}(?![A-Za-z0-9_-])", source):
            found.append(path)
    return found


#: The one thing `_present_output_at` assumes about a unit's checks: they READ the submission's
#: output, they do not EXECUTE it. A checks process that runs participant code (imports a module
#: from the output, adds it to `sys.path`, runs it in a subprocess, `exec`s its text) hands that
#: code the presentation directory itself, and from there the "restored -> not restored"
#: distinction below stops being organizer-only. Measured 2026-09-10: 0 of 87 public and 0 of
#: 29 sealed checks files do; the 11 `sys.path` users point at `__file__`-relative helpers and
#: the 2 `subprocess` users run the organizer's own `solution/solve.sh`. The roster tests
#: (`tests/test_scoring_bypass.py::TestTheClassifierOverTheRoster`) and the private census tool
#: keep it at 0 by refusing the shapes `_calls_executing_from_output` recognises. The name test
#: is by the CALL's dotted name; the location test is over the WHOLE call, so a multi-line
#: `subprocess.run([\n ..., str(OUTPUT_DIR / "solve.py")])` is seen. A path stored in a variable
#: first is not: this is a roster-hygiene guard for authored files, not a sandbox.
_EXECUTION_CALL_RE = re.compile(
    r"^(?:[\w.]+\.)?(?:sys\.path\.\w+|subprocess\.\w+|Popen|importlib(?:\.\w+)+|runpy\.\w+"
    r"|exec|eval|__import__|os\.(?:system|popen|exec\w*|spawn\w*|posix_spawn\w*))$"
)
_OUTPUT_LOCATION_RE = re.compile(
    r"OUTPUT_DIR|output_dir|(?<![.\w])/app/output|(?<![.\w])/output(?![A-Za-z0-9_-])"
)


def _calls_executing_from_output(source: str) -> list[int]:
    """Line numbers of calls in `source` that hand the output location to an execution
    facility. Empty for a checks file that only reads its output. A file that does not parse
    raises `SyntaxError`: pytest could not collect it either, so it is a roster defect too."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if not _EXECUTION_CALL_RE.match(ast.unparse(node.func)):
            continue
        segment = ast.get_source_segment(source, node) or ""
        if _OUTPUT_LOCATION_RE.search(segment):
            hits.append(node.lineno)
    return hits


class _UnpresentableOutput(Exception):
    """The submission's output tree cannot be presented by copy for a reason that is the tree's
    own: a special file (a FIFO would block the copy forever; a device node could feed it
    without end), an entry the scorer cannot read, or no tree at all. Participant material:
    `_run_trusted_checks` turns it into a non-"ran" verdict, never an `OrganizerFault`."""


def _scan_presentable(output_dir: pathlib.Path) -> str | None:
    """Why `output_dir` cannot be copied, or ``None`` when every entry is a regular file, a
    directory or a symlink (kept as a symlink, never followed) that this process can read."""
    if not output_dir.is_dir():
        return "the output directory does not exist"
    for root, dirs, files in os.walk(output_dir, followlinks=False):
        for name in dirs + files:
            entry = pathlib.Path(root) / name
            shown = entry.relative_to(output_dir)
            try:
                mode = os.lstat(entry).st_mode
            except OSError as exc:
                return f"{shown} cannot be inspected: {exc.strerror}"
            if stat.S_ISLNK(mode):
                continue
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                return f"{shown} is not a regular file, a directory or a symlink"
            if not os.access(entry, os.R_OK):
                return f"{shown} is not readable"
    return None


def _claim_presentation_dir(
    target: pathlib.Path, raw: str, made_parents: list[pathlib.Path]
) -> bool:
    """Take `target` for the presentation. ``True`` when this scorer created it, ``False`` when
    it found an EMPTY directory there (the platform: CodaBench binds the scoring program's own,
    still-empty output root at `/app/output`). Anything else -- a symlink, a file, a directory
    with content, a parent that cannot be made -- is organizer material, raised as
    `OrganizerFault` and left exactly as found."""
    if target.is_symlink():
        raise OrganizerFault(
            f"the Track 1 scorer needs to present the submission's output at {raw}, but that "
            "path is a symlink this scorer did not make. Left untouched. Organizer-side "
            "environment fault, never a submission error."
        )
    if target.exists():
        if not target.is_dir():
            raise OrganizerFault(
                f"the Track 1 scorer needs to present the submission's output at {raw}, but "
                "that path is a file, not a directory. Left untouched. Organizer-side "
                "environment fault, never a submission error."
            )
        try:
            occupied = any(target.iterdir())
        except OSError as exc:
            raise OrganizerFault(
                f"the Track 1 scorer cannot list {raw} to present the submission's output "
                f"there: {exc}. Organizer-side environment fault, never a submission error."
            ) from exc
        if occupied:
            raise OrganizerFault(
                f"the Track 1 scorer needs to present the submission's output at {raw}, but "
                "that directory already has content that is not this scorer's. Left "
                "untouched: an empty directory there is expected (the platform binds the "
                "scoring output root at /app/output before the scorer starts), a populated "
                "one is not. Organizer-side environment fault, never a submission error."
            )
        return False
    parent = target.parent
    if not parent.is_dir():
        try:
            parent.mkdir(parents=True)
        except OSError as exc:
            raise OrganizerFault(
                f"the Track 1 scorer could not create {parent} to present the submission's "
                f"output at {raw}: {exc}. Organizer-side environment fault."
            ) from exc
        made_parents.append(parent)
    try:
        target.mkdir()
    except OSError as exc:
        raise OrganizerFault(
            f"the Track 1 scorer could not create {raw} to present the submission's output: "
            f"{exc}. Organizer-side environment fault."
        ) from exc
    return True


def _make_tree_removable(root: pathlib.Path) -> None:
    """Give the owner write and search on `root` and every directory below it, so that a
    read-only subdirectory does not stop the restoration: `shutil.copytree` copies modes, so a
    `0500` directory in the submission's output arrives as a `0500` directory in the
    presentation, and a check may leave one too. A file's mode does not gate its unlinking,
    so files are left alone. Directories only, by `lstat`: a symlink to a directory (kept as a
    symlink by the copy) is never followed, so nothing outside the tree is ever chmod'ed.
    Topdown, and the children of each directory before the walk descends into them, so a
    directory that cannot be listed yet (`0000`) is opened before `os.walk` tries."""

    def widen(path: pathlib.Path) -> None:
        mode = os.lstat(path).st_mode
        if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
            wanted = stat.S_IMODE(mode) | stat.S_IRWXU
            if wanted != stat.S_IMODE(mode):
                os.chmod(path, wanted)

    widen(root)
    for dirpath, dirnames, _files in os.walk(root, followlinks=False):
        for name in dirnames:
            widen(pathlib.Path(dirpath) / name)


def _restore_presentation_dir(
    target: pathlib.Path, raw: str, created: bool
) -> str | None:
    """Put `target` back the way `_claim_presentation_dir` found it: absent if this scorer made
    it, an empty directory otherwise. Everything inside goes -- what was copied in and anything
    the checks wrote next to it; on the platform the worker refuses an output root that already
    holds a `metadata` file, and nothing a check leaves there is part of the verdict. A
    read-only subdirectory in there (copied from the output tree, or left by a check) is opened
    first (`_make_tree_removable`); left as found, it would fail the removal, and a populated
    root fails the NEXT hardcoded unit as an organizer fault. Returns a description, leaving
    the path alone, when it is no longer the directory that was populated (a symlink or a file
    now stands there: not ours to remove)."""
    try:
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            return f"{raw} is no longer the directory this scorer populated"
        if target.is_dir():
            _make_tree_removable(target)
            for entry in list(target.iterdir()):
                if entry.is_symlink() or not entry.is_dir():
                    entry.unlink()
                else:
                    shutil.rmtree(entry)
            if created:
                target.rmdir()
        elif not created:
            # The checks removed the empty directory the scorer was given (possible only off
            # the platform: a bind mount cannot be removed). Restore what was found.
            target.mkdir()
    except OSError as exc:
        return f"{raw} could not be restored: {exc}"
    return None


def _copy_failure_summary(exc: OSError) -> str:
    """`exc` without the paths it carries. `str(exc)` names the SOURCE of what failed, and
    the source is the run's output directory -- on the platform `res/<unit>`, whose last
    component is the unit's handle. An `OrganizerFault` message goes to the scoring log,
    which is not the place for a sealed unit's handle. `shutil.Error` is the collected form
    (one ``(src, dst, why)`` triple per failed entry, each `why` a `str(OSError)` with paths):
    reduced to the count. A bare `OSError` keeps errno and strerror (the C library's text,
    never a path); anything without them is named by type only."""
    if isinstance(exc, shutil.Error):
        failed = exc.args[0] if exc.args and isinstance(exc.args[0], list) else []
        return (
            f"shutil.Error: {len(failed)} of the output's entries could not be copied"
        )
    if exc.errno is not None and exc.strerror:
        return f"{type(exc).__name__}: [Errno {exc.errno}] {exc.strerror}"
    return type(exc).__name__


@contextlib.contextmanager
def _present_output_at(
    paths: list[str], output_dir: pathlib.Path
) -> Iterator[list[str]]:
    """Make the contents of `output_dir` visible at each of `paths` while the block runs.

    Why: on the platform `score.py` scores every unit with `output_dir = res/<unit>`, never
    `/app/output`, and 48 of the 87 Development units' checks hardcode `/app/output` (measured
    2026-09-10). Until this existed the scorer refused those units as ``not_redirectable`` and
    `_g3_domain_semantics` filed the refusal as the PARTICIPANT's `T1_WRONG_NUMERIC`, so on 48
    units a correct solution was labelled exactly like a placeholder, for every team.

    How: a COPY of the output tree into the named directory, which the scorer either creates
    (and removes afterwards) or finds already there and EMPTY (and empties afterwards). The
    second case is the platform's, not an edge case: the vendored CodaBench worker binds the
    scoring program's own output directory at `/app/output` for every scoring container
    (`compute_worker.py`, `volumes_config[...] = {"bind": "/app/output"}`), that directory is
    a fresh, empty one for every run, and `score.py` writes nothing into it until the unit loop
    has finished. The first version of this function refused any pre-existing path, which on
    the platform turned "48 units scored as participant zero" into "the whole evaluation
    aborted as an organizer fault, nothing scored" -- caught in review before it shipped, never
    deployed. A symlink cannot do the platform case at all (a bind mount cannot be replaced),
    per-entry symlinks would hide subdirectories from `os.walk` and `Path.rglob` (one public
    unit rglobs its output), and a bind mount needs privileges the container may not have.

    Precondition, held by the roster tests, not by this code: the checks READ the output, they
    never execute it (see `_EXECUTION_CALL_RE`). Given that, everything below the copy is
    organizer material and raises `OrganizerFault`, which scores nobody: a path that is a
    symlink, a file or a populated directory (never touched -- it could be a real mount), a
    parent or directory that cannot be created, a copy that fails on a tree already checked to
    be copyable, or a path that is no longer the directory this scorer populated when the
    checks finish (left in place). What IS the submission's -- an output tree that cannot be
    copied because of what it contains -- raises `_UnpresentableOutput` before anything is
    touched, and `_run_trusted_checks` files that with the submission.

    Known window, documented rather than closed: a process a unit's checks leave running past
    pytest's exit can read the NEXT unit's presentation through the same path. Same submission,
    organizer-owned checks; the precondition above is what keeps it that way. A leftover
    process that WRITES into the bound path after the restoration makes the NEXT hardcoded
    unit an `OrganizerFault` (`_claim_presentation_dir` finds the root populated), which is
    the intended loud failure: nothing is scored against a presentation that is not the
    scorer's own.
    """
    if paths:
        reason = _scan_presentable(output_dir)
        if reason is not None:
            raise _UnpresentableOutput(reason)
    placed: list[tuple[pathlib.Path, str, bool]] = []
    made_parents: list[pathlib.Path] = []
    try:
        for raw in paths:
            target = pathlib.Path(raw)
            created = _claim_presentation_dir(target, raw, made_parents)
            placed.append((target, raw, created))
            try:
                shutil.copytree(output_dir, target, symlinks=True, dirs_exist_ok=True)
            except OSError as exc:  # shutil.Error is an OSError
                raise OrganizerFault(
                    f"the Track 1 scorer could not copy the submission's output to {raw} "
                    f"({_copy_failure_summary(exc)}). The output tree was checked to be "
                    "copyable first, so this is the scoring environment's (space, "
                    "permissions). Organizer-side fault. The failure's own text is not "
                    "repeated here: it names the run's output directory."
                ) from exc
        yield list(paths)
    finally:
        not_restored: list[str] = []
        for target, raw, created in reversed(placed):
            problem = _restore_presentation_dir(target, raw, created)
            if problem is not None:
                not_restored.append(problem)
        for parent in reversed(made_parents):
            with contextlib.suppress(OSError):
                parent.rmdir()
        if not_restored:
            raise OrganizerFault(
                "the Track 1 scorer's presentation of the submission's output was replaced "
                f"while the unit's checks ran ({'; '.join(not_restored)}); it was left in "
                "place and the checks' verdict cannot be trusted. Organizer-side environment "
                "fault."
            )


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


_INPUT_PATHS = {"/input": "", "/app/data": "environment/data"}
_IMAGE_INPUT_ROOT = "/app"
_REFERENCE_INPUT_ROOT = "/tests/reference_data"


def _checker_input_paths(source: str) -> set[str]:
    """Literal organizer input paths only; never treat output/log paths as inputs."""
    roots = (*_INPUT_PATHS, _REFERENCE_INPUT_ROOT, _IMAGE_INPUT_ROOT)
    tree = ast.parse(source)
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    ignored: set[int] = set()

    def ignore(node: ast.AST | None) -> None:
        if node is not None:
            ignored.update(id(child) for child in ast.walk(node))

    def inert_declaration(node: ast.AST | None) -> bool:
        return (isinstance(node, ast.Constant) and isinstance(node.value, str)) or (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) in ("Path", "pathlib.Path")
            and not node.keywords
            and all(
                isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                for arg in node.args
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            ignore(node.value)  # A docstring or another inert string expression.
        elif isinstance(node, ast.Assert) and isinstance(node.msg, ast.Constant):
            ignore(node.msg)  # A literal failure message is not an input dependency.
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for argument in node.exc.args:
                if isinstance(argument, ast.Constant):
                    ignore(argument)
        elif isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if (
                len(names) == len(node.targets)
                and names.isdisjoint(loaded)
                and inert_declaration(node.value)
            ):
                ignore(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id not in loaded and inert_declaration(node.value):
                ignore(node.value)
        elif isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name == "print" or name.startswith(("logging.", "logger.")):
                for argument in node.args:
                    if isinstance(argument, ast.Constant):
                        ignore(argument)
    interpolated_directories = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and id(node) not in ignored:
            # Constant fragments are not filenames. Only the complete fixed directory
            # before the first interpolation can be checked without evaluating Python.
            prefix = ""
            for piece in node.values:
                if not isinstance(piece, ast.Constant) or not isinstance(
                    piece.value, str
                ):
                    break
                prefix += piece.value
            if prefix.startswith("/"):
                interpolated_directories.append(
                    prefix.rpartition("/")[0]
                    if any(
                        isinstance(piece, ast.FormattedValue) for piece in node.values
                    )
                    else prefix
                )
            for piece in node.values:
                if isinstance(piece, ast.Constant):
                    ignore(piece)
    values = interpolated_directories + [
        node.value
        for node in ast.walk(tree)
        if id(node) not in ignored
        and isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    ]
    paths = set()
    for value in values:
        value = value.rstrip("/")
        if any(
            value == p or value.startswith(p + "/")
            for p in (*_PRESENTABLE_OUTPUT_PATHS, "/app/output", "/output")
        ):
            continue
        if any(value == root or value.startswith(root + "/") for root in roots):
            if ".." in pathlib.PurePosixPath(value).parts:
                raise OrganizerFault("the checker names an unsafe organizer input path")
            paths.add(value)
    return paths


def _input_presentations(
    unit_dir: pathlib.Path, source: str
) -> dict[str, pathlib.Path]:
    """Resolve literal COPY data mappings without executing a Dockerfile or reading host inputs.

    Only the selected organizer unit is a source. Unsupported/absent mappings fail before
    pytest, including checkers that silently tolerate a missing reference directory.
    """
    named = _checker_input_paths(source)
    mappings = {
        target: unit_dir / relative for target, relative in _INPUT_PATHS.items()
    }
    mappings[_REFERENCE_INPUT_ROOT] = unit_dir / "checks/reference_data"
    dockerfile = unit_dir / "environment/Dockerfile"
    if dockerfile.is_file():
        if (
            dockerfile.is_symlink()
            or (unit_dir / "environment").is_symlink()
            or not dockerfile.resolve().is_relative_to(unit_dir.resolve())
        ):
            raise OrganizerFault(
                "the organizer Dockerfile is outside its unit or symlinked"
            )
        mappings.pop(_IMAGE_INPUT_ROOT + "/data", None)
        for line in dockerfile.read_text().splitlines():
            # Restricted, literal, single-source COPY grammar used by the public units.
            # JSON form, variables, flags, globs and multi-stage copies are not inferred.
            match = re.fullmatch(
                r"\s*COPY\s+(data(?:/[\w.\-/]*)?)\s+(/[^\s$*?\[\]]+)\s*", line
            )
            if not match:
                continue
            relative, destination = match.groups()
            src = unit_dir / "environment" / relative
            dest = pathlib.PurePosixPath(destination)
            root = pathlib.PurePosixPath(_IMAGE_INPUT_ROOT)
            if ".." in pathlib.PurePosixPath(relative).parts or ".." in dest.parts:
                raise OrganizerFault("the unit's organizer input mapping is unsafe")
            if not dest.is_relative_to(root):
                continue
            if src.is_dir():
                # Never replace /app itself: the scorer lives there. Present its data
                # children individually and leave unrelated pre-existing files alone.
                for child in src.iterdir():
                    mappings[str(dest / child.name)] = child
            else:
                copy_target = dest / src.name if destination.endswith("/") else dest
                mappings[str(copy_target)] = src
    selected = {}
    for target, data in mappings.items():
        if any(
            p == target or p.startswith(target + "/") or target.startswith(p + "/")
            for p in named
        ):
            if not data.exists() or not data.resolve().is_relative_to(
                unit_dir.resolve()
            ):
                raise OrganizerFault(
                    "the checker requires an absent organizer input or one outside its unit"
                )
            if (
                data.is_symlink()
                or pathlib.Path(target).is_symlink()
                or any(parent.is_symlink() for parent in pathlib.Path(target).parents)
            ):
                raise OrganizerFault("the organizer input mapping contains a symlink")
            if data.is_dir() and any(item.is_symlink() for item in data.rglob("*")):
                raise OrganizerFault("the organizer input tree contains a symlink")
            if any(
                target == root or target.startswith(root + "/")
                for root in _PRESENTABLE_OUTPUT_PATHS
            ):
                raise OrganizerFault(
                    "the organizer input mapping overlaps a submission output path"
                )
            selected[target] = data
    for path in named:
        candidates = [
            (target, data)
            for target, data in selected.items()
            if path == target or path.startswith(target + "/")
        ]
        if not candidates:
            if not any(target.startswith(path + "/") for target in selected):
                raise OrganizerFault(
                    "the checker requires an unmapped organizer input path"
                )
        elif not any(
            (data / pathlib.PurePosixPath(path).relative_to(target)).exists()
            for target, data in candidates
        ):
            raise OrganizerFault("the checker requires an absent organizer input file")
    return selected


@contextlib.contextmanager
def _present_input_file(target: pathlib.Path, data: pathlib.Path) -> Iterator[None]:
    """Create exactly one absent input file; never replace an existing host entry."""
    created_parents = []
    created = False
    try:
        for parent in reversed(target.parents):
            if parent.is_symlink():
                raise OrganizerFault(
                    "the organizer input destination has a symlink parent"
                )
            if not parent.exists():
                parent.mkdir()
                created_parents.append(parent)
        with target.open("xb") as destination:
            created = True
            with data.open("rb") as source:
                shutil.copyfileobj(source, destination)
        yield
    except OSError as exc:
        raise OrganizerFault(
            "the organizer input file cannot be presented without replacing existing state"
        ) from exc
    finally:
        if created:
            if target.is_symlink() or not target.is_file():
                raise OrganizerFault(
                    "the organizer input presentation was replaced by the checker"
                )
            target.unlink()
        for parent in reversed(created_parents):
            with contextlib.suppress(OSError):
                parent.rmdir()


@contextlib.contextmanager
def _present_inputs(unit_dir: pathlib.Path, source: str) -> Iterator[None]:
    """Present inputs; normalize only input setup/cleanup faults, never checker-body faults."""
    stack = contextlib.ExitStack()
    try:
        try:
            for target, data in _input_presentations(unit_dir, source).items():
                if data.resolve() == pathlib.Path(target).resolve():
                    continue
                if data.is_dir():
                    stack.enter_context(_present_output_at([target], data))
                elif data.is_file():
                    stack.enter_context(_present_input_file(pathlib.Path(target), data))
                else:
                    raise OrganizerFault(
                        "the organizer input is not a regular file or directory"
                    )
        except (_UnpresentableOutput, OSError, UnicodeError, OrganizerFault):
            # Neither source paths nor unit-specific destination names belong in feedback.
            raise OrganizerFault(
                "the checker requires unavailable or unsafe organizer input"
            ) from None
        yield
    finally:
        try:
            stack.close()
        except (_UnpresentableOutput, OSError, UnicodeError, OrganizerFault):
            raise OrganizerFault(
                "the organizer input presentation could not be restored"
            ) from None


def _run_trusted_checks(
    unit_dir: pathlib.Path, output_dir: pathlib.Path, timeout_sec: float = 900.0
) -> tuple[bool, dict[str, Any]]:
    """Run the unit's grader-owned checks against the submission's output.

    Returns ``(passed, detail)``. **A run that cannot happen is not a pass.** If the checks time
    out, this returns ``False`` with a reason — a correctness gate that cannot execute must fail
    closed, never report green (global rule 7).

    Failing closed is right only when the fault could be the submission's (a check that never
    finishes may be reading a pathological deliverable). When the fault is provably ours — the
    checks file is absent from the unit, it cannot be pointed at this output directory, the
    scorer cannot launch its own interpreter, no test runner in the scoring environment, or
    pytest exiting on its own internal/usage error — a ``False`` here would be charged to the
    participant as ``T1_WRONG_NUMERIC``. Every one of those raises `OrganizerFault` instead,
    which scores nobody.

    Returns ``False`` with ``trusted_checks="unpresentable_output"`` when the checks name the
    path statically and the output tree itself cannot be copied there (a special file, an
    unreadable entry): that is the submission's tree, so it stays with the submission.

    Raises:
        OrganizerFault: the unit ships no checks file; the checks resolve their path statically
            and the scorer cannot present the output there (see `_present_output_at`); the
            scoring environment has no importable pytest or cannot launch it; or pytest exited
            with an internal (3) or usage (4) error without judging the submission.
    """
    # Resolved before anything uses them. The subprocess below runs with `cwd=unit_dir`, so a
    # RELATIVE `unit_dir` -- which is exactly what the README's own command produces
    # (`qfbench2 smoke units/<unit> <out> --track coding`) -- makes the checks path resolve
    # against the new working directory, where it does not exist. pytest then exits 4 (usage
    # error) and `_HARNESS_FAULT_EXIT_CODES` correctly refuses to score it, so the participant
    # gets an OrganizerFault traceback for running the documented command. Measured on
    # `units/t1-EXAMPLE-bs-greeks-pde`: relative -> exit 4, absolute -> the checks run.
    unit_dir = pathlib.Path(unit_dir).resolve()
    output_dir = pathlib.Path(output_dir).resolve()

    checks = unit_dir / "checks" / _CHECKS_ENTRY
    if not checks.is_file():
        # The checks are the unit's sealed grader, shipped in the organizer's reference tree. A
        # unit without them cannot judge anybody; until 2026-09-10 this returned
        # `trusted_checks="absent"` and g3 filed it as the participant's T1_WRONG_NUMERIC.
        # Deliberately no path in the message: a sealed unit id must not travel into an operator
        # log on an abort path.
        raise OrganizerFault(
            "the Track 1 scorer found no grader-owned checks file "
            f"(checks/{_CHECKS_ENTRY}) in the unit it was asked to score. A unit that ships no "
            "checks is organizer material; this is never a submission error."
        )

    # Can these checks be pointed at THIS output directory?
    #
    # In the unit's own container the agent's output really is at the path the checks name, so
    # a hardcoded `/app/output` is correct there. The platform scorer runs somewhere else: the
    # hub's score.py scores every unit with `output_dir = res/<unit>`. Measured across the public
    # Development units (2026-09-10): 39 of 87 resolve OUTPUT_DIR from the environment and 48
    # hardcode `/app/output`. Until this date the scorer refused the 48 as `not_redirectable`
    # and g3 charged the refusal to the participant, so on 48 units the verdict did not depend
    # on the submission. Now the output is presented at the path the checks name for the
    # duration of the run (`_present_output_at`); a checks file that reads neither OUTPUT_DIR
    # nor any bound path is genuinely non-executable here, and that is an organizer fault.
    source = checks.read_text(errors="replace")
    redirectable = bool(_REDIRECTABLE_RE.search(source))
    named = _static_output_paths(source)
    present_at = (
        [p for p in named if pathlib.Path(p) != output_dir] if not redirectable else []
    )
    if not redirectable and not named:
        raise OrganizerFault(
            "the Track 1 scorer cannot point this unit's checks at the submission's output: "
            "they read neither OUTPUT_DIR from the environment nor any path the harness binds "
            f"({', '.join(_PRESENTABLE_OUTPUT_PATHS)}). The unit's checks are organizer "
            "material; this is never a submission error."
        )

    # Before anything is read as a verdict: can the runner run at all? A scoring environment
    # without pytest cannot judge this submission, and must say so as an organizer fault rather
    # than returning a "failed" that is indistinguishable from a wrong answer.
    _require_test_runner()

    env = {**os.environ, "OUTPUT_DIR": str(output_dir), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        with (
            _present_inputs(unit_dir, source),
            tempfile.TemporaryDirectory(prefix="t1-checks-") as scratch,
            _present_output_at(present_at, output_dir),
        ):
            report_path = pathlib.Path(scratch) / "junit.xml"
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
                    f"--junitxml={report_path}",
                ],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=env,
                cwd=str(unit_dir),
            )
            counts: dict[str, int] = {}
            if proc.returncode not in _HARNESS_FAULT_EXIT_CODES:
                try:
                    cases = list(ET.parse(report_path).iter("testcase"))
                except (OSError, ET.ParseError) as exc:
                    raise OrganizerFault(
                        "the checker produced no readable test-count report"
                    ) from exc
                failed = sum(case.find("failure") is not None for case in cases)
                errored = sum(case.find("error") is not None for case in cases)
                skipped = sum(case.find("skipped") is not None for case in cases)
                counts = {
                    "checks_run": len(cases) - skipped,
                    "checks_passed": len(cases) - failed - errored - skipped,
                    "checks_failed": failed,
                    "checks_errored": errored,
                    "checks_skipped": skipped,
                }
    except _UnpresentableOutput as exc:
        # Nothing was presented and nothing ran: the tree the submission wrote cannot be copied
        # to the path its unit's checks read. Its content, its failure.
        return False, {
            "trusted_checks": "unpresentable_output",
            "reason": str(exc),
            "output_presented_at": [],
        }
    except subprocess.TimeoutExpired:
        return False, {"trusted_checks": "timeout", "timeout_sec": timeout_sec}
    except OSError as exc:
        # The scorer's own interpreter could not be launched. `_require_test_runner` already
        # treats that as ours; a launch that succeeded once and fails now is no less ours.
        raise OrganizerFault(
            f"the Track 1 scorer could not launch its test runner with {sys.executable}: {exc}. "
            "Organizer-side environment fault, never a submission error."
        ) from exc
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
    if proc.returncode == 5 or (proc.returncode == 0 and counts["checks_passed"] == 0):
        raise OrganizerFault(
            "the checker passed no tests; it cannot certify this submission"
        )
    return proc.returncode == 0, {
        "trusted_checks": "ran",
        "pytest_returncode": proc.returncode,
        **counts,
        "output_presented_at": present_at,
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
    if ctx.get("operator_sink") is not None:
        sink = pathlib.Path(ctx["operator_sink"])
        record = {
            "unit_handle": ctx.get("unit_handle", "local-preview"),
            "task_passed": trusted_ok,
            **{
                key: value
                for key, value in trusted.items()
                if key.startswith("checks_")
            },
        }
        try:
            sink.mkdir(parents=True, exist_ok=True)
            with (sink / "track1_checker_counts.jsonl").open(
                "a", encoding="utf-8"
            ) as output:
                output.write(json.dumps(record, allow_nan=False, sort_keys=True) + "\n")
        except OSError as exc:
            raise OrganizerFault(
                "the operator checker-count log is not writable"
            ) from exc

    if not trusted_ok and trusted.get("trusted_checks") != "ran":
        # The checks reached no verdict for a reason that is the submission's: they started but
        # did not finish (a timeout), or the output tree could not be presented at the path they
        # read (`unpresentable_output`: a special file or an unreadable entry in what the
        # submission wrote). Everything that could not execute for OUR reasons raises
        # OrganizerFault in `_run_trusted_checks` and scores nobody. A check that never reaches
        # a verdict is not evidence of correctness and must not be scored as though it were
        # (global rule 7: a gate that cannot run fails, never passes). It stays with the
        # submission because a pathological deliverable can make a grader hang, and waving that
        # through would be a free pass.
        return GateResult(
            passed=False,
            label=FailureLabel.T1_WRONG_NUMERIC,
            detail={
                "error": "trusted checks reached no verdict",
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


def scorer_identity() -> dict[str, str]:
    """The provenance block an entrypoint stamps onto its output.

    This is what a participant resolves when asking which revision scored them. It is deliberately
    small and stable: a name and a version, not a dump of internal configuration.
    """
    return {
        "scorer_package": "qfbench2_track_coding.scoring",
        "scorer_version": SCORER_VERSION,
    }
