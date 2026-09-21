"""Synthetic public-path regression: execute real pytest checks, never task answers."""

import hashlib
import json

import pytest
from qfbench2_common.contracts import OrganizerFault
from qfbench2_track_coding import scoring


def reference_manifest(unit):
    files = [
        {"path": p.relative_to(unit).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in (unit / "checks/reference_data").iterdir() if p.is_file()
    ]
    (unit / "manifest.json").write_text(json.dumps({"files": files}))


def synthetic_unit(tmp_path, monkeypatch, *, reference=False, copy="COPY data/ /app/"):
    unit, output, mount = tmp_path / "unit", tmp_path / "out", tmp_path / "mount"
    (unit / "checks").mkdir(parents=True)
    (unit / "environment/data").mkdir(parents=True)
    output.mkdir()
    monkeypatch.setattr(scoring, "_INPUT_PATHS", {})
    monkeypatch.setattr(scoring, "_IMAGE_INPUT_ROOT", str(mount), raising=False)
    monkeypatch.setattr(
        scoring, "_REFERENCE_INPUT_ROOT", str(mount / "reference_data"), raising=False
    )
    (unit / "environment/Dockerfile").write_text(
        copy.replace("/app", str(mount)) + "\n"
    )
    if reference:
        data = unit / "checks/reference_data"
        data.mkdir()
        target = mount / "reference_data/params.txt"
    else:
        data = unit / "environment/data"
        target = mount / ("data/params.txt" if "/app/data/" in copy else "params.txt")
    (data / "params.txt").write_text("synthetic-value")
    if reference:
        reference_manifest(unit)
    (output / "answer.txt").write_text("synthetic-value")
    (unit / "checks/test_outputs.py").write_text(
        "import os, pathlib\n"
        'OUTPUT_DIR = pathlib.Path(os.environ["OUTPUT_DIR"])\n'
        f"INPUT = pathlib.Path({str(target)!r})\n"
        "def test_result():\n"
        '    assert INPUT.read_text() == (OUTPUT_DIR / "answer.txt").read_text()\n'
    )
    return unit, output, target


@pytest.mark.parametrize(
    "copy",
    [
        "COPY data/ /app/",
        "COPY data/params.txt /app/params.txt",
        "COPY data/ /app/data/",
    ],
)
def test_docker_input_paths_judge_correct_and_wrong_output(tmp_path, monkeypatch, copy):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch, copy=copy)
    passed, detail = scoring._run_trusted_checks(unit, output)
    assert passed, detail
    assert not target.exists()
    (output / "answer.txt").write_text("wrong")
    passed, detail = scoring._run_trusted_checks(unit, output)
    assert not passed and detail["checks_failed"] == 1, detail
    assert not target.exists()


def test_reference_path_is_presented_and_restored(tmp_path, monkeypatch):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch, reference=True)
    passed, detail = scoring._run_trusted_checks(unit, output)
    assert passed, detail
    assert not target.exists()


def test_missing_reference_is_organizer_fault_even_if_checker_would_ignore_it(
    tmp_path, monkeypatch
):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch, reference=True)
    (unit / "checks/reference_data/params.txt").unlink()
    (unit / "checks/reference_data").rmdir()
    (unit / "checks/test_outputs.py").write_text(
        'import os\nOUTPUT_DIR = os.environ["OUTPUT_DIR"]\n'
        f"INPUT = {str(target)!r}\ndef test_result():\n    assert isinstance(os.path.exists(INPUT), bool)\n"
    )
    with pytest.raises(OrganizerFault):
        scoring._run_trusted_checks(unit, output)


def test_preexisting_input_file_is_not_overwritten(tmp_path, monkeypatch):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch)
    target.parent.mkdir()
    target.write_text("operator-owned")
    with pytest.raises(OrganizerFault):
        scoring._run_trusted_checks(unit, output)
    assert target.read_text() == "operator-owned"


def test_unmapped_input_cannot_silently_produce_a_verdict(tmp_path, monkeypatch):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch)
    (unit / "environment/Dockerfile").write_text(
        "COPY --from=unavailable /params.txt /app/params.txt\n"
    )
    with pytest.raises(OrganizerFault, match="organizer input"):
        scoring._run_trusted_checks(unit, output)


def test_organizer_source_symlink_cannot_read_outside_unit(tmp_path, monkeypatch):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch)
    source = unit / "environment/data/params.txt"
    source.unlink()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    source.symlink_to(outside)
    with pytest.raises(OrganizerFault):
        scoring._run_trusted_checks(unit, output)
    assert not target.exists()


def test_organizer_input_destination_symlink_parent_is_refused(tmp_path, monkeypatch):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    target.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OrganizerFault):
        scoring._run_trusted_checks(unit, output)
    assert list(outside.iterdir()) == []


