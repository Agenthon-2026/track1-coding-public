# Track 1 — Coding Agents · Public Starter Kit

## Executive summary (read this first)

This is the **public practice kit** for Track 1 of Agenthon 2026 (a NeurIPS competition). Track
1 asks one question: *can an AI coding agent write correct quantitative-finance code?* Participants
submit their agent as a **Docker image** — a self-contained program that accepts the verb `solve`
and writes its output to `/app/output`. The agent is graded on **pass@1** (the chance its first
attempt solves a task) and **pass@3** (the chance any of three attempts solves it). The baseline
to beat is **FinanceZero**, a simple single-call language-model agent.

**This repo contains practice tasks and examples, not answers.** The ~30 hidden evaluation tasks
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
| `baselines/` | The FinanceZero baseline — package a single LLM call; your target to beat |
| `.github/workflows/` | CI: canary uniqueness, manifest checksums, public-safety scans |

## What is NOT in this repo

These live in the **sealed private repo** and are never visible to participants:

- The ~30 hidden `private-test` evaluation tasks
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

# Install the shared scoring toolkit (inherits from the main repo)
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.3.1#subdirectory=common"

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

### 4. Smoke-test the exemplar

The smoke runner builds the thin unit image, runs a mock solve, then runs the checks
**offline** (`python -m pytest`, no network) and writes the reward artifacts. Track 1 units
run under **both** runners:

```bash
# Agenthon harness (g0–g3 verifier + reward.json):
qfbench2 smoke units/t1-EXAMPLE-bs-greeks-pde <output_dir> --track coding

# or under Harbor (QFBench-native; reward in /logs/verifier/reward.txt):
harbor run --path units --task-name t1-EXAMPLE-bs-greeks-pde --agent <agent> --model <model>

# or via the qfbench2 Harbor adapter — launch a job, then score official pass@1/pass@3:
qfbench2 track1 harbor-run --units-dir units --jobs-dir <dir> --job-name <name>
qfbench2 track1 score-harbor-job --job-dir <dir>/<name> --units-dir units
```

`qfbench2-smoke` is kept as a back-compat alias for `qfbench2 smoke`. The full CLI is `smoke`,
`card`, `manifest`, `eval`, and `track1`. The `track1` adapter wraps
`qfbench2_common.track1.harbor`, which shells out to harbor (never imports it), so the core
toolkit runs on Python 3.13 with harbor absent; the optional `track1-harbor` extra
(`harbor>=0.15.0`, whose Python>=3.12 floor 3.13 already meets) is only for an operator running
the Harbor path. If the mock
solve passes, your local setup is correct.

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
- `MODEL_ENDPOINT` — the organizer-hosted OpenAI-compatible endpoint (e.g. `http://model:8000/v1`), when available
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

### 6. Run the local smoke test on your own agent

```bash
qfbench2 smoke units/t1-EXAMPLE-bs-greeks-pde <output_dir> --track coding --agent-image your-agent:latest
```

This runs your Docker image against the exemplar's checks and reports pass/fail.

### 7. Submit to the leaderboard

Push your Docker image to a container registry (e.g. Docker Hub, AWS ECR) and register the
image URL on the track's CodaBench competition page. The submission interface and the full
submission instructions are published there; the competition page link is announced on the
competition website and in the participant announcements, and `SUBMISSION_CLI.md` in this repo
documents the image contract the page expects.

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
| `g1_schema` | `<output>/reward.json` exists and is well-formed |
| `g2_cutoff_resource` | Agent finished within time limit; no canary GUID emitted |
| `g3_domain_semantics` | Pytest test suite passed; financial invariants hold |

Only an attempt that passes all four gates earns `score = 1.0`. The leaderboard ranks by mean
pass@1 (primary) and mean pass@3 (secondary), both with 95% bootstrap confidence intervals.

The baseline to beat is **FinanceZero** (see `baselines/`). On the hidden `private-test` split,
your agent must achieve a higher mean pass@1 than FinanceZero to be considered competitive.

Full scoring code is in `qfbench2_track_coding/scoring.py`. It inherits all shared logic from the
`qfbench2-common` toolkit. Install it with:

```bash
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.3.1#subdirectory=common"
```

---

## Running the full smoke test suite

First build the shared base once (`docker build -t finance-bench-sandbox:latest -f
docker/sandbox.Dockerfile .`), then run all public-dev tasks through the smoke test (takes
~5–20 minutes):

```bash
for unit in units/*/; do
    echo "=== $unit ==="
    qfbench2 smoke "$unit" /tmp/smoke-out --track coding
done
```

Or target a specific task:

```bash
qfbench2 smoke units/t1-EXAMPLE-bs-greeks-pde /tmp/smoke-out --track coding
```

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
   where the API supports it. Two ways to submit — `api` (house endpoint only; your contribution
   is the prompts/harness) and BYO (you ship a **LoRA adapter of rank ≤ 64**, never model
   weights and never a model server, and the organizer serves the base model with your adapter
   loaded) — share one leaderboard; every entry is tagged
   with its category, pinned models, and training cutoffs. In `submission.json` a BYO entry
   declares `byo-large` or `byo-small` — they are legacy names for the same thing, both still
   accepted by the descriptor enum. There is no small-weights tier. See [`SUBMISSION_CLI.md`](SUBMISSION_CLI.md) for the
   adapter contract. A uniform per-unit model-API budget
   applies (**provisional: 1,000,000 input + 100,000 output tokens per unit — finalized before
   the dev phase opens**).
2. **Docker image.** CLI verb: `solve --task-dir /input --out /app/output`.
3. **Time limit.** Per task, declared by `[agent].timeout_sec` in that unit's card; the card is
   authoritative. The value varies by unit — across the 87 public units it ranges from 1200 to
   5400 seconds (20 to 90 minutes): 63 units at 1800, 18 at 2400, 4 at 3600, one at 1200 and one
   at 5400. `[verifier].timeout_sec` (the checker's budget, after your agent exits) and
   `[environment].build_timeout_sec` (the image build) are separate fields with their own values;
   do not read either as the agent's limit.
4. **Resources.** 16 vCPUs, 128 GB RAM, GPU available. Every unit card declares this in
   `[environment]` (`cpus = 16`, `memory = "128G"`, `gpu = true`); the card is authoritative.
5. **Metric.** Mean pass@1 (primary), mean pass@3 (secondary), 95% bootstrap CIs.
6. **Baseline.** Beat FinanceZero on pass@1 over the `private-test` split.
7. **Data cutoff.** Each task card declares a `data_cutoff`; agents must not use data beyond it.

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
