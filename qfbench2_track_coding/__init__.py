"""Track 1 (Coding Agents) scoring package.

Public interface consumed by the shared harness and by the sealed final scorer:

    build_verifier(ctx: dict) -> HierarchicalVerifier
        Construct the full g0-g3 gate chain for a single T1 evaluation attempt.

    LEADERBOARD_SORT : str
        Direction for the leaderboard; Track 1 ranks higher pass@k as better.

The scoring primitive (pass@k) lives in the shared package:
    qfbench2_common.scoring.passk.pass_at_k
    qfbench2_common.scoring.passk.suite_summary
    qfbench2_common.scoring.bootstrap.bootstrap_ci
"""

from __future__ import annotations

from .scoring import LEADERBOARD_SORT, build_verifier

__all__ = ["build_verifier", "LEADERBOARD_SORT"]
