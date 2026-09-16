"""Organizer input mounts are restored between units, just like output mounts."""

import json

import pytest

from qfbench2_common.contracts import OrganizerFault
from qfbench2_track_coding import scoring


@pytest.mark.parametrize("relative", ["", "environment/data"])
def test_checker_reads_its_own_input_and_restores_mount(tmp_path, monkeypatch, relative):
    target = tmp_path / "mount"
    monkeypatch.setattr(scoring, "_INPUT_PATHS", {str(target): relative})
    for value in ("first", "second"):
        unit, output = tmp_path / value, tmp_path / f"out-{value}"
        (unit / "checks").mkdir(parents=True)
        data = unit / relative
        data.mkdir(parents=True, exist_ok=True)
        (data / "input.txt").write_text(value)
        output.mkdir()
        (output / "answer.txt").write_text(value)
        (unit / "checks/test_outputs.py").write_text(
            'import os, pathlib\n'
            'OUTPUT_DIR = pathlib.Path(os.environ["OUTPUT_DIR"])\n'
            f'INPUT_DIR = pathlib.Path({str(target)!r})\n'
            'def test_result():\n'
            '    assert (INPUT_DIR / "input.txt").read_text() == (OUTPUT_DIR / "answer.txt").read_text()\n'
        )
        passed, detail = scoring._run_trusted_checks(unit, output)
        assert passed, detail
        assert not target.exists()


def test_absent_organizer_data_is_not_a_wrong_answer(tmp_path, monkeypatch):
    target = tmp_path / "mount"
    monkeypatch.setattr(scoring, "_INPUT_PATHS", {str(target): "environment/data"})
    unit = tmp_path / "unit"
    (unit / "checks").mkdir(parents=True)
    (unit / "checks/test_outputs.py").write_text(
        'import os\nOUTPUT_DIR = os.environ["OUTPUT_DIR"]\n'
        f'INPUT = {str(target)!r}\ndef test_result():\n    assert isinstance(os.path.exists(INPUT), bool)\n'
    )
    with pytest.raises(OrganizerFault, match="organizer input"):
        scoring._run_trusted_checks(unit, tmp_path)


def test_populated_input_mount_is_not_overwritten(tmp_path, monkeypatch):
    target = tmp_path / "mount"
    target.mkdir()
    (target / "untouched").write_text("original")
    monkeypatch.setattr(scoring, "_INPUT_PATHS", {str(target): ""})
    with pytest.raises(OrganizerFault):
        with scoring._present_inputs(tmp_path, "open(" + json.dumps(str(target)) + ")"):
            pytest.fail("must not enter the checker")
    assert (target / "untouched").read_text() == "original"
