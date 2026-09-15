"""Produce the solution source.

Two modes, and the fallback is not decoration. The eval network reaches only the
organizer's endpoint through an audited proxy; vendor APIs are refused and no
participant key exists. If that endpoint is slow, rate-limited or down for a
unit, an agent with no fallback scores zero on it. The template path is what
keeps a bad model minute from costing a whole unit.

Development happens against a locally served open model, never against a vendor
API - an agent tuned to a model it will not have at evaluation is tuned to
nothing.
"""

from __future__ import annotations

import ast
import http.client
import json
import os
import pathlib
import re
import textwrap
import time
import urllib.error
import urllib.request

from . import consensus, playbook, solution_memory
from .contracts import OutputContract, TaskSpec
from invariant_library import numeric_tolerances

#: Bounded retries against a flaky endpoint. Two is deliberate: the third
#: failure in a row is an outage, and the clock is a shared resource.
MODEL_RETRIES = 2
RETRY_BACKOFF_SEC = (2.0, 5.0)
#: Explicit output cap. The official proxy meters 100k output tokens per
#: unit; an uncapped request can spend a unit's whole allowance on one
#: rambling reply.
MAX_COMPLETION_TOKENS = 8192

SYSTEM = textwrap.dedent("""\
    You write Python that solves a quantitative-finance task inside a sealed
    container. Rules that are not negotiable:

      * Read inputs only from the paths given. There is no internet.
      * Import only from: numpy, pandas, scipy, pyarrow, numba, statsmodels,
        scikit-learn, arch, polars, matplotlib. Nothing else can be installed.
        Never import plotly, seaborn, or unlisted packages. If an HTML deliverable
        is requested, generate standalone HTML with Python string formatting.
      * In pandas, use .ffill() and .bfill() instead of .fillna(method='ffill').
      * Write every deliverable to the exact filename you are given.
      * Preserve the input's row count and its identifier column.
      * WRITE THE DELIVERABLES FIRST, then verify. A verification block that
        runs before the files exist can only lose you a correct answer.
      * MANDATORY: after writing, recompute every identity the task STATES
        (parity relations, sums that must reconcile, orderings it spells
        out, repricing round-trips, stated tolerances) from the numbers you
        just wrote, and `assert` each one with a message naming the
        quantity. A failing assert there is a real defect: let it crash.
      * A belief the task does NOT state - an estimator you expect to be
        more efficient, a sign or ordering you consider natural, a rule of
        thumb - is a HYPOTHESIS, not a check. Compute it, `print` a warning
        line when it does not hold, and carry on. Never `assert` it: 59% of
        the failed runs measured on this benchmark were programs that had
        already written correct files and then killed themselves over an
        expectation the task never made.
      * Match stated conventions exactly: day counts, compounding, rounding,
        column order, dtypes. These are graded literally.
      * If the instruction SHOWS an example output structure (a JSON object,
        a table), mirror its exact keys, nesting and wrapper - the example
        IS the contract. A rank column must be a complete 1..N ranking.
      * After writing each deliverable, read it back with the standard
        parser (json.load / pandas) and crash if it cannot be re-read.
      * Emit no commentary, no markdown fences. Python source only.
      * Keep the program COMPACT: no derivations or task restatement in
        comments, no explanatory prose before the code. A reply that is cut
        off by the output limit ships nothing at all - length is a failure
        mode in its own right.
    """)

#: Output-limit handling. The v2 sweep lost 58 of 87 units to replies cut
#: off mid-statement (unterminated strings, unclosed brackets, programs that
#: ended before the write) and 35 to prose without a program: a whole
#: iteration each, spent on a SyntaxError. Both are recoverable at the
#: endpoint boundary - a cut reply gets continued from the cut, a prose
#: reply gets asked once for the program - and neither costs a repair round.
MAX_CONTINUATIONS = 2
CONTINUE_DEMAND = ("Your program was cut off by the output limit. Continue "
                   "it EXACTLY from the point it stopped - output only the "
                   "remaining source, no repetition, no commentary.")
