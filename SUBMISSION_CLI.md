# QFBench 2.0 — Published Submission CLI Contract (`interface_version = 2.0`)

A submission is a **Docker image**. The organizer runs it in the sealed scoring environment;
the image must implement the track verb below. The harness invokes the image, the image reads
from a read-only input mount, writes to an output mount, and **exits 0** on success.

```
docker run --rm \
  --network=none|qfb2-eval \             # "none" (simulation) or the internal eval network (agent tracks) — see "Network modes"
  --cpus=<card.cpus> --memory=<card.memory> [--gpus all] \
  -v <unit-dir>:/input:ro \              # read-only inputs — the UNIT DIRECTORY itself is mounted at /input
  -v <run>/output:/output \              # outputs (deliverables + logs); a normal read-write bind
  [-v <run>/output:/app/output] \       # T1 ONLY: the same host dir, also at the QFBench path (see invariant 8)
  <SUBMISSION_IMAGE> <verb> [args]
```

**The verb is the container command.** It arrives as the first argument after the image
reference, so your image must either resolve it from `PATH` (build with no `ENTRYPOINT` — the
Track 3 reference baseline does this, shipping `simulate` and `simulate-batch` as executables)
or consume it as a leading positional (the `ENTRYPOINT ["python", "agent.py"]` pattern, where
`agent.py` declares `parser.add_argument("verb")`). An image that does not accept the verb fails
every unit — as `127` if the verb is not on `PATH`, as `126` if it is present but not executable,
or as whatever your own argument parser exits with if it consumes and rejects it. All three are
recorded as **your** failure, not an organizer fault, and score zero on that unit.

The harness logs `sha256(image)` (anti-cheat), applies the card's CPU, memory, GPU and network
settings, and mounts only files whose `manifest.json` checksum matches.
`LABEL qfbench2.interface_version="2.0"` is required on the image.

