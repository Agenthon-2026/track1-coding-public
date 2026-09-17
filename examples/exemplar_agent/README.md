# Track 1 Exemplar Agent

## Executive summary (read this first)

This example generates deliverables for `t1-EXAMPLE-bs-greeks-pde`. It is not an official
baseline or a solver for the remaining tasks. It writes no reward or verifier report.
The scorer runs the task's checks against the generated output.

## Verified Smoke Flow

After installing the toolkit and track package as described in the main README, run these
commands from the repository root inside an isolated Linux scoring container:

```bash
python -m examples.exemplar_agent.solve solve \
  --task-dir units/t1-EXAMPLE-bs-greeks-pde --out /tmp/t1-exemplar-output
```

This writes `results.parquet` to `/tmp/t1-exemplar-output`. To check it, use the sandbox route
from the main README (step 6): build `finance-bench-sandbox:latest` and run the unit's
`checks/test.sh` against that output directory. The expected result is `reward: 1.0` in
`reward.json` (measured with toolkit `v2.4.2`: 14 checks pass, 1 skipped).

`qfbench2 smoke ... --track coding` does **not** score Track 1 output: since toolkit `v2.4.0` it
reports "This track has no local preview: the checker requires unavailable or unsafe organizer
input" and exits 0. That is the expected message, not a fault in your setup — the rankable
coding verifier runs only with organizer-held inputs, and `checks/test.sh` in the sandbox is
the local route.

## Agent Integration

`harbor_agent.py` implements the external-agent interface. Its import path is
`examples.exemplar_agent.harbor_agent:ExemplarAgent`. Use it with the shared toolkit's
`qfbench2 track1 run` entrypoint once your installed toolkit provides that command; the current
public toolkit pin may not yet expose it. Do not substitute a private repository install URL.
The execution engine stays behind `qfbench2`.

Replace this example's solver with your own agent when moving beyond the exemplar. See the
main README for the separate participant submission-image contract.
