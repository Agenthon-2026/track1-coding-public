# Model access and agent packaging

**Track 1 ships no official baseline agent, and there is no reference score to beat.** Entries are
ranked against each other on mean `pass@1` over the private-test split.

This page is the contract: how an agent reaches a model, and how it must be packaged. It uses a
deliberately minimal *example* agent throughout — one model call per task, the instruction text as
the prompt, write the result, run it, exit — because that is the shortest thing that exercises
every part of the contract. It is an illustration, not a competitor and not a threshold.

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

There is no open internet either way; every connection is logged. An agent of this shape is a
**category `api`** entry: it ships no adapter — the whole contribution is the prompt and the
packaging. Its model version is pinned (a dated snapshot), its training cutoff is disclosed in the
submission metadata, and vendor-side tools (web search, code execution, retrieval) are disabled in
the call, as the rules require of every submission.

## Packaging an agent for the solve CLI

Your agent must conform to the Track 1 CLI contract and write its deliverables
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
an agent then gets no model access, so expect reward 0.

### Build your agent image

Build on the **shared sandbox base image**, `finance-bench-sandbox:latest`. That base is built **once** from
`docker/sandbox.Dockerfile` (+ `docker/requirements-sandbox.txt`) and already
bakes both the financial stack (numpy/pandas/scipy/pyarrow) and the
verification stack (pytest, pytest-json-report, pytest-timeout):

```bash
# Build the shared base once, from the public repo root:
docker build -t finance-bench-sandbox:latest -f docker/sandbox.Dockerfile .
```

Then keep your Dockerfile **thin** — `FROM` the shared base and add
only what is not already in it:

```
Dockerfile (sketch)
─────────────────────────────
FROM finance-bench-sandbox:latest

# The standard financial + verification stack is already in the base image,
# so do NOT reinstall numpy/pandas/scipy/pytest here. Add only a pinned extra
# the base does not provide. An api-category agent talks to the house endpoint,
# so it needs an OpenAI-compatible client pointed at $MODEL_ENDPOINT through the
# audited proxy (HTTPS_PROXY). Vendor SDKs are of no use here: their endpoints
# are refused by the proxy (policy 2026-08-04) and no API keys are injected.
RUN pip install --no-cache-dir openai==1.40.0

COPY agent.py /agent/agent.py
LABEL qfbench2.interface_version="2.0"

ENTRYPOINT ["python", "/agent/agent.py"]
CMD ["solve", "--task-dir", "/input", "--out", "/app/output"]
```

`agent.py` entry point pseudocode:

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

## Where the headroom is

The example above is the floor of what the contract allows, not a target. Any of the following is
expected to do substantially better:

- Multi-turn agent loop with self-repair on test failures.
- Retrieval-augmented code generation (offline, all data pre-baked into the image).
- Specialised system prompt with domain-specific chain-of-thought.
- Code execution + invariant checking in the agent loop.
- Fine-tuned or few-shot model with QFBench-style examples.

The leaderboard is the track's CodaBench competition page; see the repository `README.md` for
where the submission instructions and the competition page link are published.
