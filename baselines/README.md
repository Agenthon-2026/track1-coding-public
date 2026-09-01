# FinanceZero Baseline

FinanceZero is the official Track 1 minimal baseline.  Submitted agents must
beat it on mean `pass@1` over the private-test split.

## What FinanceZero does

FinanceZero makes a **single model call** per task with the instruction text
verbatim as the prompt, writes whatever code the model returns directly to a
file, executes it, and exits.  No tool use, no reflection, no self-repair.  It
is deliberately minimal to set a low but non-trivial threshold.

The call goes out over the **restricted** eval network the only way any
submission can reach a model:

- the **organizer-hosted model endpoint** (`$MODEL_ENDPOINT`, an
  OpenAI-compatible server such as `http://model:8000/v1`; open models, free,
  within the per-run budget), reached through the organizer's audited proxy
  (`HTTPS_PROXY`).

Vendor APIs — `api.anthropic.com`, `api.openai.com`,
`generativelanguage.googleapis.com`, any other — are **refused by the proxy**
(policy 2026-08-04), and no participant API keys exist: the harness injects none
and there is no mechanism to supply one. The alternative is a BYO entry, which
ships a **LoRA adapter of rank ≤ 64** — not model weights — that the organizer
loads onto the base model behind `$MODEL_ENDPOINT`. See `SUBMISSION_CLI.md`.

There is no open internet either way; every connection is logged. FinanceZero
is a **category `api`** entry: it ships no adapter — the whole
contribution is the prompt and the packaging. Its model version is pinned (a
dated snapshot), its training cutoff is disclosed in the submission metadata,
and vendor-side tools (web search, code execution, retrieval) are disabled in
the API call, as the rules require of every submission.

Approximate `pass@1` on public-dev split (QFBench v1 migration):

| Category | FinanceZero pass@1 |
|---|---|
| `derivatives-pricing` | ~0.42 |
| `fixed-income` | ~0.51 |
| `credit` | ~0.34 |
| `factor-research` | ~0.38 |
| `backtesting` | ~0.47 |
| `risk-management` | ~0.39 |
| `microstructure` | ~0.28 |
| `fx` | ~0.44 |
| `nlp-on-finance` | ~0.31 |
| `cross-domain` | ~0.19 |

*Numbers are indicative from the QFBench v1 migration run; final numbers will
be published with the competition.*

## Packaging FinanceZero as a solve-CLI agent

FinanceZero must conform to the Track 1 CLI contract and write its deliverables
to `/app/output` (the QFBench/Harbor output convention). At scoring time it runs
on the internal eval network with the standard restricted-mode environment
contract (this is the same invocation every submission gets):

```
docker run --rm --network qfb2-eval \
  -e HTTP_PROXY -e HTTPS_PROXY \
  -e MODEL_ENDPOINT \
  -e QFBENCH_NETWORK=restricted \
  -e MODEL_NAME \
  -v <unit>/input:/input:ro \
  -v <run>/output:/app/output \
  -v <run>/output:/output \
  <IMAGE> solve --task-dir /input --out /app/output
```

Note the **two binds of the same host directory**. Track 1 units are split between the two
spellings — 64 of 87 `instruction.md` tell the agent `/app/output` (the QFBench/Harbor
convention this track inherits), 23 say `/output` — so the harness binds both to one place and
either is captured. Write to whichever your unit's `instruction.md` names; nothing you write to
either path is lost. A path outside those two is written into your container's own filesystem
and discarded by `--rm`. See [`SUBMISSION_CLI.md`](../SUBMISSION_CLI.md), invariant 8.

`HTTP_PROXY`/`HTTPS_PROXY` point at the audited proxy (the only route out of
the container); `MODEL_ENDPOINT` points at the organizer-hosted
OpenAI-compatible endpoint when available, and `MODEL_NAME` names the served
model. No API keys are injected and none exist (policy 2026-08-04). For a local smoke run without
the eval network, the harness falls back to `--network=none` with a warning —
the baseline then gets no model access, so expect reward 0.

Reference implementation (not included in this repo — participants receive
the image hash on the leaderboard).

### Build your own baseline image

If you want to reproduce or extend FinanceZero, build on the **shared sandbox
base image**, `finance-bench-sandbox:latest`. That base is built **once** from
`docker/sandbox.Dockerfile` (+ `docker/requirements-sandbox.txt`) and already
bakes both the financial stack (numpy/pandas/scipy/pyarrow) and the
verification stack (pytest, pytest-json-report, pytest-timeout):

```bash
# Build the shared base once, from the public repo root:
docker build -t finance-bench-sandbox:latest -f docker/sandbox.Dockerfile .
```

Then keep your baseline Dockerfile **thin** — `FROM` the shared base and add
only what is not already in it:

```
Dockerfile.baseline (sketch)
─────────────────────────────
FROM finance-bench-sandbox:latest

# The standard financial + verification stack is already in the base image,
# so do NOT reinstall numpy/pandas/scipy/pytest here. Add only a pinned extra
# the base does not provide. FinanceZero talks to the house endpoint, so it
# needs an OpenAI-compatible client pointed at $MODEL_ENDPOINT through the
# audited proxy (HTTPS_PROXY). Vendor SDKs are of no use here: their endpoints
# are refused by the proxy (policy 2026-08-04) and no API keys are injected.
RUN pip install --no-cache-dir openai==1.40.0

COPY finance_zero.py /agent/finance_zero.py
LABEL qfbench2.interface_version="2.0"

ENTRYPOINT ["python", "/agent/finance_zero.py"]
CMD ["solve", "--task-dir", "/input", "--out", "/app/output"]
```

`finance_zero.py` entry point pseudocode:

```python
import argparse, pathlib, subprocess, sys
import os
from openai import OpenAI        # call goes out via the audited proxy (HTTPS_PROXY)

def solve(task_dir: str, out_dir: str) -> None:
    instruction = (pathlib.Path(task_dir) / "instruction.md").read_text()
    # The house endpoint is the ONLY reachable model. No API key is injected and
    # none exists; vendor endpoints are refused by the proxy (policy 2026-08-04).
    client = OpenAI(base_url=os.environ["MODEL_ENDPOINT"], api_key="unused")
    response = client.chat.completions.create(
        model=os.environ["MODEL_NAME"],      # pinned by the organizer, disclosed per run
        max_tokens=4096,
        messages=[{"role": "user", "content": instruction}],
        # No vendor-side tools (web search / code execution / retrieval) — required.
    )
    code = response.choices[0].message.content
    script = pathlib.Path(out_dir) / "solution.py"
    script.write_text(code)
    subprocess.run([sys.executable, str(script)], cwd=out_dir, check=False)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("verb")
    p.add_argument("--task-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    assert args.verb == "solve"
    pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
    solve(args.task_dir, args.out)
```

## How to beat FinanceZero

Any of the following improvements are expected to push well above the baseline:

- Multi-turn agent loop with self-repair on test failures.
- Retrieval-augmented code generation (offline, all data pre-baked into the image).
- Specialised system prompt with domain-specific chain-of-thought.
- Code execution + invariant checking in the agent loop.
- Fine-tuned or few-shot model with QFBench-style examples.

The leaderboard is the track's CodaBench competition page; see the repository `README.md` for
where the submission instructions and the competition page link are published.
