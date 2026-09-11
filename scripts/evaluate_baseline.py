#!/usr/bin/env python3
"""Sealed public-dev evaluation using the repository's Track 1 verifier.

prepare builds both trees via the repository splitter and freezes a stratified
roster. run uses separate agent and grader containers, including per-unit Docker
data layout. No task outputs or grading answers belong in the submission image.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temporary.replace(path)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError("Dataset trees must not contain symlinks")
        if p.is_file():
            digest.update(str(p.relative_to(root)).encode() + b"\0")
            digest.update(hashlib.sha256(p.read_bytes()).digest())
    return digest.hexdigest()


def grader_dockerfile(source: str, base: str) -> str:
    # The grader stack is already installed. Reproduce the unit's COPY data
    # layout without replaying legacy dependency installers (the exemplar's
    # numba==0.60.0 installer, for example, predates Python 3.13).
    logical = source.replace("\\\n", " ").splitlines()
    lines = [
        line
        for line in logical
        if line.split(maxsplit=1)[:1] in (["COPY"], ["WORKDIR"])
    ]
    return f"FROM {base}\n" + "\n".join(lines) + "\n"


def prepare(args: argparse.Namespace) -> None:
    from build_dev_dataset import build

    out = args.out.resolve()
    if out.exists():
        raise ValueError(
            "Choose a new dataset directory; existing evaluations are never overwritten"
        )
    cards = []
    for unit in sorted(args.units.resolve().iterdir()):
        if not unit.is_dir():
            continue
        card = tomllib.loads((unit / "card.toml").read_text())
        if card["task"]["split"] != "public-dev":
            raise ValueError("The local baseline roster only accepts public-dev tasks")
        cards.append((unit, card))
    build(args.units.resolve(), out)
    groups: dict[str, list] = {}
    for unit, card in cards:
        category = card["metadata"]["category"]
        groups.setdefault(category, []).append((unit, card))
    rows = []
    for category, entries in sorted(groups.items()):
        entries.sort(
            key=lambda e: hashlib.sha256(
                ("t1-baseline-v1:" + e[0].name).encode()
            ).hexdigest()
        )
        for i, (unit, card) in enumerate(entries):
            rows.append(
                {
                    "id": unit.name,
                    "category": category,
                    "partition": "validation" if i % 3 == 1 else "tuning",
                    "smoke": i == 0,
                    "timeout_sec": card["agent"]["timeout_sec"],
                    "manifest_sha256": hashlib.sha256(
                        (unit / "manifest.json").read_bytes()
                    ).hexdigest(),
                    "input_sha256": tree_digest(
                        out / "ingestion/input/ref" / unit.name
                    ),
                    "grader_sha256": tree_digest(out / "scoring/input/ref" / unit.name),
                }
            )
    roster = {
        "schema_version": 1,
        "source_split": "public-dev",
        "note": "Public validation is a development partition, not unseen official evaluation.",
        "units": sorted(rows, key=lambda r: r["id"]),
    }
    write_json(out / "roster.json", roster)
    print(
        json.dumps(
            {
                "tasks": len(rows),
                "categories": len(groups),
                "smoke": sum(r["smoke"] for r in rows),
                "validation": sum(r["partition"] == "validation" for r in rows),
            }
        )
    )


def verify() -> None:
    """Container-only grading entry point, never imported into the agent image."""
    from qfbench2_track_coding.scoring import build_verifier

    unit, output = Path("/input"), Path("/app/output")
    card = tomllib.loads((unit / "card.toml").read_text())
    ctx = {
        "unit_dir": unit,
        "output_dir": output,
        "elapsed_sec": float(os.environ["AGENT_ELAPSED"]),
        "agent_timeout_sec": card["agent"]["timeout_sec"],
        "network": card["environment"]["network"],
        "image_hash": os.environ["AGENT_IMAGE_HASH"],
        "canary_registry": {card["contamination"]["canary_guid"]},
    }
    os.environ["PYTEST_ADDOPTS"] = (
        "--json-report --json-report-file=/app/output/pytest_report.json"
    )
    verdict = build_verifier(ctx).run(ctx)
    result = asdict(verdict)
    # Canary hits contain the actual GUID. Store the label but not a GUID -> unit map.
    for gate in result["gate_results"].values():
        gate["detail"].pop("canary_guids_found", None)
    result["detail"].pop("canary_guids_found", None)
    write_json(Path("/evaluation/verdict.json"), result)
    write_json(output / "reward.json", {"reward": float(verdict.admissible)})
    Path("/logs/verifier").mkdir(parents=True, exist_ok=True)
    Path("/logs/verifier/reward.txt").write_text("1\n" if verdict.admissible else "0\n")


def docker(command: list[str], log: Path, timeout: float) -> int:
    with log.open("w") as f:
        proc = subprocess.run(
            command, stdout=f, stderr=subprocess.STDOUT, timeout=timeout
        )
    return proc.returncode


def attempt(
    args: argparse.Namespace, row: dict, repetition: int, image_hash: str
) -> dict:
    dataset, run = args.dataset.resolve(), args.out.resolve()
    unit_id = row["id"]
    unit = dataset / "scoring/input/ref" / unit_id
    mounted = dataset / "ingestion/input/ref" / unit_id
    if (
        tree_digest(mounted) != row["input_sha256"]
        or tree_digest(unit) != row["grader_sha256"]
    ):
        raise ValueError("Frozen dataset tree changed")
    if (
        hashlib.sha256((unit / "manifest.json").read_bytes()).hexdigest()
        != row["manifest_sha256"]
    ):
        raise ValueError("Dataset manifest changed after roster freeze")
    from qfbench2_common.manifest import verify_manifest

    if verify_manifest(unit) or verify_manifest(mounted):
        raise ValueError(f"Dataset checksum failure: {unit_id}")
    # Ensure the staged view is exactly the grader-owned input subset, and sealed.
    if any((mounted / p).exists() for p in ("checks", "reference")):
        raise ValueError("Answer material present in agent input")
    for p in mounted.rglob("*"):
        if p.is_symlink():
            raise ValueError("Symlink in staged input")
        # The shared splitter removes sealed entries from the mounted manifest.
        if p == mounted / "manifest.json":
            continue
        if (
            p.is_file()
            and p.read_bytes() != (unit / p.relative_to(mounted)).read_bytes()
        ):
            raise ValueError("Staged input differs from frozen grader tree")
    for p in (unit / "environment").rglob("*"):
        if p.is_file() and not (mounted / p.relative_to(unit)).is_file():
            raise ValueError("Staged input file missing")
    trial = run / unit_id / str(repetition)
    trial.mkdir(parents=True)
    output, grading = trial / "output", trial / "grading"
    output.mkdir()
    grading.mkdir()
    card = tomllib.loads((unit / "card.toml").read_text())
    # Build the unit's real data layout on the grader base; do not guess /app paths.
    source = (unit / "environment/Dockerfile").read_text()
    source = grader_dockerfile(source, args.grader_image)
    dockerfile = trial / "Dockerfile.grader"
    dockerfile.write_text(source)
    tag = "t1-local-grader:" + uuid.uuid4().hex
    rc = docker(
        [
            "docker",
            "build",
            "-t",
            tag,
            "-f",
            str(dockerfile),
            str(unit / "environment"),
        ],
        trial / "build.log",
        900,
    )
    if rc:
        raise RuntimeError(f"Grader image build failed; see {trial / 'build.log'}")
    name = "t1-agent-" + uuid.uuid4().hex
    grader_name = "t1-grade-" + uuid.uuid4().hex
    caps = [
        "--cpus",
        str(card["environment"]["cpus"]),
        "--memory",
        card["environment"]["memory"],
    ]
    mounts = ["-v", f"{output}:/app/output", "-v", f"{output}:/output"]
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit",
        "512",
        "--tmpfs",
        "/tmp:rw,exec,size=8g",
        "--network",
        args.network,
        *caps,
        *mounts,
        "-v",
        f"{mounted}:/input:ro",
        "-e",
        f"QFBENCH_SEED={args.seed + repetition}",
        "-e",
        "QFBENCH_NETWORK=restricted",
    ]
    for key in (
        "MODEL_ENDPOINT",
        "MODEL_NAME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "BASELINE_MAX_STEPS",
        "BASELINE_TIMEOUT_SEC",
        "BASELINE_INPUT_TOKENS",
        "BASELINE_OUTPUT_TOKENS",
    ):
        if key in os.environ:
            command += ["-e", key]
    command += [args.image, "solve", "--task-dir", "/input", "--out", "/app/output"]
    start = time.monotonic()
    try:
        try:
            rc = docker(command, trial / "agent.log", float(row["timeout_sec"]))
        except subprocess.TimeoutExpired:
            rc = 124
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        elapsed = time.monotonic() - start
        if rc in (125, 126, 127):
            raise RuntimeError(
                f"Agent container launch failed with {rc}; inspect {trial / 'agent.log'}"
            )
        grader = [
            "docker",
            "run",
            "--rm",
            "--name",
            grader_name,
            "--network=none",
            *caps,
            *mounts,
            "-v",
            f"{unit}:/input:ro",
            "-v",
            f"{grading}:/evaluation",
            "-e",
            f"AGENT_ELAPSED={elapsed}",
            "-e",
            f"AGENT_IMAGE_HASH={image_hash}",
            "--entrypoint",
            "python",
            tag,
            "/opt/evaluate_baseline.py",
            "verify",
        ]
        if docker(grader, trial / "grader.log", 1100):
            raise RuntimeError(
                f"Grader infrastructure error; inspect {trial / 'grader.log'}"
            )
        verdict = json.loads((grading / "verdict.json").read_text())
        return {
            "id": unit_id,
            "category": row["category"],
            "repetition": repetition,
            "passed": rc == 0 and verdict["admissible"],
            "agent_exit_code": rc,
            "elapsed_sec": elapsed,
            "verdict": verdict,
        }
    finally:
        subprocess.run(["docker", "rm", "-f", grader_name], capture_output=True)
        subprocess.run(["docker", "image", "rm", tag], capture_output=True)


def summarize(rows: list[dict], results: list[dict], attempts: int) -> dict:
    import numpy as np
    from qfbench2_common.scoring.passk import suite_summary
    from qfbench2_common.scoring.bootstrap import bootstrap_ci

    complete = len(results) == len(rows) * attempts
    report = {
        "scope": "public-dev; not official leaderboard",
        "complete": complete,
        "tasks": len(rows),
        "attempts_per_task": attempts,
        "completed_attempts": len(results),
    }
    if not complete:
        return report  # never turn unrun or infrastructure-aborted tasks into a score
    index = {r["id"]: i for i, r in enumerate(rows)}
    passed = np.zeros((len(rows), attempts), dtype=bool)
    for result in results:
        passed[index[result["id"]], result["repetition"]] = result["passed"]
    first = suite_summary(passed[:, :1], ks=(1,))["pass@1"]
    report.update(
        {
            "single_pass_at_1": float(first.mean()),
            "solved_first_attempt": int(first.sum()),
            "by_category": {
                c: float(
                    first[[i for i, r in enumerate(rows) if r["category"] == c]].mean()
                )
                for c in sorted({r["category"] for r in rows})
            },
        }
    )
    if attempts >= 3:
        report["offline_development"] = {
            key: {
                "mean": float(values.mean()),
                "bootstrap_ci": bootstrap_ci(values)[1:],
            }
            for key, values in suite_summary(passed, ks=(1, 3)).items()
        }
    return report


def run(args: argparse.Namespace) -> None:
    if not os.getenv("MODEL_ENDPOINT") or not os.getenv("MODEL_NAME"):
        raise ValueError(
            "Real evaluation requires MODEL_ENDPOINT and MODEL_NAME; no mock score is reported"
        )
    if args.out.exists():
        raise ValueError("Use a fresh run directory")
    roster = json.loads((args.dataset / "roster.json").read_text())
    rows = [
        r
        for r in roster["units"]
        if args.subset == "all"
        or (r["smoke"] if args.subset == "smoke" else r["partition"] == args.subset)
    ]
    if not rows:
        raise ValueError("Empty evaluation roster")
    image_hash = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", args.image], text=True
    ).strip()
    subprocess.run(
        ["docker", "network", "inspect", args.network], check=True, capture_output=True
    )
    args.out.mkdir(parents=True)
    metadata = {
        "image_hash": image_hash,
        "model": os.environ["MODEL_NAME"],
        "seed": args.seed,
        "subset": args.subset,
        "roster_sha256": hashlib.sha256(
            (args.dataset / "roster.json").read_bytes()
        ).hexdigest(),
        "baseline_overrides": {
            k: v for k, v in os.environ.items() if k.startswith("BASELINE_")
        },
    }
    write_json(args.out / "configuration.json", metadata)
    results = []
    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [
                pool.submit(attempt, args, row, rep, image_hash)
                for row in rows
                for rep in range(args.attempts)
            ]
            try:
                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    write_json(args.out / "attempts.json", results)
                    print(
                        f"{result['id']} attempt={result['repetition']} passed={result['passed']}",
                        flush=True,
                    )
            except BaseException:
                # Do not launch the rest of the roster after an infrastructure fault.
                for future in futures:
                    future.cancel()
                raise
    finally:
        write_json(args.out / "summary.json", summarize(rows, results, args.attempts))
    print((args.out / "summary.json").read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--units", type=Path, default=ROOT / "units")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--image", default="track1-iterative:latest")
    p.add_argument("--grader-image", default="track1-grader:latest")
    p.add_argument("--network", default="qfb2-eval")
    p.add_argument(
        "--subset", choices=["all", "smoke", "tuning", "validation"], default="all"
    )
    p.add_argument("--attempts", type=int, choices=[1, 3], default=1)
    p.add_argument("--jobs", type=int, choices=range(1, 17), default=1)
    p.add_argument("--seed", type=int, default=0)
    sub.add_parser("verify")
    args = parser.parse_args()
    if args.command == "verify":
        verify()
    else:
        globals()[args.command](args)


if __name__ == "__main__":
    main()
