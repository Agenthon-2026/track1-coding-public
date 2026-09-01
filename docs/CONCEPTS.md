# Track 1 — Core Concepts Explained

## Executive summary (read this first)

This document explains every concept a Track 1 newcomer needs to understand — without assuming
prior knowledge of Docker, software testing, or competition infrastructure. Each concept is
explained in plain English with a concrete example. If you are a quant or business student who
has never built a Docker image or run a test suite, start here before reading anything else. For
every term used across all four Agenthon tracks, also see the competition-wide GLOSSARY
published with the shared toolkit: `Agenthon-2026/Agenthon2026-public`, file
`docs/GLOSSARY.md`.

---

## What is a Docker image?

Imagine you are sending a computer program to a stranger across the world. You want it to run
exactly the same way on their machine as on yours — same Python version, same libraries, same
file structure, same operating system settings. If you just sent them the `.py` file, it might
fail because they have a different Python version or a missing library.

A **Docker image** solves this. Think of it as a self-contained "snapshot" of a mini-computer:
it packages your code together with the exact Python version, every library it needs, and even
the operating system layer. When someone runs your Docker image, they get exactly the same
environment you tested in.

In Track 1, participants submit their AI agent as a Docker image. The competition harness
downloads that image and runs it against each hidden task in a controlled environment.

**Docker image in one sentence:** a portable, frozen bundle of your code + its entire runtime
environment, so it runs identically on any machine.

---

## What is a sandbox?

The **sandbox** is the isolated environment in which your agent runs. It has strict resource
limits:

- **No open internet — model APIs only.** The container runs on a **restricted** network
  (`network = "restricted"` in the card): the only way out is the organizer's audited proxy,
  which reaches exactly one thing — the organizer-hosted model endpoint (`$MODEL_ENDPOINT`,
  open models, free within a per-run budget). Vendor APIs such as `api.anthropic.com`,
  `api.openai.com` and `generativelanguage.googleapis.com` are **refused by the proxy**
  (policy 2026-08-04), and no participant API keys exist. Your agent **can** call a language model; it **cannot** look up market data, browse
  the web, or download packages. Vendor-side tools (web search, code execution, retrieval)
  must be disabled in API calls. Every connection is logged (domain, bytes, timestamps).
- **CPU, memory and GPU limits.** 16 vCPUs, 128 GB RAM, GPU available — as declared in each
  unit card's `[environment]` block (`cpus`, `memory`, `gpu`), which is authoritative.
- **Time limit.** Wall-clock seconds per task, declared per unit by `[agent].timeout_sec` in the
  card, which is authoritative. It is not the same for every unit: across the 87 public units it
  ranges from 1200 to 5400 seconds, most commonly 1800. `[verifier].timeout_sec` and
  `[environment].build_timeout_sec` are different fields — the checker's budget and the image
  build — and neither is the agent's limit.

The sandbox protects the fairness of the competition: every team's agent runs in the same
constrained environment, and no team can cheat by fetching answers or post-cutoff data from
an external service — model inference is the only thing the proxy lets through, and the audit
log proves it. (For local smoke runs without the eval network, the harness falls back to
`--network=none` with a warning — same sandbox, just no model access.)

**Sandbox in one sentence:** a locked box where your agent runs — no web, model APIs only,
limited resources, ticking clock.

---

## What is pytest?

**pytest** is a popular Python testing framework. You write small functions (called "tests")
that check whether some code does what it is supposed to do. If the check passes, the test
passes; if it fails (raises an `AssertionError`), the test fails.

Example:

```python
# checks/test_outputs.py
import pandas as pd

def test_required_columns(results):
    # This test FAILS if the agent forgot to output the "price" column.
    assert "price" in results.columns, "Missing 'price' column in output"
```

In Track 1, each task ships with a `checks/test_outputs.py` file containing tests that
check the agent's output. After the agent finishes, `checks/test.sh` runs pytest **offline**
(the restricted network reaches the house model endpoint only — PyPI is not on the allowlist — so pytest is
baked into the shared base image; no run-time install):

```bash
python -m pytest checks/test_outputs.py --json-report --json-report-file=<output>/pytest_report.json
```

If all tests pass, the agent earns a reward of 1.0 for that attempt; if any test fails, the
reward is 0.0. `test.sh` records this in two places — `/logs/verifier/reward.txt` (Harbor,
`1`/`0`) and `<output>/reward.json` (the Agenthon g0–g3 verifier) — so the same unit runs under
both runners. Under Harbor, organizers launch a job with `qfbench2 track1 harbor-run` and score
official pass@1/pass@3 with `qfbench2 track1 score-harbor-job` (a thin adapter over
`qfbench2_common.track1.harbor`); the Agenthon path is `qfbench2 smoke`.

**pytest in one sentence:** a Python tool that runs your test functions and reports which ones
pass and which ones fail.

---

## What is a financial invariant?

