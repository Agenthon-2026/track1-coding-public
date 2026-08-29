#!/usr/bin/env bash
# Track 1 standard verifier runner (QFBench 2.0, interface_version 2.0).
# Called by the runner AFTER the agent container exits.
#
# Runs under BOTH runners:
#   * Harbor (QFBench)  : reads agent deliverables in /app/output, writes /logs/verifier/reward.txt.
#   * Agenthon harness  : also writes <output>/reward.json + pytest_report.json (g0-g3 + DI overlay).
#
# RESTRICTED NETWORK: no open internet — egress only to the organizer-hosted model
# endpoint via the audited proxy; vendor model APIs are refused. pytest + all task deps are baked into
# finance-bench-sandbox:latest (docker/sandbox.Dockerfile); PyPI is unreachable at run time.
# Do NOT add curl / uvx / pip-install lines here. Task-specific logic belongs in test_outputs.py only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Output dir: honor an explicit override, else QFBench/Harbor's /app/output, else /output.
if [ -n "${OUTPUT_DIR:-}" ]; then :;
elif [ -d /app/output ]; then OUTPUT_DIR=/app/output;
else OUTPUT_DIR=/output; fi
export OUTPUT_DIR                      # test_outputs.py reads the agent's deliverables here
mkdir -p "${OUTPUT_DIR}" /logs/verifier

REWARD_JSON="${OUTPUT_DIR}/reward.json"
REWARD_TXT="/logs/verifier/reward.txt"        # Harbor reward artifact
echo '{"reward": 0.0, "details": "test runner not yet completed"}' > "${REWARD_JSON}"

PYTEST_ARGS=(
    "${SCRIPT_DIR}/test_outputs.py"
    "--tb=short"
    "--no-header"
    "-q"
    "--timeout=270"          # leave 30 s headroom inside the 300 s verifier budget
    "--json-report"
    "--json-report-file=${OUTPUT_DIR}/pytest_report.json"
)

if python -m pytest "${PYTEST_ARGS[@]}"; then
    echo 1 > "${REWARD_TXT}"
    cat > "${REWARD_JSON}" <<EOF
{
  "reward": 1.0,
  "pytest_exit_code": 0,
  "details": "all checks passed"
}
EOF
    echo "[test.sh] All checks passed. reward=1.0"
else
    EC=$?
    echo 0 > "${REWARD_TXT}"
    cat > "${REWARD_JSON}" <<EOF
{
  "reward": 0.0,
  "pytest_exit_code": ${EC},
  "details": "one or more checks failed"
}
EOF
    echo "[test.sh] Checks failed (exit ${EC}). reward=0.0"
fi

# Exit 0 regardless of pytest outcome: the runner reads the reward artifacts, not this exit code.
exit 0
