#!/usr/bin/env python3
"""CI unit validator (root-relative).

Validates every public unit in ./units against:
  - card.toml: schema_version == "2.0"; [task] id/track/title/split present (no placeholders);
    [task].track matches the expected track; no private-test unit in a public repo;
  - [contamination].canary_guid present, a valid UUIDv4, and globally unique across units;
  - manifest.json checksums (qfbench2_common.manifest.verify_manifest);
  - public-safety firewall (qfbench2_common.manifest.assert_public_safe) — no oracle/solution leak.

Usage:  python .github/validate_units.py <expected-track>
Exit 0 if all units pass; exit 1 with a list of errors otherwise.
"""

from __future__ import annotations

import fnmatch
import os
import pathlib
import re
import sys
import tomllib

from qfbench2_common.manifest import assert_public_safe, verify_manifest

UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

# Lines that would require open-internet access at verifier RUN time (forbidden: the
# "restricted" network reaches allowlisted model APIs only — PyPI is not on the allowlist).
# Matched only at the start of a command line so comments mentioning them do not trip the check.
_NET_INSTALL = re.compile(r"^\s*(curl|wget|uvx|pip3?\s+install|uv\s+pip\s+install)\b", re.M)

# ---------------------------------------------------------------------------------------
# Repo-local oracle-filename firewall.
#
# qfbench2_common.manifest._ORACLE_GLOBS blocks exactly four name patterns for every split:
#     ('*oracle*', 'answer_key*', 'solve.sh', 'solution.py')
# Every T1 public unit is split = "public-dev", so the *directory* rules that would block
# reference/ (manifest._ANSWER_DIRS) are deliberately skipped here -- public-dev units are
# allowed to ship reference VALUES for self-grading. The consequence is a blind spot: an
# oracle IMPLEMENTATION dropped in as reference/solve.py, reference/reference_solution.py,
# reference/solve.ipynb, reference/model_answer.py or checks/solve.py matches none of the
# four hub globs and passes public-safety silently.
#
# These extra patterns close that hole from inside this repo (the hub globs cannot be edited
# from here). They are matched on the BASENAME, at or below the unit, for every split -- an
# oracle implementation is never legitimate in a public repo regardless of where it sits.
# The walk does not follow symlinks: assert_public_safe already rejects any link in a unit,
# and following one would enumerate a tree this check cannot vouch for.
#
# Verified against the clean tree: none of the 87 units' filenames match any pattern below.
_EXTRA_ORACLE_GLOBS = (
    "solve.*",            # reference/solve.py, reference/solve.ipynb, checks/solve.py
    "solution.*",         # any extension, not just the hub's solution.py
    "*_solution.*",       # reference_solution.py, model_solution.ipynb
    "model_answer.*",
    "answer.*",
    "answers.*",
    "gold.*",
    "gold_*",
    "ground_truth*",
    "groundtruth*",
)


def check_oracle_filenames(u: pathlib.Path) -> list[str]:
    """Block oracle IMPLEMENTATION filenames the hub's _ORACLE_GLOBS miss (see above)."""
    errs: list[str] = []
    for dirpath, dirnames, filenames in os.walk(u, followlinks=False):
        # Sorted in place so the error list is deterministic across filesystems.
        dirnames.sort()
        for name in sorted(filenames):
            for pattern in _EXTRA_ORACLE_GLOBS:
                if fnmatch.fnmatch(name, pattern):
                    rel = pathlib.Path(dirpath, name).relative_to(u).as_posix()
                    errs.append(
                        f"{u.name}: public-safety: public unit must not contain '{rel}' "
                        f"(oracle implementation; matched {pattern!r})"
                    )
                    break
    return errs


def check_coding_verifier_contract(u: pathlib.Path) -> list[str]:
    """T1 QFBench-2.0 contract: checks/test.sh must write the Agenthon reward.json (g0-g3 / DI),
    SHOULD also write the Harbor reward.txt (so the unit runs under Harbor too), and must NOT
    install dependencies over the network at run time (deps live in the shared base image)."""
    errs: list[str] = []
    ts = u / "checks" / "test.sh"
    if not ts.exists():
        return [f"{u.name}: missing checks/test.sh"]
    text = ts.read_text()
    if "reward.json" not in text:
        errs.append(f"{u.name}: checks/test.sh does not write reward.json (Agenthon g0-g3 contract)")
    if "reward.txt" not in text:
        errs.append(f"{u.name}: checks/test.sh does not write /logs/verifier/reward.txt "
                    "(Harbor compatibility)")
    for m in _NET_INSTALL.finditer(text):
        errs.append(f"{u.name}: checks/test.sh runs a network install at verifier run time: "
                    f"{m.group(0).strip()!r} (bake deps into the finance-bench-sandbox base image)")
    if not (u / "checks" / "test_outputs.py").exists():
        errs.append(f"{u.name}: missing checks/test_outputs.py")
    return errs


def main(expected_track: str) -> int:
    root = pathlib.Path("units")
    units = [u for u in sorted(root.iterdir()) if u.is_dir()] if root.is_dir() else []
    errors: list[str] = []
    guids: dict[str, str] = {}

    for u in units:
        card_path = u / "card.toml"
        if not card_path.exists():
            errors.append(f"{u.name}: missing card.toml")
            continue
        try:
            card = tomllib.loads(card_path.read_text())
        except Exception as exc:  # noqa: BLE001 - report any parse failure
            errors.append(f"{u.name}: card.toml parse error: {exc}")
            continue

        if card.get("schema_version") != "2.0":
            errors.append(f"{u.name}: schema_version must be '2.0'")

        task = card.get("task", {})
        for field in ("id", "track", "title", "split"):
            value = str(task.get(field, ""))
            if not value or "<" in value:
                errors.append(f"{u.name}: [task].{field} is empty or a placeholder")
        if task.get("track") != expected_track:
            errors.append(
                f"{u.name}: [task].track must be {expected_track!r}, got {task.get('track')!r}"
            )
        if task.get("split") == "private-test":
            errors.append(f"{u.name}: a private-test unit must never appear in a public repo")

        guid = card.get("contamination", {}).get("canary_guid", "")
        if not guid or not UUID4.match(str(guid).lower()):
            errors.append(f"{u.name}: missing or invalid canary_guid")
        elif guid in guids:
            errors.append(f"{u.name}: duplicate canary_guid (also used by {guids[guid]})")
        else:
            guids[guid] = u.name

        errors.extend(f"{u.name}: manifest: {e}" for e in verify_manifest(u))
        errors.extend(f"{u.name}: public-safety: {e}" for e in assert_public_safe(u))
        errors.extend(check_oracle_filenames(u))
        if expected_track == "coding":
            errors.extend(check_coding_verifier_contract(u))

    if errors:
        print("UNIT VALIDATION ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(
        f"All {len(units)} unit(s) valid: schema, track, canary uniqueness, "
        "manifest checksums, public-safety."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
