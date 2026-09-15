"""Work out what file the task wants, and what has to be in it.

Measured on all 87 public units, the deliverable filename is recoverable from
`instruction.md` alone in 78 of them (90%):

    full /app/output/... path AND a backticked name    26   30%
    full path only                                     21   24%
    backticked filename only                           31   36%
    neither                                             9   10%

That 90% is why the agent does not need `checks/` at runtime. The remaining 10%
is why it needs an ordered fallback that says which rung it landed on, so a
local run can tell a confident read from a guess.

Path convention: `/app/output` dominates - 38 references to
`/app/output/results.json` alone against a single `/output/results.parquet`.
SUBMISSION_CLI names `/app/output` for T1 and the harness binds the same host
directory at both, so writing there is right either way.
"""

from __future__ import annotations

import pathlib
import re

from .contracts import OutputContract

#: A fully-qualified deliverable path in prose or a heading. One level of
#: subdirectory is allowed (`tables/summary.parquet`): real instructions do ask
#: for nested deliverables, and a detector that cannot hold a path silently
#: falls back to a guess.
#: `py` is in the list because deliverables ARE sometimes code: the API-
#: migration unit asks for /app/output/function-under-new-api.py, and a
#: detector blind to the extension shipped a guessed results.json into 57
#: failing checks.
FULL_PATH = re.compile(
    r"/(?:app/)?output/((?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_.-]+\.(?:json|csv|parquet|txt|html|md|py|png))")
#: A backticked bare filename (optionally with one subdirectory level).
#: `png` joined the list after fama-french asked for three chart files the
#: detector could not see (graded: three test_*_png_exists failures).
BARE_NAME = re.compile(
    r"`((?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_.-]+\.(?:json|csv|parquet|txt|html|md|py|png))`")
#: An enumerated deliverable heading: "### File 1: calibration.json",
#: "Output 2 - summary.json". No verb, no backticks, no path - and as strong
#: a request as a full path (asian-option named three files this way; all
#: three were missed and a guessed results.json met 25 failing checks).
HEADING_NAME = re.compile(
    r"^\s*#*\s*(?:file|output|deliverable|artifact|table)\s*#?\s*\d+\s*[:.)-]\s*`?"
    r"((?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_.-]+\.(?:json|csv|parquet|txt|html|md|py|png))`?",
    re.IGNORECASE | re.MULTILINE)
#: A markdown heading that IS a filename: "### calibration.json". No verb,
#: no number, no backticks - and the whole deliverable list of ou-jump was
#: written this way (four files; the detector saw none and the agent shipped
#: a guessed results.json into 24 failing checks). A heading is a request.
HEADING_ONLY = re.compile(
    r"^\s*#{1,6}\s*`?((?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_.-]+"
    r"\.(?:json|csv|parquet|txt|html|md|py|png))`?\s*$",
    re.MULTILINE)
#: Plain filenames in an explicitly named output section. This catches
#: "summary.json" in a Deliverables list even when the author omitted
#: backticks and a markdown heading.
OUTPUT_SECTION = re.compile(
    r"^\s*#{1,6}\s*(?:outputs?|deliverables?|artifacts?|required\s+files?)\b[^\n]*\n"
    r"(?P<body>.*?)(?=^\s*#{1,6}\s+|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL)
#: The lookbehind excludes `/` as well: without it, "Save
#: `/app/output/results.json`" inside an Outputs section also matched the
#: tail "output/results.json", adding a phantom nested deliverable next to
#: the real one (19 such contracts across 10 units, including units that
#: were passing - the self-check then demanded /app/output/output/...).
#: A full path is FULL_PATH's job; this pattern is only for plain names.
SECTION_FILE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])((?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_.-]+\.(?:json|csv|parquet|txt|html|md|py|png))(?![A-Za-z0-9_.-])",
    re.IGNORECASE)
#: Explicit prose is also strong evidence: "the output file is summary.json"
#: or "write a file named summary.json". The context is deliberately narrow
#: so ordinary input filenames elsewhere remain excluded.
NAMED_OUTPUT = re.compile(
    r"\b(?:output\s+file|deliverable|artifact|file|filename)\s+"
    r"(?:named|called|is|to\s+be|:)\s*`?"
    r"((?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_.-]+\.(?:json|csv|parquet|txt|html|md|py|png))`?",
    re.IGNORECASE)
#: Written by the verifier, never by us - the exemplar says so explicitly.
NEVER_OURS = {"reward.json", "reward.txt", "pytest_report.json"}

EXT_TO_FMT = {
    ".json": "json", ".csv": "csv", ".parquet": "parquet",
    ".txt": "txt", ".html": "txt", ".md": "txt", ".py": "txt",
}

#: Used only when nothing else yields a name. `results.json` is the single most
#: referenced deliverable across the public units, so it is the least-bad guess -
#: but a contract carrying source="default" is a contract we did not read.
LAST_RESORT = "results.json"


def _fmt_of(filename: str) -> str:
    return EXT_TO_FMT.get(pathlib.Path(filename).suffix.lower(), "unknown")


