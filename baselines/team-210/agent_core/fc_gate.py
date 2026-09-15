"""False-confidence risk gate - the output-level honesty driver.

Calibrated on 38 real contrast pairs from the v1 87-unit sweep (17
false-confidence solutions vs 21 honestly-passing ones): leave-one-out AUC
0.706. The direction is counterintuitive and earned: dishonest successes are
SHORT programs DENSE with self-asserts - assert theater - while honest
passes are longer and reference tolerances more. A model asserting its own
formula passes its own bug; this gate looks at the shape of that behaviour.

Soft gate by design: at self-check PASS, a high risk score buys ONE extra
repair round demanding an independent second computation path - it never
blocks an answer outright (AUC 0.7 is a nudge, not a judge).

Constants come from stress_suite/calibrate_fc_gate.py; recalibrate as the
contrast set grows and paste the new numbers here.
"""

from __future__ import annotations

import math
import re

#: Standardisation + weights from the 2026-09-04 calibration (n=38).
_MEANS = {"asserts_per_100loc": 7.386, "n_assert": 16.684,
          "readback_after_write": 0.974, "tolerance_refs": 8.105,
          "loc": 237.658}
_STDS = {"asserts_per_100loc": 3.333, "n_assert": 7.049,
         "readback_after_write": 0.16, "tolerance_refs": 6.512,
         "loc": 76.378}
_WEIGHTS = {"asserts_per_100loc": +0.731, "n_assert": +0.052,
            "readback_after_write": +0.284, "tolerance_refs": -0.275,
            "loc": -0.511}
_INTERCEPT = -0.251

#: Precision-leaning: only clearly risky shapes spend the extra round.
RISK_THRESHOLD = 0.60


def features_of(source: str) -> dict:
    loc = max(1, source.count("\n"))
    n_assert = len(re.findall(r"^\s*assert\b|raise\s+AssertionError", source,
                              re.M))
    readback = len(re.findall(r"read_parquet|read_csv|json\.load", source))
    writes = len(re.findall(r"to_parquet|to_csv|json\.dump|write_text", source))
    tol_refs = len(re.findall(r"tol|atol|rtol|1e-\d|np\.isclose|allclose",
                              source))
    return {"asserts_per_100loc": 100.0 * n_assert / loc,
            "n_assert": float(n_assert),
            "readback_after_write": float(readback >= writes and writes > 0),
            "tolerance_refs": float(tol_refs),
            "loc": float(loc)}


def risk_of(source: str) -> float:
    """P(false confidence) estimate for a solution that self-checked PASS."""
    f = features_of(source)
    z = _INTERCEPT
    for name, weight in _WEIGHTS.items():
        z += weight * (f[name] - _MEANS[name]) / (_STDS[name] + 1e-9)
    return 1.0 / (1.0 + math.exp(-z))


CROSS_CHECK_DEMAND = (
    "self-audit: the answer passed local checks, but its shape matches the "
    "false-confidence profile (short program, self-referential asserts). "
    "Recompute the HEADLINE quantities a SECOND, independent way (closed "
    "form vs simulation, matrix vs iterative, library vs manual), assert "
    "agreement within the stated tolerance, and only then rewrite the "
    "deliverables. Keep everything that already verified.")
