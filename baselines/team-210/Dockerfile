# Agenthon 2026 Track 1 submission image.
#
# Based on the same sandbox the units use. That is deliberate: the agent
# executes the solution it writes *inside this container*, so every package the
# generated code might import has to be here. The instruction files advertise
# numpy/pandas/scipy/pyarrow/numba, but the sandbox also carries arch,
# statsmodels, scikit-learn, ta-lib, backtrader and polars - a GARCH task will
# reach for `arch`, and on a python:3.13-slim base that is an ImportError the
# repair loop cannot fix, because nothing can be installed at run time.
#
# For submission the built image must be pushed whole. `finance-bench-sandbox`
# is a locally built tag and does not exist in the organizers' registry; the
# layers travel with the image, the tag does not.
FROM finance-bench-sandbox:latest

WORKDIR /agent
COPY agent.py /agent/agent.py
COPY agent_core/ /agent/agent_core/
COPY invariant_library/ /agent/invariant_library/
COPY solution_library/ /agent/solution_library/

# Required by the harness; an image without it is inadmissible.
LABEL qfbench2.interface_version="2.0"

# A container killed at the budget cap loses whatever stdout was still
# buffered - which is exactly the run whose logs matter most.
ENV PYTHONUNBUFFERED=1

# The verb arrives as the first argument after the image reference. With this
# entrypoint it lands as argv[1], which agent.py declares as a positional.
ENTRYPOINT ["python", "/agent/agent.py"]
CMD ["solve", "--task-dir", "/input", "--out", "/app/output"]