#: Another deliverable-looking filename (or a heading) after the mention:
#: the boundary of this file's specification.
_OTHER_FILE = re.compile(
    r"(?:^#{1,6}\s.*?)?`?((?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_.-]+\.(?:json|csv|parquet|txt|html|md|py|png))`?",
    re.M)


def _columns_near(text: str, filename: str) -> tuple[str, ...]:
    """Column names from the markdown table that follows a filename mention.

    21 of 87 instructions carry a markdown table. When one sits under the
    deliverable heading, its first column is the schema.

    The LAST mention is scanned, not the first. A deliverable is routinely
    named early (an overview, an Inputs table sharing the name) and specified
    late, under a Deliverables heading; scanning after the first mention read
    the *input* schema as the required output columns whenever the two were
    more than a window apart.
    """
    index = text.rfind(filename)
    if index < 0:
        return ()
    window = text[index: index + 2500]
    # The window ends where the NEXT deliverable's specification begins:
    # a fixed 2500 chars ran into the following file's table and merged
    # two schemas into one column list, which then failed a 129/130
    # solution as schema_mismatch (credit-portfolio, v5b) and pushed the
    # model into rewrites that crashed.
    later = [m.start() for m in _OTHER_FILE.finditer(window, len(filename))
             if m.group(1) != filename and m.group(1) != pathlib.Path(filename).name]
    if later:
        window = window[: later[0]]
    rows = re.findall(r"^\|\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\s*\|", window, re.M)
    # Drop the header separator artefacts and obvious prose columns.
    columns = [r for r in rows if r.lower() not in {"column", "field", "name",
                                                    "type", "path", "format"}]
    seen, ordered = set(), []
    for c in columns:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return tuple(ordered)


#: A filename mentioned under an input-side path is being described, not
#: requested. Units mount inputs at /input but also reference container
#: paths like /app/data/.
INPUT_PATH = re.compile(
    r"/(?:input|app/data|data)/[A-Za-z0-9_./-]*?([A-Za-z0-9_.-]+\.\w+)")

#: Verbs (and headings) that mark a filename mention as a request to produce
#: the file, rather than a discussion of it.
_REQUEST_CONTEXT = re.compile(
    r"\b(write|writes|written|produce|produces|produced|save|saves|saved|"
    r"output|outputs|deliver|delivered|deliverables?|emit|emits|emitted|"
    r"create|creates|created|generate|generates|generated)\b"
    # Enumerated deliverable headings carry no verb at all: "### File 1:
    # calibration.json" (asian-option: three such files, all missed, the
    # agent shipped a guessed results.json into 25 failing checks).
    r"|\b(?:file|output|deliverable|artifact|table)\s*#?\s*\d+\s*[:.)-]",
    re.IGNORECASE)


_NEGATED_CONTEXT = re.compile(
    r"\b(ignore|do not|don't|never|must not|not a deliverable|forbidden)\b",
    re.IGNORECASE)


def _requested(text: str, name: str) -> bool:
    """Does any mention of `name` sit in a context that asks for the file?

    The scan is confined to the mention's own sentence. A wider window steals
    requesting verbs from neighbouring sentences about *other* files - in both
    directions: "write `answer.json`. ... a scratch file called `debug.log`"
    must not mark debug.log as requested, and "ignore `x_TEMPLATE.json`; the
    deliverable is `x.json`" must not let the semicolon's far side vouch for
    the template. Sentences are cut at a delimiter followed by whitespace
    (so a soft markdown line wrap does not end one, and a bare dot inside a
    file extension cannot), or at a paragraph break.
    """
    for match in re.finditer(re.escape(name), text):
        sentence = _sentence_around(text, match.start(), match.end())
        if _NEGATED_CONTEXT.search(sentence):
            continue
        if _REQUEST_CONTEXT.search(sentence):
            return True
    return False


_LEFT_DELIMS = ("; ", ". ", "! ", "? ", ";\n", ".\n", "!\n", "?\n",
                "\n\n", "\n#", "\n|", "\n-", "\n*")
_RIGHT_DELIMS = ("; ", ". ", "! ", "? ", ";\n", ".\n", "!\n", "?\n", "\n\n")


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(delim, 0, start) for delim in _LEFT_DELIMS)
    rights = [c for c in (text.find(delim, end) for delim in _RIGHT_DELIMS)
              if c >= 0]
    right = min(rights) if rights else len(text)
    return text[left + 1: right]


def _only_negated(text: str, name: str) -> bool:
    """Every mention of `name` sits in a negating sentence."""
    mentions = list(re.finditer(re.escape(name), text))
    if not mentions:
        return False
    return all(_NEGATED_CONTEXT.search(
        _sentence_around(text, m.start(), m.end())) for m in mentions)


def _output_section_names(text: str) -> list[str]:
    """Return filenames from sections whose heading explicitly requests output."""
    names: list[str] = []
    for section in OUTPUT_SECTION.finditer(text):
        names.extend(SECTION_FILE.findall(section.group("body")))
    return names


