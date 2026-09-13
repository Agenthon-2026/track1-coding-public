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
qfbench2 smoke units/t1-EXAMPLE-bs-greeks-pde /tmp/t1-exemplar-output --track coding
```

The expected result is `admissible=True, score=1.0`. These commands run in the Linux container
CI test. `smoke` verifies existing output; it does not run an agent. The scorer needs permission
to temporarily present this unit's input at `/input`. It refuses to overwrite a populated mount.

## Agent Integration

`harbor_agent.py` implements the external-agent interface. Its import path is
`examples.exemplar_agent.harbor_agent:ExemplarAgent`. Use it with the shared toolkit's
`qfbench2 track1 run` entrypoint once your installed toolkit provides that command; the current
public toolkit pin may not yet expose it. Do not substitute a private repository install URL.
The execution engine stays behind `qfbench2`.

Replace this example's solver with your own agent when moving beyond the exemplar. See the
main README for the separate participant submission-image contract.
