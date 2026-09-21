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
  card, which is authoritative. It is not the same for every unit: across the 86 public units it
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
both runners. Under Harbor, organizers launch a job with `qfbench2 track1 harbor-run` and produce
the offline pass@1/pass@3 development report with `qfbench2 track1 score-harbor-job` (a thin adapter over
`qfbench2_common.track1.harbor`). `qfbench2 smoke` verifies existing deliverables; it does
not launch the agent. For a local run with the required input/output mounts and a reward check,
follow [README step 6](../README.md#6-run-your-agent-then-check-its-output).

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

## What are pass@1 and pass@3?

### Official leaderboard: one execution per task

The official Track 1 metric is **mean pass@1** (higher is better), computed from **one
execution per task** over the signed task roster with a fixed denominator. An execution earns
1 only if it passes all four admissibility and correctness gates; otherwise it earns 0.
Wrong, crashed, timed-out or missing outputs remain in the denominator as zero. The score is
therefore the fraction of tasks solved in that single execution. It is published **without a
confidence interval** (ruled 2026-09-03).

### Offline development: repeated attempts

The Harbor development report can use several attempts per task to estimate **pass@k**: the
probability that at least one of *k* independent attempts passes. For a task with *n* observed
attempts and *c* passes, the shared scorer uses:

```text
pass@k = 1 - C(n - c, k) / C(n, k), with n >= k
```

Here `C(a, b)` counts combinations and is zero when `b > a`. In particular, **pass@1 = c / n**:
all observed attempts contribute, regardless of their order. It does not select the first
recorded attempt. The report averages these per-task estimates, giving each task equal weight.

For illustration, suppose an offline run gives an agent 3 attempts on each of 4 tasks:

| Task | Attempt 1 | Attempt 2 | Attempt 3 | pass@1 | pass@3 |
|---|---|---|---|---|---|
| T1 | ✓ | ✓ | ✗ | 2/3 | 1 |
| T2 | ✗ | ✗ | ✓ | 1/3 | 1 |
| T3 | ✗ | ✗ | ✗ | 0 | 0 |
| T4 | ✓ | ✗ | ✓ | 2/3 | 1 |

- **Mean pass@1** = `(2/3 + 1/3 + 0 + 2/3) / 4` = **5/12 ≈ 0.417**.
- **Mean pass@3** = `(1 + 1 + 0 + 1) / 4` = **0.75**.

With exactly three attempts per task, pass@3 is 1 if any attempt passes and 0 otherwise. With
more than three attempts, the scorer uses the formula above. The offline report also computes
bootstrap confidence intervals across tasks; none are shown in this example. These estimates
and intervals do not change the official rule of one execution per task.

### How does this relate to accuracy?

For the official one-execution setup, pass@1 is task-level accuracy: the number of tasks solved
divided by the number of tasks in the fixed roster. "Accuracy" does not mean that every attempt
must succeed. For repeated-attempt analysis, pass@1 estimates single-attempt success, while
pass@3 estimates the chance of at least one success in three attempts. Neither metric awards
partial credit for an attempt that fails a required gate or correctness check.

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

1. **Contamination detection.** If an AI agent's output contains any canary GUID from
   the registry — any task's, not only the one being solved — it suggests the agent reproduced
   task material rather than solving the task, whether that material came from training data that
   included the cards or from something the image carried in. This triggers a
   `CONTAMINATION_CANARY` disqualification label.
2. **Uniqueness enforcement.** CI checks that no two tasks share a canary GUID; every task
   must have its own fresh UUID4.

The canary is visible in `card.toml` (the public task description), but the checker scans the
*output files* for every registered canary. An agent that correctly solves a task from scratch
will never emit one.

**Canary string in one sentence:** a unique random ID in each task's metadata; if the agent
outputs any of them, it flags potential memorization or copied task material.

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

## Is there a baseline agent to beat?

**No. Track 1 ships no official baseline agent, and there is no reference score you must clear.**
Entries are ranked against each other on mean pass@1 over the `private-test` split.

The design bar the tasks are held to is unchanged, and it is worth knowing as a task author or as
an entrant: a task that a general-purpose language model solves in a single call, with no tool
use and no iteration, is too easy for the competition. Every Track 1 task is meant to require
something more — correct numerical computation, a working algorithm, or a structured code
solution.

`baselines/` documents how an agent reaches a model and how it must be packaged. It is the
contract, not a competitor.

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
