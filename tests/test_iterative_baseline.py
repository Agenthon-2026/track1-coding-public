"""Harness tests use invented arithmetic, never benchmark reference outputs.

Mock inference validates plumbing only; these tests are NOT a capability score.
"""

import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
import requests

from baselines.iterative import agent
from scripts.evaluate_baseline import summarize


@pytest.fixture
def task(tmp_path):
    task = tmp_path / "input"
    data = task / "environment/data"
    data.mkdir(parents=True)
    (data / "numbers.json").write_text("[2, 7, 13]")
    (task / "instruction.md").write_text(
        "Sum numbers.json; write total.json with key total."
    )
    (task / "card.toml").write_text("[agent]\ntimeout_sec = 90\n")
    return task


def fake_model(monkeypatch, replies):
    seen = []
    iterator = iter(replies)

    class FakeClient:
        model = "test-fixture"
        calls = input_charged = output_charged = usage_input = usage_output = 0

        def __init__(self, *args):
            pass

        def complete(self, messages):
            seen.append(messages)
            return json.dumps(next(iterator))

    monkeypatch.setattr(agent, "Client", FakeClient)
    return seen


SUM = """import json, os
from pathlib import Path
values = json.loads((Path(os.environ['DATA_DIR'])/'numbers.json').read_text())
(Path(os.environ['OUTPUT_DIR'])/'total.json').write_text(json.dumps({'total':sum(values)}))
"""
AUDIT = """import json, os
from pathlib import Path
data=json.loads((Path(os.environ['DATA_DIR'])/'numbers.json').read_text())
total=json.loads((Path(os.environ['OUTPUT_DIR'])/'total.json').read_text())['total']
assert total/len(data) == sum(x/len(data) for x in data)
"""


def test_repairs_execution_and_requires_a_fresh_audit(monkeypatch, task, tmp_path):
    seen = fake_model(
        monkeypatch,
        [
            {"action": "python", "code": "raise ValueError('bad column')"},
            {"action": "python", "code": SUM},
            {"action": "finish"},
            {"action": "finish"},
            {"action": "python", "code": AUDIT},
            {"action": "finish"},
        ],
    )
    out = tmp_path / "output"
    assert agent.solve(task, out) == 0
    assert json.loads((out / "total.json").read_text()) == {"total": 22}
    assert "bad column" in str(seen[1])
    assert "bad column" not in str(
        seen[3]
    )  # fresh audit does not inherit author's claims
    assert "Execute the independent audit" in str(seen[4])
    assert not (out / "reward.json").exists()


def test_failed_refinement_restores_last_success(monkeypatch, task, tmp_path):
    monkeypatch.setenv("BASELINE_MAX_STEPS", "2")
    fake_model(
        monkeypatch,
        [
            {"action": "python", "code": SUM},
            {
                "action": "python",
                "code": "import os, pathlib\np=pathlib.Path(os.environ['OUTPUT_DIR'])/'total.json'\np.write_text('broken')\nraise RuntimeError()",
            },
        ],
    )
    out = tmp_path / "output"
    assert agent.solve(task, out) == 0
    assert json.loads((out / "total.json").read_text())["total"] == 22


def test_refuses_unsealed_input(task, tmp_path):
    (task / "checks").mkdir()
    with pytest.raises(ValueError, match="Unsealed"):
        agent.solve(task, tmp_path / "out")


def test_finish_without_outputs_fails(monkeypatch, task, tmp_path):
    monkeypatch.setenv("BASELINE_MAX_STEPS", "2")
    fake_model(monkeypatch, [{"action": "finish"}] * 2)
    assert agent.solve(task, tmp_path / "output") == 1


def test_stale_outputs_rejected(monkeypatch, task, tmp_path):
    fake_model(monkeypatch, [])
    out = tmp_path / "output"
    out.mkdir()
    (out / "stale.txt").write_text("stale")
    with pytest.raises(ValueError, match="empty"):
        agent.solve(task, out)


def test_reserved_artifact_rejected(monkeypatch, task, tmp_path):
    fake_model(
        monkeypatch,
        [
            {
                "action": "python",
                "code": "import os, pathlib\n(pathlib.Path(os.environ['OUTPUT_DIR'])/'reward.json').write_text('{}')",
            }
        ],
    )
    with pytest.raises(RuntimeError, match="reserved"):
        agent.solve(task, tmp_path / "output")


def test_executor_kills_descendants(tmp_path):
    marker = tmp_path / "escaped.txt"
    child = f"import time,pathlib; time.sleep(1); pathlib.Path({str(marker)!r}).touch()"
    code = f"import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c',{child!r}])\ntime.sleep(30)"
    rc, _ = agent.execute(code, tmp_path, dict(os.environ), 0.2)
    assert rc == 124
    time.sleep(1.2)
    assert not marker.exists()


