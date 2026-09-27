"""Pro-rata allocation that sums exactly: the largest-remainder method."""

from __future__ import annotations

import math
from collections.abc import Hashable, Mapping
from decimal import Decimal
from fractions import Fraction

PENNY = Decimal("0.01")


def allocate[K: Hashable](
    total: Decimal,
    weights: Mapping[K, Decimal],
    *,
    quantum: Decimal = PENNY,
) -> dict[K, Decimal]:
    """Split `total` across keys in proportion to `weights`.

    Guarantees:
      * sum(result.values()) == total, exactly;
      * each share is within one quantum of its exact pro-rata value;
      * deterministic: leftover quanta go to the largest fractional remainders,
        ties broken by str(key).
    Works for negative totals (e.g. an allocated loss) by allocating the magnitude.
    """
    if not weights:
        raise ValueError("cannot allocate across zero recipients")
    if any(w < 0 for w in weights.values()):
        raise ValueError("weights must be non-negative")
    weight_sum = sum(weights.values(), Decimal(0))
    if weight_sum == 0:
        raise ValueError("weights must not all be zero")

    units = Fraction(abs(total)) / Fraction(quantum)
    if units.denominator != 1:
        raise ValueError(f"{total} is not a whole multiple of {quantum}")
    total_units = int(units)

    exact = {k: total_units * Fraction(w) / Fraction(weight_sum) for k, w in weights.items()}
    floors = {k: math.floor(v) for k, v in exact.items()}
    leftover = total_units - sum(floors.values())
    by_remainder = sorted(weights, key=lambda k: (-(exact[k] - floors[k]), str(k)))
    for k in by_remainder[:leftover]:
        floors[k] += 1

    sign = -1 if total < 0 else 1
    return {k: sign * floors[k] * quantum for k in weights}
