#!/usr/bin/env python3
"""CI check: no held-out exam material in this public repo — by digest, not by trust.

Compares every unit in ./units against .github/heldout_roster_hashes.json, the hash-only
derivative of the private held-out roster. Three arms, all independent of what any card
claims about itself (the card is not evidence — a mislabelled unit fails exactly the same):

  1. unit id       sha256(directory name)         in id_sha256        -> held-out unit committed here
  2. canary guid   sha256([contamination].canary_guid) in canary_guid_sha256
                                                                      -> held-out unit relabelled
  3. file digest   sha256(every committed file)   in input_sha256     -> held-out input smuggled in,
                                                                         whatever it is named

ARRAY LENGTHS IN THE ARTIFACT CARRY NO INFORMATION. Every array is padded to a fixed constant
with random decoys and sorted, so the number of entries is not the number of held-out units. That
is enforced here, not merely documented: an array whose length does not match its declared
`pad_targets` entry fails this check, because an unpadded array discloses the roster size. The
artifact this replaced did exactly that -- two arrays agreeing at 14 read as a roster of 14.

`blessed_digests` lists file hashes ruled public by the organizer; they are exempt from arm 3 and
each carries its rationale. The generator now subtracts digests already present in this repository,
so it is normally empty; it remains supported for an organizer override.

This is the CI tier only. It cannot see a held-out GUID buried in prose or a near-miss copy;
a second sweep, run organizer-side against the real roster over every ref, covers those before
anything flips public. Stdlib-only; no secrets; runs identically on fork PRs.

Exit 0 clean; exit 1 with one line per hit.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTIFACT = pathlib.Path(__file__).resolve().parent / "heldout_roster_hashes.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    art = json.loads(ARTIFACT.read_text())

    # Fail closed on an unpadded array. A hand-edited or hand-regenerated artifact is how the
    # roster size leaked before, and how the roster went 81 commits stale with no signal.
    pad_targets = art.get("pad_targets")
    if not pad_targets:
        print("check_heldout_roster: artifact declares no pad_targets — regenerate it with "
              "scripts/gen_heldout_roster_hashes.py (organizer-side). Refusing to pass: an "
              "unpadded artifact discloses the held-out roster size through its array lengths.")
        return 1
    for key, target in pad_targets.items():
        if len(art.get(key, [])) != target:
            print(f"check_heldout_roster: {key} has {len(art.get(key, []))} entries, expected the "
                  f"fixed pad target {target}. Refusing to pass: the roster size may be disclosed.")
            return 1

    id_hashes = set(art["id_sha256"])
    guid_hashes = set(art["canary_guid_sha256"])
    input_hashes = set(art["input_sha256"])
    blessed = set(art.get("blessed_digests", {}))

    units_dir = ROOT / "units"
    units = sorted(p for p in units_dir.iterdir() if p.is_dir()) if units_dir.is_dir() else []
    if len(units) == 0:
        print("check_heldout_roster: refusing to pass an empty scan (no units found)")
        return 1

    hits: list[str] = []
    scanned_files = 0
    for unit in units:
        if sha256_bytes(unit.name.encode()) in id_hashes:
            hits.append(f"{unit.name}: unit id is on the held-out roster "
                        "(a held-out unit is committed to this public repo)")
        # arm 2: canary guid from the card, parsed leniently (a broken card is not a pass)
        card = unit / "card.toml"
        if card.exists():
            try:
                import tomllib
                guid = str(tomllib.loads(card.read_text()).get(
                    "contamination", {}).get("canary_guid", ""))
            except Exception:
                guid = ""
            if guid and sha256_bytes(guid.encode()) in guid_hashes:
                hits.append(f"{unit.name}: canary_guid is a held-out unit's GUID "
                            "(held-out unit relabelled as public)")
        # arm 3: every committed byte
        for f in sorted(p for p in unit.rglob("*") if p.is_file()):
            scanned_files += 1
            digest = sha256_bytes(f.read_bytes())
            if digest in blessed:
                continue
            if digest in input_hashes:
                hits.append(f"{unit.name}: {f.relative_to(unit)} is byte-identical to a "
                            f"held-out input (sha256 {digest[:12]}…); renaming does not help")

    if hits:
        print(f"HELD-OUT MATERIAL DETECTED ({len(hits)} hit(s) over {len(units)} units):")
        for h in hits:
            print(f"  - {h}")
        return 1
    # Print the artifact's age every run. A stale artifact covers only the units that existed when
    # it was generated, and says "clean" for every unit added since; the previous one did that for
    # weeks with nothing to surface it, because nothing here can compare the artifact to a roster
    # it cannot see. Age is the one staleness signal available public-side. It does not fail the
    # build: a hard expiry would break participant forks on a date they cannot fix. Real
    # enforcement is organizer-side, via
    # `gen_heldout_roster_hashes.py --check-only` in the private repository's CI.
    age = ""
    try:
        gen = dt.datetime.strptime(art["generated_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc)
        days = (dt.datetime.now(dt.timezone.utc) - gen).days
        age = f", artifact {days}d old"
        if days > 30:
            print(f"::warning::held-out roster artifact is {days} days old; if the sealed roster "
                  "has changed since, this check is a no-op for the units added after it.")
    except (KeyError, ValueError):
        print("::warning::artifact has no readable generated_utc; staleness cannot be assessed.")

    print(f"check_heldout_roster: clean — {len(units)} units, {scanned_files} files, "
          f"0 roster hits (roster head {art['roster_source_head'][:12]}{age})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
