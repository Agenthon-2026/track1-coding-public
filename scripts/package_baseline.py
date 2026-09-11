#!/usr/bin/env python3
"""Create and validate the frozen C5 submission descriptor from real metadata."""

import argparse
import json
from pathlib import Path

from qfbench2_common.contracts.descriptor import (
    SubmissionDescriptor,
    seal_descriptor_digest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "competition-id",
        "team-id",
        "phase",
        "registry",
        "repository",
        "image-digest",
        "model-name",
        "model-version",
        "model-revision",
        "training-cutoff",
        "license",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument(
        "--image-access", choices=["public", "organizer_mirror"], default="public"
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    body = {
        "schema_version": "1.0.0",
        "interface_version": "2.0",
        "competition_id": args.competition_id,
        "team_id": args.team_id,
        "track": "coding",
        "phase": args.phase,
        "category": "api",
        "image": {
            "registry": args.registry,
            "repository": args.repository,
            "digest": args.image_digest,
        },
        "image_access": args.image_access,
        "license": args.license,
        "models": [
            {
                "name": args.model_name,
                "version": args.model_version,
                "training_cutoff": args.training_cutoff,
                "access": "api",
                "revision": args.model_revision,
            }
        ],
    }
    descriptor = SubmissionDescriptor.from_mapping(seal_descriptor_digest(body))
    with args.out.open("x") as f:
        f.write(json.dumps(descriptor.to_mapping(), indent=2) + "\n")
    print(descriptor.image_reference())


if __name__ == "__main__":
    main()