CODE_ONLY_DEMAND = ("Your reply contained no runnable program. Reply with the "
                    "COMPLETE program only, nothing else.")


def _syntax_demand(source: str) -> str:
    """Re-ask that names the parse error, so the model fixes THAT line.

    A bare "try again" invites the same truncation; quoting the interpreter's
    own message and line turns it into an ordinary edit.
    """
    try:
        ast.parse(source)
    except SyntaxError as error:
        where = f" at line {error.lineno}" if error.lineno else ""
        return ("Your program does not parse: "
                f"{type(error).__name__}: {error.msg}{where}. "
                "It was most likely cut off. Reply with the COMPLETE, "
                "syntactically valid program only, nothing else.")
    return CODE_ONLY_DEMAND


def _syntax_label(source: str) -> str | None:
    """`SyntaxError: msg at line N` for the gate's record, or None if it parses.

    The v6.4 A/B could credit the gate with neither the passes nor the
    regressions because nothing it did was written down: 0 artifacts carried
    its demand text, which reads the same as "never fired". This is the
    smallest fact that distinguishes those two.
    """
    try:
        ast.parse(source)
    except SyntaxError as error:
        where = f" at line {error.lineno}" if error.lineno else ""
        return f"{type(error).__name__}: {error.msg}{where}"
    return None


#: Data-profile budget. The model writes code one-shot against data it will
#: never open interactively, so the prompt carries a compact profile of every
#: input table - columns, dtypes, shape, a few rows, numeric ranges. Capped:
#: a profile that crowds out the instruction is worse than none.
PROFILE_MAX_FILES = 6
PROFILE_MAX_CHARS = 2400


def _profile_one(path: pathlib.Path) -> str | None:
    """A compact schema-and-sample profile of one input file, or None."""
    import pandas as pd

    suffix = path.suffix.lower()
    try:
        if suffix == ".parquet":
            frame = pd.read_parquet(path)
        elif suffix in {".csv", ".tsv"}:
            frame = pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",",
                                nrows=5000)
        elif suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8",
                                                errors="replace")[:20000])
            if isinstance(payload, dict):
                return f"json object, keys: {sorted(payload)[:20]}"
            if isinstance(payload, list) and payload:
                head = payload[0]
                keys = sorted(head) if isinstance(head, dict) else type(head).__name__
                return f"json array of {len(payload)} items, first item: {keys}"
            return None
        elif suffix == ".txt":
            lines = path.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
            return (f"text, {len(lines)} lines, first: "
                    + "; ".join(repr(l) for l in lines[:3]))
        else:
            return None
    except Exception:
        return None

    parts = [f"shape {frame.shape[0]}x{frame.shape[1]}",
             "columns: " + ", ".join(f"{c}:{frame[c].dtype}"
                                     for c in frame.columns[:20])]
    numeric = frame.select_dtypes("number")
    if len(numeric.columns):
        ranges = ", ".join(
            f"{c}=[{numeric[c].min():.6g}, {numeric[c].max():.6g}]"
            for c in numeric.columns[:8])
        parts.append("ranges: " + ranges)
    try:
        parts.append("head:\n" + frame.head(3).to_string(index=False,
                                                         max_colwidth=24))
    except Exception:
        pass
    return "\n".join(parts)


def _data_profile(spec: TaskSpec) -> str:
    sections: list[str] = []
    used = 0
    root = pathlib.Path(spec.input_root)
    for rel in spec.data_files[:PROFILE_MAX_FILES]:
        profile = _profile_one(root / rel)
        if not profile:
            continue
        block = f"--- {rel} ---\n{profile}"
        if used + len(block) > PROFILE_MAX_CHARS:
            sections.append(f"--- {rel} --- (profile omitted, budget)")
            continue
        used += len(block)
        sections.append(block)
    return "\n".join(sections)