def test_source_read_error_restores_new_input_file(tmp_path, monkeypatch):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch)
    source = unit / "environment/data/params.txt"
    path_type = type(source)
    original_open = path_type.open

    def fail_source(path, *args, **kwargs):
        if path == source:
            raise PermissionError("synthetic read failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(path_type, "open", fail_source)
    with pytest.raises(OrganizerFault):
        with scoring._present_input_file(target, source):
            pytest.fail("unreadable source cannot enter checker")
    assert not target.exists()
    assert not target.parent.exists()


@pytest.mark.parametrize(
    "inert",
    [
        'REFERENCE_DIR = pathlib.Path("/tests/reference_data")',
        '"""/tests/reference_data"""',
        'def never_called():\n    """/tests/reference_data"""',
        'assert True, "/tests/reference_data"',
        'print("/tests/reference_data")',
        'if False:\n    raise ValueError("/tests/reference_data")',
    ],
)
def test_inert_reference_path_is_not_an_input_dependency(tmp_path, inert):
    unit, output = tmp_path / "unit", tmp_path / "out"
    (unit / "checks").mkdir(parents=True)
    output.mkdir()
    (output / "answer.txt").write_text("synthetic")
    (unit / "checks/test_outputs.py").write_text(
        "import os, pathlib\n"
        'OUTPUT_DIR = pathlib.Path(os.environ["OUTPUT_DIR"])\n' + inert + "\n"
        "def test_result():\n"
        '    assert (OUTPUT_DIR / "answer.txt").read_text() == "synthetic"\n'
    )
    passed, detail = scoring._run_trusted_checks(unit, output)
    assert passed, detail


def test_fstring_checks_real_reference_directory_not_literal_fragment(
    tmp_path, monkeypatch
):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch, reference=True)
    reference = unit / "checks/reference_data"
    (reference / "step_1.txt").write_text("synthetic-value")
    reference_manifest(unit)
    (unit / "checks/test_outputs.py").write_text(
        "import os, pathlib\n"
        'OUTPUT_DIR = pathlib.Path(os.environ["OUTPUT_DIR"])\n'
        "def test_result():\n"
        "    step = 1\n"
        f'    path = pathlib.Path(f"{target.parent}/step_{{step}}.txt")\n'
        '    assert path.read_text() == (OUTPUT_DIR / "answer.txt").read_text()\n'
    )
    passed, detail = scoring._run_trusted_checks(unit, output)
    assert passed, detail
    assert not target.parent.exists()
    (reference / "step_1.txt").unlink()
    (reference / "params.txt").unlink()
    reference.rmdir()
    with pytest.raises(OrganizerFault):
        scoring._run_trusted_checks(unit, output)


def test_external_dockerfile_is_not_read(tmp_path, monkeypatch):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch)
    dockerfile = unit / "environment/Dockerfile"
    dockerfile.unlink()
    outside = tmp_path / "outside-Dockerfile"
    outside.write_text("unrelated host material")
    dockerfile.symlink_to(outside)
    with pytest.raises(OrganizerFault, match="organizer input"):
        scoring._run_trusted_checks(unit, output)
    assert not target.exists()


def test_dockerfile_read_failure_does_not_expose_source_path(tmp_path, monkeypatch):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch)
    dockerfile = unit / "environment/Dockerfile"
    path_type = type(dockerfile)
    original_read = path_type.read_text

    def fail_dockerfile(path, *args, **kwargs):
        if path == dockerfile:
            raise PermissionError(13, "synthetic failure", str(dockerfile))
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(path_type, "read_text", fail_dockerfile)
    with pytest.raises(OrganizerFault) as caught:
        scoring._run_trusted_checks(unit, output)
    assert str(unit) not in str(caught.value)
    assert not target.exists()


@pytest.mark.parametrize("collision", ["populated", "symlink"])
def test_input_directory_fault_hides_unit_specific_destination(
    tmp_path, monkeypatch, collision
):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch, reference=True)
    sensitive_name = "SYNTHETIC_PRIVATE_DATASET_DIRECTORY"
    sensitive_target = target.parent.parent / sensitive_name
    monkeypatch.setattr(scoring, "_REFERENCE_INPUT_ROOT", str(sensitive_target))
    (unit / "checks/test_outputs.py").write_text(
        'import os, pathlib\nOUTPUT_DIR = os.environ["OUTPUT_DIR"]\n'
        f"INPUT = pathlib.Path({str(sensitive_target)!r})\n"
        'def test_result():\n    assert (INPUT / "params.txt").read_text()\n'
    )
    sensitive_target.parent.mkdir(parents=True)
    if collision == "symlink":
        sensitive_target.symlink_to(
            unit / "checks/reference_data", target_is_directory=True
        )
    else:
        sensitive_target.mkdir()
        (sensitive_target / "keep.txt").write_text("preexisting")
    with pytest.raises(OrganizerFault) as caught:
        scoring._run_trusted_checks(unit, output)
    assert sensitive_name not in str(caught.value)
    assert caught.value.__suppress_context__
    assert sensitive_target.exists()


def test_unused_read_result_still_requires_its_input(tmp_path, monkeypatch):
    unit, output, target = synthetic_unit(tmp_path, monkeypatch, reference=True)
    (unit / "checks/reference_data/params.txt").unlink()
    (unit / "checks/reference_data").rmdir()
    (unit / "checks/test_outputs.py").write_text(
        'import os, pathlib\nOUTPUT_DIR = os.environ["OUTPUT_DIR"]\n'
        f"UNUSED_RESULT = pathlib.Path({str(target)!r}).read_text()\n"
        "def test_result():\n    assert True\n"
    )
    with pytest.raises(OrganizerFault, match="organizer reference"):
        scoring._run_trusted_checks(unit, output)