A **financial invariant** is a mathematical fact that must be true for any correct
implementation — regardless of the specific numbers or method used. It is like a sanity check
that the laws of finance impose.

The most important invariant to understand is **put-call parity**.

### Worked example: put-call parity

Suppose a stock trades at S = $100. There is a call option (right to *buy* at K = $100 in T = 1
year) and a put option (right to *sell* at K = $100 in T = 1 year). The risk-free rate is r =
5% per year.

**Put-call parity says:**

```
C - P = S - K × exp(-r × T)
```

Let us plug in the numbers:

```
Right-hand side = 100 - 100 × exp(-0.05 × 1.0)
               = 100 - 100 × 0.9512
               = 100 - 95.12
               = 4.88
```

So no matter how the agent calculates the prices, `C - P` must equal approximately 4.88.

**Why must this hold?** Because if it did not, you could construct a riskless profit: for
example, if `C - P = 6.00` (too large), you could sell the call, buy the put, buy the stock,
and borrow $95.12 — and lock in a riskless $1.12 profit. Real markets eliminate such
opportunities instantly. This is called "no-arbitrage."

In `checks/test_outputs.py`, the checker asserts:

```python
np.testing.assert_allclose(C - P, S - K * np.exp(-r * T), atol=1e-3)
```

The `atol=1e-3` allows for small numerical errors from the solver (e.g., a finite-difference
grid that is not infinitely fine). The test does **not** check whether the price is exactly
$5.24 — it checks the structural relationship.

**Financial invariant in one sentence:** a structural mathematical fact that any correct
implementation must satisfy, regardless of the specific numbers (e.g. put-call parity, or
the fact that a bond price decreases when yield increases).

---

## What is pass@1 and pass@3?

Track 1 grades agents on **pass@k** — the probability that the agent solves a task correctly
in *k* tries. This metric comes from the code generation literature and corrects for the
fact that language models are stochastic: they give different outputs each time you call them,
and some of those outputs will be correct even if others are not.

### Concrete numeric example

Suppose we give an agent 3 attempts on each of 4 tasks. Here are the results:

| Task | Attempt 1 | Attempt 2 | Attempt 3 | pass@1 | pass@3 |
|---|---|---|---|---|---|
| T1 | ✓ | ✓ | ✗ | 1 | 1 |
| T2 | ✗ | ✗ | ✓ | 0 | 1 |
| T3 | ✗ | ✗ | ✗ | 0 | 0 |
| T4 | ✓ | ✗ | ✓ | 1 | 1 |

- **pass@1** for each task: Did attempt 1 pass? Results: 1, 0, 0, 1. Mean = **0.50**
- **pass@3** for each task: Did any of 3 attempts pass? Results: 1, 1, 0, 1. Mean = **0.75**

So this agent has **mean pass@1 = 0.50** and **mean pass@3 = 0.75** over these 4 tasks.

**pass@1 is the primary metric for the leaderboard** (higher is better). pass@3 is the
secondary metric. Both are reported with 95% bootstrap confidence intervals so we can tell
whether one team is genuinely better than another.

### Why not just use "accuracy"?

"Accuracy" (did the agent always get it right?) is too strict — a near-miss on attempt 2 still
counts as zero. pass@k respects the stochastic nature of language models and rewards
consistency. A team whose agent solves each task 2 out of 3 times scores better than a team
whose agent solves half the tasks perfectly and fails all others.

**pass@1 in one sentence:** the fraction of tasks where the agent's *first* attempt passes all
tests; the primary leaderboard metric.

**pass@3 in one sentence:** the fraction of tasks where *at least one* of three attempts passes;
rewards consistency.

---

## What is the oracle solution?

The **oracle solution** is the reference implementation written by a task author that solves
the task correctly. It lives in `private/units/<task-id>/reference/solve.sh` in the *sealed*
private repo — never in the public repo.

The oracle serves two purposes:

1. **Verification.** Task authors run the oracle against their own tests to confirm that the
   tests are solvable and the invariants are correct.
2. **Baseline comparison.** The oracle result is the upper bound: if the oracle itself cannot
   pass the tests, the tests are wrong.

**Participants never see the oracle.** If the oracle solution leaked into the public repo, the
contest would be broken — participants could submit it directly and get a perfect score.

**Oracle solution in one sentence:** the correct reference implementation of a task, sealed in
the private repo, used to validate tests and set an upper bound on scores.

---

## What is a canary string?

Every task card (`card.toml`) contains a unique identifier called a **canary GUID** (a
Globally Unique Identifier — a random 128-bit number formatted as a string like
`d369fcb0-2d9e-42c0-a42c-ef6c5fcd2553`). It is called a "canary" after the canary in a coal
mine: if it appears somewhere it should not, something is wrong.

The canary does two jobs:

1. **Contamination detection.** If an AI agent's output contains the canary GUID of a task,
   it suggests the agent was trained on data that included the task's card — it might have
   "memorized" the task rather than solving it. This triggers a `CONTAMINATION_CANARY`
   disqualification label.
