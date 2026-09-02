"""Correctness must come from the grader's checks, never from the submission's own file.

`reward.json` is written by the submission's container. Until 2026-08-28 the gate chain read it and
admitted on its contents: measured on a real unit, an output directory containing nothing but
`{"reward": 1.0}` -- no solution, no deliverable, nothing executed -- was admitted with score 1.0,
identical to a genuinely correct submission. `checks_dir`, the documented "harness re-runs pytest"
path, appeared only in a docstring and was never read.

`reward.json` is OPTIONAL since 2026-09-02: it is written by `checks/test.sh`, and `checks/` is
stripped from every mounted tree, so a participant container normally cannot write it. Requiring
it at g1 made every real Track 1 submission inadmissible before the grader ran. It never decided
anything; now it is not needed either.
"""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from qfbench2_common.contracts import OrganizerFault

from qfbench2_track_coding import scoring
from qfbench2_track_coding.scoring import _g3_domain_semantics

CHECKS = textwrap.dedent(
    """
    import os, pathlib
    OUTPUT_DIR = pathlib.Path(os.environ.get("OUTPUT_DIR") or "/app/output")

    def test_deliverable():
        p = OUTPUT_DIR / "answer.txt"
        assert p.exists(), f"no deliverable at {p}"
        assert p.read_text().strip() == "42"
    """
)


@pytest.fixture
def unit(tmp_path: pathlib.Path) -> pathlib.Path:
    u = tmp_path / "unit"
    (u / "checks").mkdir(parents=True)
    (u / "checks" / "test_outputs.py").write_text(CHECKS, encoding="utf-8")
    (u / "card.toml").write_text('schema_version = "2.0"\n[task]\nsplit = "public-dev"\n', encoding="utf-8")
    (u / "manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    return u


def _verdict(unit: pathlib.Path, out: pathlib.Path):
    return _g3_domain_semantics({"unit_dir": str(unit), "output_dir": str(out)})


def _out(tmp_path: pathlib.Path, *, deliverable: str | None, reward) -> pathlib.Path:
    o = tmp_path / "out"
    o.mkdir(exist_ok=True)
    if deliverable is not None:
        (o / "answer.txt").write_text(deliverable, encoding="utf-8")
    if reward is not None:
        (o / "reward.json").write_text(
            reward if isinstance(reward, str) else json.dumps({"reward": reward}), encoding="utf-8"
        )
    return o


class TestTheSubmissionCannotScoreItself:
    def test_a_forged_reward_with_no_deliverable_is_refused(self, unit, tmp_path):
        """The bypass, as it was. This is the whole point of the file."""
        r = _verdict(unit, _out(tmp_path, deliverable=None, reward=1.0))
        assert not r.passed

    def test_a_forged_reward_over_a_wrong_deliverable_is_refused(self, unit, tmp_path):
        r = _verdict(unit, _out(tmp_path, deliverable="99", reward=1.0))
        assert not r.passed

    def test_a_correct_submission_that_under_reports_itself_still_passes(self, unit, tmp_path):
        """Admission comes from the checks, so the claim cannot lower it either."""
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=0.0))
        assert r.passed


class TestGenuineOutcomes:
    def test_a_genuinely_correct_submission_passes(self, unit, tmp_path):
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))
        assert r.passed
        assert r.detail["trusted_checks"] == "ran"

    def test_failed_checks_are_refused(self, unit, tmp_path):
        assert not _verdict(unit, _out(tmp_path, deliverable="wrong", reward=1.0)).passed

    def test_missing_output_is_refused(self, unit, tmp_path):
        o = tmp_path / "empty"
        o.mkdir()
        assert not _verdict(unit, o).passed

    def test_malformed_reward_json_is_refused(self, unit, tmp_path):
        assert not _verdict(unit, _out(tmp_path, deliverable="42", reward="NOT-JSON")).passed


class TestAGateThatCannotRunDoesNotPass:
    """Global rule 7: a required check that cannot execute fails, it never reports green."""

    def test_absent_checks_are_refused(self, unit, tmp_path):
        (unit / "checks" / "test_outputs.py").unlink()
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))
        assert not r.passed
        assert r.detail["trusted_checks"] == "absent"

    def test_checks_that_cannot_be_pointed_at_this_output_do_not_pass(self, unit, tmp_path):
        """A unit whose checks resolve their path statically can only be trusted in-container.
        Reporting a verdict from outside it would be a guess wearing a result's clothes."""
        (unit / "checks" / "test_outputs.py").write_text(
            'import pathlib\nOUTPUT_DIR = pathlib.Path("/app/output")\ndef test_x():\n    assert True\n',
            encoding="utf-8",
        )
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))
        assert not r.passed
        assert r.detail["trusted_checks"] == "not_redirectable"