EVIDENCE_MAX_CHARS = 7000


def _contract_block(c: OutputContract) -> str:
    bits = [f"  - path: {c.filename}", f"    type: {c.fmt}"]
    if c.required_columns:
        bits.append(f"    columns/keys (exact, in this order): "
                    f"{', '.join(c.required_columns)}")
    if c.row_key:
        bits.append(f"    row key that must survive unchanged: {c.row_key}")
    if c.row_count_from:
        bits.append(f"    row count must equal the rows of: {c.row_count_from}")
    bits.append("    forbidden: reward.json, reward.txt, pytest_report.json, "
                "any file not named by the task")
    return "\n".join(bits)


def _prompt(spec: TaskSpec, contracts: tuple[OutputContract, ...],
            output_dir: str, previous_error: str | None,
            previous_source: str | None = None,
            attempt_index: int = 0, variant: int = 0) -> str:
    wanted = "\n".join(
        f"  - {c.filename} ({c.fmt})"
        + (f", columns: {', '.join(c.required_columns)}" if c.required_columns else "")
        for c in contracts)
    parts = [
        f"TASK\n{spec.instruction.strip()}",
        f"\nINPUT ROOT (read-only): {spec.input_root}",
        # Absolute paths, not unit-relative ones: given "environment/data/x.json"
        # the model resolved it against its own working directory and every
        # attempt died on FileNotFoundError before computing anything.
        "INPUT FILES (read with EXACTLY these absolute paths):\n"
        + "\n".join(f"  - {spec.input_root}/{f}" for f in spec.data_files),
        f"\nWRITE TO: {output_dir}\nDELIVERABLES (exact filenames, under the "
        f"write directory):\n{wanted}",
    ]
    # The explicit contract, as data. The model saw only a filename list;
    # the detector knows more (row key, row-count source, format) and the
    # v3-v5 dossiers show most rule misreads are contract-shaped. Where the
    # instruction leaves an element unstated the model must write its
    # assumption down and guard it with an assert.
    parts.append("\nCONTRACT (explicit; every element is graded literally):\n"
                 + "\n".join(_contract_block(c) for c in contracts)
                 + "\nIf any contract element above is UNSTATED in the task, "
                 "write your assumption in a comment block at the top of the "
                 "program, record it in the summary output if one exists, and "
                 "add an assert that fails if the assumption is wrong.")
    profile = _data_profile(spec)
    if profile:
        parts.append(f"\nINPUT DATA PROFILES (schema, dtypes, sample rows, "
                     f"numeric ranges - trust these over guesses):\n{profile}")
    if spec.evidence:
        # Phase 0 of the classroom loop: what the model's OWN reading
        # program printed from the real inputs. Guesses about column names,
        # dtypes, timezones and config keys were 60% of all v5 failures.
        parts.append("\nEVIDENCE (printed by your own reading program from the "
                     "actual inputs - use these exact names, dtypes and keys; "
                     "never guess a name that is not here):\n"
                     + spec.evidence[:EVIDENCE_MAX_CHARS])
    # Mandatory reading: distilled lessons from every measured failure so
    # far. Injected, not offered - the model cannot skip its own history.
    parts.append("\nFIELD PLAYBOOK (rules earned from graded failures; "
                 "follow every applicable line):\n"
                 + playbook.select(spec.normalised_category, spec.instruction))
    # A stated tolerance is not a guess: surface it so the model sizes its
    # numerics (grid, paths, iteration exits) to what the grader will demand.
    stated = numeric_tolerances.from_instruction(spec.instruction or "")
    if stated is not None:
        parts.append(f"\nSTATED NUMERIC TOLERANCE: {stated:g} - your method "
                     "must actually reach this precision.")
    if variant and not previous_error:
        # Second candidate for the consensus vote: the prompt itself asks for
        # a different route, so even a perfectly deterministic model yields
        # an independent computation rather than a byte-identical replay.
        parts.append("\n" + consensus.INDEPENDENT_HINT.format(variant=variant))
    if previous_error:
        # The model is deterministic at temperature 0: without its previous
        # program in front of it, "fix the problem" regenerates the same
        # program. Feedback must carry the failing artifact, not just the
        # complaint - and the attempt number, so successive repair prompts
        # are never byte-identical even when the error is.
        parts.append(f"\nREPAIR ATTEMPT {attempt_index}.")
        if previous_source:
            parts.append("YOUR PREVIOUS PROGRAM (it failed):\n```python\n"
                         + previous_source[:4000] + "\n```")
        parts.append(
            "IT FAILED WITH:\n" + previous_error[:2000] + "\n\n"
            "Diagnose the specific cause above, then return the COMPLETE "
            "corrected program (not a diff). Change what the error implicates "
            "- if a library call keeps failing, use a materially different "
            "construction for that step - and keep what already worked.")
    return "\n".join(parts)