2. **Uniqueness enforcement.** CI checks that no two tasks share a canary GUID; every task
   must have its own fresh UUID4.

The canary is visible in `card.toml` (the public task description), but the checker scans the
*output files* for it. An agent that correctly solves a task from scratch will never emit the
canary in its output.

**Canary string in one sentence:** a unique random ID in each task's metadata; if the agent
outputs it, it flags potential memorization (training data contamination).

---

## What are the admissibility gates g0–g3?

The harness grades each submission attempt through four **gates** in sequence. If any gate
fails, the attempt is immediately disqualified (score = 0.0) and the reason is recorded. Only
an attempt that passes all four gates earns a score.

The gates are named g0 through g3 and always run in this fixed order:

### g0 — Integrity (`g0_integrity`)

**What it checks:** Does the task's `manifest.json` match the actual files? Are all checksums
correct? Is `schema_version` set to "2.0"?

**Why it exists:** To ensure no one has tampered with the task files and that the task was
authored correctly.

**In plain English:** "Are the task files exactly as we expect them to be?"

---

### g1 — Output schema (`g1_schema`)

**What it checks:** Did `checks/test.sh` produce `<output>/reward.json`? Is it valid JSON? Is
the `reward` field either exactly `0.0` or `1.0`?

**Why it exists:** The harness needs a signal from the pytest runner in a consistent format.

**In plain English:** "Did the agent produce *any* output at all, in the right format?"

---

### g2 — Cutoff and resource (`g2_cutoff_resource`)

**What it checks:**
- Did the agent finish within that unit's time limit (`[agent].timeout_sec` in its card, which
  varies by unit)?
- Did the agent's output contain any canary GUID from the registry?
- Did network egress stay inside the restricted contract — nothing beyond the allowlisted
  model APIs and the organizer model endpoint, verified against the audited proxy log?

**Why it exists:** To enforce the data/text cutoff rule (the agent must not use information
beyond the task's cutoff) and the contamination policy. Model APIs are allowed; fetching data
is not — and the cutoff story is unchanged by that.

**In plain English:** "Did the agent play by the rules — no web access, within time, no
memorized answers?"

---

### g3 — Domain semantics (`g3_domain_semantics`)

**What it checks:** Did the pytest test suite in `checks/test_outputs.py` pass? This is
where the financial invariants are enforced.

**Why it exists:** To verify the agent actually solved the finance problem correctly, not just
produced a syntactically valid file.

**In plain English:** "Is the financial output actually correct according to the domain rules?"

---

### Summary

```
g0 (integrity) → g1 (schema) → g2 (cutoff + canary) → g3 (finance tests)
     ↓ fail             ↓ fail             ↓ fail             ↓ fail
   score=0           score=0            score=0            score=0
                                                               ↓ pass
                                                           score=1.0
```

Only an attempt that passes all four gates earns `score = 1.0`, which counts towards pass@k.

**Gates g0–g3 in one sentence:** four sequential quality checks (file integrity, output format,
resource compliance, finance correctness) that every submission attempt must pass in order.

---

## What is the FinanceZero baseline?

**FinanceZero** is the baseline agent that all participants must beat. It is a deliberately
simple agent: it packages a single language model call in a Docker image. Given a task
instruction, it asks the model once and writes the response to `/app/output`. No tool use, no
iteration, no code execution.

FinanceZero represents the minimum level of sophistication: if a task can be solved by just
asking a general-purpose language model once, it is too easy for the competition. All Track 1
tasks are designed to require something more — correct numerical computation, a working
algorithm, or a structured code solution.

You can find the FinanceZero packaging in `public/baselines/`. Running it gives you a sense of
the score a "lazy" agent achieves — and your agent needs to clearly exceed it on the
`private-test` split.

**FinanceZero in one sentence:** the single-call LLM baseline that all Track 1 agents must
beat; it represents the minimum score an unspecialised language model achieves with zero
agentic effort.

---

## What does "deterministic / seed" mean?

The word **deterministic** means the program always produces the same output given the same
input. In software, randomness is usually generated by a pseudo-random number generator (PRNG)
that is initialised from a **seed** — a starting number. If you fix the seed, the sequence of
"random" numbers is actually fully determined and reproducible.

**Why it matters for Track 1.** Some tasks use randomly generated data (e.g. 500 Monte Carlo
paths to price an option). If the data generation is not seeded, two runs with identical code
might produce slightly different outputs. Task authors must seed all random data generation
(e.g. `np.random.seed(42)`) so that the test suite is reproducible and the harness can verify
manifests correctly.

Some tasks also require agents to fix their own seed when running Monte Carlo — the instruction
will say so explicitly.

**Deterministic / seed in one sentence:** fixing the random seed ensures a program produces
exactly the same output every time it runs, which is essential for reproducible testing.
