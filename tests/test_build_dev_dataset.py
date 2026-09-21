"""Synthetic-only tests for explicit Development selection and artifact preservation."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_dev_dataset.py"
SPEC = importlib.util.spec_from_file_location("t1_dev_dataset_builder", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def unit(units: Path, name: str) -> Path:
    path = units / name
    path.mkdir(parents=True)
    (path / "card.toml").write_text(f'[task]\nid = "{name}"\n')
    (path / "instruction.md").write_text("Solve the synthetic example.\n")
    (path / "environment").mkdir()
    (path / "environment/input.txt").write_text("synthetic input: " + name)
    (path / "checks/reference_data").mkdir(parents=True)
    (path / "checks/reference_data/result.txt").write_bytes(b"synthetic answer bytes: " + name.encode())
    return path


def artifact(out: Path) -> dict[str, bytes]:
    for rel in ("ingestion/input/ref/old/input.json", "scoring/input/ref/old/result.json",
                "operator-metadata.txt"):
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"previous artifact {rel}\n")
    return snapshot(out)


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def assert_preserved(out: Path, previous: dict[str, bytes]) -> None:
    assert snapshot(out) == previous
    assert not list(out.parent.glob(f".{out.name}.build-*"))
    assert not list(out.parent.glob(f".{out.name}.previous-*"))


def test_explicit_order_excludes_unselected_directories_and_retains_metadata(tmp_path):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    unit(units, "b")
    (units / "unselected-without-card").mkdir()
    (units / "unselected-link").symlink_to(tmp_path, target_is_directory=True)
    previous = artifact(out)
    roster = tmp_path / "roster.txt"
    roster.write_text("# proposed only\nb\n\na\n")
    assert builder.build(units, out, builder.read_roster(roster)) == 0
    assert json.loads((out / "build-roster.json").read_text())["unit_handles"] == ["b", "a"]
    for branch in ("ingestion", "scoring"):
        assert {p.name for p in (out / branch / "input/ref").iterdir()} == {"a", "b"}
    assert not (out / "ingestion/input/ref/a/checks/reference_data/result.txt").exists()
    assert not (out / "ingestion/input/ref/a/checks").exists()
    assert (out / "ingestion/input/ref/a/environment/input.txt").read_text() == "synthetic input: a"
    assert (out / "scoring/input/ref/a/checks/reference_data/result.txt").read_bytes().startswith(b"synthetic")
    assert (out / "operator-metadata.txt").read_bytes() == previous["operator-metadata.txt"]


def test_default_keeps_sorted_all_directory_selection(tmp_path):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "b")
    unit(units, "a")
    (units / "README.txt").write_text("not a unit")
    builder.build(units, out)
    assert json.loads((out / "build-roster.json").read_text())["unit_handles"] == ["a", "b"]


@pytest.mark.parametrize("roster", [[], ["a", "a"], ["missing"], ["../a"], ["a/nested"],
                                    ["/a"], ["."], [".."], ["a\\nested"], [""], ["a b"]])
def test_bad_selection_fails_before_building_and_preserves_output(tmp_path, monkeypatch, roster):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    previous = artifact(out)
    monkeypatch.setattr(builder, "split_unit", lambda *args: pytest.fail("preflight was bypassed"))
    with pytest.raises(ValueError):
        builder.build(units, out, roster)
    assert_preserved(out, previous)


def test_unknown_later_unit_shape_refuses_before_any_copy(tmp_path, monkeypatch):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    unknown = unit(units, "b")
    (unknown / "unreviewed-inputs").mkdir()
    previous = artifact(out)
    monkeypatch.setattr(builder, "split_unit", lambda *args: pytest.fail("preflight was bypassed"))
    with pytest.raises(builder.AnswerLeak, match="unrecognised top-level"):
        builder.build(units, out, ["a", "b"])
    assert_preserved(out, previous)


def test_both_t1_answer_directories_are_stripped_and_retained_for_grader(tmp_path):
    units, out = tmp_path / "units", tmp_path / "out"
    selected = unit(units, "a")
    (selected / "reference").mkdir()
    (selected / "reference/synthetic-answer.txt").write_text("another synthetic answer")
    builder.build(units, out, ["a"])
    for directory in builder.T1_ANSWER_DIRS:
        assert not (out / "ingestion/input/ref/a" / directory).exists()
        assert (out / "scoring/input/ref/a" / directory).is_dir()


def test_duplicate_answer_bytes_count_as_distinct_files(tmp_path, capsys):
    units, out = tmp_path / "units", tmp_path / "out"
    selected = unit(units, "a")
    answer = selected / "checks/reference_data/result.txt"
    (selected / "checks/reference_data/duplicate.txt").write_bytes(answer.read_bytes())
    builder.build(units, out, ["a"])
    assert "answer files stripped from the mounted tree: 2" in capsys.readouterr().out
    grader = out / "scoring/input/ref/a/checks/reference_data"
    assert (grader / "result.txt").read_bytes() == (grader / "duplicate.txt").read_bytes()


@pytest.mark.parametrize("existing", [False, True])
def test_zero_answers_guard_preserves_prior_artifact(tmp_path, existing):
    units, out = tmp_path / "units", tmp_path / "out"
    selected = unit(units, "a")
    shutil.rmtree(selected / "checks")
    previous = artifact(out) if existing else {}
    with pytest.raises(ValueError, match="zero answer files stripped"):
        builder.build(units, out, ["a"])
    assert_preserved(out, previous)
    if not existing:
        assert not out.exists()


@pytest.mark.parametrize("damage", ["missing", "altered"])
def test_grader_answer_mismatch_preserves_prior_artifact(tmp_path, monkeypatch, damage):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    previous = artifact(out)
    real_split = builder.split_unit

    def damage_grader(source, ingestion, scoring, track):
        result = real_split(source, ingestion, scoring, track)
        answer = scoring / source.name / "checks/reference_data/result.txt"
        if damage == "missing":
            answer.unlink()
        else:
            answer.write_text("synthetic replacement")
        return result

    monkeypatch.setattr(builder, "split_unit", damage_grader)
    with pytest.raises(ValueError, match="grader answer paths or bytes differ"):
        builder.build(units, out, ["a"])
    assert_preserved(out, previous)


def test_t1_still_strips_checks_when_hub_declares_only_reference(tmp_path, monkeypatch):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    monkeypatch.setattr(builder, "answer_paths", lambda track: (("reference",), ()))

    def old_split(source, ingestion, scoring, track):
        shutil.copytree(source, ingestion / source.name)
        shutil.copytree(source, scoring / source.name)

    monkeypatch.setattr(builder, "split_unit", old_split)
    builder.build(units, out, ["a"])
    assert not (out / "ingestion/input/ref/a/checks").exists()
    assert (out / "scoring/input/ref/a/checks/reference_data/result.txt").is_file()


def test_t1_content_gate_still_catches_renamed_answer_with_older_hub(tmp_path, monkeypatch):
    units, out = tmp_path / "units", tmp_path / "out"
    selected = unit(units, "a")
    (selected / "environment/renamed.txt").write_bytes(
        (selected / "checks/reference_data/result.txt").read_bytes()
    )
    previous = artifact(out)
    monkeypatch.setattr(builder, "answer_paths", lambda track: (("reference",), ()))

    def old_split(source, ingestion, scoring, track):
        shutil.copytree(source, ingestion / source.name)
        shutil.copytree(source, scoring / source.name)

    monkeypatch.setattr(builder, "split_unit", old_split)
    with pytest.raises(builder.AnswerLeak, match="byte-identical"):
        builder.build(units, out, ["a"])
    assert_preserved(out, previous)


def test_later_missing_card_fails_before_any_unit_is_built(tmp_path, monkeypatch):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    (units / "b").mkdir()
    previous = artifact(out)
    monkeypatch.setattr(builder, "split_unit", lambda *args: pytest.fail("preflight was bypassed"))
    with pytest.raises(ValueError, match="card.toml"):
        builder.build(units, out, ["a", "b"])
    assert_preserved(out, previous)


@pytest.mark.parametrize("kind", ["unit", "card", "nested", "fifo"])
def test_unsafe_selected_source_fails_before_building(tmp_path, monkeypatch, kind):
    units, out = tmp_path / "units", tmp_path / "out"
    selected = unit(units, "a")
    if kind == "unit":
        selected.rename(units / "real")
        selected.symlink_to(units / "real", target_is_directory=True)
    elif kind == "card":
        (selected / "card.toml").rename(selected / "real-card.toml")
        (selected / "card.toml").symlink_to(selected / "real-card.toml")
    elif kind == "nested":
        (selected / "environment/nested").mkdir()
        (selected / "environment/nested/link").symlink_to(tmp_path / "missing")
    else:
        import os
        os.mkfifo(selected / "pipe")
    previous = artifact(out)
    monkeypatch.setattr(builder, "split_unit", lambda *args: pytest.fail("preflight was bypassed"))
    with pytest.raises(ValueError):
        builder.build(units, out, ["a"])
    assert_preserved(out, previous)


@pytest.mark.parametrize("kind", ["units", "out", "out-parent", "out-child"])
def test_symlink_locations_are_refused(tmp_path, kind):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    previous = artifact(out)
    actual_units, actual_out = units, out
    if kind == "units":
        actual_units = tmp_path / "units-link"
        actual_units.symlink_to(units, target_is_directory=True)
    elif kind == "out":
        actual_out = tmp_path / "out-link"
        actual_out.symlink_to(out, target_is_directory=True)
    elif kind == "out-parent":
        link = tmp_path / "parent-link"
        link.symlink_to(tmp_path, target_is_directory=True)
        actual_out = link / "out"
    else:
        (out / "unsafe").symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="symlink"):
        builder.build(actual_units, actual_out, ["a"])
    assert_preserved(out, previous)


@pytest.mark.parametrize("kind", ["same", "descendant", "ancestor"])
def test_input_output_overlap_preserves_input(tmp_path, kind):
    units = tmp_path / "units"
    unit(units, "a")
    out = {"same": units, "descendant": units / "artifact", "ancestor": tmp_path}[kind]
    previous = snapshot(units)
    with pytest.raises(ValueError, match="overlap"):
        builder.build(units, out, ["a"])
    assert snapshot(units) == previous


def test_real_leak_gate_on_later_unit_preserves_previous_artifact(tmp_path):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    leaking = unit(units, "b")
    (leaking / "environment/innocent-input.txt").write_bytes((leaking / "checks/reference_data/result.txt").read_bytes())
    previous = artifact(out)
    with pytest.raises(builder.AnswerLeak):
        builder.build(units, out, ["a", "b"])
    assert_preserved(out, previous)


def test_io_failure_after_first_unit_preserves_previous_artifact(tmp_path, monkeypatch):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    unit(units, "b")
    previous = artifact(out)
    real_split = builder.split_unit

    def fail_second(source, *args):
        if source.name == "b":
            raise OSError("synthetic disk failure")
        return real_split(source, *args)

    monkeypatch.setattr(builder, "split_unit", fail_second)
    with pytest.raises(OSError, match="synthetic disk failure"):
        builder.build(units, out, ["a", "b"])
    assert_preserved(out, previous)


def test_promotion_failure_restores_previous_artifact(tmp_path, monkeypatch):
    units, out = tmp_path / "units", tmp_path / "out"
    unit(units, "a")
    previous = artifact(out)
    real_rename = Path.rename

    def fail_candidate(path, target):
        if path.name.startswith(".out.build-"):
            raise OSError("synthetic promotion failure")
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_candidate)
    with pytest.raises(OSError, match="synthetic promotion failure"):
        builder.build(units, out, ["a"])
    assert_preserved(out, previous)


@pytest.mark.parametrize("kind", ["missing", "symlink", "directory"])
def test_roster_path_must_be_regular_file(tmp_path, kind):
    roster = tmp_path / "roster.txt"
    if kind == "symlink":
        roster.symlink_to(tmp_path / "missing")
    elif kind == "directory":
        roster.mkdir()
    with pytest.raises(ValueError):
        builder.read_roster(roster)


def test_cli_uses_roster_and_reports_leak_without_replacing_output(tmp_path, monkeypatch, capsys):
    units, out = tmp_path / "units", tmp_path / "out"
    leaking = unit(units, "a")
    (leaking / "environment/copied-answer.txt").write_bytes((leaking / "checks/reference_data/result.txt").read_bytes())
    previous = artifact(out)
    roster = tmp_path / "roster.txt"
    roster.write_text("a\n")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--units", str(units), "--out", str(out),
                                     "--roster", str(roster)])
    with pytest.raises(SystemExit) as raised:
        builder.main()
    assert raised.value.code == 1
    assert "LEAK GATE:" in capsys.readouterr().err
    assert_preserved(out, previous)