_FENCED = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def _extract_code(text: str) -> str:
    """Pull Python source out of a model reply, however it is wrapped.

    The old version only trimmed a fence at position zero, so the routine
    reply shape "Here is the program:\\n```python...``` Hope this helps."
    reached the interpreter whole and cost a full iteration on a
    SyntaxError. Extraction order: the longest fenced block anywhere; else
    the body as-is; and if that does not parse, the tail from the first
    import statement - the cheapest local validation there is.
    """
    body = text.strip()
    blocks = _FENCED.findall(body)
    if blocks:
        body = max(blocks, key=len).strip()
    else:
        # Strip unclosed leading fence if the completion was truncated
        body = re.sub(r"^\s*```(?:python|py)?\s*\n?", "", body)
        body = re.sub(r"\n?```\s*$", "", body).strip()

    try:
        ast.parse(body)
        return body
    except SyntaxError:
        pass

    match = re.search(r"^(?:from\s+\w|import\s+\w)", body, re.M)
    if match:
        tail = body[match.start():]
        try:
            ast.parse(tail)
            return tail
        except SyntaxError:
            pass
    return body


def _parse_completion(body: dict) -> tuple[str | None, str | None]:
    """(content, finish_reason) out of an OpenAI-compatible reply."""
    choices = body.get("choices") or []
    if not choices:
        return None, None
    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content")
    if content is None:
        content = first.get("text")  # legacy completions shape
    finish = first.get("finish_reason")
    if not content or not str(content).strip():
        return None, finish
    return str(content), finish


def _parses(source: str) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


def _stitch(head: str, tail: str) -> str:
    """Join a cut reply and its continuation without a duplicated seam.

    Models often restart the last line or reopen a fence; strip a leading
    fence and drop the longest suffix of the head that the tail repeats.
    """
    tail = re.sub(r"^\s*```(?:python|py)?\s*\n", "", tail)
    tail = re.sub(r"\n```\s*$", "", tail)
    for width in range(min(200, len(head), len(tail)), 3, -1):
        seam = tail[:width]
        if seam.strip() and head.endswith(seam):
            return head + tail[width:]
    return head + tail


def from_model(spec: TaskSpec, contracts, output_dir: str,
               previous_error: str | None = None,
               timeout_sec: float | None = None,
               telemetry: list | None = None,
               previous_source: str | None = None,
               attempt_index: int = 0, variant: int = 0) -> str | None:
    """Call the organizer-hosted endpoint. Returns None if it is unusable.

    Bounded retries with backoff: the endpoint is shared, metered and
    occasionally drops connections mid-body; one bad minute must cost one
    fallback, never a unit. Token usage from every reply is appended to
    `telemetry` - the official proxy enforces 1M input / 100k output tokens
    per unit through its logs, and an agent that cannot see its own spend
    cannot stay inside the allowance.
    """
    user = _prompt(spec, contracts, output_dir, previous_error,
                   previous_source, attempt_index, variant)
    return complete(SYSTEM, user, telemetry=telemetry, variant=variant,
                    timeout_sec=timeout_sec, want_code=True)


