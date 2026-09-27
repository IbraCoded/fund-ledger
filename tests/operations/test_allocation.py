from decimal import Decimal as D
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from operations.allocation import allocate

weights_strategy = st.lists(
    st.decimals(min_value=D("0.01"), max_value=D("1000000000"), places=2), min_size=1, max_size=50
)


@given(pennies=st.integers(min_value=0, max_value=10**11), weights=weights_strategy)
def test_shares_sum_exactly_and_stay_within_a_penny(pennies, weights):
    total = D(pennies).scaleb(-2)
    w = dict(enumerate(weights))
    shares = allocate(total, w)

    assert sum(shares.values()) == total
    weight_sum = sum(weights)
    for k, share in shares.items():
        exact = Fraction(total) * Fraction(w[k]) / Fraction(weight_sum)
        assert abs(Fraction(share) - exact) < Fraction(1, 100)
        assert share >= 0


@pytest.mark.parametrize("n", range(1, 51))
def test_awkward_total_across_n_equal_partners(n):
    total = D("1000000.01")
    shares = allocate(total, {i: D("1") for i in range(n)})
    assert sum(shares.values()) == total
    assert max(shares.values()) - min(shares.values()) <= D("0.01")


def test_is_deterministic():
    weights = {"b": D("1"), "a": D("1"), "c": D("1")}
    assert allocate(D("1.00"), weights) == allocate(D("1.00"), dict(reversed(weights.items())))
    assert allocate(D("1.00"), weights) == {"a": D("0.34"), "b": D("0.33"), "c": D("0.33")}


def test_negative_totals_allocate_the_magnitude():
    shares = allocate(D("-10.00"), {"x": D("1"), "y": D("2")})
    assert shares == {"x": D("-3.33"), "y": D("-6.67")}


@pytest.mark.parametrize(
    ("total", "weights"),
    [
        (D("1.00"), {}),
        (D("1.00"), {"x": D("0")}),
        (D("1.00"), {"x": D("-1")}),
        (D("1.001"), {"x": D("1")}),
    ],
)
def test_rejects_impossible_allocations(total, weights):
    with pytest.raises(ValueError):
        allocate(total, weights)
