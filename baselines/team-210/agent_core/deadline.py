"""Wall-clock budget.

`card.toml` gives the agent 1800 seconds. A container killed at the cap may not
flush anything - no artifact, no log, no failure map. Since the reward is binary
either way, the difference between exiting cleanly and being killed is entirely
in what we learn from the run, which is the thing we actually need during
development.

The loop asks `can_afford()` before starting an attempt rather than checking
elapsed time after, because the useful question is not "how long have I been
running" but "is there room for another full round plus the write".
"""

from __future__ import annotations

import time

DEFAULT_BUDGET_SEC = 1800.0
#: Reserved for writing the best artifact and shutting down cleanly.
DEFAULT_RESERVE_SEC = 120.0


class Deadline:
    #: The reserve may never eat the whole budget. A sweep runs units at a small
    #: budget for speed, and a fixed 120s reserve against a 90s budget makes
    #: `remaining` negative before the first attempt: every unit then reports
    #: TIMEOUT on iteration zero and the failure map says nothing true. Found by
    #: running the matrix, where all 87 units came back timed out in 90 seconds.
    MAX_RESERVE_FRACTION = 0.25

    def __init__(self, budget_sec: float = DEFAULT_BUDGET_SEC,
                 reserve_sec: float = DEFAULT_RESERVE_SEC) -> None:
        self.started = time.monotonic()
        self.budget = float(budget_sec)
        self.reserve = min(float(reserve_sec),
                           self.budget * self.MAX_RESERVE_FRACTION)
        #: Measured cost of the attempts made so far, used to predict the next.
        self._attempt_costs: list[float] = []

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining(self) -> float:
        """Seconds left before the reserve must be protected."""
        return self.budget - self.reserve - self.elapsed

    def record_attempt(self, seconds: float) -> None:
        self._attempt_costs.append(seconds)

    @property
    def predicted_attempt_cost(self) -> float:
        """What the next attempt will probably cost.

        The worst observed rather than the mean: attempts get slower as the
        solution grows, and being optimistic here is how a run gets killed.
        """
        if not self._attempt_costs:
            return 0.0
        return max(self._attempt_costs)

    def can_afford(self, minimum_sec: float = 30.0) -> bool:
        need = max(minimum_sec, self.predicted_attempt_cost)
        return self.remaining > need

    def summary(self) -> dict:
        return {
            "elapsed_sec": round(self.elapsed, 2),
            "remaining_sec": round(self.remaining, 2),
            "attempts_timed": len(self._attempt_costs),
            "worst_attempt_sec": round(self.predicted_attempt_cost, 2),
        }