def test_api_contract_and_usage(monkeypatch):
    monkeypatch.setenv("MODEL_ENDPOINT", "http://house.invalid/v1")
    monkeypatch.setenv("MODEL_NAME", "house-pinned-20260828")
    client = agent.Client(time.monotonic() + 30, 7)
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": '{"action":"finish"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8},
            },
        )

    monkeypatch.setattr(client.session, "post", post)
    client.complete([{"role": "user", "content": "x"}])
    url, kwargs = calls[0]
    assert url == "http://house.invalid/v1/chat/completions"
    assert set(kwargs["json"]) == {
        "model",
        "messages",
        "temperature",
        "seed",
        "max_tokens",
        "stream",
    }
    assert kwargs["allow_redirects"] is False
    assert kwargs["json"]["seed"] == 7
    assert client.output_charged == 8


def test_uncertain_timeout_is_charged_and_cannot_exceed_budget(monkeypatch):
    monkeypatch.setenv("MODEL_ENDPOINT", "http://house.invalid/v1")
    monkeypatch.setenv("MODEL_NAME", "house-pinned-20260828")
    monkeypatch.setenv("BASELINE_OUTPUT_TOKENS", "8192")
    client = agent.Client(time.monotonic() + 30, 0)

    def timeout(*args, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(client.session, "post", timeout)
    monkeypatch.setattr(agent.time, "sleep", lambda _: None)
    with pytest.raises(agent.BudgetExhausted):
        client.complete([{"role": "user", "content": "x"}])
    assert client.calls == 1
    assert client.output_charged == 8192


def test_incomplete_roster_has_no_score():
    report = summarize([{"id": "a", "category": "c"}], [], 1)
    assert report["complete"] is False
    assert "single_pass_at_1" not in report


def test_first_attempt_and_pass3_are_distinct():
    rows = [{"id": x, "category": "c"} for x in ["a", "b"]]
    results = [
        {"id": x, "repetition": rep, "passed": x == "a" and rep == 2}
        for x in ["a", "b"]
        for rep in range(3)
    ]
    report = summarize(rows, results, 3)
    assert report["single_pass_at_1"] == 0
    assert report["offline_development"]["pass@3"]["mean"] == 0.5
    assert report["offline_development"]["pass@1"]["mean"] == pytest.approx(1 / 6)


def test_evaluator_accepts_shared_splitter_filtered_manifest(monkeypatch, tmp_path):
    import hashlib
    import shutil
    from qfbench2_common.dataset import split_unit
    from scripts import evaluate_baseline as evaluation

    source = Path(__file__).resolve().parents[1] / "units/t1-EXAMPLE-bs-greeks-pde"
    unit = tmp_path / "source" / source.name
    shutil.copytree(source, unit)
    manifest = json.loads((unit / "manifest.json").read_text())
    for check in (unit / "checks").rglob("*"):
        if check.is_file():
            manifest["files"].append(
                {
                    **manifest["files"][0],
                    "path": str(check.relative_to(unit)),
                    "sha256": hashlib.sha256(check.read_bytes()).hexdigest(),
                    "bytes": check.stat().st_size,
                }
            )
    (unit / "manifest.json").write_text(json.dumps(manifest))
    dataset = tmp_path / "dataset"
    ing = dataset / "ingestion/input/ref"
    sco = dataset / "scoring/input/ref"
    ing.mkdir(parents=True)
    sco.mkdir(parents=True)
    split_unit(unit, ing, sco, "coding")
    assert (ing / unit.name / "manifest.json").read_bytes() != (
        unit / "manifest.json"
    ).read_bytes()
    args = SimpleNamespace(
        dataset=dataset, out=tmp_path / "run", grader_image="test-grader"
    )
    row = {
        "id": unit.name,
        "input_sha256": evaluation.tree_digest(ing / unit.name),
        "grader_sha256": evaluation.tree_digest(sco / unit.name),
        "manifest_sha256": hashlib.sha256(
            (unit / "manifest.json").read_bytes()
        ).hexdigest(),
    }

    def reached_build(*args, **kwargs):
        raise RuntimeError("passed staging validation; reached build")

    monkeypatch.setattr(evaluation, "docker", reached_build)
    with pytest.raises(RuntimeError, match="reached build"):
        evaluation.attempt(args, row, 0, "fixture-image")


def test_grader_preserves_data_layout_without_legacy_installers():
    from scripts.evaluate_baseline import grader_dockerfile

    source = "FROM old\nRUN pip install incompatible-version\nCOPY data/ /app/data/\nWORKDIR /app\n"
    generated = grader_dockerfile(source, "tested-grader")
    assert generated == "FROM tested-grader\nCOPY data/ /app/data/\nWORKDIR /app\n"
