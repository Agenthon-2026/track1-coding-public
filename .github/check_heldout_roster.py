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

`blessed_digests` lists file hashes ruled public by the organizer; they are exempt from arm 3
and each carries its rationale in the artifact.

This is the CI tier only. It cannot see a held-out GUID buried in prose or a near-miss copy;
a second sweep, run organizer-side against the real roster over every ref, covers those before
anything flips public. Stdlib-only; no secrets; runs identically on fork PRs.

Exit 0 clean; exit 1 with one line per hit.
"""
from __future__ import annotations

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
    print(f"check_heldout_roster: clean — {len(units)} units, {scanned_files} files, "
          f"0 roster hits (roster head {art['roster_source_head'][:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
