"""The oracle-filename firewall must catch an oracle IMPLEMENTATION under ``reference/``.

    python tests/test_oracle_filename_firewall.py

It exercises ``.github/validate_units.py``'s repo-local ``check_oracle_filenames``
directly. ``check_oracle_filenames`` is itself stdlib-only, but importing the validator
module pulls in ``qfbench2_common``, so this test belongs in the ``validate-units`` CI
job (which installs the toolkit), not in the secret-free ``firewall`` job. Measured: with
``qfbench2_common`` blocked, this file dies at
``from qfbench2_common.manifest import assert_public_safe, verify_manifest``.

Why this exists
---------------
Public-safety for a unit is ``qfbench2_common.manifest.assert_public_safe``. Its
per-split rules are deliberate: ``reference/`` is answer-bearing material, so it is
blocked only for units that are NOT ``public-dev`` -- a practice unit is allowed to ship
reference VALUES for self-grading. Every one of this repo's 87 units is ``public-dev``.

What the split rules leave uncovered is an oracle *implementation* smuggled in under a
name the hub's four ``_ORACLE_GLOBS`` (``*oracle*``, ``answer_key*``, ``solve.sh``,
``solution.py``) do not spell. Measured on 2026-08-27 against the toolkit at v2.3.0, all
five names below were planted in ``units/t1-bs-greeks-pde`` and
``python .github/validate_units.py coding`` printed "All 87 unit(s) valid" and exited 0.

``check_oracle_filenames`` closes that hole from inside this repo. These cases are the
standing proof; each one must stay RED if the check is weakened, and the clean tree must
stay GREEN so the check can never be "fixed" by making it fire on real units.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent

# The names the hub globs miss. Each is an oracle implementation, not a reference value.
MISSED_BY_HUB_GLOBS = (
    "reference/solve.py",
    "reference/reference_solution.py",
    "reference/solve.ipynb",
    "reference/model_answer.py",
    "checks/solve.py",
)

# The names the hub globs already cover; the repo-local check must not regress them.
ALREADY_COVERED = (
    "solve.sh",
    "solution.py",
)


def _load_validator():
    """Import .github/validate_units.py by path (``.github`` is not an importable package)."""
    spec = importlib.util.spec_from_file_location(
        "t1_validate_units", REPO / ".github" / "validate_units.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _units() -> list[pathlib.Path]:
    return sorted(p for p in (REPO / "units").iterdir() if p.is_dir())


def test_clean_tree_is_silent() -> list[str]:
    """No real unit may trip the check -- a firewall that cries wolf gets switched off."""
    check = _load_validator().check_oracle_filenames
    failures = []
    hits = [e for u in _units() for e in check(u)]
    if hits:
        failures.append(
            f"clean tree must produce no oracle-filename errors, got {len(hits)}: {hits[:5]}"
        )
    print(f"  clean tree: {len(_units())} units, {len(hits)} oracle-filename errors")
    return failures


def test_each_missed_name_is_caught() -> list[str]:
    """Every name in MISSED_BY_HUB_GLOBS, planted alone, must be reported."""
    check = _load_validator().check_oracle_filenames
    failures = []
    source = REPO / "units" / "t1-bs-greeks-pde"
    for rel in MISSED_BY_HUB_GLOBS + ALREADY_COVERED:
        with tempfile.TemporaryDirectory() as tmp:
            unit = pathlib.Path(tmp) / source.name
            shutil.copytree(source, unit)
            planted = unit / rel
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text('print("ORACLE")\n')
            errs = check(unit)
            if not any(rel in e for e in errs):
                failures.append(f"planted {rel!r} was NOT reported; errors were {errs}")
            else:
                print(f"  caught: {rel}")
    return failures


def main() -> int:
    failures: list[str] = []
    for test in (test_clean_tree_is_silent, test_each_missed_name_is_caught):
        print(f"{test.__name__}:")
        failures.extend(test())
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: oracle-filename firewall covers all "
          f"{len(MISSED_BY_HUB_GLOBS) + len(ALREADY_COVERED)} names and is silent on the clean tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
