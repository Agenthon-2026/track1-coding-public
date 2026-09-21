# Track 1 — Coding Agents · Public Starter Kit

## Executive summary (read this first)

This is the **public practice kit** for Track 1 of Agenthon 2026 (a NeurIPS competition). Track
1 asks one question: *can an AI coding agent write correct quantitative-finance code?* Participants
submit their agent as a **Docker image** — a self-contained program that accepts the verb `solve`
and writes its output to `/app/output`. The official leaderboard grades the agent on **pass@1**
with one execution per task: the share of tasks solved, over a fixed denominator, with no
confidence interval. (`pass@3` — the chance any of three attempts solves a task — is reported only
by the offline Harbor development report, not by the leaderboard.) **Track 1 ships no official
baseline agent**: you are ranked against the other entries, not against a reference agent.

**This repo contains practice tasks and examples, not answers.** The hidden evaluation tasks
and their reference solutions live in the sealed private repo, which no participant can access. Use
this starter kit to test your agent locally before submitting to the leaderboard.

> **Track 1 is QFBench.** Agenthon 2026 is QFBench 2.0, and Track 1 reuses QFBench's
> infrastructure with deliberate adjustments. If you have contributed to QFBench, read
> **[docs/QFBENCH-HERITAGE.md](docs/QFBENCH-HERITAGE.md)** first — it lists exactly what was kept
> (Harbor runner, `/app/output`, the shared base image), what changed (offline pytest, the dual
> reward artifact, `card.toml`), and the `task.toml → card.toml` field map.

**New to the concepts?** Read `docs/CONCEPTS.md` first (what is a Docker image, what is
pass@k, what are the admissibility gates). Then read `docs/CATEGORIES.md` to see what kinds of
tasks exist. For all technical terms, see the competition-wide GLOSSARY published with the
shared toolkit: `Agenthon-2026/Agenthon2026-public`, file `docs/GLOSSARY.md`.

---

## What is in this repo

| Path | Contents |
|---|---|
| `docs/QFBENCH-HERITAGE.md` | What Track 1 kept vs. adjusted from QFBench; `task.toml → card.toml` map |
| `docs/CONCEPTS.md` | Plain-English explainer of every concept a newcomer needs |
| `docs/CATEGORIES.md` | The ten task categories, with examples, invariants, and difficulty guide |
| `docs/AUTHORING-GUIDE.md` | How to design and contribute a new task (community authoring) |
| `templates/` | Blank card.toml, instruction.md, Dockerfile, and test templates to copy |
| `units/` | Practice tasks from the public-dev split; the exemplar is `t1-EXAMPLE-bs-greeks-pde` |
| `qfbench2_track_coding/scoring.py` | The verifier and pass@k scorer (what the harness runs on your agent) |
| `baselines/` | Model access and packaging rules for a Track 1 agent (no baseline agent ships) |
| `.github/workflows/` | CI: canary uniqueness, manifest checksums, public-safety scans |

## What is NOT in this repo

These live in the **sealed private repo** and are never visible to participants:

- The hidden `private-test` evaluation tasks
- Oracle `solve.sh` reference solutions
- The sealed final scorer (pass@k aggregation + failure map)
- The canary GUID registry
- Data generation and reference-output regeneration scripts

---

## How a participant uses this repo

### 1. Clone and install

```bash
git clone https://github.com/Agenthon-2026/track1-coding-public.git
cd track1-coding-public

# Install the shared scoring toolkit (inherits from the main repo).
# Pin toolkit v2.4.3 for the current submission commands and fixtures.
# The installed package reports version 2.4.2.
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.4.3#subdirectory=common"

# Make THIS repo's track package importable. `qfbench2 smoke --track coding` loads
# qfbench2_track_coding, which lives here and is not part of the toolkit; without this the
# command dies with `ModuleNotFoundError: No module named 'qfbench2_track_coding'`
# (measured 2026-08-24 on a fresh checkout).
export PYTHONPATH="$PWD"          # or: pip install -e .
```

Every `qfbench2 smoke` command below assumes that `PYTHONPATH` is set, or the repo installed.

### 2. Study the exemplar task

