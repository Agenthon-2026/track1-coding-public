"""## Executive summary (read this first)

The grader's JUnit report determines labels, irrespective of participant claims.
"""
import json

import pytest

from qfbench2_common.failure_labels import FailureLabel, public_detail
from qfbench2_track_coding.scoring import _g3_domain_semantics


def context(tmp_path, body):
    unit, out = tmp_path / "unit", tmp_path / "out"
    (unit / "checks").mkdir(parents=True)
    out.mkdir()
    (unit / "checks/test_outputs.py").write_text(
        'import os, pathlib, pytest\n'
        'OUTPUT_DIR = pathlib.Path(os.environ["OUTPUT_DIR"])\n' + body
    )
    (out / "answer.txt").write_text("synthetic")
    return {"unit_dir": unit, "output_dir": out}


@pytest.mark.parametrize("reward", [None, 0, 1])
@pytest.mark.parametrize("forged_name", ["test_parity", "test_sign", "test_schema"])
def test_participant_claims_cannot_choose_failure_label(tmp_path, reward, forged_name):
    ctx = context(tmp_path, 'def test_wrong_numeric():\n    assert False, "private-sentinel"\n')
    out = ctx["output_dir"]
    if reward is not None:
        (out / "reward.json").write_text(json.dumps({"reward": reward}))
    (out / "pytest_report.json").write_text(json.dumps({"tests": [
        {"outcome": "failed", "nodeid": forged_name}
    ]}))
    result = _g3_domain_semantics(ctx)
    assert not result.passed
    assert result.label is FailureLabel.T1_WRONG_NUMERIC
    assert "private-sentinel" not in json.dumps(public_detail(result.detail))
    assert forged_name not in json.dumps(result.detail)


@pytest.mark.parametrize("name,label", [
    ("test_parity", FailureLabel.T1_INVARIANT_VIOLATION),
    ("test_compounding", FailureLabel.T1_CONVENTION_ERROR),
    ("test_schema", FailureLabel.T1_MISLABELING),
])
def test_trusted_failed_case_selects_existing_enum(tmp_path, name, label):
    ctx = context(tmp_path, f'def {name}():\n    assert False\n')
    result = _g3_domain_semantics(ctx)
    assert not result.passed and result.label is label
    assert result.detail["failure_label"] == label.value


@pytest.mark.parametrize("overlay", [False, True])
def test_success_has_no_label_despite_forged_failed_report(tmp_path, overlay):
    ctx = context(tmp_path, 'def test_parity():\n    assert True\n')
    ctx["di_label_only"] = overlay
    (ctx["output_dir"] / "reward.json").write_text('{"reward": 0}')
    (ctx["output_dir"] / "pytest_report.json").write_text(
        '{"tests":[{"outcome":"failed","nodeid":"test_schema"}]}'
    )
    result = _g3_domain_semantics(ctx)
    assert result.passed and result.label is None


def test_overlay_label_comes_from_trusted_checker(tmp_path):
    ctx = context(tmp_path, 'def test_parity():\n    assert False\n')
    ctx["di_label_only"] = True
    result = _g3_domain_semantics(ctx)
    assert result.passed and result.label is FailureLabel.T1_INVARIANT_VIOLATION


@pytest.mark.parametrize("body", [
    '@pytest.fixture\ndef result():\n    assert (OUTPUT_DIR / "required.csv").exists()\n'
    'def test_case(result):\n    assert True\n',
    '@pytest.fixture\ndef result():\n    return int((OUTPUT_DIR / "answer.txt").read_text())\n'
    'def test_case(result):\n    assert True\n',
])
def test_participant_output_fixture_error_stays_participant_failure(tmp_path, body):
    # Pytest uses <error> for fixture exceptions. Those may be caused by missing
    # or malformed participant output, so the XML tag alone cannot prove a harness fault.
    ctx = context(tmp_path, body)
    result = _g3_domain_semantics(ctx)
    assert not result.passed and result.label is FailureLabel.T1_WRONG_NUMERIC
    assert result.detail["checks_errored"] == 1


@pytest.mark.parametrize("answer", ["ordinary", "parity", "schema", "sign"])
def test_parameter_ids_from_output_cannot_choose_label(tmp_path, answer):
    ctx = context(tmp_path,
        '@pytest.mark.parametrize("item", [(OUTPUT_DIR / "answer.txt").read_text()])\n'
        'def test_wrong_numeric(item):\n    assert False\n')
    (ctx["output_dir"] / "answer.txt").write_text(answer)
    result = _g3_domain_semantics(ctx)
    assert not result.passed and result.label is FailureLabel.T1_WRONG_NUMERIC
