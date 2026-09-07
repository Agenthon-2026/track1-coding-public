"""Budgeted inference -> local execution -> repair -> fresh-context audit.

Only MODEL_ENDPOINT is contacted. No vendor tools or runtime dependencies are used.
Run generated code inside the competition container, never on an unsandboxed host.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from urllib.parse import urlsplit

import requests

from .prompts import REVIEW, SYSTEM

UUID = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")
RESERVED = {"reward.json", "pytest_report.json", "reward.txt"}


def clean(text: str) -> str:
    return UUID.sub("[identifier omitted]", text)


def tail(text: str, limit: int = 16000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit // 4] + "\n[truncated]\n" + text[-3 * limit // 4 :]


class BudgetExhausted(RuntimeError):
    pass


class Client:
    def __init__(self, deadline: float, seed: int):
        self.endpoint = os.environ.get("MODEL_ENDPOINT", "").rstrip("/")
        self.model = os.environ.get("MODEL_NAME", "")
        url = urlsplit(self.endpoint)
        if url.scheme not in {"http", "https"} or not url.hostname or not self.model:
            raise ValueError("Set MODEL_ENDPOINT and pinned MODEL_NAME before solving")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError(
                "MODEL_ENDPOINT must be a plain base URL without credentials"
            )
        if self.model.endswith("-latest"):
            raise ValueError("MODEL_NAME must be pinned, not a -latest alias")
        self.deadline, self.seed = deadline, seed
        self.input_limit = min(
            int(os.getenv("BASELINE_INPUT_TOKENS", "800000")), 1000000
        )
        self.output_limit = min(
            int(os.getenv("BASELINE_OUTPUT_TOKENS", "90000")), 100000
        )
        self.input_charged = self.output_charged = self.calls = 0
        self.usage_input = self.usage_output = 0
        self.session = requests.Session()  # honours organizer proxy / NO_PROXY

    def complete(self, messages: list[dict[str, str]]) -> str:
        # UTF-8 byte length plus framing is a conservative token reservation. Charge
        # every network attempt, including timeouts; a lost reply may still be billed.
        request_bound = len(json.dumps(messages, ensure_ascii=False).encode()) + 512
        for attempt in range(3):
            left = self.deadline - time.monotonic()
            cap = min(8192, self.output_limit - self.output_charged)
            if (
                left < 5
                or cap < 512
                or self.input_charged + request_bound > self.input_limit
            ):
                raise BudgetExhausted("Inference time or token budget exhausted")
            body = dict(
                model=self.model,
                messages=messages,
                temperature=0,
                seed=self.seed,
                max_tokens=cap,
                stream=False,
            )
            self.input_charged += request_bound
            self.output_charged += cap
            self.calls += 1
            try:
                response = self.session.post(
                    self.endpoint + "/chat/completions",
                    json=body,
                    timeout=(min(10, left), min(180, left)),
                    allow_redirects=False,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.ConnectionError(
                        f"transient HTTP {response.status_code}"
                    )
                if response.status_code != 200:
                    raise RuntimeError(
                        f"Model endpoint returned HTTP {response.status_code}"
                    )
                payload = response.json()
                usage = payload.get("usage", {})
                actual = usage.get("completion_tokens")
                self.usage_input += int(usage.get("prompt_tokens", 0))
                self.usage_output += int(actual or 0)
                if isinstance(actual, int) and 0 <= actual <= cap:
                    self.output_charged -= cap - actual
                content = payload["choices"][0]["message"].get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("Model returned no content")
                return clean(content)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                time.sleep(min(2**attempt, max(0, self.deadline - time.monotonic())))
        raise AssertionError("unreachable")


def parse_action(text: str) -> dict:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    action = json.loads(text)
    if not isinstance(action, dict) or action.get("action") not in {"python", "finish"}:
        raise ValueError("Use action python or finish")
    if action["action"] == "python" and not isinstance(action.get("code"), str):
        raise ValueError("A python action requires a code string")
    return action


def execute(
    code: str, work: Path, env: dict[str, str], timeout: float
) -> tuple[int, str]:
    script = work / "action.py"
    script.write_text(code)
    # A file bounds RAM even if generated code emits a very large diagnostic stream.
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(script)],
            cwd=work,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            rc = proc.wait(timeout=max(0.1, timeout))
        except subprocess.TimeoutExpired:
            rc = 124
        finally:
            # Kill descendants even if the parent exited successfully.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        size = log.tell()
        log.seek(max(0, size - 20000))
        output = log.read().decode(errors="replace")
    return rc, clean(tail(output))


def inventory(data: Path) -> str:
    entries = []
    for p in sorted(data.rglob("*")):
        if p.is_file() and not p.is_symlink():
            entries.append(f"{p.relative_to(data)} ({p.stat().st_size} bytes)")
    return tail("\n".join(entries), 16000)


def solve(task: Path, out: Path) -> int:
    task, out = task.resolve(), out.resolve()
    # A raw public unit contains answer-bearing tests. Local evaluation must use
    # scripts/build_dev_dataset.py, just like the actual sealed input contract.
    if any((task / d).exists() for d in ("checks", "reference")):
        raise ValueError(
            "Unsealed task: stage inputs with scripts/build_dev_dataset.py first"
        )
    if not (task / "instruction.md").is_file():
        raise ValueError("Task has no instruction.md")
    card = tomllib.loads((task / "card.toml").read_text())
    limit = float(card.get("agent", {}).get("timeout_sec", 1800))
    limit = min(limit, float(os.getenv("BASELINE_TIMEOUT_SEC", str(limit))))
    deadline = time.monotonic() + max(1, limit - 15)
    seed = int(os.getenv("QFBENCH_SEED", "0"))
    client = Client(deadline, seed)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("Output directory must be empty to prevent stale deliverables")
    data = task / "environment" / "data"
    if not data.is_dir():
        data = task / "environment"
    context = clean((task / "instruction.md").read_text())
    context += "\n\nAvailable input files (relative to DATA_DIR):\n" + inventory(data)
    context += "\nCategory: " + str(
        card.get("metadata", {}).get("category", "unspecified")
    )
    history: list[dict[str, str]] = []
    reviewed = audit_executed = False
    last_ok = False
    stop = "step_limit"
    with tempfile.TemporaryDirectory(prefix="t1-agent-") as tmp:
        work = Path(tmp)
        env = {
            **os.environ,
            "TASK_DIR": str(task),
            "DATA_DIR": str(data),
            "OUTPUT_DIR": str(out),
            "WORK_DIR": str(work),
            "QFBENCH_SEED": str(seed),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": str(seed % 4294967296),
            "MPLCONFIGDIR": str(work / "mpl"),
        }
        checkpoint = work / "last_successful_outputs"
        context += (
            f"\nTASK_DIR={task}\nDATA_DIR={data}\nOUTPUT_DIR={out}\nWORK_DIR={work}\n"
        )
        last_code = ""
        for step in range(min(64, int(os.getenv("BASELINE_MAX_STEPS", "32")))):
            # Keep instructions and the most recent full code, then bounded recent
            # observations; no lossy model summarizer or hidden cross-task memory.
            recent = []
            used = 0
            for msg in reversed(history):
                if used + len(msg["content"]) > 48000:
                    break
                recent.insert(0, msg)
                used += len(msg["content"])
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": context},
            ]
            if last_code and not any(last_code in m["content"] for m in recent):
                messages.append(
                    {"role": "user", "content": "Last executed code:\n" + last_code}
                )
            messages += recent
            try:
                reply = client.complete(messages)
            except BudgetExhausted as exc:
                stop = str(exc)
                break
            except (requests.RequestException, RuntimeError):
                if checkpoint.exists():
                    stop = "endpoint_failure_preserved_successful_outputs"
                    break
                raise
            history.append({"role": "assistant", "content": reply})
            try:
                action = parse_action(reply)
            except (ValueError, KeyError) as exc:
                history.append(
                    {"role": "user", "content": str(exc) + "; return valid JSON only."}
                )
                continue
            files = [
                p for p in out.rglob("*") if p.is_file() and p.name not in RESERVED
            ]
            if action["action"] == "finish":
                if not files or not last_ok:
                    history.append(
                        {
                            "role": "user",
                            "content": "Execute the solver successfully and write all deliverables first.",
                        }
                    )
                    continue
                if not reviewed:
                    # Fresh review removes the author's earlier claims of correctness.
                    reviewed = True
                    history = [
                        {
                            "role": "user",
                            "content": REVIEW + "\nMost recent code:\n" + last_code,
                        }
                    ]
                    continue
                if not audit_executed:
                    history.append(
                        {
                            "role": "user",
                            "content": "Execute the independent audit before finishing.",
                        }
                    )
                    continue
                stop = "finished_after_audit"
                break
            last_code = action["code"]
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                stop = "time_limit"
                break
            rc, observation = execute(last_code, work, env, min(300, remaining))
            last_ok = rc == 0
            if reviewed and last_ok:
                audit_executed = True
            forbidden = [p for p in out.rglob("*") if p.name in RESERVED]
            if forbidden:
                raise RuntimeError("Generated code wrote a reserved grading artifact")
            if any(p.is_symlink() for p in out.rglob("*")):
                raise RuntimeError("Deliverables must not be symlinks")
            if last_ok and any(p.is_file() for p in out.rglob("*")):
                if checkpoint.exists():
                    shutil.rmtree(checkpoint)
                shutil.copytree(out, checkpoint)
            elif not last_ok and checkpoint.exists():
                for p in out.iterdir():
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                shutil.copytree(checkpoint, out, dirs_exist_ok=True)
                observation += (
                    "\nRestored deliverables from the previous successful execution."
                )
            file_names = [
                str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()
            ]
            history.append(
                {
                    "role": "user",
                    "content": f"Local exit code: {rc}\n{observation}\nDeliverables: {file_names}",
                }
            )
            print(
                json.dumps(
                    {"step": step, "exit_code": rc, "deliverables": len(file_names)}
                ),
                flush=True,
            )
        has_checkpoint = checkpoint.exists()
    print(
        json.dumps(
            {
                "stop": stop,
                "model": client.model,
                "calls": client.calls,
                "input_reserved": client.input_charged,
                "output_reserved": client.output_charged,
                "usage_input": client.usage_input,
                "usage_output": client.usage_output,
            }
        ),
        flush=True,
    )
    return (
        0
        if any(p.is_file() for p in out.rglob("*")) and (last_ok or has_checkpoint)
        else 1
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("verb", choices=["solve"])
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        return solve(args.task_dir, args.out)
    except Exception as exc:
        # Avoid response bodies / URLs / credentials in submission logs.
        message = (
            "Model request failed"
            if isinstance(exc, requests.RequestException)
            else clean(str(exc))
        )
        print(
            f"Baseline stopped: {type(exc).__name__}: {message}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
