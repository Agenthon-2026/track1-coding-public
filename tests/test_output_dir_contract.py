"""This repo requires the harness to bind the run output directory at BOTH output paths.

    python tests/test_output_dir_contract.py

Stdlib-only, unit-data-only: no pytest, no Docker, no toolkit import, so it runs in the lint job.

Track 1 inherits QFBench/Harbor, which puts agent deliverables in ``/app/output``; the rest of
Agenthon uses a bare ``/output``. Both spellings are live here, and the units are *internally*
consistent -- each one's instruction.md and checks agree with each other. They just do not all
agree with each other ACROSS units:

* 48 of 87 ``checks/test_outputs.py`` read a hardcoded ``/app/output`` with no env fallback;
* 39 resolve ``os.environ["OUTPUT_DIR"]`` (which ``checks/test.sh`` sets), defaulting to a
  hardcoded literal if it is unset;
* 82 of 87 ``instruction.md`` name ``/app/output``, 6 name ``/output``.

These counts are measured AFTER the 2026-08-27 relative-path fix. Before it, 19 instruction.md
named a bare ``./output`` and the numbers above read 63 / 5 / 19 — see
``test_no_unit_names_a_relative_output_directory`` for why that was invisible here.

The CodaBench harness originally bound the run's output directory at ``/output`` only, while
passing ``solve --task-dir /input --out /output``. That is silent and total: an agent obeying its
own instruction.md writes ``/app/output``, which is an ordinary directory inside the container;
``--rm`` deletes it; ``res/<unit>/`` is empty; ``_g1_schema`` fails with "reward.json not found";
the unit scores 0 -- not for a bad agent, but for every agent, indistinguishably from genuinely
failing the hidden tests.

The harness now binds one host directory at both container paths, which
fixes all 87 units without editing any of them. These tests are the standing proof that the
second bind is load-bearing and cannot be dropped: they enumerate, from the unit data itself,
which paths this repo actually requires.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_UNITS = _REPO / "units"

# The container paths the harness binds to the run's output directory. Keep in sync with
# ingest.output_mounts() and SUBMISSION_CLI.md invariant 8. A path outside this set is written
# into the container's own filesystem and discarded by `docker run --rm`.
BOUND_OUTPUT_PATHS = frozenset({"/app/output", "/output"})

# The left-hand lookbehind is load-bearing. Without it this matched the ``/output`` INSIDE a
# relative ``./output``, so 19 units telling the agent to write to an unbound relative path were
# counted here as compliant users of the bound ``/output`` — the guard reported the corpus clean
# while documenting the defect it exists to catch. `.` and `\w` both have to be excluded: `\w`
# alone still admits ``./output``.
_OUTPUT_PATH_RE = re.compile(r"(?<![.\w])(/(?:app/)?output)(?![A-Za-z0-9_-])")

# A relative output path is not a spelling variant of a bound one. ``./output`` resolves against
# the submission image's WORKDIR, which the participant chooses and no mount binds, so the dual
# bind cannot rescue it: the deliverables land inside the container and ``--rm`` discards them.
_RELATIVE_OUTPUT_RE = re.compile(r"(?<![\w/])\./output\b")
# e.g.  OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/app/output")
_ENV_DEFAULT_RE = re.compile(
    r"""(?:environ\.get|getenv)\s*\(\s*['"]OUTPUT_DIR['"]\s*,\s*['"]([^'"]+)['"]"""
)

_FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        _FAILURES.append(message)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _units() -> list[Path]:
    return sorted(p for p in _UNITS.iterdir() if p.is_dir())


def test_every_hardcoded_output_path_is_one_the_harness_binds() -> None:
    """The load-bearing assertion.

    Run this with BOUND_OUTPUT_PATHS narrowed to {"/output"} -- the mount the shipped harness
    actually used -- and it fails on 46 units. That is the defect, expressed as a test.
    """
    for unit in _units():
        for rel in ("instruction.md", "checks/test_outputs.py"):
            for found in _OUTPUT_PATH_RE.findall(_read(unit / rel)):
                check(
                    found in BOUND_OUTPUT_PATHS,
                    f"{unit.name}/{rel}: names output path {found!r}, which the harness does "
                    f"not bind (bound: {sorted(BOUND_OUTPUT_PATHS)}); anything written there is "
                    f"discarded by --rm",
                )


def test_both_bound_paths_are_actually_required_by_the_units() -> None:
    """Proof that dropping either bind breaks real units -- with the units named.

    If this ever fails because one path is unused, the repo has converged and the harness MAY be
    narrowed to a single mount. Until then, narrowing it silently zeroes a whole group.
    """
    users: dict[str, list[str]] = {p: [] for p in BOUND_OUTPUT_PATHS}
    for unit in _units():
        for rel in ("instruction.md", "checks/test_outputs.py"):
            for found in set(_OUTPUT_PATH_RE.findall(_read(unit / rel))):
                if found in users:
                    users[found].append(f"{unit.name}/{rel}")
    for path, needing in users.items():
        check(
            bool(needing),
            f"no unit references {path} any more — the harness bind for it may be dropped",
        )
    if not _FAILURES:
        print(
            "    required binds: "
            + ", ".join(f"{p} ({len(u)} refs)" for p, u in sorted(users.items()))
        )


def test_no_unit_names_a_relative_output_directory() -> None:
    """A relative ``./output`` is unbound, and the harness cannot bind it.

    ``/app/output`` and ``/output`` are both mounted at the run directory, so a unit naming
    either is safe. ``./output`` is neither: it resolves against the submission image's WORKDIR,
    which is the participant's choice. With WORKDIR ``/app`` it happens to coincide with a bound
    path; with anything else the write lands in the container filesystem and ``--rm`` takes it.

    15 of the 19 units this caught phrased it as ``the OUTPUT_DIR environment variable
    (default: ./output)``. ``OUTPUT_DIR`` is set by ``checks/test.sh`` for the CHECKER; it is
    never injected into the AGENT container, so for the agent that sentence read as an
    unconditional instruction to use the unbound default.
    """
    for unit in _units():
        for rel in ("instruction.md", "checks/test_outputs.py"):
            body = _read(unit / rel)
            for found in set(_RELATIVE_OUTPUT_RE.findall(body)):
                check(
                    False,
                    f"{unit.name}/{rel}: names a relative {found!r}, which resolves against the "
                    f"submission image's WORKDIR and is bound by no mount; name /app/output",
                )


def test_the_relative_detector_is_not_vacuous() -> None:
    """Controls, because the bug this file is fixing was a regex that silently matched nothing.

    A detector with no control is how the previous version reported 87 clean units while 19 of
    them named an unbound path.
    """
    check(bool(_RELATIVE_OUTPUT_RE.search("write to ./output/x")),
          "the relative detector does not fire on './output' — it cannot catch the defect")
    check(not _RELATIVE_OUTPUT_RE.search("write to /app/output/x"),
          "the relative detector fires on '/app/output' — it would flag compliant units")
    check(not _OUTPUT_PATH_RE.findall("write to ./output/x"),
          "the absolute detector still matches inside './output' — the anchor is not working")
    check(_OUTPUT_PATH_RE.findall("write to /app/output/x") == ["/app/output"],
          "the absolute detector stopped matching a real bound path")


def test_env_var_defaults_are_bound_paths_too() -> None:
    """`os.environ.get("OUTPUT_DIR", <default>)` must degrade to a path that still works.

    If test.sh's export is ever lost, these fall back to their literal default. That default has
    to be a bound path or the fallback silently reads an empty directory.
    """
    for unit in _units():
        for default in _ENV_DEFAULT_RE.findall(_read(unit / "checks" / "test_outputs.py")):
            normalized = default.rstrip("/") or "/"
            check(
                normalized in BOUND_OUTPUT_PATHS,
                f"{unit.name}/checks/test_outputs.py: OUTPUT_DIR default {default!r} is not a "
                f"bound path; if the export is lost this reads an empty directory and reports "
                f"missing deliverables",
            )


def test_test_sh_resolves_every_bound_path() -> None:
    """test.sh writes reward.json, the artifact _g1_schema looks for. Its fallback chain
    (OUTPUT_DIR -> /app/output -> /output) is what lets one runner serve both conventions."""
    for unit in _units():
        body = _read(unit / "checks" / "test.sh")
        check(bool(body), f"{unit.name}: no checks/test.sh")
        check("OUTPUT_DIR" in body, f"{unit.name}/checks/test.sh: no OUTPUT_DIR resolution")
        for bound in sorted(BOUND_OUTPUT_PATHS):
            check(
                bound in body,
                f"{unit.name}/checks/test.sh: no fallback to {bound}; a unit written against "
                f"that spelling produces no reward.json and scores 0 with no diagnostic",
            )


def test_each_unit_names_an_output_directory() -> None:
    """A unit that never says where deliverables go cannot be solved deliberately."""
    for unit in _units():
        named = set(_OUTPUT_PATH_RE.findall(_read(unit / "instruction.md"))) | set(
            _OUTPUT_PATH_RE.findall(_read(unit / "checks" / "test_outputs.py"))
        )
        env_driven = "OUTPUT_DIR" in _read(unit / "instruction.md")
        check(
            bool(named) or env_driven,
            f"{unit.name}: names no output directory in instruction.md or checks/test_outputs.py",
        )


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    if _FAILURES:
        print(f"FAILED ({len(_FAILURES)}):")
        for failure in _FAILURES:
            print(f"  - {failure}")
        return 1
    print(f"OK: {len(tests)} output-dir contract tests passed over {len(_units())} units")
    return 0


if __name__ == "__main__":
    sys.exit(main())