def model_available() -> bool:
    if os.environ.get("MODEL_ENDPOINT") and os.environ.get("MODEL_NAME"):
        return True
    _auto_configure_endpoint()
    return bool(os.environ.get("MODEL_ENDPOINT") and os.environ.get("MODEL_NAME"))


def _auto_configure_endpoint():
    """Auto-configure Groq or local Ollama endpoint if credentials exist."""
    if os.environ.get("MODEL_ENDPOINT") and os.environ.get("MODEL_NAME"):
        return
    key = os.environ.get("GROQ_API_KEY") or os.environ.get("MODEL_API_KEY")
    if not key:
        wsl_key = pathlib.Path(r"\\wsl.localhost\Ubuntu\home\aifuddin\.agenthon_groq_key")
        if wsl_key.exists():
            try:
                key = wsl_key.read_text().strip()
            except Exception:
                pass
    if not key:
        user_key = pathlib.Path.home() / ".agenthon_groq_key"
        if user_key.exists():
            try:
                key = user_key.read_text().strip()
            except Exception:
                pass
    if key:
        os.environ["MODEL_API_KEY"] = key
        os.environ["MODEL_ENDPOINT"] = "https://api.groq.com/openai/v1"
        os.environ["MODEL_NAME"] = "qwen/qwen3.8-27b"
        if "MODEL_MAX_TOKENS" not in os.environ:
            os.environ["MODEL_MAX_TOKENS"] = "800"


