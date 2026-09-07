# Iterative participant baseline

This is a participant harness, not an organizer baseline or a measured performance
claim. It solves from each task's instruction and data, without task-ID routing,
reference values, access to grading tests, or third-party inference endpoints.

The agent inspects inputs, writes and executes Python, repairs runtime failures,
then starts a fresh-context audit which must execute before it can finish. It
retains the last successfully generated deliverables if a later refinement crashes.
Prompts cover financial conventions, numerical stability, independent checks,
data alignment, and exact deliverable schemas. All inference goes to
`MODEL_ENDPOINT` with `MODEL_NAME`; JSON actions are executed locally, with no
vendor-side tools. Generated code must run inside an isolated container.

## Build

From the repository root, with Python 3.13 and the pinned shared toolkit installed:

```bash
docker build -t finance-bench-sandbox:latest -f docker/sandbox.Dockerfile .
docker build -t track1-iterative:latest -f baselines/iterative/Dockerfile .
docker build -t track1-grader:latest -f baselines/iterative/grader.Dockerfile .
```

The agent image copies only this baseline directory. The separate grader image
contains the shared toolkit at `v2.3.1` and the repository scorer. The baseline uses
`requests` already provided by the sandbox. Standard dependencies inherit the
organizer's base; record the built image digest to reproduce an evaluation.

## Build the local evaluation set

```bash
python scripts/evaluate_baseline.py prepare --out /tmp/t1-dataset
```

This calls `scripts/build_dev_dataset.py`, retaining answers only in the grader
tree and removing `checks/` and `reference/` from the agent tree. The agent refuses
raw public units containing either directory. Keep the generated dataset and runs
outside the source tree. The roster contains all 87 public tasks and their manifest
digests plus hashes of both full trees (including instructions and grading code).
Deterministic SHA-256 ordering within each **actual card category** assigns
positions 2, 5, 8, ... to validation, the rest to tuning, and the first task per
category to smoke. Smoke is entirely inside tuning and never overlaps validation.
There are 34 category strings in the current cards, giving 34 smoke tasks, 62 tuning
tasks and 25 validation tasks. These public partitions are development data; they
do not estimate performance on unseen official tasks without further evaluation.

## Measure

Configure the organizer-provided `MODEL_ENDPOINT`, pinned `MODEL_NAME`, and proxy
variables. The default `qfb2-eval` Docker network must already have model access.
The script fails when configuration is missing instead of assigning a model score.

```bash
python scripts/evaluate_baseline.py run \
  --dataset /tmp/t1-dataset --out /tmp/t1-run \
  --image track1-iterative:latest --subset all --attempts 1 --jobs 1
```

Use `--subset smoke`, `tuning`, or `validation` for iteration. Keep validation
results separate from tuning and freeze the image before validation. For the
offline multi-attempt report use `--attempts 3` and a fresh output directory.
`--network` can select a local house-model test network; it does not establish or
audit a restricted network. Official egress controls remain the organizer's job.

Each agent gets the sealed input and a fresh output volume in a read-only container,
with per-card CPU/memory/time limits. Each separate grader container gets the
unit's original Docker `COPY`/`WORKDIR` data layout, full task and output volume;
it has no network. Grading dependencies come from the shared base and toolkit,
without replaying legacy unit installers (such as the exemplar's Python-3.13-
incompatible `numba==0.60.0` pin; see the
[Numba compatibility table](https://numba.readthedocs.io/en/stable/user/installing.html#version-support-information)).
It calls `qfbench2_track_coding.scoring.build_verifier` directly and writes reward
artifacts. The evaluator does not infer correctness from the agent's own claims.

`summary.json` reports single-attempt pass@1 over the complete selected roster.
Crashes and timeouts remain failures. Infrastructure errors make the report
incomplete and suppress the score. Repeated runs additionally call shared
`suite_summary` and `bootstrap_ci` for the **offline** pass@1/pass@3 report.
`attempts.json`, per-attempt logs and `configuration.json` record provenance and
failures. No numeric test fraction is substituted for the all-gates pass verdict.

The installed toolkit's `qfbench2 smoke` checks **existing outputs**; version 2.3.1
does not accept `--agent-image`, despite older README examples. The container
runner above runs the agent and handles hardcoded `/app` paths before grading.

## Budget controls

Defaults: 32 actions, 8,192 tokens per model response, 800,000 input and 90,000
output token allowance, and the card timeout minus 15 seconds for cleanup.
`BASELINE_MAX_STEPS`, `BASELINE_TIMEOUT_SEC`, `BASELINE_INPUT_TOKENS` and
`BASELINE_OUTPUT_TOKENS` override these within the official token/time caps.
Temperature is zero and `QFBENCH_SEED` is forwarded to inference and local code.

Requests reserve a conservative UTF-8 byte-based input estimate plus framing;
actual completion usage releases unused output reservation. Requests with uncertain
outcomes retain their reservation. Retries, executions and descendants are bounded.
This may stop earlier than the organizer's tokenizer would require; it is deliberate
budget headroom. The organizer's audited accounting is authoritative.

## Submit

Push the tested agent image to your chosen registry, record its **registry digest**,
then create `submission.json` using the actual team, competition and model metadata:

```bash
python scripts/package_baseline.py --help
```

The packaging command requires every disclosure and validates the descriptor and
its canonical digest with the shared C5 contract. It does not invent model training
cutoffs or registry digests. Upload that descriptor through the competition's
published submission interface. Code contributions go through a branch and PR.

## Tests and current measurements

```bash
python -m pytest tests/test_iterative_baseline.py tests/test_scoring_bypass.py -q
```

The baseline tests use invented arithmetic and fake inference responses to check
repair, auditing, timeouts, isolation, budgets and reporting. They are infrastructure
tests, not task-solving results. See `validation.md` for the actual execution record.
