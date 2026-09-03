# AGENTS.md — Track 1 Public Repo Rules for AI Agents

## Executive summary (read this first)

This file tells an AI coding agent — or a new teammate — how to behave specifically inside the
**Track 1 public repo** (`track1-coding-public`). It supplements the competition-wide agent
rules published with the shared toolkit (`Agenthon-2026/Agenthon2026-public`, file
`AGENTS.md`); read that first, then this. Three rules dominate:
**(1)** the public/private firewall — never write oracle material here; **(2)** call the shared
scorer in `qfbench2_track_coding/scoring.py` (do not rewrite it); **(3)** keep gate and verb names exactly as
specified — they are fixed across the whole competition.

---

## The firewall (most important rule)

**Nothing that reveals an answer that counts toward the ranking may exist in this repo.**
The check is tiered by unit split:

Never create or modify, for any unit, files that:
- Are named `solution/`, `oracle_*`, `answer_key*`, or live under `dev/`
- Import the oracle solution from a private path
- Reveal the canary GUID → task mapping (the registry lives only in the private repo's
  `canary_registry.json`)

For any **non-`public-dev`** unit, additionally never create or modify files that:
- Are named `reference/`, `expected*`, `outcome*.json`
- Contain the numerical expected output for the task

**Exception:** `public-dev` practice units MAY ship reference *values* under
`checks/reference_data/` (e.g. `checks/reference_data/expected.json`) so students can
self-grade. The held-out targets that determine the ranking live only in the private scorer.

The CI workflow `.github/workflows/ci.yml` runs `qfbench2 manifest assert-public-safe` on every
PR. This check will fail if any of the above is detected.

---

## Where things live in this repo

| Path | Purpose | Agent rule |
|---|---|---|
| `docs/QFBENCH-HERITAGE.md` | What Track 1 kept/adjusted from QFBench; `task.toml → card.toml` map | Read before changing the run/verify contract |
| `docs/CONCEPTS.md` | Plain-English explainer of Track 1 concepts | Read to understand the system |
| `docs/CATEGORIES.md` | The 10 task categories, invariants, difficulty | Read before authoring a task |
| `docs/AUTHORING-GUIDE.md` | Step-by-step task authoring | Follow exactly when creating tasks |
| `units/` | Public-dev task units (the practice set) | New tasks go here via PR |
| `units/t1-EXAMPLE-bs-greeks-pde/` | The canonical worked exemplar | Read before creating any task |
| `qfbench2_track_coding/scoring.py` | The Track 1 verifier and pass@k scorer | Call it; do not rewrite it |
| `templates/` | Copy-to-start templates | Start every new task from here |
| `baselines/` | FinanceZero packaging | Reference to understand the baseline |

---

## Calling the shared scorer

Do not reimplement `pass_at_k`, `suite_summary`, `bootstrap_ci`, or any gate logic. Call them:

```python
from qfbench2_track_coding.scoring import build_verifier, LEADERBOARD_SORT
from qfbench2_common.scoring.passk import suite_summary
from qfbench2_common.scoring.bootstrap import bootstrap_ci

verifier = build_verifier(ctx)
verdict = verifier.run(ctx)
```

If you find a bug in the scorer, fix it in `qfbench2_track_coding/scoring.py` and upstream to
`qfbench2_common` in the main repo — do not create a local fork.

---

## Fixed names — do not invent new ones

These names are used across the harness, CI, and documentation. They cannot change:

| Thing | Fixed name |
|---|---|
| Submission verb | `solve` |
| Admissibility gates | `g0_integrity`, `g1_schema`, `g2_cutoff_resource`, `g3_domain_semantics` |
| Verifier field in card.toml | `"t1.pytest_invariants"` |
| Metric field in card.toml | `"pass@k"` |
| k values | `[1, 3]` |
| Agent output dir | `/app/output` (QFBench/Harbor convention) |
| Reward artifacts | `/logs/verifier/reward.txt` (Harbor) **and** `<output>/reward.json` + `pytest_report.json` (Agenthon) |

---

## Where the exemplar lives

The canonical worked exemplar for Track 1 is:

```
public/units/t1-EXAMPLE-bs-greeks-pde/
```

Read its `card.toml`, `instruction.md`, and `checks/test_outputs.py` before authoring a new
task. This exemplar demonstrates: correct card.toml structure, a clear instruction, financial
invariant tests (not hardcoded answers), canary check, and the test.sh reward schema.

---

## When in doubt

1. Check `docs/CONCEPTS.md` for terminology.
2. Check `docs/CATEGORIES.md` for what invariants belong to each category.
3. Check `docs/AUTHORING-GUIDE.md` for the step-by-step task-creation procedure.
4. Build the shared base once (`docker build -t finance-bench-sandbox:latest -f
   docker/sandbox.Dockerfile .`), then run `qfbench2 card validate units/<task-id>/` and
   `qfbench2 smoke units/<task-id> <out> --track coding` before every commit. To run units
   under Harbor and produce the offline pass@1/pass@3 development report (not the official single-pass aggregate), use the `track1` adapter: `qfbench2 track1
   harbor-run --units-dir units --jobs-dir <dir> --job-name <name>` then `qfbench2 track1
   score-harbor-job --job-dir <dir>/<name> --units-dir units` (wraps
   `qfbench2_common.track1.harbor`; the full CLI is `smoke`, `card`, `manifest`, `eval`,
   `track1`). The dual-runner contract is unchanged.
5. Never push to `main` directly — all changes go through a PR and CI.