Read `units/t1-EXAMPLE-bs-greeks-pde/instruction.md` — this is exactly what your agent will
see during evaluation. Also read the `checks/test_outputs.py` for that unit to understand what
financial invariants the checker asserts (and therefore what your agent's output must satisfy).

### 3. Build the shared sandbox base image (once)

Every unit image is **thin**: it is `FROM finance-bench-sandbox:latest` plus the unit's `data/`.
Build that shared base **once** before running any unit. It bakes both the financial stack
(numpy/pandas/scipy/pyarrow) and the verification stack (pytest, pytest-json-report,
pytest-timeout), so units never install the standard stack themselves:

```bash
# from the public repo root
docker build -t finance-bench-sandbox:latest -f docker/sandbox.Dockerfile .
```

### 4. Understand the local verification steps

`qfbench2 smoke <unit_dir> <output_dir> --track coding` verifies deliverables that already
exist. It does not run an agent, generate answers, or build an agent image. To try this one
public exemplar without first implementing your own solver, explicitly run the
[deterministic interface example](examples/exemplar_agent/README.md) before invoking smoke.
It is not an official baseline and does not solve the other tasks. For your own agent, follow
step 6 to run it and then check its output in the sandbox.
The step 6 checker needs the unit at `/input` and the output mounted at both `/app/output` and
`/output`; a host output directory alone does not provide that layout.

Harbor is a separate, optional execution path behind the toolkit. With Harbor and your chosen
agent installed:

```bash
# Launch through the toolkit adapter, then produce an offline development report:
qfbench2 track1 harbor-run --units-dir units --jobs-dir <dir> --job-name <name>
qfbench2 track1 score-harbor-job --job-dir <dir>/<name> --units-dir units
```

The `track1` adapter shells out to Harbor. Install the toolkit's optional `track1-harbor`
extra to use it; Harbor is not required for the Docker check below. `qfbench2-smoke` is a
back-compat alias for the output verifier `qfbench2 smoke`.

### 5. Build your agent Docker image

Your agent must implement the `solve` verb and write deliverables to `/app/output` (the
QFBench/Harbor output convention):

At scoring time the harness runs your image on a **restricted** network (this is what
`network = "restricted"` in every card means): there is **no open internet** — the only
egress is through the organizer's audited proxy to the **organizer-hosted model endpoint**
(open models, free within a per-run budget) and **nothing else**. Calls to `api.anthropic.com`,
`api.openai.com`, `generativelanguage.googleapis.com` or any other vendor API **will be refused
by the proxy** (policy 2026-08-04). **No participant API keys exist**: the harness injects none
and there is no mechanism for a submission to supply one, so a vendor key would have nothing to
reach even if you had one. The harness injects the environment contract shown below. Every
connection is logged (domain, bytes, timestamps) and audited.

```bash
# Scoring-time invocation (what the harness runs — internal eval network, audited proxy):
docker run --rm --network qfb2-eval \
  -e HTTP_PROXY -e HTTPS_PROXY \
  -e MODEL_ENDPOINT \
  -e QFBENCH_NETWORK=restricted \
  -v /path/to/task/:/input:ro \
  -v /tmp/output/:/app/output \
  your-agent-image:latest \
  solve --task-dir /input --out /app/output
```

- `--task-dir /input` — the task directory (instruction.md, data files, card.toml)
- `--out /app/output` — where to write results (your Parquet/CSV/JSON output files)
- `HTTP_PROXY` / `HTTPS_PROXY` — the audited proxy; **the only route out of the container**
- `MODEL_ENDPOINT` — the origin of the organizer-hosted House route (e.g. `http://model:8443`, no path); the OpenAI-compatible API is served under `/v1`, and the per-unit bearer arrives as `MODEL_TOKEN` — see [Calling the House route](https://github.com/Agenthon-2026/Agenthon2026-public/blob/main/docs/HOUSE-MODEL.md#calling-the-house-route)
- Vendor-side tools (web search, code execution, retrieval) **must be disabled** in your API
  calls — enforced by rule and by proxy audit. Model APIs are for inference only; you still
  cannot fetch data, packages, or web pages (the `g2` data/text cutoffs are unchanged).

For a **local smoke run** without the eval network, `docker run --network=none ...` with the
same mounts still works and is what the local harness falls back to (with a warning) when the
`qfb2-eval` network does not exist — your agent just gets no model access in that mode.

The agent must write its output files to `/app/output` within that unit's time limit. The limit
is `[agent].timeout_sec` in the unit's own `card.toml` and **the card is authoritative** — it is
not the same for every unit. Across the 87 public units it ranges from 1200 to 5400 seconds;
1800 is the most common value, not a universal one.
The checker (`checks/test.sh`) runs **offline** and writes the reward signal itself — do not
write the reward files yourself.

### 6. Run your agent, then check its output

To try the exemplar before implementing your own solver, use the
[executable example](examples/exemplar_agent/README.md). It is a deterministic interface
example for one public practice task, not an official model baseline.

Run this from the repository root after building the shared sandbox in step 3. Replace
`your-agent:latest` with your image. Each run uses a fresh output directory.

```bash
set -e
UNIT="$(cd units/t1-EXAMPLE-bs-greeks-pde && pwd)"
OUT="$(mktemp -d)"

# Your agent produces the deliverables.
docker run --rm --network=none \
  -v "$UNIT:/input:ro" \
  -v "$OUT:/app/output" -v "$OUT:/output" \
  your-agent:latest solve --task-dir /input --out /app/output

# The supplied checker produces the reward artifacts.
docker run --rm --network=none \
  -e OUTPUT_DIR=/app/output -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$UNIT:/input:ro" \
  -v "$OUT:/app/output" -v "$OUT:/output" \
  finance-bench-sandbox:latest bash /input/checks/test.sh

python -c 'import json,sys; r=json.load(open(sys.argv[1])); print(r); sys.exit(0 if r.get("reward")==1 else 1)' \
  "$OUT/reward.json"
```

The final command must exit zero and report `reward: 1.0`. `test.sh` itself exits zero even
when checks fail, so its exit status alone is insufficient; inspect `pytest_report.json`
for failed or skipped checks. The two output mounts bind the same host directory because
public units use both paths.

This is an offline local check. It provides no house-model access and does not exercise the
official resource limits, attestation or CodaBench submission path. There is no `--agent-image`
option on `qfbench2 smoke`; the first Docker command above runs the agent.

### 7. Submit to the leaderboard

Push your `linux/amd64` image to a registry that allows anonymous pulls by digest, write
`submission.json` with that digest, and pack the upload with the toolkit:

```bash
qfbench2 submission pack --descriptor submission.json --team-number <your team number> --out submission.zip
```

Then upload `submission.zip` on the track's CodaBench competition page from your team's
designated CodaBench account. The page link was issued to registered teams at the Development
opening and is in the participant announcements. `SUBMISSION_CLI.md` in this repo documents the
image contract and the upload mechanics ("How an upload is made"), and the hub's
[team-claim guide](https://github.com/Agenthon-2026/Agenthon2026-public/blob/v2.4.3/starter-packs/track1/TEAM-CLAIM.md)
explains the `team-claim.json` the zip carries.

---

## The submission format: the `solve` verb

Your Docker image must accept exactly this command-line interface:

```
solve --task-dir <path> --out <path>
```

| Argument | What it points to | Your agent should... |
|---|---|---|
| `--task-dir` | The task directory (read-only) | Read `instruction.md` and data files from here |
| `--out` | The output directory (`/app/output`, writable) | Write all required output files here |

**Do not write the reward files.** After your agent finishes, `checks/test.sh` runs offline
(`python -m pytest`) and writes the reward signal in two forms: `/logs/verifier/reward.txt`
(Harbor, `1`/`0`) and `<output>/reward.json` + `pytest_report.json` (Agenthon g0–g3 verifier +
the DI failure-label overlay). You produce only your deliverables under `/app/output`.

The `solve` verb name is fixed and universal across all Track 1 tasks. Do not invent a
different verb name — the harness will not recognise it.

---

## How scoring works (brief)

The harness runs four sequential admissibility gates on each attempt:

| Gate | Checks |
|---|---|
| `g0_integrity` | Task manifest checksums are correct |
| `g1_schema` | `<output>` holds at least one deliverable; `reward.json`, if present, is well-formed (it is optional: `checks/` is sealed, so a participant container normally cannot write it) |
| `g2_cutoff_resource` | Agent finished within time limit; no canary GUID emitted |
| `g3_domain_semantics` | Pytest test suite passed; financial invariants hold |

Only an attempt that passes all four gates earns `score = 1.0`. The leaderboard ranks by mean
pass@1 over one execution per task with a fixed denominator (a wrong, crashed, timed-out or
missing output stays in the denominator as zero); it publishes no confidence interval. The Harbor
adapter's pass@3 with bootstrap CIs is an offline development report, not the official aggregate.

The cards' `k_values = [1, 3]` is offline development metadata: any pass@3 figures in an offline
report are not official leaderboard scores and do not change the signed single-pass plan.

**There is no official baseline agent.** Track 1 ranks entries against each other on mean pass@1
over the hidden `private-test` split; there is no reference score you must clear to be admitted.
`baselines/` documents how an agent reaches a model and how it must be packaged — not an agent to
beat.

Full scoring code is in `qfbench2_track_coding/scoring.py`. It inherits all shared logic from the
`qfbench2-common` toolkit. Install it with:

```bash
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.4.3#subdirectory=common"
```

---

## Checking additional public tasks

Repeat step 6 for each task you want to practice, changing `UNIT` to that task's directory.
Use a fresh `OUT` each time and retain the resulting reward and pytest report. Your agent must
produce that task's required deliverables before its checks can run; the toolkit does not
supply answers or a mock solve. Runtime depends on your agent and the selected tasks.

---

## Competition rules (summary)

1. **Restricted network — house endpoint only.** Submissions run with **no open internet**. The
   only egress is through the organizer's audited proxy to the organizer-hosted model endpoint
   (`$MODEL_ENDPOINT`) and **nothing else**; `api.anthropic.com`, `api.openai.com`,
   `generativelanguage.googleapis.com` and every other vendor API are **refused by the proxy**
   (policy 2026-08-04), and no participant API keys exist. Vendor-side tools (web search, code
   execution, retrieval) must be disabled. Fetching data, packages, or web pages is impossible.
   Every connection is logged and audited. Model versions must be pinned (dated snapshots) and
   each model's training cutoff disclosed in the submission metadata; temperature/seed pinned
   where the API supports it. Every submission runs against the House model: `category` is
   `api` (house endpoint only; your contribution is the prompts/harness). **Bring-your-own
   models and adapters are not part of this competition** (ruling of 2026-09-18); the former
   `byo-large` / `byo-small` values are invalid since toolkit 2.4.3, and an upload that still
   carries one is held and never run. Every entry is tagged with its category, pinned models,
   and training cutoffs. See [`SUBMISSION_CLI.md`](SUBMISSION_CLI.md). **The model budget is
   requests per unit:** House use is limited to **25 admitted requests per unit**, with **at most
   4,000 output tokens per request**, both counted by the House route; admitted failures and
   retries count. There is no per-unit token allowance — the earlier figure of 1,000,000 input
   plus 100,000 output tokens per unit is withdrawn and nothing replaces it. See the
   [request-accounting rules](SUBMISSION_CLI.md#rules-for-model-api-use-restricted-mode).
2. **Docker image.** CLI verb: `solve --task-dir /input --out /app/output`.
3. **Time limit.** Per task, declared by `[agent].timeout_sec` in that unit's card; the card is
   authoritative. The value varies by unit — across the 87 public units it ranges from 1200 to
   5400 seconds (20 to 90 minutes): 63 units at 1800, 18 at 2400, 4 at 3600, one at 1200 and one
   at 5400. `[verifier].timeout_sec` (the checker's budget, after your agent exits) and
   `[environment].build_timeout_sec` (the image build) are separate fields with their own values;
   do not read either as the agent's limit.
4. **Resources.** A 16-CPU quota, 128 GiB RAM, and GPU access for permitted local code.
   Every unit card declares this in `[environment]` (`cpus = 16`, `memory = "128G"`, `gpu = true`); the card is authoritative.
   The `api` category does not remove its GPU grant. See the
   [Development runtime guide](https://github.com/Agenthon-2026/Agenthon2026-public/blob/v2.4.3/docs/DEVELOPMENT-RUNTIME.md)
   for the separate unit, platform-stage and House deadlines, temporary space and output limits,
   and the [image guide](https://github.com/Agenthon-2026/Agenthon2026-public/blob/v2.4.3/docs/IMAGE-SUBMISSIONS.md)
   for public pulls and organizer-confirmed private mirrors. Final resources are announced separately.
   The planned House timing release activates each unit once when the organizer begins that unit's execution setup. Queue waiting and earlier units do not spend its window, while setup/provisioning and
   container creation/execution after activation can. The card/fallback ceiling and remaining
   actual ingestion-stage time cap its fixed end; restart/retry does not renew the window or
   counters. Deployment and verification remain required before opening; no compute grant grows.
5. **Metric.** Mean pass@1, one execution per task, fixed denominator, no confidence interval.
   (pass@3 with bootstrap CIs exists only in the offline Harbor report.)
6. **Baseline.** None. Entries are ranked against each other on pass@1 over the `private-test` split.
7. **Data cutoff.** Each task card declares a `data_cutoff`; agents must not use data beyond it.
8. **Your own solutions to public units may travel in your image.** An image may carry your
   team's own solutions to public Development units and use them as in-context examples when it
   solves other units — that is part of the prompts/harness, in Development and in the Final
   alike. The canary rule is unchanged: the g2 gate flags any canary GUID from the registry that
   appears in an agent's output file, not only the target unit's, and that is a
   `CONTAMINATION_CANARY` disqualification. If you carry unit material, it is on you that no
   canary from it reaches an output.

**Where the full rules live.** There is no separate rules website. The rules that bind a Track 1
submission are the seven points above, plus:

- [`SUBMISSION_CLI.md`](SUBMISSION_CLI.md) — the image contract, the network and model-access
  rules, submission categories, and the reproducibility requirements.
- [`docs/CONCEPTS.md`](docs/CONCEPTS.md) — the sandbox, the admissibility gates, and the metric.
- each unit's `card.toml` — the per-unit limits, which are authoritative wherever prose and card
  disagree.

The track's CodaBench competition page carries the submission mechanics and any dated
amendments. If a statement here and one there conflict, the CodaBench page and the card win, and
the difference is a bug worth reporting on the issue tracker.

---

## The firewall: no answers here

This public repo contains **zero** answer material for anything that counts toward the
ranking. The rule is tiered by unit split (enforced by `assert_public_safe` in CI):

**Never committed here, for any unit:**

- Reference solutions (`solution/`, `solve.sh`, `oracle_*`, `answer_key*`, `dev/`)
- The canary GUID registry (which maps GUIDs to task IDs)
- The final scorer that aggregates pass@k across the private-test split

**Also banned for any non-`public-dev` unit:**

- Answer-bearing material such as `reference/`, `expected*`, `outcome*.json`

**Allowed for `public-dev` practice units only:** reference *values* under
`checks/reference_data/` (e.g. `checks/reference_data/expected.json`), so students can
self-grade on practice tasks. The held-out targets that determine the ranking live only in
the private scorer.

If you ever find any of the above in this repo, report it immediately to
`qfbench@neurips2026.org` — it means the firewall has been breached.

## Competition schedule and submission limits

Development runs through **October 12, 2026**. The joint **Final + Verification phase runs
October 13–25, 2026**. Each team makes **one final submission per track**; organizers perform
verification within that same phase, with no separate participant Verification submission.
If two Final submissions finish this track with the same ranking score, the tie is broken in
favour of the one uploaded earlier.
Registration and Development close together on October 12, 2026 at **23:59 Anywhere on Earth (AoE, UTC−12)**. The joint Final + Verification phase closes on October 25, 2026 at **23:59 AoE**. Other competition dates and task/data cutoffs are unchanged.

At the participant Development opening, Track 1 allows **1 upload per team per day**
and **20 total uploads per team for this track during Development**. Use your team's single
designated CodaBench account. Local validation and packaging use no attempts; held or cancelled
uploads still count. See [submission limits](SUBMISSION_CLI.md#development-submission-limits).