class TestOurOwnBrokenEnvironmentIsNotChargedToTheSubmission:
    """Failing closed is right only while the fault could be the submission's.

    `_run_trusted_checks` shells out to ``{sys.executable} -m pytest``. Measured 2026-08-29 in a
    clean venv holding exactly this package's then-declared dependencies (`qfbench2-common` and
    nothing else, so no pytest), against unit `t1-option-put-call-parity-forward-audit` and a
    submission whose four deliverables pass that unit's own checks: `python -m pytest` exited
    **1** with "No module named pytest" -- pytest's own "tests failed" code -- and g3 returned
    ``passed=False``, ``trusted_checks="ran"``, ``T1_WRONG_NUMERIC``. Every Track 1 submission
    would have been scored zero and told its answer was wrong. `pyproject.toml` now declares the
    runner; these tests are what keeps an environment that cannot judge from judging anyway.
    """

    def _shim(self, tmp_path: pathlib.Path, script: str) -> str:
        shim = tmp_path / "fake-interpreter"
        shim.write_text(script, encoding="utf-8")
        shim.chmod(0o755)
        return str(shim)

    def test_no_importable_pytest_is_an_organizer_fault_not_a_wrong_answer(
        self, unit, tmp_path, monkeypatch
    ):
        """An interpreter that runs but cannot import pytest scores nobody."""
        monkeypatch.setattr(
            scoring.sys, "executable", self._shim(tmp_path, "#!/bin/sh\nexit 1\n")
        )
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))

    def test_an_interpreter_that_cannot_be_launched_is_an_organizer_fault(
        self, unit, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(scoring.sys, "executable", str(tmp_path / "no-such-interpreter"))
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))

    def test_a_pytest_usage_error_is_an_organizer_fault(self, unit, tmp_path):
        """Exit 4 means pytest rejected OUR argv and never looked at the submission.

        Planted here the way it happens in the field: an ini file in the unit directory --
        which is the scorer's cwd -- carrying an option this pytest does not have.
        """
        (unit / "pytest.ini").write_text(
            "[pytest]\naddopts = --this-flag-does-not-exist\n", encoding="utf-8"
        )
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))

    def test_the_same_unit_without_the_planted_ini_still_scores_normally(self, unit, tmp_path):
        """The negative control: none of the above fires on a healthy environment."""
        assert _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0)).passed
        assert not _verdict(unit, _out(tmp_path, deliverable="wrong", reward=1.0)).passed


class TestRewardJsonIsOptional:
    """The file g1 demanded is produced by the grader g3 runs; no participant can write it.

    Measured 2026-09-02 on the public scorer: `_g1_schema` returned SCHEMA_INVALID_OUTPUT for
    every output directory without `reward.json`, and `checks/` -- where `test.sh` writes it --
    is in the hub's STRIP_DIRS for coding. So a correct deliverable with no claim was refused at
    g1 on every real unit, indistinguishably from a wrong one.
    """

    def test_a_correct_deliverable_with_no_claim_is_admitted(self, unit, tmp_path):
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert r.passed, r.detail
        assert r.detail["trusted_checks"] == "ran"
        assert r.detail.get("claimed_reward") is None

    def test_a_wrong_deliverable_with_no_claim_is_still_refused(self, unit, tmp_path):
        assert not _verdict(unit, _out(tmp_path, deliverable="wrong", reward=None)).passed

    def test_g1_admits_deliverables_without_a_claim_and_refuses_an_empty_output(self, tmp_path):
        out = _out(tmp_path, deliverable="42", reward=None)
        g1 = scoring._g1_schema({"output_dir": str(out)})
        assert g1.passed, g1.detail
        assert g1.detail["deliverables"] == ["answer.txt"]
        empty = tmp_path / "empty"
        empty.mkdir()
        assert not scoring._g1_schema({"output_dir": str(empty)}).passed
        assert not scoring._g1_schema({"output_dir": str(tmp_path / "absent")}).passed

    def test_g1_still_refuses_a_malformed_or_out_of_range_claim(self, tmp_path):
        assert not scoring._g1_schema({"output_dir": str(_out(tmp_path, deliverable="42", reward="NOT-JSON"))}).passed
        assert not scoring._g1_schema({"output_dir": str(_out(tmp_path, deliverable="42", reward=0.5))}).passed
        assert scoring._g1_schema({"output_dir": str(_out(tmp_path, deliverable="42", reward=1.0))}).passed

    def test_a_claim_alone_is_not_a_deliverable(self, tmp_path):
        """`reward.json` and `pytest_report.json` are the grader's artifacts; an output that holds
        nothing else wrote nothing the checks could examine."""
        assert not scoring._g1_schema({"output_dir": str(_out(tmp_path, deliverable=None, reward=1.0))}).passed
