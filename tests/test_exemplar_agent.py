"""The real exemplar through the solver CLI and qfbench2 smoke, in a Linux container."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from examples.exemplar_agent.solve import EXEMPLAR_ID, solve

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "units" / EXEMPLAR_ID


def test_solver_writes_deliverables_not_verdicts(tmp_path):
    result = solve(UNIT, tmp_path)
    assert result == tmp_path / "results.parquet"
    assert result.is_file()
    assert not (tmp_path / "reward.json").exists()
    assert not (tmp_path / "pytest_report.json").exists()


@pytest.mark.skipif(os.environ.get("T1_CONTAINER_TEST") != "1",
                    reason="requires an isolated Linux container with /input available")
def test_documented_solver_and_qfbench2_smoke(tmp_path):
    out = tmp_path / "output"
    subprocess.run([sys.executable, "-m", "examples.exemplar_agent.solve", "solve",
                    "--task-dir", str(UNIT.relative_to(ROOT)), "--out", str(out)],
                   cwd=ROOT, check=True)
    result = subprocess.run(["qfbench2", "smoke", str(UNIT.relative_to(ROOT)), str(out),
                             "--track", "coding"], cwd=ROOT, text=True,
                            capture_output=True, check=True)
    assert "admissible=True" in result.stdout, result.stdout + result.stderr
    assert "score=1.0" in result.stdout, result.stdout
    assert not Path("/input").exists()
