# Track 1 Task Authoring Guide

## Executive summary (read this first)

This guide explains how to design and contribute one high-quality coding task to Track 1. A
"task" is a self-contained quant-finance coding problem that an AI agent must solve: the agent
reads a data file, writes Python code, and produces an output file that is checked by automated
tests. There are ten steps: choose a category → name the task → copy the template → fill in the
metadata card → write the instruction → assemble data → write tests → build the manifest →
validate locally → open a pull request. **The single most important rule is: never put the
answer (the oracle) in the public repo.** Tests must check structural properties (financial
invariants), not hardcoded numerical answers. Community contributions land in the `public-dev`
split; the sealed `private-test` tasks are authored by the organizing team.

For the definitions of every term used here, see `public/docs/CONCEPTS.md` (this repo) and the
competition-wide GLOSSARY published with the shared toolkit:
`Agenthon-2026/Agenthon2026-public`, file `docs/GLOSSARY.md`.

> **Track 1 is QFBench.** Before authoring, read **[QFBENCH-HERITAGE.md](QFBENCH-HERITAGE.md)**.
> It explains the QFBench lineage, the `task.toml → card.toml` field map (so QFBench v1
> contributors can migrate fast), the thin-Dockerfile / shared-base-image contract, the dual
> reward artifact, and the rule that **the oracle must pass 100%** before a task ships.

---

## Prerequisites: install the tools

Before you start, install the shared toolkit (pinned to the `v2.3.1` release) and build the
shared sandbox base image:

```bash
# Install the shared qfbench2 toolkit from the main repo (pinned tag)
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.3.1#subdirectory=common"

# Build the shared sandbox base ONCE, from the public repo root. It bakes the financial stack
# (numpy/pandas/scipy/pyarrow) AND the verification stack (pytest, pytest-json-report,
# pytest-timeout), so units never reinstall the standard stack themselves.
docker build -t finance-bench-sandbox:latest -f docker/sandbox.Dockerfile .
```

The `qfbench2` CLI is what you use to validate, manifest, and smoke-test your task. Its command
groups are `smoke`, `card`, `manifest`, `eval`, and `track1` (`qfbench2-smoke` is a back-compat
alias for `qfbench2 smoke`). The `track1` group runs units under Harbor and produces the offline
pass@1/pass@3 development report — see Step 9. If the command is not found after install, run `pip install --user`
and add `~/.local/bin` to your PATH. You do **not** install numpy/scipy/pandas/pytest yourself —
they live in the shared base image.

---

## Step 1 — Choose a category and scope the task

Open `public/docs/CATEGORIES.md`. Choose one of the ten category IDs. Read the "What this is"
and "Example task ideas" sections for your chosen category to make sure your idea fits.

Before writing a single line of code, write a one-paragraph **scope statement** that answers
these four questions:

