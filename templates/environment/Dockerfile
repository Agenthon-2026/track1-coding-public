# Track 1 unit image template — thin, inherits the shared QFBench sandbox base.
#
# The shared base finance-bench-sandbox:latest (built from docker/sandbox.Dockerfile) already
# ships the financial stack (numpy/pandas/scipy/statsmodels/scikit-learn/ta-lib/backtrader/arch/
# polars/openpyxl/pyarrow/...) AND the verification stack (pytest, pytest-json-report,
# pytest-timeout). So a unit image only adds its own data — the QFBench shared-base model.
# Build the base once:  docker build -t finance-bench-sandbox:latest -f docker/sandbox.Dockerfile .
#
# Do NOT install packages that expose a reference solution (e.g. a pre-built pricer that solves the
# task directly) — reviewers will flag these. Only add a genuinely task-specific library here, pinned.
FROM finance-bench-sandbox:latest

WORKDIR /app

# --- input data --------------------------------------------------------------
# QFBench/Harbor convention: the agent reads inputs from the working dir and writes
# its deliverables to /app/output.
COPY data/ /app/data/

# --- rare task-specific packages (only if NOT already in the base) -----------
# RUN pip install --no-cache-dir <pinned-package>   # e.g. QuantLib-Python==1.35

# --- default CMD (local smoke only; the runner overrides it) ------------------
CMD ["bash", "-c", "echo 'Track-1 sandbox ready (finance-bench-sandbox base). Agent writes deliverables to /app/output.'"]
