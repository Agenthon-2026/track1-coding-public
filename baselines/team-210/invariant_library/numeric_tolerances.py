"""Tolerance policy, not a tolerance table.

Mining the 87 public checkers found **47 distinct tolerance values**. The
distribution is flat enough that no single number is safe:

    0.01   44x        0.001  24x        1e-08  16x
    1e-06  37x        0.02   23x        0.03   10x
    0.05   33x        1e-04  20x        1e-05   9x
    0.1    27x        1e-10  17x        1e-12   9x

The 1e-5 that the worked exemplar uses for delta bounds appears nine times out
of two hundred. A fixed table would therefore be wrong most of the time, so
this module answers a different question: given what the instruction says and
what kind of quantity this is, what is the loosest tolerance that is still
defensible?

Loosest-defensible is the right target because the failure that costs us is
being *stricter* than the grader - that rejects a correct answer and burns an
iteration. Being looser only risks passing something the grader will fail, and
the grader is the one that decides anyway.
"""

from __future__ import annotations

import re

#: Sign guards - "must be positive" - are checked near zero. The public checkers
#: use 1e-6 for this more than any other value.
SIGN_GUARD = 1e-6
#: Bound guards - "delta is in (0,1)" - allow a value to land exactly on the
#: bound, which happens whenever a normal CDF saturates in floating point.
BOUND_GUARD = 1e-5
#: Comparing two quantities the solution computed itself.
INTERNAL_CONSISTENCY = 5e-3
#: Comparing against a closed-form identity the task states.
IDENTITY = 1e-3
#: Nothing in the instruction, nothing inferable: the modal value.
FALLBACK = 1e-2

_EXPLICIT = re.compile(
    r"(?:tolerance|atol|rtol|within|accurate to|precision of)\s*"
    r"(?:of\s*)?[:=]?\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)")
_DECIMALS = re.compile(r"(\d+)\s*(?:decimal places|dp\b|significant figures|sig\.? figs?)")


def from_instruction(text: str) -> float | None:
    """A tolerance the task states outright, if it states one.

    This rung is first because a stated tolerance is not a guess. Roughly a
    quarter of the public instructions carry one somewhere.
    """
    match = _EXPLICIT.search(text)
    if match:
        try:
            value = float(match.group(1))
            if 0.0 < value < 1.0:
                return value
        except ValueError:
            pass
    match = _DECIMALS.search(text)
    if match:
        return 10.0 ** (-int(match.group(1)))
    return None


def for_check(kind: str, instruction: str = "") -> float:
    """The tolerance to use for one class of check.

    kind is one of: sign, bound, consistency, identity.
    """
    stated = from_instruction(instruction)
    if stated is not None:
        return stated
    return {
        "sign": SIGN_GUARD,
        "bound": BOUND_GUARD,
        "consistency": INTERNAL_CONSISTENCY,
        "identity": IDENTITY,
    }.get(kind, FALLBACK)
