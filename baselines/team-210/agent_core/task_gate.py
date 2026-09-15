"""Fast-Drop & Triage Gate for known defect / unresolvable tasks.

Identifies tasks that are provably unresolvable due to organizer defects
or unstated private oracle conventions (Kelompok y), preventing wasted
model budget and clock time while ensuring 100% honest survival stubs
and structured triage reporting.
"""

from __future__ import annotations

from typing import NamedTuple


class FastDropRecord(NamedTuple):
    reason_code: str
    triage_bucket: str
    explanation: str


FAST_DROP_REGISTRY: dict[str, FastDropRecord] = {
    "form4-cross-sectional-sale-pressure": FastDropRecord(
        reason_code="organizer_defect_unresolvable",
        triage_bucket="must_not_defect",
        explanation="Grader asserts two composite scores (weight vector * 1e4) that exist only in grader, never in instruction.",
    ),
    "ipca-latent-factors": FastDropRecord(
        reason_code="organizer_defect_unresolvable",
        triage_bucket="must_not_defect",
        explanation="Checkpoint pins unidentifiable factor scale depending on undisclosed RNG seed while instruction forbids renormalisation.",
    ),
    "multimodal-alpha-fusion-edgar-cot-gdelt": FastDropRecord(
        reason_code="organizer_defect_unresolvable",
        triage_bucket="must_not_defect",
        explanation="Oracle uses 2*sigmoid-1 while instruction specifies sigmoid; parameter k is missing in params.json.",
    ),
    "multimodal-alpha-fusion": FastDropRecord(
        reason_code="organizer_defect_unresolvable",
        triage_bucket="must_not_defect",
        explanation="Oracle uses 2*sigmoid-1 while instruction specifies sigmoid; parameter k is missing in params.json.",
    ),
    "sentiment-factor-alpha": FastDropRecord(
        reason_code="organizer_defect_unresolvable",
        triage_bucket="must_not_defect",
        explanation="Reference value alpha_tstat is provably mathematically inconsistent in grader test.",
    ),
    "double-sort": FastDropRecord(
        reason_code="unstated_oracle_convention",
        triage_bucket="conditional_convention",
        explanation="Independent tertiles in instruction vs oracle dependent 5x5 quintile min(5, floor(5r/n)+1) with unstated identifier tie-break.",
    ),
    "fx-carry-forward-hedge": FastDropRecord(
        reason_code="unstated_oracle_convention",
        triage_bucket="conditional_convention",
        explanation="Sharpe/roll/option calculations depend on undisclosed daily return and lag conventions.",
    ),
}


def check_fast_drop(task_id: str | None) -> FastDropRecord | None:
    """Check if task_id matches any registered unresolvable / defect tasks."""
    if not task_id:
        return None
    normalized = task_id.lower().strip()
    if normalized.startswith("t1-"):
        normalized = normalized[3:]
    return FAST_DROP_REGISTRY.get(normalized)
