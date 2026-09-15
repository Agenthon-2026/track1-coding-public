"""The structures that flow between modules.

These are written as dataclasses rather than described as pseudocode because a
dataclass is executable, type-checked and does not drift from the code it
describes. Three of them carry the decisions that are expensive to get wrong.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Literal


class FailureKind(enum.Enum):
    """Why an attempt did not score.

    This drives two things: what the repair loop tries next, and what the local
    evaluation matrix reports. A vague taxonomy makes both useless, so every
    member names a distinct remedy.
    """

    PASS = "pass"
    MISSING_OUTPUT = "missing_output"          # nothing at the deliverable path
    SCHEMA_MISMATCH = "schema_mismatch"        # wrong columns / shape / dtype
    IMPORT_ERROR = "import_error"              # a package the image lacks
    RUNTIME_ERROR = "runtime_error"            # the solution raised
    INVARIANT_VIOLATION = "invariant_violation"  # ran, but the numbers are wrong
    TIMEOUT = "timeout"                        # exceeded the per-attempt budget
    MODEL_UNAVAILABLE = "model_unavailable"    # endpoint refused or absent
    NO_CONTRACT = "no_contract"                # could not tell what to write

    @property
    def repairable(self) -> bool:
        """Is another iteration worth spending budget on?

        IMPORT_ERROR is not: the image is fixed at build time, so a package that
        is missing now is missing for every remaining attempt. MODEL_UNAVAILABLE
        is not either - retrying a refused endpoint burns the clock.
        """
        return self in {
            FailureKind.SCHEMA_MISMATCH,
            FailureKind.RUNTIME_ERROR,
            FailureKind.INVARIANT_VIOLATION,
            FailureKind.MISSING_OUTPUT,
        }


@dataclass(frozen=True)
class OutputContract:
    """What the deliverable must look like.

    Mined from 87 public checkers: 282 distinct deliverable basenames, and the
    four most common cover only 23% of references. The filename is therefore not
    guessable, and a wrong one fails `test_file_exists` no matter how good the
    finance is. This is the highest-leverage structure in the agent.

    `source` exists so the dependency on `checks/` is visible in data rather than
    buried in control flow. At final evaluation the checker may not be mounted;
    any contract whose source is CHECKS is a contract the agent must be able to
    derive another way.
    """

    filename: str
    fmt: Literal["parquet", "csv", "json", "txt", "unknown"]
    required_columns: tuple[str, ...] = ()
    row_key: str | None = None            # identifier that must survive, e.g. option_id
    row_count_from: str | None = None     # input file whose row count must be matched
    source: Literal["instruction", "checks", "template", "default"] = "default"

    @property
    def depends_on_checks(self) -> bool:
        return self.source == "checks"


@dataclass
class TaskSpec:
    """Everything the agent knows about a unit before it writes any code."""

    task_id: str
    instruction: str
    input_root: str
    data_files: tuple[str, ...] = ()
    category: str | None = None           # from card.toml; unreliable, see below
    contracts: tuple[OutputContract, ...] = ()
    checks_available: bool = False
    notes: list[str] = field(default_factory=list)
    #: `[agent].timeout_sec` from card.toml - the authority on the budget.
    agent_timeout_sec: float | None = None
    #: `[contamination].canary_guid` - must never appear in anything we write.
    canary_guid: str | None = None
    #: Phase 0 output: what the agent's own reading program printed from the
    #: real inputs (schema, dtypes, keys, ranges). Empty until explored.
    evidence: str = ""

    @property
    def normalised_category(self) -> str:
        """card.toml categories are noisy: 34 distinct strings across 87 units,
        with four spellings of derivatives pricing alone and one entry holding
        two categories joined by a comma. Normalise, and treat the result as a
        hint rather than a routing key - `cross-domain` is the largest bucket.
        """
        if not self.category:
            return "unknown"
        first = self.category.split(",")[0]
        slug = first.strip().lower().replace("_", "-").replace(" ", "-")
        aliases = {
            "derivatives": "derivatives-pricing",
            "pricing": "derivatives-pricing",
            "interest-rate-derivatives": "derivatives-pricing",
            "volatility-modeling": "derivatives-pricing",
            "credit-risk": "credit",
            "credit-analysis": "credit",
            "factor-models": "factor-research",
            "predictive-alpha-modeling": "factor-research",
            "cross-sectional-strategies": "factor-research",
            "risk-modeling": "risk-management",
            "extreme-value-theory": "risk-management",
            "dependence-modeling": "risk-management",
            "portfolio-analysis": "portfolio",
            "performance-attribution": "portfolio",
            "fx-strategy": "fx",
            "fx-pricing": "fx",
            "cross-currency-rates": "fx",
            "crypto": "fx",
            "execution": "microstructure",
            "strategy": "backtesting",
        }
        return aliases.get(slug, slug)


@dataclass
class Attempt:
    """One pass through write - run - check."""

    index: int
    kind: FailureKind
    detail: str = ""
    seconds: float = 0.0
    artifacts: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.kind is FailureKind.PASS
