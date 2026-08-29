"""Published resource numbers must equal what the unit cards declare.

    python tests/test_resource_contract_docs.py

Stdlib-only (``tomllib`` is stdlib on 3.13), unit-data-only: no toolkit, no pytest, no
Docker, so this runs in the secret-free firewall job.

Why this exists
---------------
The card's ``[environment]`` block is authoritative: ``SUBMISSION_CLI.md`` documents the
harness as invoking ``--cpus=<card.cpus> --memory=<card.memory> [--gpus all]`` and as
enforcing ``card.environment.{cpus,memory,gpu,timeout,network}``. The prose is a copy of
that number, and a copy drifts.

Measured 2026-08-27, before the fix: all 87 cards declared ``cpus = 16``,
``memory = "128G"``, ``gpu = true`` -- while five published files told participants
"4 vCPUs, 8 GB RAM, no GPU" (README.md, docs/CONCEPTS.md, docs/AUTHORING-GUIDE.md twice --
prose and the copy-paste card snippet -- units/t1-EXAMPLE-bs-greeks-pde/instruction.md and
templates/instruction.md). That is the number a team sizes a month of work against; it was
wrong by 4x on cores, 16x on memory, and categorically on GPU.

These tests fail if the cards stop agreeing with each other, or if any published vCPU/RAM
figure or GPU claim stops agreeing with the cards.
"""

from __future__ import annotations

import pathlib
import re
import sys
import tomllib

REPO = pathlib.Path(__file__).resolve().parent.parent

# Prose figures, anywhere in a tracked .md. "80GB-class GPU" (a byo-large tier note in
# README.md and SUBMISSION_CLI.md) is deliberately not matched: it is a model-weights tier,
# not the per-unit RAM limit.
VCPU_RE = re.compile(r"(\d+)\s*vCPUs?\b", re.I)
RAM_RE = re.compile(r"(\d+)\s*GB RAM\b", re.I)
NO_GPU_RE = re.compile(r"\bno GPU\b", re.I)


def _markdown_files() -> list[pathlib.Path]:
    return sorted(
        p for p in REPO.rglob("*.md")
        if ".git" not in p.parts
    )


def _cards() -> list[tuple[str, dict]]:
    out = []
    for card in sorted((REPO / "units").glob("*/card.toml")):
        out.append((card.parent.name, tomllib.loads(card.read_text(encoding="utf-8"))))
    return out


def _declared() -> tuple[int, str, bool]:
    """The single (cpus, memory, gpu) every card must agree on."""
    seen = {
        (c["environment"]["cpus"], c["environment"]["memory"], c["environment"]["gpu"])
        for _, c in _cards()
    }
    assert len(seen) == 1, f"cards disagree about [environment]: {sorted(seen)}"
    return seen.pop()


def test_cards_agree() -> list[str]:
    cards = _cards()
    failures = []
    variants = {}
    for name, c in cards:
        env = c.get("environment")
        if env is None:
            failures.append(f"{name}: card has no [environment] block")
            continue
        variants.setdefault((env.get("cpus"), env.get("memory"), env.get("gpu")), []).append(name)
    if len(variants) > 1:
        failures.append(
            "unit cards must declare ONE resource contract; found "
            + "; ".join(f"{k} in {len(v)} unit(s) e.g. {v[0]}" for k, v in variants.items())
        )
    for k, v in variants.items():
        print(f"  cpus={k[0]!r} memory={k[1]!r} gpu={k[2]!r} -> {len(v)} of {len(cards)} cards")
    return failures


def test_prose_matches_cards() -> list[str]:
    cpus, memory, gpu = _declared()
    ram_gb = int(memory.rstrip("Gg"))
    failures = []
    checked = 0
    for md in _markdown_files():
        rel = md.relative_to(REPO).as_posix()
        text = md.read_text(encoding="utf-8")
        for m in VCPU_RE.finditer(text):
            checked += 1
            if int(m.group(1)) != cpus:
                line = text[: m.start()].count("\n") + 1
                failures.append(
                    f"{rel}:{line}: says {m.group(0)!r}, cards declare cpus = {cpus}"
                )
        for m in RAM_RE.finditer(text):
            checked += 1
            if int(m.group(1)) != ram_gb:
                line = text[: m.start()].count("\n") + 1
                failures.append(
                    f"{rel}:{line}: says {m.group(0)!r}, cards declare memory = {memory!r}"
                )
        if gpu:
            for m in NO_GPU_RE.finditer(text):
                line = text[: m.start()].count("\n") + 1
                failures.append(
                    f"{rel}:{line}: says {m.group(0)!r}, cards declare gpu = true"
                )
    print(f"  checked {checked} vCPU/RAM figures across {len(_markdown_files())} markdown files")
    return failures


def test_authoring_guide_snippet_matches_template() -> list[str]:
    """The copy-paste card snippet in the authoring guide is what a new unit inherits."""
    cpus, memory, gpu = _declared()
    guide = (REPO / "docs" / "AUTHORING-GUIDE.md").read_text(encoding="utf-8")
    failures = []
    for key, want in (("cpus", str(cpus)), ("memory", f'"{memory}"'), ("gpu", str(gpu).lower())):
        m = re.search(rf"^{key}\s*=\s*(\S+)", guide, re.M)
        if m is None:
            failures.append(f"docs/AUTHORING-GUIDE.md: card snippet has no {key!r} line")
        elif m.group(1) != want:
            failures.append(
                f"docs/AUTHORING-GUIDE.md: card snippet says {key} = {m.group(1)}, "
                f"cards declare {want}"
            )
    template = (REPO / "templates" / "card.toml").read_text(encoding="utf-8")
    for key, want in (("cpus", str(cpus)), ("memory", f'"{memory}"'), ("gpu", str(gpu).lower())):
        m = re.search(rf"^{key}\s*=\s*(\S+)", template, re.M)
        if m is None or m.group(1) != want:
            got = None if m is None else m.group(1)
            failures.append(f"templates/card.toml: {key} = {got}, cards declare {want}")
    print("  authoring-guide snippet and templates/card.toml checked")
    return failures


def main() -> int:
    failures: list[str] = []
    for test in (
        test_cards_agree,
        test_prose_matches_cards,
        test_authoring_guide_snippet_matches_template,
    ):
        print(f"{test.__name__}:")
        failures.extend(test())
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    cpus, memory, gpu = _declared()
    print(f"\nOK: published prose matches the cards (cpus={cpus}, memory={memory}, gpu={gpu}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