1. **What financial computation must the agent perform?** (e.g. "Price a table of European
   options using any numerical method.")
2. **What are the inputs?** (e.g. "A Parquet file of option parameters: S, K, T, r, sigma,
   option_type.")
3. **What must the output look like?** (e.g. "A Parquet file with columns option_id, price,
   delta, gamma.")
4. **Which financial invariant(s) will the checker assert?** (e.g. "Put-call parity within
   1e-3 USD; call delta in (0, 1).")

**Rule:** the entire task — reading input, computing, writing output — must be achievable by a
domain expert in ≤ 30 minutes of wall-clock time. If your scope requires multiple non-trivial
sub-problems, either split them into separate tasks or mark the task as "hard."

**Why this step exists:** A vague scope produces a vague instruction, which produces ambiguous
tests, which produces contested results. A clear scope statement makes every subsequent step
faster.

---

## Step 2 — Pick a unique task ID and canary GUID

Task IDs follow the pattern `t1-<category-prefix>-<short-slug>`. Use these prefixes:

| Category | Prefix |
|---|---|
| derivatives-pricing | `deriv` |
| fixed-income | `fi` |
| credit | `cred` |
| factor-research | `fac` |
| backtesting | `bt` |
| risk-management | `rm` |
| microstructure | `ms` |
| fx | `fx` |
| nlp-on-finance | `nlp` |
| cross-domain | `xd` |

Examples: `t1-deriv-heston-calib`, `t1-fi-ois-bootstrap`, `t1-nlp-10k-risk-extract`.

Now generate a fresh UUIDv4 for the canary. Every task must have a **globally unique** canary
GUID; CI will reject duplicates:

```bash
python -c "import uuid; print(uuid.uuid4())"
# Example output: 3e4c6b2a-9f1d-4aa7-b830-1c2d3e4f5a6b
```

Save this value — you will paste it into `card.toml` in Step 4.

**Why this step exists:** The task ID is the permanent name of the task across all repos and
systems. The canary GUID is the contamination detector (see `public/docs/CONCEPTS.md`).
Duplicates would break the contamination scanner.

---

## Step 3 — Create the unit directory

Copy the template:

```bash
cd <repo-root>/public
cp -r templates/ units/t1-<your-slug>/
cd units/t1-<your-slug>/
```

Your unit directory must look exactly like this:

```
t1-<your-slug>/
├── card.toml              ← task metadata (filled in Step 4)
├── instruction.md         ← what the agent reads (filled in Step 5)
├── manifest.json          ← auto-generated checksums (filled in Step 8)
├── environment/
│   ├── Dockerfile         ← THIN: FROM finance-bench-sandbox:latest + COPY data/ (Step 6)
│   └── data/              ← input data files go here (filled in Step 6)
└── checks/
    ├── test_outputs.py    ← the automated tests (filled in Step 7)
    └── test.sh            ← runs python -m pytest offline, writes both reward files (do not modify)
```

**Why this step exists:** The harness expects this exact folder structure. Deviating from it
causes CI failures that are hard to debug.

---

## Step 4 — Fill in `card.toml`

Open `units/<your-task-id>/card.toml`. Replace every `<...>` placeholder. Here is the complete
list of fields and what to put in each one:

```toml
schema_version = "2.0"     # always exactly "2.0"

[task]
id    = "t1-<your-slug>"          # must match your directory name
track = "coding"                   # always "coding" for Track 1
title = "<A short human-readable title>"
split = "public-dev"               # community contributions always land here

[metadata]
author_name              = "<Your name>"
author_email             = "<your@email.com>"
difficulty               = "medium"   # "easy" / "medium" / "hard"
category                 = "<one of the 10 category IDs>"
tags                     = ["python", "<domain>", "<method>"]
expert_time_estimate_min = 15.0    # how long a domain expert takes
junior_time_estimate_min = 45.0    # how long a junior takes

[provenance]
license             = "CC0-1.0"    # or other SPDX ID for your data
data_source         = "synthetic"  # or URL if real data
data_cutoff         = ""           # YYYY-MM-DD if data has a cutoff
public_release_date = "2026-01-01"
redistributable     = true
manifest            = "manifest.json"

[contamination]
canary_guid = "<YOUR-FRESH-UUIDv4>"   # from Step 2

[scoring]
verifier            = "t1.pytest_invariants"
metric              = "pass@k"
admissibility_gates = ["g0_integrity","g1_schema","g2_cutoff_resource","g3_domain_semantics"]

[scoring.params]
k_values = [1, 3]

[verifier]
timeout_sec = 300.0    # time allowed for the checker to run

[agent]
timeout_sec = 1800.0   # wall-clock budget for the agent. This is the starting default, NOT a
                       # fixed competition-wide value: raise it for a unit that needs longer.
                       # Across the 87 public units the declared values run 1200-5400 (63 at
                       # 1800, 18 at 2400, 4 at 3600, one at 1200, one at 5400). Whatever you
                       # put here is what the harness enforces for your unit, and it is the
                       # number your instruction.md must quote.

[environment]
build_timeout_sec = 600.0
cpus              = 16
memory            = "128G"
gpu               = true
network           = "restricted"   # always "restricted" — no open internet; egress only to
                                   # the organizer-hosted model endpoint only
                                   # via the audited proxy (no data fetching; g2 cutoffs hold)
```

**Rule:** no `<...>` placeholders may remain. CI scans for them and will reject the PR.

**Why this step exists:** The card is the machine-readable contract for the task. The harness
reads `card.toml` to know which split to route the task to, what gates to run, and what timeout
to enforce.

---

## Step 5 — Write `instruction.md`

The instruction file is the only thing the agent sees when solving the task. Write it as if you
are explaining the problem to a skilled software engineer who has domain knowledge but does not
know the expected answer.

**Strict rules for the instruction:**

1. **State the output contract explicitly.** List every file the agent must write under
   `/app/output`, every column name, every data type, and every unit of measurement. Ambiguity in
   the output contract means the agent cannot know what to produce.

2. **Do not give away the algorithm.** Say "price the option" not "apply the Black-Scholes
   formula." The tests check structural correctness, not method. This prevents trivial solutions
   that only work for one specific method.

3. **Do not embed any numerical answers.** The instruction must not contain any output values.
   A reader of the instruction alone should not be able to infer the expected output.

4. **Refer to input files by their manifest paths.** All data files live under `/input`. Write
   `/input/environment/data/options.parquet`, not a relative path.

**Required sections in `instruction.md`:**

```markdown
# Task: <Title>

## Background
<2-3 sentences explaining the finance context. Assume the agent knows finance, but tell it
what kind of calculation is needed.>

## Inputs
<Table: path | format | description for each input file.>
<For each file: the schema (column names, types, units).>

## Task
<Numbered list of exactly what the agent must compute.>

## Deliverables
<For each output file: path, format, schema (column names, types, units).>

## Constraints
- Restricted network. No open internet — model-API calls only, through the organizer's
  audited proxy to $MODEL_ENDPOINT only. No data fetching: all data
  you need is under /input.
- Runtime: complete within <N> seconds. (Quote your card's own `[agent].timeout_sec` here —
  it varies by unit; do not paste another unit's number.)
- Resources: 16 vCPUs, 128 GB RAM, GPU available (see `[environment]` in the card).
- Language: Python 3.13. Available packages: numpy, pandas, scipy, pyarrow. (List what is in
  the Dockerfile.)

## Notes
<Conventions, edge cases, gotchas the agent should be aware of.>
```

**Why this step exists:** The instruction is the agent's only source of information. An unclear
instruction produces non-deterministic agent behavior, which produces non-deterministic test
results, which makes it impossible to compare agents fairly.

---

## Step 6 — Assemble input data and environment

Place all input data files under `environment/data/`. Guidelines:

- **Use only redistributable data.** Data licensed under CC0-1.0, CC-BY, or similar open
  licenses may be committed. Proprietary or non-redistributable data may **not** be committed.
- **If data is non-redistributable:** Set `"redistributable": false` in `manifest.json`,
  commit only the sha256 hash and access URL, and document the access procedure.
- **Prefer synthetic data** for control and reproducibility. The exemplar task uses synthetic
  option parameters generated with `np.random.seed(42)`.
- **Edge cases matter.** Include rows that test boundary conditions: very short maturities,
  deep in-the-money and out-of-the-money options, zero-coupon bonds at par, etc. The most
  interesting test failures happen at boundaries.

Keep `environment/Dockerfile` **thin**. It must be `FROM finance-bench-sandbox:latest` plus a
`COPY data/` — nothing more in the common case:

```dockerfile
FROM finance-bench-sandbox:latest
COPY data/ /app/data/
```

The standard financial stack (numpy/pandas/scipy/pyarrow) **and** the verification stack
(pytest, pytest-json-report, pytest-timeout) are already baked into the base image, so do
**not** add per-unit `pip install` / `uv pip install` of that standard stack. Only if your task
genuinely needs a package the base does not provide, add a single **pinned** extra:

```dockerfile
RUN pip install --no-cache-dir statsmodels==0.14.2
```

Do not install packages that would let the agent bypass the computation (e.g. a pre-computed
table of answers).

**Why this step exists:** The input data and Docker environment define the problem exactly.
Poorly constructed data leads to unchallenging tasks; a missing package causes CI failure.

---

## Step 7 — Write the checks

The checks are the most important part of the task. They are the ground truth.

### `checks/test_outputs.py`

This file is the automated judge. It runs after the agent writes its output to `/app/output`. Rules:

**Rule A — Assert the output contract first.**

```python
def test_required_columns(results):
    """Check the agent wrote all required columns."""
    required = ["option_id", "price", "delta", "gamma", "vega", "theta"]
    missing = [c for c in required if c not in results.columns]
    assert not missing, f"Missing columns: {missing}"
```

This catches agents that computed the right values but put them in wrong-named columns.

**Rule B — Assert at least one financial invariant from `CATEGORIES.md`.**

Financial invariants are structural facts, not specific numbers. They should hold for *any*
correct implementation. Examples:

```python
def test_call_delta_bounds(results, inputs):
    """Call delta must be in (0, 1) — financial invariant."""
    calls = inputs[inputs["option_type"] == "call"]
    merged = calls.merge(results[["option_id", "delta"]], on="option_id")
    assert (merged["delta"] > 0).all() and (merged["delta"] < 1).all()

def test_put_call_parity(results, inputs):
    """C - P = S - K*exp(-rT) — financial invariant, tolerance 1e-3."""
    # ... (see the exemplar for the full implementation)
    np.testing.assert_allclose(C - P, S - K * np.exp(-r * T), atol=1e-3)
```

**Rule C — Document every tolerance with a justification comment.**

```python
# Tolerance: 1e-3 USD accounts for finite-difference grid discretisation error
# with 500 space steps and 100 time steps. Closed-form BS would require ~1e-6.
np.testing.assert_allclose(C - P, rhs, atol=1e-3, ...)
```

Undocumented tolerances will be rejected in review.

**Rule D — Parametrize tests that apply to multiple rows.**

```python
@pytest.mark.parametrize("opt_type,lo,hi", [
    ("call", 0.0, 1.0),
    ("put", -1.0, 0.0),
])
def test_delta_bounds(opt_type, lo, hi, results, inputs):
    ...
```

Do not test only the first row. Financial invariants must hold *for all rows*.

**Rule E — Never hardcode an expected output value.**

```python
# WRONG — this is an answer key hidden in the test:
assert abs(results.loc[0, "price"] - 5.2471) < 0.001

# RIGHT — this is a structural check:
assert results["price"].min() >= 0, "Option prices cannot be negative."
```

**Rule F — Do not import from `reference/` or any private path.**

The test file must be self-contained. It may only import from the output directory, the input
directory, and standard Python libraries.

### `checks/test.sh`

Copy from `templates/checks/test.sh` and do not modify it. It runs **offline** (cards declare
`network = "restricted"`: the only egress is to the house model endpoint via the audited proxy,
so PyPI and the open web are unreachable): it invokes `python -m pytest` — **not** `uv run`,
`uvx`, or `curl` — using
the pytest stack already baked into the base image. It writes the reward signal in **both**
forms: `/logs/verifier/reward.txt` (Harbor, `1`/`0`) and `<output>/reward.json` +
`pytest_report.json` (the Agenthon g0–g3 verifier plus the DI failure-label overlay). Writing
both means a unit runs unchanged under **Harbor** (`harbor run --path units ...`) and the
**Agenthon harness** (`qfbench2 smoke <unit> <out> --track coding`). If you change the reward
schema, the g1 gate will fail.

**Why this step exists:** The tests are the competition's ground truth. Weak tests (that pass
for wrong reasons) produce inflated scores and unfair rankings. Strong tests (structural
invariants) reward agents that truly understand the finance.

---

## Step 8 — Build the manifest

Run the CLI to hash all committed files and build `manifest.json`:

```bash
qfbench2 manifest build public/units/<your-task-id>/
```

This writes (or overwrites) `manifest.json` with sha256 checksums of every file in the unit
directory. **Regenerate the manifest every time you change any input file.** If the manifest
is stale, the g0 integrity gate will fail.

Commit the updated `manifest.json`:

```bash
git add public/units/<your-task-id>/manifest.json
git commit -m "chore: regenerate manifest for <your-task-id>"
```

**Why this step exists:** The manifest is the anti-tampering mechanism. It guarantees that the
files participants see are exactly the files the organizers hashed. Any tampering (including
accidental edits) causes a mismatch.

---

## Step 9 — Validate locally

Run these commands in sequence, all must exit with code 0. (Build the shared base first if you
have not already: `docker build -t finance-bench-sandbox:latest -f docker/sandbox.Dockerfile .`)

```bash
# 1. Schema + provenance checks (validates card.toml structure)
qfbench2 card validate public/units/<your-task-id>/

# 2. Public-safety check (split-tiered firewall: scans for oracle files, solution dirs, etc.)
qfbench2 manifest assert-public-safe public/units/<your-task-id>/

# 3. Smoke test (builds the thin unit image, runs a mock solve, runs checks offline)
qfbench2 smoke public/units/<your-task-id> /tmp/smoke-out --track coding

# 4. Run the full per-track unit validator (the same one CI runs)
python .github/validate_units.py coding
```

To additionally verify the unit under Harbor (the QFBench-native runner) and get the offline
pass@1/pass@3 development report (not the official single-pass aggregate), use the `track1` adapter (it wraps `qfbench2_common.track1.harbor`, which shells
out to harbor; needs the optional `track1-harbor` extra, `harbor>=0.15.0`):

```bash
qfbench2 track1 harbor-run --units-dir public/units --jobs-dir <dir> --job-name <name>
qfbench2 track1 score-harbor-job --job-dir <dir>/<name> --units-dir public/units
```

**Confirm the oracle passes 100%.** Run your private reference solution against your own checks
and verify every test passes before you ship — if the oracle cannot pass, the tests are wrong.

If any command fails, fix the errors before opening a PR. CI runs the same commands and will
reject the PR if they fail.

**Why this step exists:** Catching errors locally takes 2 minutes; catching them in CI after a
failed PR round-trip takes much longer. The smoke test in particular catches Docker build errors,
missing dependencies, and reward.json format errors.

---

## Step 10 — Open a pull request

1. Create a branch: `git checkout -b task/<your-task-id>`
2. Commit all files in `public/units/<your-task-id>/`
3. Push and open a PR to the `main` branch
4. Fill the PR description template (scope, category, invariants tested, and — if marking the
   task as "hard" — evidence that a single-call language-model attempt fails it)
5. CI runs the review checklist automatically
6. A domain-expert reviewer (auto-assigned by category label) must approve

**Why this step exists:** Human review catches things CI cannot: whether the instruction is
clear, whether the invariants actually test the right things, and whether the task is an
interesting challenge.

---

## Review checklist

The following must all pass before a PR is merged. Items marked "(CI)" are checked
automatically; items marked "(human)" require reviewer judgment.

### Card and metadata

- [ ] `canary_guid` is a valid UUIDv4 format and unique across all tasks (CI)
- [ ] No `<...>` placeholder strings remain in `card.toml` (CI)
- [ ] `split` is `public-dev` (CI — community contributions only)
- [ ] `category` is one of the 10 valid IDs from `CATEGORIES.md` (CI)
- [ ] `verifier = "t1.pytest_invariants"` and `metric = "pass@k"` (CI)
- [ ] `network = "restricted"` in `[environment]` (CI)

### Manifest and data

- [ ] `manifest.json` checksums match committed files (CI via `verify_manifest`)
- [ ] No directories named `reference/`, `solution/`, `oracle_output/` exist (CI)
- [ ] No files matching `expected.json`, `answer_key*`, `*oracle*` exist (CI)
- [ ] All committed data files are licensed under a redistributable SPDX identifier (human)
- [ ] Non-redistributable data has `redistributable=false` and a hash-only commit (human)

### Instruction ↔ checks consistency

| Direction | Rule |
|---|---|
| Instruction → checks | Every output file and column named in the instruction has a test in `test_outputs.py` (human) |
| Checks → instruction | Every invariant in `test_outputs.py` follows from domain knowledge alone, not from a leaked reference value (human + CI canary scan) |
| No orphan assertions | No test passes trivially (e.g. `assert True`) (human) |
| No hardcoded answers | `test_outputs.py` does not import from `reference/` or any private path (CI grep) |

### Financial invariants

- [ ] At least one financial invariant from `CATEGORIES.md` is asserted for this category (human + CI)
- [ ] Tolerances are documented with a justification comment in the test code (human)
- [ ] Invariant tests are parametrised over all rows/assets, not just the first (human)

### Solution hygiene (most critical)

- [ ] `instruction.md` contains no numerical answer keys (CI regex scan)
- [ ] `checks/test_outputs.py` contains no hardcoded values that match the oracle solution (human + CI)
- [ ] The canary GUID appears only in `card.toml`, not in any other file in the unit (CI `scan_canary`)
- [ ] An agent can solve the task by reading `instruction.md` alone, without reading the test file (human)

### Docker environment

- [ ] `Dockerfile` is **thin**: `FROM finance-bench-sandbox:latest` + `COPY data/`, no per-unit install of the standard stack (CI)
- [ ] Any extra package is a single **pinned** install the base does not already provide (human)
- [ ] `test.sh` is unmodified from the template: runs `python -m pytest` offline and writes **both** `/logs/verifier/reward.txt` and `<output>/reward.json` + `pytest_report.json` (CI)
- [ ] No `pip install` / `uv pip install` of packages that expose reference solutions (human)
- [ ] Verified the unit runs under both Harbor and `qfbench2 smoke ... --track coding` (human)

### Oracle and validation

- [ ] The private oracle reference solution passes **100%** of `checks/test_outputs.py` (human)
- [ ] `python .github/validate_units.py coding` exits 0 (CI)
- [ ] `card.toml [contamination].canary_guid` is a fresh UUIDv4, unique per unit, registered in the private `canary_registry.json` (CI)

---

## The golden rule: keep the oracle out of the public repo

The single most common mistake in task authoring is accidentally leaking the reference solution.

**Do:**
- Compute expected outputs in a private notebook; store only the *structural invariant* (e.g.
  monotonicity, sign, parity condition) in the public test file.
- Use `environment/data/` for inputs; never put reference outputs there.
- If you need to test against a specific numeric target, store it in the private repo under
  `private/units/<id>/reference/` and reference it only in the sealed final scorer.

**Do not:**
- Hardcode `assert result ≈ 0.3267` in `test_outputs.py` (this is an answer key in disguise).
- Import `from reference.solution import expected_greeks` (the canary scanner will catch this,
  but the reviewer should catch it first).
- Name any file `expected.json`, `answer_key.csv`, `solution.py`, or similar (CI blocks these
  names automatically).
- Put the solution method in a comment inside `instruction.md` (e.g. "Hint: use
  `scipy.stats.norm.cdf(d1)` for the delta").

**Why this matters.** The canary scanner (`qfbench2_common.leakage.scan_canary`) looks for
canary GUIDs in any text the agent emits. If training data included a public task's `card.toml`,
the canary appears in the agent's output and triggers disqualification. Hardcoded answer keys
create a weaker but similar contamination signal. Tests must be independent of the answer.