For Development, Coding and Explainability take the per-unit timeout from `[agent].timeout_sec`;
Forecasting and Simulation use the launcher's 1,800-second fallback where no timeout is supplied.
The unit clock includes container creation and an image pull when needed. The ingestion stage
runs units sequentially within a separate 43,200-second (12-hour) platform clock; scoring has
its own stage clock. In the planned timing release, a House unit activates once when the organizer begins that unit's execution setup. Its fixed end is capped by the card/fallback unit ceiling and
the remaining actual ingestion-stage time. Queue waiting and earlier units do not spend its own
window; setup/provisioning and container creation/execution after activation can. Restarting or
retrying under the same allocation resets neither the window nor request counters. Credentials
last at most 7,200 seconds from issue and never beyond that fixed end. Deployment and verification
remain required before opening; this changes no compute allowance.
See the [Development runtime guide](https://github.com/Agenthon-2026/Agenthon2026-public/blob/v2.4.3/docs/DEVELOPMENT-RUNTIME.md)
for applied limits and pending access status. Development settings do not certify Final resources.

Build a `linux/amd64` image identified by its immutable digest. Follow the
[image submission guide](https://github.com/Agenthon-2026/Agenthon2026-public/blob/v2.4.3/docs/IMAGE-SUBMISSIONS.md)
for anonymous public pulls and the organizer confirmation required before using a private mirror.
A descriptor category or image-access field does not itself make a service available.

## How an upload is made

An upload is a **zip, not an image reference**. Push your `linux/amd64` image to a registry that
allows anonymous pulls by digest (the image submission guide above), write `submission.json`
with that digest (the sealed descriptor, see the
[descriptor guide](https://github.com/Agenthon-2026/Agenthon2026-public/blob/v2.4.3/starter-packs/track1/SUBMISSION-DESCRIPTOR.md)),
then let the toolkit seal and pack it:

```bash
qfbench2 submission pack --descriptor submission.json --team-number <your team number> --out submission.zip
```

`pack` asks for your Team Key on a hidden prompt, derives your `team_id`, and writes
`submission.zip` containing `submission.json` and `team-claim.json` -- the
[team-claim guide](https://github.com/Agenthon-2026/Agenthon2026-public/blob/v2.4.3/starter-packs/track1/TEAM-CLAIM.md)
explains the claim and what happens when it is wrong. Upload `submission.zip` on this track's
CodaBench competition page from your team's designated CodaBench account; the page link was
issued to registered teams at the Development opening and is in the participant announcements.
The Team Key never goes into the zip and is never sent to anyone.

## Development submission limits

At the participant Development opening, **Track 1 allows 1 upload per team per day**,
with **20 total uploads per team for this track during Development**. Upload through your
team's single designated CodaBench account. Held or cancelled uploads count even when they
receive no score; local validation and packaging use no attempts. An upload the platform marks
`Failed` does not consume an attempt — the platform's daily count excludes it. Track 1 has a 1-per-day limit;
Tracks 2, 3 and 4 retain 5 per day.

Development runs through **October 12, 2026**. The joint **Final + Verification phase runs
October 13–25, 2026**. Each team makes **one final submission per track**; organizers perform
verification within that same phase, with no separate participant Verification submission.
Registration and Development close together on October 12, 2026 at **23:59 Anywhere on Earth (AoE, UTC−12)**. The joint Final + Verification phase closes on October 25, 2026 at **23:59 AoE**. Other competition dates and task/data cutoffs are unchanged.
See the [Development submission limits](https://github.com/Agenthon-2026/Agenthon2026-public/blob/main/docs/DEVELOPMENT-RUNTIME.md#submission-limits-at-the-development-opening).

## Network modes (per unit card, `[environment].network`)

There are exactly two network modes; every unit card declares one. **There is never open
internet** in official scoring.

| Mode | Who | Meaning |
|---|---|---|
| `none` | **Simulation (T3)** | Fully offline (`--network=none`). Exactly the historical closed-resource behavior; any attempted outbound connection fails the run. |
| `restricted` | **Agent tracks (T1 coding, T2 forecasting, T4 Explainability)** | No open internet. Egress **only** through the organizer's audited proxy to the **organizer-hosted model endpoint** given by `MODEL_ENDPOINT` (open models, free to use, per-run budget). Every connection is logged (domain, bytes, timestamps); the log is the audit artifact for verification within the joint Final + Verification phase. |

> ### ⚠️ Agent tracks: there is no third-party model-API access
>
> Read this before you design your agent. (Track 3 is unaffected — it runs fully offline.)
>
> The proxy allowlist contains the organizer-hosted endpoint and **nothing else**. Calls to
> `api.anthropic.com`, `api.openai.com`, `generativelanguage.googleapis.com` or any other vendor
> API **will be refused by the proxy**, and there is no route around it: the eval network is
> `--internal`, so the proxy is the only path off the host.
>
> There is one model access: the **House endpoint** — call `$MODEL_ENDPOINT/v1/chat/completions`
> with `MODEL_NAME` and the `MODEL_TOKEN` bearer (see `docs/HOUSE-MODEL.md` in the hub). Free,
> metered per run. **Bring-your-own models and adapters are not part of this competition**
> (ruling of 2026-09-18): no LoRA adapter path, no in-image model weights path, nothing fetched
> at run time.
>
> **No participant API keys exist.** The harness injects none and there is no mechanism for a
> submission to supply one, so a vendor key would have nothing to reach even if you had one.

Data and text cutoffs (gate `g2_cutoff_resource`) are unchanged and still enforced by the harness
in both modes — network access is for **model calls only**, never for fetching data.

### Submission categories (agent tracks only)

Track 3 (simulation) sits outside these categories: submissions are simulators and the network
stays `none`. For the agent tracks, every submission declares one category in `submission.json`:

| Category | What you bundle | Model access | Compute tier |
|---|---|---|---|
| `api` | prompts / harness / system-prompts / agents (your contribution is the scaffolding) | the **house endpoint only**, via the proxy | the task card's CPU and GPU grant |

**Every submission runs against the House model.** Submitting your own model or adapter is not
part of this competition, so `api` is the category for every agent-track entry (if your agent
calls no model at all, declare `api` and leave `models` empty). The former `byo-small` /
`byo-large` values are invalid since toolkit 2.4.3 (`CATEGORIES = ("api", "simulator")` in
`qfbench2_common.contracts.descriptor`): `qfbench2 submission pack` refuses them, and an upload
that still carries one is held by the organizer's intake and never run.

`gpu = true` on a task card grants a device for permitted local code. The `api` category denotes
House access and does not remove that GPU grant. This does not authorize an additional model
server or change the adapter eligibility rules above.

### Container environment contract (`restricted` mode, set by the harness)

| Variable | Value |
|---|---|
| `HTTP_PROXY` / `HTTPS_PROXY` | the audited egress proxy. **Read these from the environment; never hardcode a proxy host** — the address is an operational detail and it has changed. Most HTTP clients honour them automatically |
| `NO_PROXY` | hosts that must bypass the proxy |
| `MODEL_ENDPOINT` | the **origin** of the organizer-hosted House route (`scheme://host:port`, no path). The OpenAI-compatible API is served under `/v1`: `POST $MODEL_ENDPOINT/v1/chat/completions`. `$MODEL_ENDPOINT/chat/completions` (no `/v1`) is refused with 403. This is the **only** model API you can reach |
| `MODEL_NAME` | the pinned house-model id served at `MODEL_ENDPOINT` (use it in your client calls; published with the model pin) |
| `MODEL_TOKEN` | the per-unit bearer credential. Send `Authorization: Bearer $MODEL_TOKEN` on every request; without it the route answers 401. With the OpenAI client: `OpenAI(base_url=os.environ["MODEL_ENDPOINT"].rstrip("/") + "/v1", api_key=os.environ["MODEL_TOKEN"])`. Full contract: [Calling the House route](https://github.com/Agenthon-2026/Agenthon2026-public/blob/main/docs/HOUSE-MODEL.md#calling-the-house-route) |
| `QFBENCH_NETWORK` | `restricted` (or `none` for simulation / local fallback) |

### Rules for model-API use (`restricted` mode)

1. **Vendor-side tools OFF.** Web search, code execution, retrieval, and any other vendor-side
   tool MUST be disabled in every API call. Enforced by rule + audit of the proxy logs.
2. **Pin model versions.** The house endpoint serves a pinned model id (`MODEL_NAME`). Floating
   aliases (`*-latest`) are not reproducible and are rejected at verification.
3. **Disclose training cutoffs.** The training cutoff of every model used MUST be declared in
   submission metadata (`models[].training_cutoff` in `submission.json`).
4. **Pin temperature/seed** where the API supports it. Entries are verified
   *statistically* (bootstrap-CI overlap on organizer rerun for T2/T3/T4; for T1, the single-pass
   per-unit verdicts must agree exactly).
5. **House API allocation — the budget is requests per unit.** The House allowance is
   **25 admitted requests per unit**, with **at most 4,000 output tokens per call**; both are
   counted and applied by the House route. Omitted output limits use 4,000; larger limits are
   reduced to 4,000, and smaller valid limits are preserved. Multiple generated alternatives are
   refused. **There is no per-unit token allowance** — the earlier figure of 1,000,000 input plus
   100,000 output tokens per unit is withdrawn and nothing replaces it. An admitted request is
   charged before forwarding: upstream failures or a lost response do not refund it. An admitted
   participant or SDK retry can consume another slot, even with the same content. Invalid requests
   refused before admission do not consume a slot. Budget automatic retries. Platform availability
   and deployment status will be announced separately.

**One leaderboard.** All categories rank on a single board; every entry is tagged with its
category, the models used (pinned versions), and their training cutoffs.

| Track | Verb | Inputs (under `/input`) | Required output (under `/output`) |
|---|---|---|---|
| **T1 Coding** | `solve --task-dir /input --out /app/output` | task spec + environment files | task-specified deliverables written to **`/app/output`** (QFBench/Harbor convention); the `checks/` step asserts correctness and writes **both** `reward.txt` and `reward.json` (see T1 note below) |
| **T2 Time-Series Forecasting** | `forecast --panels /input/panels/ --text /input/text/ --asof <YYYY-MM-DD> --out /output/forecast.parquet` | `panels/` — multivariate time-series parquet files; `text/` — time-stamped text corpus (news, FOMC, macro releases); all timestamps must be ≤ `--asof` (gate g2 enforces both) | joint predictive distribution conforming to `forecast.schema.json`; sidecar `forecast_meta.json` required; **`forecast_rationale.md` required and never scored** (see T2 note below) |
| **T3 Simulation** (single scenario) | `simulate --config /input/scenario.json --out /output/trace.parquet` | scenario config + ABIDES environment | message-level trace conforming to `sim_scenario.schema.json` + `events.json` (counts/timing) |
| **T3 Simulation** (batched, family GB) | `simulate-batch --batch-dir /input/scenarios --out-dir /output` | `batch.json` — the sub-scenario roster; `scenarios/` — one config per sub-scenario. These units have **no** top-level `scenario.json`. | one output subdir per sub-scenario, each with `trace.parquet` + `events.json`, plus `batch_events.json` at the root of `--out-dir` |
| **T4 Tabular Prediction** | `analyze --task /input/task.json --corpus /input/corpus/ --out /output/answer.json` | `task.json` — tabular dataset (rows = entities) + target column spec + `target_type` (classification/regression/ranking); `corpus/` — frozen evidence corpus | prediction + interval + citations per row conforming to `analysis.schema.json`; `target_type` in output must match card |

> **T2 status (2026-08-20).** The unit-layout half of this is closed: `--panels` names the STAGED
> unit's `panels/` directory. `stage_bundle.py` relocates root panels into `panels/` and its S6
> gate refuses to emit a unit whose `panels/` is empty, and participant containers mount the
> staged tree, never the raw repo. Verified by execution: `--panels /input/` dies with "no
> .parquet found"; `/input/panels/` scores the full chain. The interface half ships in `track2-forecasting-public` — a `forecast`
> CLI, a console-script entry point and a `Dockerfile`, built and run on linux/arm64 (GH200) and
> admitted by g0–g3 against the exemplar unit under `--network=none`.

> **T2 note — `forecast_rationale.md`.** Alongside `forecast.parquet` a submission writes
> `forecast_rationale.md` to `/output`: the derivation behind the distribution. Numbered steps —
> the anchor, each adjustment with its size and what supports it, then the scale and shape —
> naming the series and dates computed from and the documents cited, and ending with an
> adjustment ledger so the arithmetic can be followed.
>
> **It is required and it is never scored.** No submission is ranked higher or lower because of
> this file; `g1_schema` checks only that it exists and is non-empty, and no scoring code reads
> its content. It exists because a submission that recalled its answer and one that derived it
> are indistinguishable as a set of draws, so the parquet alone cannot support any review at all.
>
> It is read as a **screen over the top of the leaderboard**, not a gate: a flag opens a human
> review and cannot by itself produce a DNF or move a score. That restriction stands until a
> false-positive rate has been measured on a large honest corpus — the current measurement is
> 4/4 true positives and 0/4 false positives, and 0-of-4 carries a 95 % interval reaching ~0.6.
> Two alternative mechanisms were tested and rejected: re-executing the trace (backward-built
> traces reproduced *more* exactly than honest ones, so as a gate it favours the cheater) and
> scanning the text for leakage admissions (a guarded prompt drove self-declaration from 100 % to
> 0 % with no change in the numbers). Method and data:
> `track2-forecasting-public/docs/RATIONALE-REVIEW.md`.

**Your image must implement BOTH Track 3 verbs.** The harness picks the verb per unit, from the
unit's contents: a unit carrying `batch.json` + `scenarios/` is dispatched to `simulate-batch`,
everything else to `simulate`. Six of the public dev units (`t3-gbatch-*`) are batched.

**Contract invariants (enforced by gate `g0_integrity` / `g1_schema` / `g2_cutoff_resource`):**

1. The image must honor the card's network mode: `none` (simulation) means fully offline — any
   attempted outbound connection fails the run; `restricted` (agent tracks) means egress only
   through the audited proxy to the house model endpoint — any connection outside that allowlist
   fails the run, and no vendor model API is on it.
2. Output must validate against the track output schema *before* any scoring (`g1_schema`).
3. The image must not read any path outside `/input` and `/output`; the canary registry and held-out
   targets are never mounted.
4. Determinism: the harness sets `QFBENCH_SEED`; organizer verification within the joint Final + Verification phase
   reruns on fresh seeds/resamples and compares against the final-submission result (reproducibility gate).
5. Wall-clock and resource caps are per-track (`card.environment`); exceeding them is a `g2` failure.
6. **T2 text cutoff (g2):** every document in `/input/text/` must have a timestamp field ≤ `--asof`.
   The harness checks text timestamps in addition to panel data timestamps. A document with a
   post-as-of date causes a `shared.leakage.cutoff_violation` failure label
   (`FailureLabel.LEAKAGE_CUTOFF` in `qfbench2_common.failure_labels`).
7. **T4 target type:** the `target_type` field in `/input/task.json` (and matching `card.toml`) declares
   the task as `classification`, `regression`, or `ranking`. The `answer.json` output must include a
   matching `target_type` field. Mixed task types within one unit are not allowed.
8. **T1 deliverable dir + dual reward (QFBench heritage):** Track 1 *is* QFBench, so it inherits
   QFBench's conventions. The agent writes its deliverables to **`/app/output`**, which is what
   `--out` is set to and what the units' `instruction.md` and `checks/test_outputs.py` say. The
   harness binds the run's output directory at **both** `/app/output` and `/output`, so the
   minority of units phrased against a bare `/output` are captured identically — writing to
   either path is safe, and neither is silently discarded.
   `checks/test.sh` runs **offline** via `python -m pytest` and writes **both**
   Harbor's `/logs/verifier/reward.txt` (1/0) **and** `<output>/reward.json` + `pytest_report.json`
   for the Agenthon g0–g3 verifier and DI failure-label overlay. The same unit therefore runs under
   **both** Harbor (`harbor run --path units ...`) and the Agenthon harness
   (`qfbench2 smoke <unit> <out> --track coding`). **On the evaluation platform `checks/` is
   sealed** — it is not mounted into your container — so the verifier runs the checks itself
   against your deliverables. `reward.json` is therefore *optional* in your output and never
   decides admission; what you must write is the unit's deliverables (point 9). See
   `tracks/track1-coding/public/docs/QFBENCH-HERITAGE.md`. (T2/T3/T4 keep the generic `/output`
   contract above.)
9. **T1 output contract is PER-UNIT, and generalising from one unit will cost you a submission.**
   The dual mount above settles *where* to write. It does not settle **what filename, and in what
   shape** — those come from that unit's own `instruction.md`, and they differ between units in the
   same task. Two units currently shipped together disagree on both:

   | | `t1-EXAMPLE-bs-greeks-pde` | `t1-zero-coupon-bootstrapping` |
   |---|---|---|
   | output file | `results.parquet` | **`results.json`**, shaped `{"zero_rates": {...}}` |
   | input read | `/input/environment/data/options.parquet` | **`/app/curve_data.json`** |

   An agent that solves the exemplar and generalises writes `results.parquet` into both unit
   directories. The second unit wanted `results.json`; the run produced real work and scored zero
   for a filename. Measured by NVIDIA on the eval fleet, issue #17.

   Read every unit's `instruction.md`. Do not infer the deliverable from the exemplar — the
   exemplar is one unit, and it is not representative of the corpus: across the public units,
   **four files in total are parquet** while csv and json dominate. The exemplar's
   `options.parquet` is the exception, not the pattern, and an agent that hardcodes a `*.parquet`
   search finds nothing on almost every other unit.


## Open Division tag

Do **not** add `house_endpoint_only` -- or any key the descriptor schema does not list -- to
`submission.json`: the schema refuses unknown keys, so a submission carrying it is rejected
before it runs. Whether every model call used the house endpoint exclusively is read from
the audited egress-proxy logs during the joint Final + Verification phase; it drives an "Open Division"
display filter of the single leaderboard (never a separate ranking) and needs nothing
from you.
