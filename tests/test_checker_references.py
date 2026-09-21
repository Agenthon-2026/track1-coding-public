"""Organizer reference faults cannot admit wrong output or become participant zeros."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import shutil

import pytest

from qfbench2_common.contracts import OrganizerFault
from qfbench2_track_coding import checker_references, scoring
from qfbench2_track_coding.checker_references import validate_reference_inputs

ROOT = pathlib.Path(__file__).resolve().parents[1]


def manifest(unit):
    entries = [
        {
            "path": p.relative_to(unit).as_posix(),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "role": "reference",
            "redistributable": True,
        }
        for p in sorted((unit / "checks/reference_data").iterdir())
        if p.is_file()
    ]
    (unit / "manifest.json").write_text(json.dumps({"files": entries}))


@pytest.fixture
def generic_unit(tmp_path):
    unit, output = tmp_path / "unit", tmp_path / "output"
    refs = unit / "checks/reference_data"
    refs.mkdir(parents=True)
    output.mkdir()
    # Reuse the real shared grader implementation, with entirely synthetic reference values.
    shutil.copyfile(
        ROOT / "units/t1-bl-regime-hmm/checks/verifier.py", unit / "checks/verifier.py"
    )
    (unit / "checks/test_outputs.py").write_text(
        "import os, sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent))\n"
        "from verifier import run_verification\n"
        'OUTPUT_DIR = Path(os.environ["OUTPUT_DIR"])\n'
        "def test_reference():\n"
        '    assert run_verification(OUTPUT_DIR, Path(__file__).parent / "reference_data", '
        'OUTPUT_DIR.parent / "logs") == "PERFECT"\n'
    )
    documents = {
        "expected.json": {
            "deliverables": [
                {
                    "name": "synthetic_total",
                    "path": "results.json:synthetic_total",
                    "value": 7,
                    "tolerance": {"atol": 0},
                }
            ]
        },
        "checkpoints.json": {
            "checkpoints": {
                "synthetic_step": {
                    "value": 3,
                    "concept": "",
                    "domain": "",
                    "tolerance": {"atol": 0},
                }
            }
        },
        "concept_graph.json": {"nodes": ["synthetic_node"], "edges": []},
        "bridges.json": {"bridges": []},
    }
    for name, value in documents.items():
        (refs / name).write_text(json.dumps(value))
    (unit / "card.toml").write_text(
        'schema_version = "2.0"\n[task]\nsplit = "public-dev"\n'
    )
    (output / "results.json").write_text('{"synthetic_total": 7}')
    (output / "solution.json").write_text(
        '{"intermediates": {"synthetic_step": {"value": 3}}}'
    )
    manifest(unit)
    return unit, output


def verdict(unit, output):
    ctx = {
        "unit_dir": unit,
        "output_dir": output,
        "canary_registry": set(),
        "elapsed_sec": 0.0,
        "agent_timeout_sec": 30.0,
    }
    return scoring.build_verifier(ctx).run(ctx)


def output_variant(output, variant):
    if variant == "wrong":
        (output / "results.json").write_text('{"synthetic_total": -500}')
    elif variant == "malformed":
        (output / "results.json").write_text("not-json")
    elif variant == "empty":
        for p in output.iterdir():
            p.unlink()


@pytest.fixture
def plain_manifest_unit(tmp_path):
    """A plain pytest unit has no reference_data guard to parse its root manifest."""
    unit, output = tmp_path / "plain-unit", tmp_path / "plain-output"
    (unit / "checks").mkdir(parents=True)
    (unit / "environment/data").mkdir(parents=True)
    output.mkdir()
    (unit / "checks/test_outputs.py").write_text(
        "import os\nfrom pathlib import Path\n"
        'OUTPUT_DIR = Path(os.environ["OUTPUT_DIR"])\n'
        "def test_synthetic_deliverable():\n"
        '    assert (OUTPUT_DIR / "answer.txt").read_text() == "synthetic correct"\n'
    )
    (unit / "card.toml").write_text('schema_version = "2.0"\n')
    source = unit / "environment/data/input.txt"
    source.write_text("Synthetic organizer input.\n")
    (unit / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "environment/data/input.txt",
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "role": "input",
                        "redistributable": True,
                    }
                ]
            }
        )
    )
    (output / "answer.txt").write_text("synthetic correct")
    return unit, output


@pytest.mark.parametrize(
    "corruption",
    [
        "malformed_json",
        "nested_json",
        "invalid_utf8",
        "null",
        "number",
        "array",
        "array_with_files",
        "missing_files",
        "wrong_files_type",
        "missing",
        "unreadable",
        "checksum",
        "missing_manifested_input",
    ],
)
def test_plain_organizer_manifest_fault_is_not_participant_output(
    plain_manifest_unit, monkeypatch, corruption
):
    unit, output = plain_manifest_unit
    path = unit / "manifest.json"
    raw = {
        "malformed_json": b"{synthetic sealed diagnostic must not escape",
        "nested_json": b"[" * 5000 + b"0" + b"]" * 5000,
        "invalid_utf8": b"\xff",
        "null": b"null",
        "number": b"42",
        "array": b"[]",
        "array_with_files": b'["files"]',
        "missing_files": b"{}",
        "wrong_files_type": b'{"files": null}',
    }
    if corruption in raw:
        path.write_bytes(raw[corruption])
    elif corruption == "missing":
        path.unlink()
    elif corruption == "unreadable":
        original = pathlib.Path.read_text

        def read(candidate, *args, **kwargs):
            if candidate == path:
                raise PermissionError("synthetic sealed diagnostic must not escape")
            return original(candidate, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, "read_text", read)
    else:
        data = unit / "environment/data/input.txt"
        if corruption == "checksum":
            data.write_text("Changed organizer input; participant bytes untouched.\n")
        else:
            data.unlink()
        # Observe the genuine canonical returned-error path, not a parser stub.
        assert scoring.verify_manifest(unit)
    with pytest.raises(OrganizerFault, match="organizer manifest") as caught:
        verdict(unit, output)
    assert "synthetic sealed diagnostic" not in str(caught.value)
    assert (output / "answer.txt").read_text() == "synthetic correct"


@pytest.mark.parametrize("variant", ["correct", "wrong", "malformed_reward", "empty"])
def test_plain_valid_manifest_keeps_participant_verdicts(plain_manifest_unit, variant):
    unit, output = plain_manifest_unit
    if variant == "wrong":
        (output / "answer.txt").write_text("synthetic wrong")
    elif variant == "malformed_reward":
        (output / "reward.json").write_text("{malformed participant json")
    elif variant == "empty":
        (output / "answer.txt").unlink()
    result = verdict(unit, output)
    assert result.admissible is (variant == "correct")


def test_manifest_boundary_does_not_capture_participant_parser_errors(
    plain_manifest_unit, monkeypatch
):
    unit, output = plain_manifest_unit

    def participant_parser(ctx):
        raise ValueError("synthetic participant parsing exception")

    monkeypatch.setattr(scoring, "_g1_schema", participant_parser)
    with pytest.raises(ValueError, match="participant parsing exception"):
        verdict(unit, output)


def test_real_generic_grader_good_output_passes(generic_unit):
    unit, output = generic_unit
    assert verdict(unit, output).admissible


@pytest.mark.parametrize("field", ["rtol", "atol"])
@pytest.mark.parametrize("sign", [1, -1])
def test_large_integer_tolerance_preserves_actual_grader_semantics(
    generic_unit, field, sign
):
    unit, output = generic_unit
    path = unit / "checks/reference_data/expected.json"
    reference = json.loads(path.read_text())
    reference["deliverables"][0]["tolerance"] = {field: sign * 10**400}
    path.write_text(json.dumps(reference))
    manifest(unit)
    if sign > 0:
        passed, detail = scoring._execute_trusted_checks(unit, output, 30.0)
        assert passed and detail["checks_run"] == 1
        assert verdict(unit, output).admissible
    else:
        with pytest.raises(OrganizerFault, match="organizer reference"):
            verdict(unit, output)


@pytest.mark.parametrize("corruption", ["missing", "malformed", "whole_directory"])
def test_missing_checker_does_not_hide_organizer_reference_faults(
    generic_unit, corruption
):
    unit, output = generic_unit
    (unit / "checks/test_outputs.py").unlink()
    reference = unit / "checks/reference_data/expected.json"
    if corruption == "missing":
        reference.unlink()
    elif corruption == "malformed":
        reference.write_text("not-json")
        manifest(unit)
        output_variant(output, "empty")
    else:
        shutil.rmtree(unit / "checks")
    with pytest.raises(OrganizerFault, match="no grader-owned checks"):
        verdict(unit, output)


@pytest.mark.parametrize("entrypoint", ["outer", "direct"])
def test_non_utf8_checker_is_an_organizer_fault(generic_unit, entrypoint):
    unit, output = generic_unit
    (unit / "checks/test_outputs.py").write_bytes(b"\xff")
    with pytest.raises(OrganizerFault, match="organizer checks are unreadable"):
        if entrypoint == "outer":
            verdict(unit, output)
        else:
            scoring._run_trusted_checks(unit, output)


def test_relative_unit_path_stays_bound_when_working_directory_changes(
    generic_unit, monkeypatch, tmp_path
):
    unit, output = generic_unit
    monkeypatch.chdir(unit.parent)
    other = tmp_path / "other-working-directory"
    other.mkdir()
    integrity = scoring._g0_integrity

    def change_working_directory(ctx):
        result = integrity(ctx)
        monkeypatch.chdir(other)
        return result

    monkeypatch.setattr(scoring, "_g0_integrity", change_working_directory)
    ctx = {
        "unit_dir": unit.name,
        "output_dir": output,
        "canary_registry": set(),
        "elapsed_sec": 0.0,
        "agent_timeout_sec": 30.0,
    }
    assert scoring.build_verifier(ctx).run(ctx).admissible
    assert ctx["unit_dir"] == unit.name


@pytest.mark.parametrize("variant", ["wrong", "malformed", "empty"])
def test_participant_failures_still_receive_a_verdict(generic_unit, variant):
    unit, output = generic_unit
    output_variant(output, variant)
    assert not verdict(unit, output).admissible
    passed, detail = scoring._run_trusted_checks(unit, output)
    assert not passed and detail["checks_run"] == 1


@pytest.mark.parametrize("variant", ["good", "wrong", "empty"])
@pytest.mark.parametrize(
    "corruption", ["missing", "malformed", "empty", "array", "missing_deliverables"]
)
def test_reference_failure_precedes_participant_output(
    generic_unit, monkeypatch, variant, corruption
):
    unit, output = generic_unit
    output_variant(output, variant)
    reference = unit / "checks/reference_data/expected.json"
    if corruption == "missing":
        reference.unlink()
    else:
        reference.write_text(
            {
                "malformed": "{not-json",
                "empty": "{}",
                "array": "[]",
                "missing_deliverables": '{"meta": {}}',
            }[corruption]
        )
        # Authoring errors must also fail when checksums were regenerated around them.
        manifest(unit)
    monkeypatch.setattr(
        scoring, "_require_test_runner", lambda: pytest.fail("pytest must not launch")
    )
    with pytest.raises(OrganizerFault, match="organizer reference") as caught:
        verdict(unit, output)
    assert str(unit) not in str(caught.value)
    assert "expected.json" not in str(caught.value)
    with pytest.raises(OrganizerFault, match="organizer reference"):
        scoring._run_trusted_checks(unit, output)


@pytest.mark.parametrize(
    "filename,value",
    [
        ("expected.json", {"deliverables": []}),
        ("expected.json", {"deliverables": [None]}),
        ("expected.json", {"deliverables": [{"name": "x", "path": "results.json:x"}]}),
        (
            "expected.json",
            {
                "deliverables": [
                    {"name": "x", "value": 1, "path": "results.json:x", "tolerance": []}
                ]
            },
        ),
        (
            "expected.json",
            {
                "deliverables": [
                    {
                        "name": "x",
                        "value": 1,
                        "path": "results.json:x",
                        "tolerance": {"atol": -1},
                    }
                ]
            },
        ),
        (
            "expected.json",
            {
                "deliverables": [
                    {
                        "name": "x",
                        "value": 1,
                        "path": "results.json:x",
                        "tolerance": {"rtol": True},
                    }
                ]
            },
        ),
        (
            "expected.json",
            {"deliverables": [{"name": "x", "value": 1, "path": "../results.json:x"}]},
        ),
        ("checkpoints.json", {"checkpoints": {}}),
        ("checkpoints.json", {"checkpoints": {"x": {}}}),
        ("checkpoints.json", {"checkpoints": {"x": {"value": 1, "siblings": []}}}),
        ("concept_graph.json", {"nodes": [], "edges": []}),
        ("concept_graph.json", {"nodes": ["x"], "edges": [{"from": "x"}]}),
        ("bridges.json", {"bridges": [{"from_node": "x"}]}),
        ("alt_paths.json", {"paths": []}),
        (
            "alt_paths.json",
            {"paths": [{"name": "x", "deliverables": [], "checkpoints": {}}]},
        ),
    ],
)
def test_structurally_invalid_reference_is_organizer_fault(
    generic_unit, filename, value
):
    unit, output = generic_unit
    (unit / "checks/reference_data" / filename).write_text(json.dumps(value))
    manifest(unit)
    with pytest.raises(OrganizerFault, match="organizer reference"):
        verdict(unit, output)


def test_alternative_convention_remains_supported(generic_unit):
    unit, output = generic_unit
    refs = unit / "checks/reference_data"
    expected = json.loads((refs / "expected.json").read_text())["deliverables"]
    checkpoints = json.loads((refs / "checkpoints.json").read_text())["checkpoints"]
    alternate_expected, alternate_checkpoints = (
        copy.deepcopy(expected),
        copy.deepcopy(checkpoints),
    )
    alternate_expected[0]["value"] = 9
    alternate_checkpoints["synthetic_step"]["value"] = 5
    (refs / "alt_paths.json").write_text(
        json.dumps(
            {
                "paths": [
                    {
                        "name": "original",
                        "deliverables": expected,
                        "checkpoints": checkpoints,
                    },
                    {
                        "name": "alternative",
                        "deliverables": alternate_expected,
                        "checkpoints": alternate_checkpoints,
                    },
                ]
            }
        )
    )
    manifest(unit)
    (output / "results.json").write_text('{"synthetic_total": 9}')
    (output / "solution.json").write_text(
        '{"intermediates": {"synthetic_step": {"value": 5}}}'
    )
    assert verdict(unit, output).admissible
    (refs / "alt_paths.json").unlink()
    with pytest.raises(OrganizerFault, match="organizer reference"):
        verdict(unit, output)


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "unlisted",
        "unmanifested",
        "nonredistributable_missing",
        "duplicate_keys",
    ],
)
def test_reference_manifest_is_required_and_exact(generic_unit, change):
    unit, output = generic_unit
    refs = unit / "checks/reference_data"
    path = unit / "manifest.json"
    data = json.loads(path.read_text())
    if change == "hash":
        (refs / "expected.json").write_text((refs / "expected.json").read_text() + "\n")
    elif change == "unlisted":
        data["files"] = [
            r for r in data["files"] if not r["path"].endswith("expected.json")
        ]
    elif change == "unmanifested":
        (refs / "extra.json").write_text('{"synthetic": true}')
    elif change == "nonredistributable_missing":
        data["files"][0]["redistributable"] = False
        (unit / data["files"][0]["path"]).unlink()
    else:
        (refs / "expected.json").write_text('{"deliverables": [], "deliverables": []}')
        manifest(unit)
        data = json.loads(path.read_text())
    path.write_text(json.dumps(data))
    with pytest.raises(OrganizerFault, match="organizer reference"):
        verdict(unit, output)


@pytest.mark.parametrize("link", ["file", "directory", "hardlink"])
def test_reference_links_are_refused(generic_unit, tmp_path, link):
    unit, output = generic_unit
    refs = unit / "checks/reference_data"
    if link == "directory":
        target = tmp_path / "original-reference"
        refs.rename(target)
        refs.symlink_to(target, target_is_directory=True)
    else:
        path = refs / "expected.json"
        target = tmp_path / "original-reference.json"
        path.rename(target)
        if link == "file":
            path.symlink_to(target)
        else:
            path.hardlink_to(target)
    with pytest.raises(OrganizerFault, match="organizer reference"):
        verdict(unit, output)


@pytest.mark.parametrize("payload", ["x,x\n1,2\n", "x,y\n1\n", 'x\n"unterminated', ""])
def test_bad_reference_csv_is_organizer_fault(generic_unit, payload):
    unit, output = generic_unit
    (unit / "checks/reference_data/table.csv").write_text(payload)
    manifest(unit)
    with pytest.raises(OrganizerFault, match="organizer reference"):
        verdict(unit, output)


def test_raw_expected_object_is_not_misclassified_by_participant_deliverables_key(
    generic_unit,
):
    unit, _ = generic_unit
    refs = unit / "checks/reference_data"
    for p in refs.iterdir():
        p.unlink()
    (refs / "expected.json").write_text('{"synthetic_scalar": 5}')
    manifest(unit)
    source = 'result = {"deliverables": []}\nvalue = result["deliverables"]\n'
    validate_reference_inputs(unit, source, required=True)


@pytest.mark.parametrize("format_name", ["deliverables", "checkpoints"])
def test_explicit_direct_reference_schema_is_enforced(generic_unit, format_name):
    unit, _ = generic_unit
    source = 'T1_REFERENCE_FORMATS = {"expected.json": ' + repr(format_name) + "}\n"
    (unit / "checks/reference_data/expected.json").write_text('{"other": true}')
    manifest(unit)
    with pytest.raises(OrganizerFault, match="organizer reference"):
        validate_reference_inputs(unit, source, required=False)


def test_all_current_public_reference_formats_pass_preflight():
    units = sorted((ROOT / "units").glob("*/card.toml"))
    assert len(units) == 87
    for card in units:
        scoring._preflight_reference_inputs(card.parent)


def test_participant_fixture_errors_remain_participant_failures(generic_unit):
    unit, output = generic_unit
    (unit / "checks/test_outputs.py").write_text(
        'import os, pathlib, pytest\nOUTPUT_DIR = pathlib.Path(os.environ["OUTPUT_DIR"])\n'
        '@pytest.fixture\ndef participant_data():\n    return (OUTPUT_DIR / "absent.json").read_text()\n'
        "def test_output(participant_data):\n    assert participant_data\n"
    )
    result = verdict(unit, output)
    assert not result.admissible
    passed, detail = scoring._run_trusted_checks(unit, output)
    assert not passed and detail["checks_errored"] == 1


def change_reference(unit, mutation):
    path = unit / "checks/reference_data/expected.json"
    original = path.read_bytes()
    if mutation == "remove":
        path.unlink()
    elif mutation == "malformed":
        path.write_text("{not-json")
    elif mutation == "replace_same_bytes":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(original)
        replacement.replace(path)
    elif mutation == "rewrite_and_restore":
        path.write_text("{not-json")
        path.write_bytes(original)
    elif mutation == "manifest_only":
        manifest(unit)
    elif mutation == "replace_checks_and_restore":
        checks = unit / "checks"
        moved = unit / "moved-checks"
        checks.rename(moved)
        moved.rename(checks)
    else:
        expected = json.loads(original)
        expected["deliverables"][0]["value"] = -500
        path.write_text(json.dumps(expected))
        if mutation == "reference_and_manifest":
            manifest(unit)
        else:
            assert mutation == "valid_reference"


@pytest.mark.parametrize("method", ["direct", "outer"])
@pytest.mark.parametrize(
    "mutation",
    [
        "remove",
        "malformed",
        "valid_reference",
        "reference_and_manifest",
        "replace_same_bytes",
        "rewrite_and_restore",
        "manifest_only",
        "replace_checks_and_restore",
    ],
)
def test_changed_references_cannot_release_actual_pytest_verdict(
    generic_unit, monkeypatch, method, mutation
):
    unit, output = generic_unit
    output_variant(output, "wrong")
    require_runner = scoring._require_test_runner
    execute = scoring._execute_trusted_checks
    observed = []

    def change_after_preflight():
        change_reference(unit, mutation)
        require_runner()

    def observe_actual_checks(*args):
        result = execute(*args)
        observed.append(result)
        return result

    monkeypatch.setattr(scoring, "_require_test_runner", change_after_preflight)
    monkeypatch.setattr(scoring, "_execute_trusted_checks", observe_actual_checks)
    with pytest.raises(OrganizerFault, match="organizer reference"):
        if method == "direct":
            scoring._run_trusted_checks(unit, output)
        else:
            verdict(unit, output)
    assert len(observed) == 1 and observed[0][1]["checks_run"] == 1
    if mutation in {"remove", "malformed", "valid_reference", "reference_and_manifest"}:
        # Real generic pytest would accept the wrong answer after these changes. The
        # bound-reference guard must intercept that result, rather than trusting it.
        assert observed[0][0]


@pytest.mark.parametrize("variant", ["wrong", "empty"])
def test_outer_binding_survives_new_matching_manifest_between_gates(
    generic_unit, monkeypatch, variant
):
    unit, output = generic_unit
    output_variant(output, variant)
    gate = scoring._g1_schema

    def change_between_gates(ctx):
        result = gate(ctx)
        change_reference(unit, "reference_and_manifest")
        return result

    monkeypatch.setattr(scoring, "_g1_schema", change_between_gates)
    with pytest.raises(OrganizerFault, match="organizer reference"):
        verdict(unit, output)


def test_reference_binding_precedes_checksum_validation(generic_unit, monkeypatch):
    unit, output = generic_unit
    verify = checker_references.verify_manifest

    def change_after_checksum(*args):
        result = verify(*args)
        change_reference(unit, "reference_and_manifest")
        return result

    monkeypatch.setattr(checker_references, "verify_manifest", change_after_checksum)
    monkeypatch.setattr(
        scoring, "_require_test_runner", lambda: pytest.fail("pytest must not launch")
    )
    with pytest.raises(OrganizerFault, match="organizer reference"):
        verdict(unit, output)


@pytest.mark.parametrize("failure", ["timeout", "fixture_error"])
def test_reference_changes_override_actual_checker_timeout_and_fixture_error(
    generic_unit, failure
):
    unit, output = generic_unit
    behavior = (
        "time.sleep(20)" if failure == "timeout" else "raise ValueError('synthetic')"
    )
    (unit / "checks/test_outputs.py").write_text(
        "import os, pathlib, pytest, time\n"
        'OUTPUT_DIR = pathlib.Path(os.environ["OUTPUT_DIR"])\n'
        "@pytest.fixture\ndef changed_reference():\n"
        '    (pathlib.Path(__file__).parent / "reference_data/expected.json").unlink()\n'
        f"    {behavior}\n"
        "def test_output(changed_reference):\n    assert False\n"
    )
    with pytest.raises(OrganizerFault, match="organizer reference"):
        scoring._run_trusted_checks(unit, output, timeout_sec=2.0)
    assert not (unit / "checks/reference_data/expected.json").exists()


def test_reference_change_during_score_cannot_release_outer_verdict(
    generic_unit, monkeypatch
):
    unit, output = generic_unit
    scorer = scoring._t1_scorer

    def change_during_score(ctx):
        change_reference(unit, "reference_and_manifest")
        return scorer(ctx)

    monkeypatch.setattr(scoring, "_t1_scorer", change_during_score)
    with pytest.raises(OrganizerFault, match="organizer reference"):
        verdict(unit, output)