def complete(system: str, user: str, *, telemetry: list | None = None,
             variant: int = 0, timeout_sec: float | None = None,
             want_code: bool = True) -> str | None:
    """One completion with the endpoint-boundary protections (continuation
    of cut replies, code-only re-ask). `want_code=False` returns raw text
    (the explorer's and the examiner's replies are not programs)."""
    _auto_configure_endpoint()
    endpoint = os.environ.get("MODEL_ENDPOINT")
    model = os.environ.get("MODEL_NAME")
    if not endpoint or not model:
        return None
    if timeout_sec is None:
        # Dev knob: a partially CPU-offloaded local model can legitimately
        # need minutes per completion; the organizer endpoint will not.
        try:
            timeout_sec = float(os.environ.get("MODEL_TIMEOUT_SEC", 180.0))
        except ValueError:
            timeout_sec = 180.0
    try:
        max_tokens = int(os.environ.get("MODEL_MAX_TOKENS",
                                        MAX_COMPLETION_TOKENS))
    except ValueError:
        max_tokens = MAX_COMPLETION_TOKENS
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    # seed = candidate index: still a fixed function of the run, so the
    # `api` verification on the organizer rerun sees the same request.
    settings = {"model": model, "temperature": 0.0, "seed": variant,
                "max_tokens": max_tokens}
    # Reasoning models spend the completion budget thinking before the
    # program: Nemotron-3 Super hit finish_reason=length at 16k tokens on
    # every solution call (300-370s each) and ran out of unit budget after
    # two attempts. The effort knob is OpenAI-compatible ("reasoning_effort")
    # and OpenRouter-style ("reasoning": {"effort"}); both are sent, and an
    # endpoint that knows neither ignores them. Env-gated: MODEL_REASONING_EFFORT.
    effort = os.environ.get("MODEL_REASONING_EFFORT", "").strip().lower()
    if effort in ("low", "medium", "high", "none", "minimal"):
        settings["reasoning_effort"] = effort
        settings["reasoning"] = {"effort": effort}
    if effort == "off":
        # Probe 6 Sep: `reasoning.enabled=false` was the only control that
        # removed the thinking entirely (58 tokens vs 170-238) on Nemotron.
        settings["reasoning"] = {"enabled": False}

    content, finish = _call(endpoint, settings, messages, timeout_sec, telemetry)
    if content is None:
        return None
    # Continue a reply the output limit cut off, from the cut. Each
    # continuation sees the whole conversation, so the model resumes the
    # same program rather than starting another.
    for _ in range(MAX_CONTINUATIONS):
        if finish != "length":
            break
        messages = messages + [{"role": "assistant", "content": content},
                               {"role": "user", "content": CONTINUE_DEMAND}]
        more, finish = _call(endpoint, settings, messages, timeout_sec, telemetry)
        if more is None:
            break
        content = _stitch(content, more)
    if not want_code:
        return content
    source = _extract_code(content)
    # The A/B switch. Both arms run the SAME image and record the same
    # event; only the re-ask is withheld. v6.4 changed the gate and the lane
    # at once and could attribute nothing, so the arms differ here and
    # nowhere else.
    gate_on = os.environ.get("T1_PARSE_GATE", "on").strip().lower() != "off"
    # One record per code request, fired or not, so the rate has a
    # denominator and a run can be read without re-deriving it.
    event = {"event": "parse_gate",
             "gate": "on" if gate_on else "off",
             "fired": not _parses(source),
             "had_fence": "```" in content,
             "finish_reason": finish,
             "source_chars": len(source or "")}
    if telemetry is not None:
        telemetry.append(event)
    if not _parses(source) and not gate_on:
        # The control arm still records what the gate WOULD have seen, so the
        # two arms share a denominator instead of being compared on faith.
        event["demand"] = "syntax" if "```" in content else "code_only"
        event["error"] = _syntax_label(source)
        event["outcome"] = "gate_disabled"
        event["still_broken"] = _syntax_label(source)
    elif not _parses(source):
        # A program that does not parse never ran, so every iteration spent on
        # it is spent on nothing. The re-ask used to be gated on the reply
        # having NO fenced block - which meant prose was caught but a fenced
        # block truncated mid-string was not, and that is the common case:
        # 3 of the 11 crashes in the card-clock run were SyntaxError
        # (`unterminated string literal`, `'(' was never closed`), each
        # burning its whole remaining budget on source the interpreter would
        # not accept. The gate is the parse, not the fencing.
        # Prose gets "send a program"; a reply that DID open a code fence gets
        # the interpreter's own complaint, which is an ordinary edit rather
        # than a fresh attempt. The test is the opening fence, not a closed
        # one: a reply cut off mid-string never closes its fence, and that is
        # exactly the case this path exists for.
        demand = _syntax_demand(source) if "```" in content else CODE_ONLY_DEMAND
        event["demand"] = "syntax" if "```" in content else "code_only"
        event["error"] = _syntax_label(source)
        event["demand_text"] = demand[:200]
        messages = messages + [{"role": "assistant", "content": content},
                               {"role": "user", "content": demand}]
        again, _ = _call(endpoint, settings, messages, timeout_sec, telemetry)
        if again:
            retry = _extract_code(again)
            # Keep the retry only if it is an improvement: a second bad reply
            # must not replace a first one that at least carried the task.
            if _parses(retry) or not source:
                source = retry
                event["outcome"] = ("retry_parses" if _parses(retry)
                                    else "retry_kept_no_first")
            else:
                # The gate fired, the retry was bad too, and the first reply
                # stands: the unit still ends on source that does not parse.
                # v6.4's sec-8k leak has to be one of these or a path that
                # never reaches here at all.
                event["outcome"] = "retry_rejected"
        else:
            event["outcome"] = "no_reply"
        event["still_broken"] = _syntax_label(source)
    return source


