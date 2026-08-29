#!/usr/bin/env bash
# Verifier runner for t1-EXAMPLE-bs-greeks-pde (QFBench 2.0, interface_version 2.0).
# Identical pattern to templates/checks/test.sh — see that file for comments.
# Dual-compatible: Harbor (/logs/verifier/reward.txt, /app/output) AND Agenthon (<output>/reward.json).
# RESTRICTED NETWORK: no open internet (house-endpoint egress only, via the audited proxy);
# pytest + deps baked into finance-bench-sandbox:latest.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${OUTPUT_DIR:-}" ]; then :;
elif [ -d /app/output ]; then OUTPUT_DIR=/app/output;
else OUTPUT_DIR=/output; fi
export OUTPUT_DIR
mkdir -p "${OUTPUT_DIR}" /logs/verifier

REWARD_JSON="${OUTPUT_DIR}/reward.json"
REWARD_TXT="/logs/verifier/reward.txt"
echo '{"reward": 0.0, "details": "test runner not yet completed"}' > "${REWARD_JSON}"

PYTEST_ARGS=(
    "${SCRIPT_DIR}/test_outputs.py"
    "--tb=short"
    "--no-header"
    "-q"
    "--timeout=270"
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

exit 0
