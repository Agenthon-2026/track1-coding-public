"""Read a unit into a TaskSpec.

Two modes, and the distinction is the whole point:

    no_checks    instruction.md + input files          <- what final evaluation gives
    with_checks  the above, plus the unit's checker    <- development only

The agent must produce the same result in both. `dev_tools/compare_check_dependency.py`
runs every unit twice and flags any unit whose outcome differs, which is the only
honest way to know the runtime does not lean on something that may be absent.
"""

from __future__ import annotations

import pathlib

from . import output_contract
from .contracts import TaskSpec

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

DATA_SUFFIXES = {".csv", ".json", ".parquet", ".pqt", ".txt", ".tsv",
                 ".xlsx", ".feather", ".npy", ".npz"}
#: Directories under a unit that are the grader's, not the agent's input.
GRADER_OWNED = {"checks"}


def _read_card(unit: pathlib.Path, notes: list[str]) -> dict:
    """Parse card.toml; a failure is diagnosed, never swallowed silently.

    A card that fails to parse used to become an empty dict with no trace,
    which is indistinguishable from a unit that simply has no card - and the
    difference matters, because a broken card also takes the unit id and the
    agent budget with it.
    """
    card = unit / "card.toml"
    if not card.is_file():
        notes.append("card.toml absent")
        return {}
    if tomllib is None:  # pragma: no cover
        notes.append("tomllib unavailable; card.toml not read")
        return {}
    try:
        return tomllib.loads(card.read_text(encoding="utf-8", errors="replace"))
    except Exception as error:
        notes.append(f"card.toml unparseable ({type(error).__name__}); "
                     "working from instruction.md alone")
        return {}


def _data_files(unit: pathlib.Path) -> tuple[str, ...]:
    """Every file the agent may legitimately read, relative to the unit root.

    `checks/` is excluded here even in development: the agent's own view of its
    inputs should never include the grader's directory, or the two modes stop
    being comparable.
    """
    found = []
    for path in sorted(unit.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(unit)
        if relative.parts and relative.parts[0] in GRADER_OWNED:
            continue
        if path.suffix.lower() in DATA_SUFFIXES:
            found.append(str(relative).replace("\\", "/"))
    return tuple(found)


def read(unit_dir: str | pathlib.Path, *, use_checks: bool = False) -> TaskSpec:
    unit = pathlib.Path(unit_dir)
    notes: list[str] = []

    instruction_path = unit / "instruction.md"
    if instruction_path.is_file():
        instruction = instruction_path.read_text(encoding="utf-8", errors="replace")
    else:
        instruction = ""
        notes.append("instruction.md absent")

    card = _read_card(unit, notes)
    category = card.get("metadata", {}).get("category")

    # The card is the authority on the budget: 1200/1800/2400/3600/5400 all
    # occur in the wild. An agent that hardcodes 1800 is late on short cards
    # and gives up early on long ones.
    agent_timeout = None
    raw_timeout = card.get("agent", {}).get("timeout_sec")
    if isinstance(raw_timeout, (int, float)) and raw_timeout > 0:
        agent_timeout = float(raw_timeout)

    canary = card.get("contamination", {}).get("canary_guid") or None

    checks_dir = unit / "checks"
    checks_available = checks_dir.is_dir()
    del use_checks  # accepted for dev-caller compatibility; the rung is gone

    data_files = _data_files(unit)
    contracts = output_contract.detect(instruction, inputs=data_files)

    for contract in contracts:
        if contract.depends_on_checks:
            notes.append(f"contract for {contract.filename} came from checks/ - "
                         "not available at final evaluation")
        if contract.source == "default":
            notes.append(f"contract for {contract.filename} is a guess, not a read")

    return TaskSpec(
        task_id=card.get("task", {}).get("id", unit.name),
        instruction=instruction,
        input_root=str(unit),
        data_files=data_files,
        category=category,
        contracts=contracts,
        checks_available=checks_available,
        notes=notes,
        agent_timeout_sec=agent_timeout,
        canary_guid=canary,
    )
