"""Count only the grader's run, not a participant-authored report."""

import json

import pytest

from qfbench2_common.contracts import OrganizerFault
from qfbench2_common.failure_labels import public_detail
from qfbench2_track_coding.scoring import build_verifier


def context(tmp_path, checks):
    unit, out = tmp_path / "unit", tmp_path / "out"
    (unit / "checks").mkdir(parents=True)
    out.mkdir()
    (unit / "card.toml").write_text('schema_version = "2.0"\n')
    (unit / "manifest.json").write_text('{"files": []}')
    (unit / "checks/test_outputs.py").write_text(
        'import os, pathlib, pytest\n'
        'OUTPUT_DIR = pathlib.Path(os.environ["OUTPUT_DIR"])\n' + checks
    )
    (out / "answer.txt").write_text("42")
    return {"unit_dir": unit, "output_dir": out, "unit_handle": "u-synthetic"}


def test_partial_tests_do_not_pass_the_task(tmp_path):
    ctx = context(tmp_path,
        'def test_good():\n    assert (OUTPUT_DIR / "answer.txt").read_text() == "42"\n'
        'def test_wrong():\n    assert False\n')
    sink = tmp_path / "operator"
    ctx["operator_sink"] = sink
    (ctx["output_dir"] / "pytest_report.json").write_text(
        '{"summary": {"passed": 999, "total": 999}}'
    )
    verdict = build_verifier(ctx).run(ctx)
    assert not verdict.admissible
    counts = json.loads((sink / "track1_checker_counts.jsonl").read_text())
    assert counts == {"unit_handle": "u-synthetic", "task_passed": False,
                      "checks_run": 2, "checks_passed": 1, "checks_failed": 1,
                      "checks_errored": 0, "checks_skipped": 0}
    assert "checks_passed" not in public_detail(counts)


def test_all_passed_and_skipped_are_counted_separately(tmp_path):
    ctx = context(tmp_path,
        'def test_good():\n    assert (OUTPUT_DIR / "answer.txt").read_text() == "42"\n'
        '@pytest.mark.skip(reason="synthetic")\ndef test_skip():\n    pass\n')
    ctx["operator_sink"] = tmp_path / "operator"
    verdict = build_verifier(ctx).run(ctx)
    assert verdict.admissible and verdict.score == 1.0
    counts = json.loads((ctx["operator_sink"] / "track1_checker_counts.jsonl").read_text())
    assert counts["checks_run"] == counts["checks_passed"] == 1
    assert counts["checks_skipped"] == 1


@pytest.mark.parametrize("checks", ["", '@pytest.mark.skip\ndef test_skip():\n    pass\n'])
def test_no_passing_tests_is_an_organizer_fault(tmp_path, checks):
    ctx = context(tmp_path, checks)
    with pytest.raises(OrganizerFault, match="passed no tests"):
        build_verifier(ctx).run(ctx)


@pytest.mark.parametrize("checks", [
    'def test_wrong():\n    assert False, "synthetic-private-diagnostic"\n',
    'def test_good():\n    print("synthetic-private-diagnostic"); assert True\n',
    'raise RuntimeError("synthetic-private-diagnostic")\n',
])
def test_private_capture_preserves_full_checker_output_and_junit(tmp_path, monkeypatch, checks):
    import sys
    from types import SimpleNamespace
    from qfbench2_track_coding import scoring
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    monkeypatch.setitem(sys.modules, "qfbench2_common.private_diagnostics",
                        SimpleNamespace(directory=lambda: root))
    ctx = context(tmp_path, checks)
    scoring._run_trusted_checks(ctx["unit_dir"], ctx["output_dir"])
    import hashlib
    target = root / (hashlib.sha256(ctx["unit_dir"].name.encode()).hexdigest() + "-checker")
    assert (target / "junit.xml").is_file()
    assert (target / "stdout.log").stat().st_size > 0
    assert json.loads((target / "status.json").read_text())["junit_present"]
    if "def test_good" in checks:
        assert "synthetic-private-diagnostic" in (target / "junit.xml").read_text()
    for path in target.iterdir():
        assert path.stat().st_mode & 0o077 == 0
    assert not list(ctx["output_dir"].glob("*.log"))


def test_private_timeout_preserves_partial_streams(tmp_path, monkeypatch):
    import subprocess
    import sys
    from types import SimpleNamespace
    from qfbench2_track_coding import scoring
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    monkeypatch.setitem(sys.modules, "qfbench2_common.private_diagnostics",
                        SimpleNamespace(directory=lambda: root))
    ctx = context(tmp_path, "def test_good():\n    assert True\n")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic-checker", 1, output=b"partial", stderr=b"error")
    monkeypatch.setattr(scoring, "_require_test_runner", lambda: None)
    monkeypatch.setattr(scoring.subprocess, "run", timeout)
    passed, detail = scoring._run_trusted_checks(ctx["unit_dir"], ctx["output_dir"])
    assert not passed and detail["trusted_checks"] == "timeout"
    import hashlib
    target = root / (hashlib.sha256(ctx["unit_dir"].name.encode()).hexdigest() + "-checker")
    assert (target / "stdout.log").read_bytes() == b"partial"
    status = json.loads((target / "status.json").read_text())
    assert status["timed_out"] and not status["junit_present"]


@pytest.mark.parametrize("helper_present", [False, True])
def test_no_private_context_preserves_participant_pytest_options(tmp_path, monkeypatch, helper_present):
    import sys
    from types import SimpleNamespace
    from qfbench2_track_coding import scoring
    monkeypatch.setitem(sys.modules, "qfbench2_common.private_diagnostics",
                        SimpleNamespace(directory=lambda: None) if helper_present else None)
    ctx = context(tmp_path, "def test_good():\n    assert True\n")
    original = scoring.subprocess.run
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return original(argv, **kwargs)
    monkeypatch.setattr(scoring.subprocess, "run", run)
    passed, detail = scoring._run_trusted_checks(ctx["unit_dir"], ctx["output_dir"])
    assert passed and detail["checks_passed"] == 1
    assert not any("junit_logging=all" in argv for argv in calls)
    assert not list(tmp_path.rglob("*-checker"))


@pytest.mark.parametrize("answer", [True, False])
def test_private_capture_does_not_change_admission_or_counts(tmp_path, monkeypatch, answer):
    import sys
    from types import SimpleNamespace
    from qfbench2_track_coding import scoring
    helper = SimpleNamespace(directory=lambda: None)
    monkeypatch.setitem(sys.modules, "qfbench2_common.private_diagnostics", helper)
    ctx = context(tmp_path, f"def test_answer():\n    assert {answer}\n")
    ctx["operator_sink"] = tmp_path / "counts"
    without = build_verifier(ctx).run(ctx)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    helper.directory = lambda: root
    with_capture = build_verifier(ctx).run(ctx)
    assert with_capture.admissible == without.admissible == answer
    assert with_capture.score == without.score
    counts = [json.loads(line) for line in
              (ctx["operator_sink"] / "track1_checker_counts.jsonl").read_text().splitlines()]
    assert len(counts) == 2 and counts[0] == counts[1]
    assert counts[0]["checks_run"] == 1
    assert counts[0]["checks_passed"] == int(answer)
    assert scoring._private_checker_root() == root
