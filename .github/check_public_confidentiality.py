#!/usr/bin/env python3
"""Dependency-free checks for public data and accidental confidential artifact classes.

Reject non-public task splits, solution/registry paths, and roster-export structures even
when renamed. Public practice reference values remain allowed. This uses no organizer data
or fingerprints and cannot establish that arbitrary content is safe to publish. Organizers
must separately compare release history with their private sources before publication.
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import sys
import tomllib

PROHIBITED_NAMES = ("*oracle*", "answer_key*", "solution.*", "*_solution.*", "canary_registry*")
PROHIBITED_DIRS = {"solution", "solutions", "dev"}
ROSTER_KEYS = {"id_sha256", "canary_guid_sha256", "input_sha256", "roster_source_head", "canaries"}


def contains_roster_export(value: object) -> bool:
    if isinstance(value, dict):
        if ROSTER_KEYS.intersection(value):
            return True
        return any(contains_roster_export(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_roster_export(v) for v in value)
    return False


def check(root: Path) -> list[str]:
    errors = set()
    units = root / "units"
    cards = sorted(units.glob("*/card.toml"))
    if not cards:
        errors.add("no public task cards to check")
    for unit in sorted(units.iterdir()) if units.is_dir() else []:
        if unit.is_dir() and not (unit / "card.toml").is_file():
            errors.add("task directory has no card")
    for card in cards:
        try:
            task = tomllib.loads(card.read_text())["task"]
            if task.get("split") != "public-dev":
                errors.add("task split is not public-dev")
        except (OSError, ValueError, KeyError, TypeError):
            errors.add("task card cannot be validated")
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(n for n in names if n not in {".git", "__pycache__", ".pytest_cache"})
        for name in names + sorted(files):
            path = Path(directory) / name
            if path.is_symlink():
                errors.add("symlink is not a public artifact")
                continue
            in_unit = path.is_relative_to(units)
            if (name in PROHIBITED_DIRS or name.lower().startswith("canary_registry")
                    or (in_unit and any(fnmatch.fnmatch(name.lower(), p) for p in PROHIBITED_NAMES))):
                errors.add("solution or registry artifact is present")
            if not path.is_file():
                continue
            # Parse JSON content regardless of suffix: renaming a roster export is no defense.
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            stripped = text.lstrip()
            if stripped.startswith(("{", "[")):
                try:
                    if contains_roster_export(json.loads(stripped)):
                        errors.add("roster export structure is present")
                except json.JSONDecodeError:
                    pass  # Other validators own arbitrary data formats.
    return sorted(errors)


def main() -> int:
    try:
        errors = check(Path(__file__).resolve().parents[1])
    except OSError:
        errors = ["public tree could not be fully read"]
    if errors:
        print("Public confidentiality check refused: " + "; ".join(errors))
        return 1
    print("Public confidentiality classes checked; organizer release review is separate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
