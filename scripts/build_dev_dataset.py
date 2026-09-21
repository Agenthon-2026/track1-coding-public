#!/usr/bin/env python3
"""Build a Track 1 CodaBench dataset (dev or final) from a units tree.

Produces TWO trees, because `ingest.py` bind-mounts each unit directory wholesale at
`/input` (`-v {unit_dir}:/input:ro`) with no filtering of any kind:

    <out>/ingestion/input/ref/<unit>/   task spec + environment only; MOUNTED INTO THE SUBMISSION
    <out>/scoring/input/ref/<unit>/     the complete unit, answers included; GRADER ONLY

Why Track 1 enforces both answer directories, including with older shared toolkits:

    A T1 *public* unit normally has no `reference/` directory. Its answers
    live in `checks/` -- `checks/test_outputs.py` carries the asserted values and
    `checks/reference_data/` carries expected outputs outright. So a split that strips only
    `reference/` strips NOTHING from a public unit, reports "0 answer paths stripped", passes
    the leak gate, and mounts the graded answers into the submission. Green by absence.

    Sealed units can instead use `reference/`, which is why this script strips both and
    treats either as fatal. Current shared toolkits already declare both; the local check
    also protects use with an older toolkit that declares only `reference/`.

The published contract already answers whether an agent may read its own grading tests:

    SUBMISSION_CLI.md invariant 3 -- "the canary registry and held-out targets are never mounted"
    SUBMISSION_CLI.md track table -- T1 inputs under /input are "task spec + environment files"
    README.md -- reference values under `checks/reference_data/` are allowed "for public-dev
      practice units ONLY ... so students can self-grade on practice tasks. The held-out targets
      that determine the ranking live only in the private scorer."

    Shipping answers in the REPO for local self-grading is deliberate and stays. Mounting those
    same directories into a RANKED phase is the thing no policy sanctions. Stripping `checks/`
    makes the implementation match the contract rather than changing it.

Stripping `checks/` does not break grading: the scoring program reads each unit from the
GRADER tree -- `score.py` sets `ctx["unit_dir"]` from `input/ref/`, never from the mounted
tree -- so the checks it runs are the organizer's copy, which a submission cannot reach or
tamper with.

Usage:
    python scripts/build_dev_dataset.py --out /absolute/real/path/t1-dev
    python scripts/build_dev_dataset.py --out /absolute/real/path/t1-dev --roster roster.txt
    python scripts/build_dev_dataset.py --units /path/to/the/sealed/units --out /path/t1-final

An optional roster selects immediate unit-directory handles in the supplied order. Without
one, all immediate unit directories are selected in sorted order. A refused build leaves a
prior output intact; the two trees are prepared together before promotion. See
docs/DEVELOPMENT-DATASET-BUILDER.md for the preparation and recovery contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import stat
import sys
import tempfile
import uuid
from collections.abc import Sequence

from qfbench2_common.dataset import AnswerLeak, answer_paths, split_unit

TRACK = "coding"
HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

# Answer material for T1, whatever the hub currently declares. `checks` is listed here because
# it is where a public unit's answers actually live; if/when the hub declaration adds it, this
# script defers to the hub and says so rather than stripping twice.
T1_ANSWER_DIRS = ("reference", "checks")

# Every top-level entry a T1 unit is known to carry, enumerated across BOTH repos. Anything
# outside this vocabulary stops the build rather than being mounted,
# because an unrecognised entry is exactly where an undeclared answer directory would appear: a
# declaration only covers the layouts it has seen, and a unit family whose shape nobody enumerated
# is how answer material reaches a mounted tree while the gate reports success. Widening this set
# is a deliberate, reviewed act -- which is the point.
KNOWN_TOP_LEVEL = frozenset(
    {
        # The per-entry census that used to sit here stated how many units on each side of the
        # split carry each name. What this vocabulary needs to say is WHICH entries exist and
        # which are answer material; the counts were a roster size in disguise.
        "card.toml",  # universal
        "instruction.md",  # universal, apart from a scaffold unit that carries none
        "manifest.json",
        "environment",
        "checks",  # ANSWER MATERIAL
        "reference",  # ANSWER MATERIAL -- never present on a public unit
    }
)


def _assert_known_shape(unit: pathlib.Path) -> None:
    """Refuse a unit whose layout this splitter has never seen.

    Strip-what-is-declared is silent about what it was never told to look for. Enumerate-and-refuse
    fails loudly instead, so a new unit family cannot be mounted merely because nobody updated a
    tuple.
    """
    unknown = sorted(e.name for e in unit.iterdir() if e.name not in KNOWN_TOP_LEVEL)
    if unknown:
        raise AnswerLeak(
            f"{unit.name}: unrecognised top-level entries {unknown}. This splitter refuses layouts "
            f"it has not seen rather than mounting them. If these carry answer material, add them "
            f"to T1_ANSWER_DIRS; if a submission may read them, add them to KNOWN_TOP_LEVEL -- "
            f"deliberately, in a reviewed commit."
        )


def _answer_inventory(unit: pathlib.Path, dirs: tuple[str, ...]) -> dict[str, str]:
    """Relative path -> sha256; duplicate answer bytes still count as distinct files."""
    out: dict[str, str] = {}
    for d in dirs:
        root = unit / d
        if root.is_dir():
            for f in root.rglob("*"):
                if f.is_file():
                    h = hashlib.sha256()
                    with f.open("rb") as fh:
                        for chunk in iter(lambda: fh.read(1 << 20), b""):
                            h.update(chunk)
                    out[f.relative_to(unit).as_posix()] = h.hexdigest()
    return out


def _assert_clean(
    mounted: pathlib.Path, digests: set[str], dirs: tuple[str, ...]
) -> None:
    """Names AND content: a renamed copy of an answer file is still the answer."""
    for d in dirs:
        if (mounted / d).exists():
            raise AnswerLeak(f"{d}/ present in the mounted tree: {mounted}")
    for f in mounted.rglob("*"):
        if f.is_file():
            h = hashlib.sha256()
            with f.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() in digests:
                raise AnswerLeak(
                    f"{f} is byte-identical to an answer file, under a different name"
                )


def _location(path: pathlib.Path) -> pathlib.Path:
    """Reject links before resolving aliases such as '..'."""
    path = path.expanduser().absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"symlink path is not allowed: {part}")
    return path.resolve()


def _regular_tree(root: pathlib.Path) -> None:
    """Inspect metadata only; the shared splitter still owns safe copying."""
    pending = [root]
    while pending:
        path = pending.pop()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            pending.extend(path.iterdir())
        elif not stat.S_ISREG(mode):
            raise ValueError(f"symlink or special node is not allowed: {path}")


def _selection(units: pathlib.Path, roster: Sequence[str] | None) -> list[pathlib.Path]:
    children = {p.name: p for p in units.iterdir()}
    handles = (
        sorted(name for name, path in children.items() if path.is_dir())
        if roster is None else list(roster)
    )
    if not handles:
        raise ValueError(f"no units selected under {units}")
    selected = []
    seen: set[str] = set()
    for handle in handles:
        if not isinstance(handle, str) or not HANDLE.fullmatch(handle) or handle in (".", ".."):
            raise ValueError(f"invalid immediate unit directory handle: {handle!r}")
        if handle in seen:
            raise ValueError(f"duplicate unit directory handle: {handle}")
        seen.add(handle)
        unit = children.get(handle)
        if unit is None or unit.is_symlink() or not unit.is_dir():
            raise ValueError(f"selected unit is not an immediate real directory: {handle}")
        _regular_tree(unit)
        if not (unit / "card.toml").is_file():
            raise ValueError(f"selected unit has no card.toml: {handle}")
        _assert_known_shape(unit)
        selected.append(unit)
    return selected


def read_roster(path: pathlib.Path) -> list[str]:
    """One handle per line, with blank lines and full-line comments permitted."""
    path = _location(path)
    if not path.is_file():
        raise ValueError(f"roster is not a regular file: {path}")
    return [
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _publish(staging: pathlib.Path, out: pathlib.Path) -> None:
    """Keep the prior whole artifact until promotion succeeds; restore on ordinary failure."""
    backup = out.with_name(f".{out.name}.previous-{uuid.uuid4().hex}")
    if out.exists():
        out.rename(backup)
    try:
        staging.rename(out)
    except BaseException:
        if backup.exists():
            try:
                backup.rename(out)
            except OSError as exc:
                raise RuntimeError(f"promotion failed; prior artifact retained at {backup}") from exc
        raise
    if backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError:
            print(f"previous artifact retained for cleanup: {backup}", file=sys.stderr)


def build(units: pathlib.Path, out: pathlib.Path, roster: Sequence[str] | None = None) -> int:
    units, out = _location(units), _location(out)
    if not units.is_dir():
        raise ValueError(f"units root is not a directory: {units}")
    if units == out or units in out.parents or out in units.parents:
        raise ValueError("units and output paths must not overlap")
    unit_dirs = _selection(units, roster)
    if out.exists():
        if not out.is_dir():
            raise ValueError(f"output is not a directory: {out}")
        _regular_tree(out)

    hub_dirs, _hub_files = answer_paths(TRACK)
    extra = tuple(d for d in T1_ANSWER_DIRS if d not in hub_dirs)
    if extra:
        print(
            f"note: hub declares ANSWER_DIRS[{TRACK!r}] = {hub_dirs}; this script additionally "
            f"strips {extra} -- see the module docstring for why. Adding {extra} to the shared "
            f"toolkit's ANSWER_DIRS declaration is the one-line change that would make this "
            f"local handling unnecessary.\n"
        )

    # Preflight above is read-only. Replace both generated trees in a sibling candidate,
    # preserving unrelated operator metadata and leaving the previous artifact intact on refusal.
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(tempfile.mkdtemp(prefix=f".{out.name}.build-", dir=out.parent))
    stripped_total = 0
    grader_total = 0
    try:
        if out.exists():
            shutil.copytree(out, staging, dirs_exist_ok=True, symlinks=True)
        ing_root = staging / "ingestion" / "input" / "ref"
        sco_root = staging / "scoring" / "input" / "ref"
        for root in (ing_root, sco_root):
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True)
        for u in unit_dirs:
            answers = _answer_inventory(u, T1_ANSWER_DIRS)
            # The hub mechanism does the copy and its own declared-answer gate first.
            split_unit(u, ing_root, sco_root, TRACK)
            mounted = ing_root / u.name
            # Then T1's own rule, for the dirs the hub does not (yet) declare.
            for d in extra:
                victim = mounted / d
                if victim.is_dir():
                    shutil.rmtree(victim)
            _assert_clean(mounted, set(answers.values()), T1_ANSWER_DIRS)
            grader_answers = _answer_inventory(sco_root / u.name, T1_ANSWER_DIRS)
            if grader_answers != answers:
                raise ValueError(f"{u.name}: grader answer paths or bytes differ from the source")
            n_here = len(answers)
            stripped_total += n_here
            grader_total += len(grader_answers)
            print(f"  {u.name:<44} answer files stripped: {n_here:>3}")
        if stripped_total == 0:
            raise ValueError(
                "zero answer files stripped over the whole tree. Either the units carry "
                "no answers (then this dataset cannot be graded) or the declaration is wrong. "
                "A build that strips nothing is the failure this script exists to prevent."
            )
        (staging / "build-roster.json").write_text(
            json.dumps({"track": TRACK, "unit_handles": [u.name for u in unit_dirs]}, indent=2)
            + "\n", encoding="utf-8",
        )
        _regular_tree(staging)
        _publish(staging, out)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    ing_root = out / "ingestion" / "input" / "ref"
    sco_root = out / "scoring" / "input" / "ref"
    print(f"\ningestion tree: {ing_root}   ({len(unit_dirs)} units, submission-facing)")
    print(f"scoring tree:   {sco_root}   ({len(unit_dirs)} units, grader only)")
    print(f"answer files stripped from the mounted tree: {stripped_total}")
    print(f"answer files still present in the grader tree: {grader_total}")
    # The two upload roots sit at DIFFERENT LEVELS, and guessing fails SILENTLY rather than
    # loudly: ingest.py iterates `(inp / "ref")` (bundle-t1-coding/ingestion_program/ingest.py:670),
    # so input_data must CONTAIN ref/; CodaBench mounts reference_data AT /app/input/ref and
    # score.py then does `ref = input_dir / "ref"` (scoring_program/score.py:78), so reference_data
    # must BE the units. Upload the ingestion tree one level too deep and ingest.py finds no ref/,
    # the task still reads healthy, and the first submission exits on `no_input_units` having
    # launched nothing. Print the exact roots so nobody has to infer them.
    print("\nUPLOAD ROOTS -- they are at DIFFERENT levels; guessing fails silently:")
    print(f"  input_data      {ing_root.parent}")
    print('                  (root must CONTAIN ref/ -- ingest.py iterates inp/"ref")')
    print(f"  reference_data  {sco_root}")
    print(
        "                  (root must BE the units -- CodaBench mounts it at /app/input/ref)"
    )
    print("\nSwapping the two hands every participant the answers.")
    print("This splitter does not create or re-sign an evaluation plan or its trust store.")
    print("Any retained plan must be checked against the new roster and dataset before upload.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    here = pathlib.Path(__file__).resolve().parents[1]
    ap.add_argument("--units", default=str(here / "units"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--roster", type=pathlib.Path,
                    help="ordered file of immediate unit directory handles, one per line")
    a = ap.parse_args()
    try:
        roster = read_roster(a.roster) if a.roster is not None else None
        return build(pathlib.Path(a.units), pathlib.Path(a.out), roster)
    except AnswerLeak as exc:
        ap.exit(1, f"LEAK GATE: {exc}\n")
    except (OSError, ValueError) as exc:
        ap.exit(1, f"BUILD REFUSED: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