def from_instruction(text: str, inputs: tuple[str, ...] = ()) -> list[OutputContract]:
    """Read the deliverables the instruction names, best rung first.

    Inputs must be subtracted. The exemplar's instruction names
    `options.parquet` in its Inputs table and backticks it, so a detector that
    only looks for backticked filenames asks the agent to produce its own input
    - which it then reports as a missing deliverable, every iteration, until the
    budget runs out. Found by running the skeleton, not by reading the code.
    """
    excluded = {pathlib.Path(f).name for f in inputs}
    excluded |= set(INPUT_PATH.findall(text))
    excluded |= NEVER_OURS

    def _safe(name: str) -> bool:
        return ".." not in name and not name.startswith("/")

    # A full /app/output/... path is a stated deliverable, and the output
    # context overrides the input-basename exclusion: "read portfolio.csv,
    # write the enriched portfolio.csv to /app/output/" is a real task shape,
    # and erasing the name because an input shares it leaves no contract at
    # all. Only the grader's own files are never ours.
    strong = [n for n in (FULL_PATH.findall(text) + HEADING_NAME.findall(text)
                          + HEADING_ONLY.findall(text)
                          + _output_section_names(text)
                          + NAMED_OUTPUT.findall(text))
              if pathlib.Path(n).name not in NEVER_OURS and _safe(n)]
    weak = [n for n in BARE_NAME.findall(text)
            if n not in excluded and pathlib.Path(n).name not in NEVER_OURS
            and _safe(n)]

    # Both naming styles count. `strong or weak` silently dropped every
    # deliverable that happened to be named in the weaker style whenever any
    # full path was present - half the deliverables of a mixed-style
    # instruction, reported as PASS by the self-check because the contract
    # never knew about them. But a backtick anywhere is still weaker evidence:
    # once a full path exists, a weak name joins only when its mention sits in
    # a requesting context ("also produce `summary.csv`"), so that a file
    # merely *discussed* in prose does not become a deliverable.
    strong_basenames = {pathlib.Path(n).name for n in strong}
    if strong:
        weak = [w for w in weak if _requested(text, w)]
    else:
        # With no full path anywhere, every backticked name counts (the
        # 31/87-unit weak-only population rarely bothers with verbs) - except
        # a name whose every mention is a negation ("ignore x_TEMPLATE.json").
        weak = [w for w in weak if not _only_negated(text, w)]
    names = strong + [w for w in weak
                      if w not in strong and pathlib.Path(w).name not in strong_basenames]

    ordered, seen = [], set()
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    contracts = []
    for name in ordered:
        columns = _columns_near(text, name)
        # A JSON deliverable is often specified by *showing* it - a fenced
        # example object - rather than by a column table. 4 held-out units
        # failed test_json_summary_when_requested by omitting the wrapper the
        # instruction displayed: the shape was stated, just not in the one
        # notation the detector read. The example's top-level keys are the
        # schema.
        if not columns and _fmt_of(name) == "json":
            columns = _json_keys_near(text, name)
        contracts.append(OutputContract(
            filename=name,
            fmt=_fmt_of(name),
            required_columns=columns,
            row_key=_row_key_of(columns),
            source="instruction",
        ))
    return contracts


_FENCED_JSON = re.compile(r"```(?:json)?\s*\n(\{.*?\})\s*```", re.DOTALL)


def _json_keys_near(text: str, filename: str) -> tuple[str, ...]:
    """Top-level keys of a fenced JSON example shown near the last mention."""
    import json as _json
    index = text.rfind(filename)
    if index < 0:
        return ()
    window = text[index: index + 2500]
    match = _FENCED_JSON.search(window)
    if not match:
        return ()
    try:
        example = _json.loads(match.group(1))
    except ValueError:
        return ()
    if not isinstance(example, dict):
        return ()
    keys = [k for k in example
            if isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)]
    return tuple(keys[:20])


#: Identifier-looking column names. When one leads the required columns, it
#: is the key the grader's ubiquitous test_*_ids_match checks will assert
#: survives - so the self-check asserts it first.
_ID_COLUMN = re.compile(r"(?:^id$|_id$|^ticker$|^symbol$|^asset$|^contract$)",
                        re.IGNORECASE)


def _row_key_of(columns: tuple[str, ...]) -> str | None:
    for column in columns[:2]:
        if _ID_COLUMN.search(column):
            return column
    return None


def detect(instruction: str, checks_dir: pathlib.Path | None = None,
           use_checks: bool = False,
           inputs: tuple[str, ...] = ()) -> tuple[OutputContract, ...]:
    """The ordered fallback: instruction -> last resort.

    The checks/ rung is gone from the shipped agent entirely. It used to exist
    behind a dev-only flag, but a submission image carrying code that *can*
    read the grader's directory invites an audit finding regardless of any
    default; the reader now lives in `dev_tools/checks_dev.py` where it cannot
    ship. `checks_dir`/`use_checks` are accepted and ignored so existing dev
    callers keep working - the guarantee is structural, not behavioural.
    """
    del checks_dir, use_checks
    contracts = from_instruction(instruction, inputs)
    if contracts:
        return tuple(contracts)
    return (OutputContract(filename=LAST_RESORT, fmt="json", source="default"),)
