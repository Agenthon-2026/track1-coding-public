#!/usr/bin/env python3
"""Build a Track 1 CodaBench dataset (dev or final) from a units tree.

Produces TWO trees, because `ingest.py` bind-mounts each unit directory wholesale at
`/input` (`-v {unit_dir}:/input:ro`) with no filtering of any kind:

    <out>/ingestion/input/ref/<unit>/   task spec + environment only; MOUNTED INTO THE SUBMISSION
    <out>/scoring/input/ref/<unit>/     the complete unit, answers included; GRADER ONLY

Why Track 1 needs this even though `ANSWER_DIRS["coding"] == ("reference",)`:

    A T1 *public* unit has no `reference/` at all (measured: 0 of 87 on main). Its answers
    live in `checks/` -- `checks/test_outputs.py` carries the asserted values and
    `checks/reference_data/` carries expected outputs outright. So a split that strips only
    `reference/` strips NOTHING from a public unit, reports "0 answer paths stripped", passes
    the leak gate, and mounts the graded answers into the submission. Green by absence.

    `reference/` is still the right declaration for the SEALED units (29 of 29 private units
    ship `reference/solve.sh`, a runnable oracle), which is why this script strips both and
    treats either as fatal.

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
    python scripts/build_dev_dataset.py --out /tmp/t1-dev
    python scripts/build_dev_dataset.py --units /path/to/the/sealed/units --out /tmp/t1-final
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import sys

from qfbench2_common.dataset import AnswerLeak, answer_paths, split_unit

TRACK = "coding"

# Answer material for T1, whatever the hub currently declares. `checks` is listed here because
# it is where a public unit's answers actually live; if/when the hub declaration adds it, this
# script defers to the hub and says so rather than stripping twice.
T1_ANSWER_DIRS = ("reference", "checks")

# Every top-level entry a T1 unit is known to carry, enumerated across BOTH repos (87 public
# units, 29 sealed). Anything outside this vocabulary stops the build rather than being mounted,
# because an unrecognised entry is exactly where an undeclared answer directory would appear: a
# declaration only covers the layouts it has seen, and a unit family whose shape nobody enumerated
# is how answer material reaches a mounted tree while the gate reports success. Widening this set
# is a deliberate, reviewed act -- which is the point.
KNOWN_TOP_LEVEL = frozenset(
    {
        "card.toml",  # 87/87 public, 29/29 sealed
        "instruction.md",  # 87/87 public, 28/29 sealed (the EXAMPLE scaffold has none)
        "manifest.json",  # 87/87 public, 28/29 sealed
        "environment",  # 87/87 public, 28/29 sealed
        "checks",  # 87/87 public, 29/29 sealed -- ANSWER MATERIAL
        "reference",  # 0/87 public,  29/29 sealed -- ANSWER MATERIAL
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


def _blobs(unit: pathlib.Path, dirs: tuple[str, ...]) -> dict[str, bytes]:
    """sha256 -> bytes for every answer file under `dirs`, for the content check."""
    out: dict[str, bytes] = {}
    for d in dirs:
        root = unit / d
        if root.is_dir():
            for f in root.rglob("*"):
                if f.is_file():
                    b = f.read_bytes()
                    out[hashlib.sha256(b).hexdigest()] = b
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


def build(units: pathlib.Path, out: pathlib.Path) -> int:
    hub_dirs, _hub_files = answer_paths(TRACK)
    extra = tuple(d for d in T1_ANSWER_DIRS if d not in hub_dirs)
    if extra:
        print(
            f"note: hub declares ANSWER_DIRS[{TRACK!r}] = {hub_dirs}; this script additionally "
            f"strips {extra} -- see the module docstring for why. Adding {extra} to the shared "
            f"toolkit's ANSWER_DIRS declaration is the one-line change that would make this "
            f"local handling unnecessary.\n"
        )

    ing_root = out / "ingestion" / "input" / "ref"
    sco_root = out / "scoring" / "input" / "ref"
    for r in (ing_root, sco_root):
        if r.exists():
            shutil.rmtree(r)
        r.mkdir(parents=True)

    unit_dirs = sorted(p for p in units.iterdir() if p.is_dir())
    if not unit_dirs:
        sys.exit(f"no units under {units}")

    stripped_total = 0
    grader_total = 0
    for u in unit_dirs:
        digests = _blobs(u, T1_ANSWER_DIRS)
        try:
            _assert_known_shape(u)
            # The hub mechanism does the copy and its own declared-answer gate first.
            split_unit(u, ing_root, sco_root, TRACK)
            mounted = ing_root / u.name
            # Then T1's own rule, for the dirs the hub does not (yet) declare.
            for d in extra:
                victim = mounted / d
                if victim.is_dir():
                    shutil.rmtree(victim)
            _assert_clean(mounted, set(digests), T1_ANSWER_DIRS)
        except AnswerLeak as exc:
            sys.exit(f"LEAK GATE: {exc}")

        n_here = len(digests)
        stripped_total += n_here
        grader_total += sum(
            1
            for d in T1_ANSWER_DIRS
            for f in (sco_root / u.name / d).rglob("*")
            if (sco_root / u.name / d).is_dir() and f.is_file()
        )
        print(f"  {u.name:<44} answer files stripped: {n_here:>3}")

    print(f"\ningestion tree: {ing_root}   ({len(unit_dirs)} units, submission-facing)")
    print(f"scoring tree:   {sco_root}   ({len(unit_dirs)} units, grader only)")
    print(f"answer files stripped from the mounted tree: {stripped_total}")
    print(f"answer files still present in the grader tree: {grader_total}")
    if stripped_total == 0:
        sys.exit(
            "REFUSING: zero answer files stripped over the whole tree. Either the units carry "
            "no answers (then this dataset cannot be graded) or the declaration is wrong. A "
            "build that strips nothing is the failure this script exists to prevent."
        )
    if grader_total != stripped_total:
        sys.exit(
            f"REFUSING: grader tree has {grader_total} answer files but {stripped_total} were "
            f"stripped; the two trees disagree."
        )
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
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    here = pathlib.Path(__file__).resolve().parents[1]
    ap.add_argument("--units", default=str(here / "units"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    return build(pathlib.Path(a.units), pathlib.Path(a.out))


if __name__ == "__main__":
    sys.exit(main())
