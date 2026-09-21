"""Validate organizer reference inputs before a participant can receive a verdict.

Reference values stay in the unit. This module validates their envelope and the shared
multi-phase grader's input schemas; it does not calculate or compare participant answers.
"""

from __future__ import annotations

import ast
import contextlib
import csv
import io
import json
import math
import os
import pathlib
import stat
from collections.abc import Iterator
from typing import Any, cast

from qfbench2_common.contracts import OrganizerFault
from qfbench2_common.manifest import verify_manifest
from qfbench2_common.sanitize import hash_regular_file

_REFERENCE = "checks/reference_data"
_FAULT = "the Track 1 unit has invalid organizer reference inputs"
_Binding = tuple[tuple[str, tuple[int, ...], str], ...]


def _require(condition: bool) -> None:
    if not condition:
        # Neither unit identities, field names nor reference values belong in an abort log.
        raise OrganizerFault(_FAULT)


def _identity(value: os.stat_result, *, content: bool = True) -> tuple[int, ...]:
    identity = (value.st_dev, value.st_ino, value.st_mode, value.st_ctime_ns)
    return identity + (
        (value.st_nlink, value.st_size, value.st_mtime_ns) if content else ()
    )


def _file_binding(parent: int, name: str) -> tuple[tuple[int, ...], str]:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    fd = os.open(name, flags, dir_fd=parent)
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1)
        digest, size = hash_regular_file(fd)
        _require(
            size == before.st_size and _identity(os.fstat(fd)) == _identity(before)
        )
        _require(
            _identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
            == _identity(before)
        )
        return _identity(before), digest
    finally:
        os.close(fd)


def _directory_binding(fd: int, prefix: str) -> _Binding:
    before = _identity(os.fstat(fd))
    rows = [(prefix, before, "")]
    for name in sorted(os.listdir(fd)):
        path = prefix + "/" + name
        entry = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(entry.st_mode):
            child = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_DIRECTORY,
                dir_fd=fd,
            )
            try:
                _require(_identity(os.fstat(child)) == _identity(entry))
                rows.extend(_directory_binding(child, path))
                _require(
                    _identity(os.stat(name, dir_fd=fd, follow_symlinks=False))
                    == _identity(os.fstat(child))
                )
            finally:
                os.close(child)
        else:
            identity, digest = _file_binding(fd, name)
            rows.append((path, identity, digest))
    _require(_identity(os.fstat(fd)) == before)
    return tuple(rows)