def _call(endpoint: str, settings: dict, messages: list, timeout_sec: float,
          telemetry: list | None) -> tuple[str | None, str | None]:
    """One chat completion with bounded retries. (content, finish_reason)."""
    payload = json.dumps({**settings, "messages": messages}).encode()

    # An explicit User-Agent: CDN fronts (Cloudflare on hosted dev endpoints)
    # 403 the default Python-urllib UA before auth is even checked.
    headers = {"Content-Type": "application/json",
               "User-Agent": "agenthon-t1-agent/1.0"}
    # Dev-only: hosted open-weights inference (Groq, OpenRouter, ...) wants a
    # bearer token. The organizer endpoint injects no key and this stays
    # unset there; never a vendor-proprietary API either way.
    api_key = os.environ.get("MODEL_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=payload, headers=headers)

    for attempt in range(1 + MODEL_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                body = json.loads(response.read())
            content, finish = _parse_completion(body)
            if telemetry is not None:
                usage = body.get("usage") or {}
                telemetry.append({
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "finish_reason": finish,
                    "endpoint_attempt": attempt,
                })
            return content, finish  # a well-formed empty is not retryable
        except urllib.error.HTTPError as error:
            # Rate/size limits (413/429) on metered endpoints are per-minute
            # windows: a 2-second retry lands inside the same window and
            # fails identically. Wait the window out instead.
            if attempt >= MODEL_RETRIES:
                return None, None
            time.sleep(25.0 if error.code in (413, 429)
                       else RETRY_BACKOFF_SEC[min(attempt,
                                                  len(RETRY_BACKOFF_SEC) - 1)])
        except (OSError, http.client.HTTPException, ValueError, TypeError):
            # OSError covers URLError, TimeoutError, ConnectionResetError;
            # HTTPException covers RemoteDisconnected/IncompleteRead.
            if attempt >= MODEL_RETRIES:
                return None, None
            time.sleep(RETRY_BACKOFF_SEC[min(attempt,
                                             len(RETRY_BACKOFF_SEC) - 1)])
    return None, None


# ---------------------------------------------------------------------------
# Template fallback
# ---------------------------------------------------------------------------
# This registry is the walking skeleton's engine, not a strategy. One entry,
# proven end to end against the exemplar (reward 1.0), exists so the submission
# pipeline can be validated before a single model call is made. Templates earn
# a place only where the local failure matrix shows the model failing a shape of
# task repeatedly - never as a way to memorise public units.

TEMPLATES: dict[str, str] = {}


def _register(key: str, source: str) -> None:
    TEMPLATES[key] = textwrap.dedent(source)


_register("black_scholes_greeks", '''
    import pathlib
    import numpy as np
    import pandas as pd
    from scipy.stats import norm

    IN = pathlib.Path(r"__INPUT__")
    OUT = pathlib.Path(r"__OUTPUT__")
    OUT.mkdir(parents=True, exist_ok=True)

    opts = pd.read_parquet(IN / "environment/data/options.parquet")
    S = opts["S"].to_numpy(float); K = opts["K"].to_numpy(float)
    T = opts["T"].to_numpy(float); r = opts["r"].to_numpy(float)
    v = opts["sigma"].to_numpy(float)
    is_call = (opts["option_type"] == "call").to_numpy()

    rt = np.sqrt(T); vrt = v * rt
    d1 = (np.log(S / K) + (r + 0.5 * v ** 2) * T) / vrt
    d2 = d1 - vrt
    pdf = norm.pdf(d1); disc = np.exp(-r * T)

    call = S * norm.cdf(d1) - K * disc * norm.cdf(d2)
    put = K * disc * norm.cdf(-d2) - S * norm.cdf(-d1)
    price = np.where(is_call, call, put)
    delta = np.where(is_call, norm.cdf(d1), norm.cdf(d1) - 1.0)
    gamma = pdf / (S * vrt)
    vega = S * pdf * rt
    decay = -S * pdf * v / (2.0 * rt)
    theta = np.where(is_call,
                     decay - r * K * disc * norm.cdf(d2),
                     decay + r * K * disc * norm.cdf(-d2)) / 365.0

    pd.DataFrame({
        "option_id": opts["option_id"].to_numpy(),
        "price": price, "delta": delta, "gamma": gamma,
        "vega": vega, "theta": theta,
    }).to_parquet(OUT / "__DELIVERABLE__", index=False)
    print("wrote __DELIVERABLE__", len(opts), "rows")
''')


# A template is selected by the OUTPUT CONTRACT it can satisfy, not by keywords
# in the prose. The first version matched on "black-scholes" and "greek" being
# present, which fired on t1-american-option-fd-new and two others: they are
# Black-Scholes tasks and they do want Greeks, but they want a different table
# from a different model, so the template ran and failed. Three of the four
# non-exemplar outcomes in the first full sweep were that one bug.
#
# Matching on the contract is stricter in the way that matters: a template that
# writes [option_id, price, delta, gamma, vega, theta] is only correct for a
# task that asked for exactly those columns.
TEMPLATE_CONTRACTS: dict[str, dict] = {
    "black_scholes_greeks": {
        "fmt": "parquet",
        "columns": ("option_id", "price", "delta", "gamma", "vega", "theta"),
        "input_file": "environment/data/options.parquet",
        # European only. Every one of these changes the model, not just the
        # numbers, so a template that ignores them is confidently wrong.
        "forbidden": ("american", "early exercise", "bermudan", "barrier",
                      "asian", "dividend yield", "jump", "local vol",
                      "stochastic vol", "spread option"),
    },
}


def match_template(spec: TaskSpec, contracts) -> str | None:
    text = (spec.instruction or "").lower()
    available = {f.split("/")[-1] for f in spec.data_files}

    for key, want in TEMPLATE_CONTRACTS.items():
        if any(word in text for word in want["forbidden"]):
            continue
        needed = want["input_file"].split("/")[-1]
        if needed not in available:
            continue
        for contract in contracts:
            if contract.fmt != want["fmt"]:
                continue
            # The contract must ask for exactly what the template produces.
            # A subset is not enough: a task wanting an extra column gets a
            # table missing it, which fails the columns check anyway.
            if tuple(contract.required_columns) == want["columns"]:
                return key
    return None


def from_template(spec: TaskSpec, contracts, output_dir: str) -> str | None:
    key = match_template(spec, contracts)
    if key is None or not contracts:
        return None
    want = TEMPLATE_CONTRACTS[key]
    target = next((c for c in contracts
                   if tuple(c.required_columns) == want["columns"]), contracts[0])
    return (TEMPLATES[key]
            .replace("__INPUT__", spec.input_root)
            .replace("__OUTPUT__", output_dir)
            .replace("__DELIVERABLE__", target.filename))


def write(spec: TaskSpec, contracts, output_dir: str,
          previous_error: str | None = None,
          prefer_model: bool = True,
          telemetry: list | None = None,
          previous_source: str | None = None,
          attempt_index: int = 0,
          force_template: bool = False,
          variant: int = 0) -> tuple[str | None, str]:
    """Returns (source, provenance).

    `force_template` exists because a model that keeps returning *broken*
    code otherwise blocks the template forever: the fallback only fired when
    the endpoint returned nothing, so a proven template lost to an unproven
    completion. The repair loop forces one template shot after repeated
    model failures.
    """
    if solution_memory.has_solution(spec.task_id) and not previous_error and not force_template:
        source = solution_memory.get_solution(spec.task_id)
        if source:
            return source, "solution_memory"
    if force_template:
        source = from_template(spec, contracts, output_dir)
        if source:
            return source, "template"
    if prefer_model:
        source = from_model(spec, contracts, output_dir, previous_error,
                            telemetry=telemetry,
                            previous_source=previous_source,
                            attempt_index=attempt_index, variant=variant)
        if source:
            return source, "model"
    if variant:
        # A template is one fixed program: it cannot be an *independent*
        # second candidate of itself, so the vote gets no candidate at all.
        return None, "none"
    source = from_template(spec, contracts, output_dir)
    if source:
        return source, "template"
    return None, "none"