def _reference_binding(unit_dir: pathlib.Path) -> _Binding:
    """Bind only the reference tree and its manifest, without following replaced nodes.

    Hashes bind bytes; inode/timestamp identities also refuse a replace-and-restore or
    rewrite-and-restore during grading. Parent directory identities bind path resolution,
    including parent replacement and restoration. Other input/output file contents are
    outside this reference-only guard.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_DIRECTORY
    try:
        with contextlib.ExitStack() as stack:
            root = os.open(unit_dir, flags)
            stack.callback(os.close, root)
            checks = os.open("checks", flags, dir_fd=root)
            stack.callback(os.close, checks)
            reference = os.open("reference_data", flags, dir_fd=checks)
            stack.callback(os.close, reference)
            identity, digest = _file_binding(root, "manifest.json")
            binding = (
                (".", _identity(os.fstat(root), content=False), ""),
                ("checks", _identity(os.fstat(checks), content=False), ""),
                ("manifest.json", identity, digest),
                *_directory_binding(reference, _REFERENCE),
            )
        return binding
    except OSError:
        raise OrganizerFault(_FAULT) from None


@contextlib.contextmanager
def reference_input_guard(
    unit_dir: pathlib.Path, source: str, *, required: bool
) -> Iterator[None]:
    """Keep the initially validated references bound until a verdict is ready.

    The final check runs for successful grading, participant failures, timeouts, and
    exceptions. It compares the original binding, never a newly trusted manifest/payload
    pair. A second preflight alone would allow both to be replaced together.
    """
    reference = unit_dir / _REFERENCE
    generic, formats = _grader_shape(source)
    if not (
        required or generic or formats or reference.exists() or reference.is_symlink()
    ):
        yield
        return
    binding = _reference_binding(unit_dir)
    validate_reference_inputs(unit_dir, source, required=required)
    _require(_reference_binding(unit_dir) == binding)
    try:
        yield
    finally:
        _require(_reference_binding(unit_dir) == binding)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes(), object_pairs_hook=_object)
    _require(isinstance(value, dict) and bool(value))
    return cast(dict[str, Any], value)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _tolerance(row: dict[str, Any]) -> None:
    if "tolerance" not in row:
        return  # The grader supplies its existing default.
    tolerance = row["tolerance"]
    _require(isinstance(tolerance, dict) and bool(tolerance))
    _require(set(tolerance) <= {"rtol", "atol"})
    for value in tolerance.values():
        _require(
            type(value) in (int, float)
            and value >= 0
            and (isinstance(value, int) or math.isfinite(value))
        )


def _deliverables(value: Any) -> None:
    _require(isinstance(value, list) and bool(value))
    names: set[str] = set()
    for row in value:
        _require(isinstance(row, dict))
        _require(_text(row.get("name")) and row["name"] not in names)
        names.add(row["name"])
        _require("value" in row and _text(row.get("path")))
        filename, separator, field = row["path"].partition(":")
        _require(
            separator == ":"
            and "/" not in filename
            and "\\" not in filename
            and filename.endswith((".json", ".csv"))
            and all(_text(part) for part in field.split("."))
        )
        _tolerance(row)


def _checkpoints(value: Any) -> None:
    _require(isinstance(value, dict) and bool(value))
    for name, row in value.items():
        _require(_text(name) and isinstance(row, dict) and "value" in row)
        _tolerance(row)
        for field in ("concept", "domain"):
            if field in row:
                _require(isinstance(row[field], str))
        if "siblings" in row:
            _require(isinstance(row["siblings"], dict))


def _generic_references(values: dict[str, dict[str, Any]]) -> None:
    _require(
        {"expected.json", "checkpoints.json", "concept_graph.json", "bridges.json"}
        <= values.keys()
    )
    _deliverables(values["expected.json"].get("deliverables"))
    _checkpoints(values["checkpoints.json"].get("checkpoints"))
    graph = values["concept_graph.json"]
    nodes, edges = graph.get("nodes"), graph.get("edges")
    _require(isinstance(nodes, list) and bool(nodes) and all(_text(n) for n in nodes))
    _require(isinstance(edges, list))
    assert isinstance(edges, list)
    for edge in edges:
        _require(
            isinstance(edge, dict) and _text(edge.get("from")) and _text(edge.get("to"))
        )
    bridges = values["bridges.json"].get("bridges")
    _require(isinstance(bridges, list))
    assert isinstance(bridges, list)
    for bridge in bridges:
        _require(isinstance(bridge, dict))
        _require(
            all(
                _text(bridge.get(k))
                for k in ("from_domain", "from_node", "to_domain", "to_node")
            )
        )
    if "alt_paths.json" in values:
        paths = values["alt_paths.json"].get("paths")
        _require(isinstance(paths, list) and bool(paths))
        assert isinstance(paths, list)
        names: set[str] = set()
        for path in paths:
            _require(isinstance(path, dict) and _text(path.get("name")))
            _require(path["name"] not in names)
            names.add(path["name"])
            _deliverables(path.get("deliverables"))
            _checkpoints(path.get("checkpoints"))


def _csv(path: pathlib.Path) -> None:
    rows = csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig")), strict=True)
    header = next(rows, None)
    _require(header is not None and bool(header))
    assert header is not None
    _require(
        all(_text(column) for column in header) and len(set(header)) == len(header)
    )
    # A legitimately empty table still carries a header (for example, no excluded days).
    for row in rows:
        _require(len(row) == len(header))


def _grader_shape(source: str) -> tuple[bool, dict[str, str]]:
    """Recognize the shared grader and explicit reference-format declarations.

    Parse organizer source without importing it. Comments and docstrings do not opt in.
    An optional alt_paths.json is required if manifested, not merely because the generic
    implementation supports it: the single-path public unit intentionally omits it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False, {}  # Preserve the existing runner's treatment of invalid checks.
    generic = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "verifier"
        and any(alias.name == "run_verification" for alias in node.names)
        for node in ast.walk(tree)
    )
    formats: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "T1_REFERENCE_FORMATS"
            for target in node.targets
        ):
            continue
        _require(isinstance(node.value, ast.Dict))
        assert isinstance(node.value, ast.Dict)
        for key, value in zip(node.value.keys, node.value.values):
            _require(
                isinstance(key, ast.Constant)
                and _text(key.value)
                and isinstance(value, ast.Constant)
                and value.value in ("deliverables", "checkpoints")
            )
            assert isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
            assert isinstance(key.value, str) and isinstance(value.value, str)
            _require(key.value not in formats)
            formats[key.value] = value.value
    return generic, formats


def validate_reference_inputs(
    unit_dir: pathlib.Path, source: str, *, required: bool
) -> None:
    """Check the immutable organizer reference envelope, before inspecting output.

    The shared manifest implementation owns path safety, file kinds, hashes and exact
    coverage. A filtered view scopes this preflight to reference data; g0 separately
    verifies the full organizer manifest. Every declared reference is required,
    including a reference marked non-redistributable in a sealed organizer dataset.
    """
    reference = unit_dir / _REFERENCE
    generic, formats = _grader_shape(source)
    if (
        not required
        and not generic
        and not formats
        and not reference.exists()
        and not reference.is_symlink()
    ):
        return
    try:
        _require(reference.is_dir())
        _require(not (unit_dir / "checks").is_symlink() and not reference.is_symlink())
        manifest = _json(unit_dir / "manifest.json")
        entries = manifest.get("files")
        _require(isinstance(entries, list))
        assert isinstance(entries, list)
        references: list[dict[str, Any]] = []
        for entry in entries:
            _require(isinstance(entry, dict) and isinstance(entry.get("path"), str))
            if entry["path"].startswith(_REFERENCE + "/"):
                references.append({**entry, "redistributable": True})
        _require(bool(references))
        _require(
            not verify_manifest(
                unit_dir, {"files": references, "coverage": [_REFERENCE]}
            )
        )
        values: dict[str, dict[str, Any]] = {}
        for entry in references:
            path = unit_dir / entry["path"]
            if path.suffix == ".json":
                value = _json(path)
                relative = path.relative_to(reference).as_posix()
                values[relative] = value
                if relative == "checkpoints.json":
                    _checkpoints(value.get("checkpoints"))
            elif path.suffix == ".csv":
                _csv(path)
        if generic:
            _generic_references(values)
        for name, format_name in formats.items():
            _require(name in values)
            if format_name == "deliverables":
                _deliverables(values[name].get("deliverables"))
            else:
                _checkpoints(values[name].get("checkpoints"))
    except OrganizerFault:
        raise
    except (OSError, ValueError, TypeError, KeyError, csv.Error):
        # Suppress underlying parser/path diagnostics: they can contain sealed content.
        raise OrganizerFault(_FAULT) from None
