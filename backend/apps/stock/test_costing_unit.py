"""Unit tests for the pure costing functions in apps/stock/costing.py.

Pure logic, no database. Covers the T-302 weighted-average costing rules from
blueprint 6.3 and worked examples 12.1.

These tests must never touch the database (the ``unit`` marker is not promoted
to ``django_db`` by the shared conftest).
"""

from decimal import Decimal
from random import Random

import pytest
from common.errors import VALIDATION_ERROR
from common.money import q3, q4

from apps.stock.costing import (
    after_adjustment_in,
    after_adjustment_out,
    after_purchase,
    after_purchase_return,
    after_return,
    after_sale,
    stock_value,
)
from apps.stock.exceptions import StockError

pytestmark = pytest.mark.unit

ZERO = Decimal("0")


def test_worked_example_12_1():
    # 10 tins at 300, then 10 tins at 400 -> average 350, quantity 20.
    first = after_purchase(ZERO, None, Decimal("10"), Decimal("300"))
    assert first == Decimal("300.0000")
    second = after_purchase(Decimal("10"), Decimal("300"), Decimal("10"), Decimal("400"))
    assert second == Decimal("350.0000")


def test_purchase_into_zero_stock_takes_incoming_cost():
    assert after_purchase(ZERO, None, Decimal("5"), Decimal("100")) == Decimal("100.0000")


def test_purchase_into_negative_stock_takes_incoming_cost():
    assert after_purchase(Decimal("-3"), None, Decimal("5"), Decimal("100")) == Decimal("100.0000")


def test_existing_stock_without_cost_raises():
    with pytest.raises(StockError) as cm:
        after_purchase(Decimal("5"), None, Decimal("3"), Decimal("100"))
    assert cm.value.code == VALIDATION_ERROR
    assert "unit_cost" in cm.value.fields


def test_average_lies_between_old_average_and_cost():
    result = after_purchase(Decimal("10"), Decimal("300"), Decimal("10"), Decimal("400"))
    assert Decimal("300") <= result <= Decimal("400")
    result = after_purchase(Decimal("10"), Decimal("400"), Decimal("10"), Decimal("300"))
    assert Decimal("300") <= result <= Decimal("400")


def test_rounding_half_up_at_fifth_decimal():
    # (1 x 1.0000 + 1 x 1.0001) / 2 = 1.00005 -> half up to 1.0001
    assert after_purchase(
        Decimal("1"), Decimal("1.0000"), Decimal("1"), Decimal("1.0001")
    ) == Decimal("1.0001")
    # (1 x 1.0000 + 1 x 1.0002) / 2 = 1.0001 exactly, stays
    assert after_purchase(
        Decimal("1"), Decimal("1.0000"), Decimal("1"), Decimal("1.0002")
    ) == Decimal("1.0001")


def test_rejects_float_unit_cost():
    with pytest.raises(TypeError):
        after_purchase(ZERO, None, Decimal("5"), 5 / 2)


def test_large_and_tiny_quantities():
    assert after_purchase(ZERO, None, Decimal("1000000"), Decimal("0.0001")) == Decimal("0.0001")
    assert after_purchase(
        Decimal("0.001"), Decimal("0.0001"), Decimal("0.001"), Decimal("0.0002")
    ) == Decimal("0.0002")


def test_after_return_identical_to_after_purchase():
    assert after_return(
        Decimal("10"), Decimal("300"), Decimal("10"), Decimal("400")
    ) == after_purchase(Decimal("10"), Decimal("300"), Decimal("10"), Decimal("400"))


def test_return_at_cost_snapshot_raises_average():
    # Stock 10 at 300; 10 returned at cost snapshot 400 -> average raised to 350.
    assert after_return(Decimal("10"), Decimal("300"), Decimal("10"), Decimal("400")) == Decimal(
        "350.0000"
    )


def test_return_at_cost_snapshot_lowers_average():
    # Stock 10 at 350; 5 returned at original cost 300 -> average 333.3333.
    assert after_return(Decimal("10"), Decimal("350"), Decimal("5"), Decimal("300")) == Decimal(
        "333.3333"
    )


def test_return_into_zero_stock_takes_incoming_cost():
    assert after_return(ZERO, None, Decimal("5"), Decimal("100")) == Decimal("100.0000")


def test_return_existing_stock_without_cost_raises():
    with pytest.raises(StockError) as cm:
        after_return(Decimal("5"), None, Decimal("3"), Decimal("100"))
    assert cm.value.code == VALIDATION_ERROR


def test_after_sale_unchanged():
    assert after_sale(Decimal("350.0000")) == Decimal("350.0000")


def test_after_adjustment_in_unchanged():
    assert after_adjustment_in(Decimal("350.0000")) == Decimal("350.0000")


def test_after_adjustment_out_unchanged():
    assert after_adjustment_out(Decimal("350.0000")) == Decimal("350.0000")


def test_after_sale_none_stays_none():
    assert after_sale(None) is None


def test_purchase_return_worked_example_value():
    # qty 15 at average 396.6667, return 4 units at cost 420 -> 388.1819
    result = after_purchase_return(Decimal("15"), Decimal("396.6667"), Decimal("4"), Decimal("420"))
    assert result == Decimal("388.1819")


def test_purchase_return_returning_everything_keeps_average():
    assert after_purchase_return(
        Decimal("15"), Decimal("396.6667"), Decimal("15"), Decimal("420")
    ) == Decimal("396.6667")


def test_purchase_return_cost_exceeding_remaining_value_raises():
    # qty 10 at 100, return 9 at cost 200 -> remaining value -800 -> error
    with pytest.raises(StockError) as cm:
        after_purchase_return(Decimal("10"), Decimal("100"), Decimal("9"), Decimal("200"))
    assert cm.value.code == VALIDATION_ERROR
    assert "unit_cost" in cm.value.fields


def test_purchase_return_all_at_any_cost_keeps_average_no_error():
    assert after_purchase_return(
        Decimal("10"), Decimal("100"), Decimal("10"), Decimal("9999")
    ) == Decimal("100.0000")


def test_purchase_return_into_zero_stock_keeps_none_average():
    assert after_purchase_return(ZERO, None, Decimal("5"), Decimal("100")) is None


def test_stock_value_quantises_to_2_decimals():
    assert stock_value(Decimal("15"), Decimal("396.6667")) == Decimal("5950.00")
    assert stock_value(Decimal("3"), Decimal("333.3333")) == Decimal("1000.00")


def test_non_recoverable_gst_included_in_inventory_cost():
    # GST non-recoverable at 18%: unit costs 354 and 472 -> avg 413.
    first = after_purchase(ZERO, None, Decimal("10"), Decimal("354"))
    second = after_purchase(Decimal("10"), Decimal("354"), Decimal("10"), Decimal("472"))
    assert first == Decimal("354.0000")
    assert second == Decimal("413.0000")


def test_recoverable_gst_excluded_from_inventory_cost():
    # GST recoverable: unit costs 300 and 400 -> avg 350.
    first = after_purchase(ZERO, None, Decimal("10"), Decimal("300"))
    second = after_purchase(Decimal("10"), Decimal("300"), Decimal("10"), Decimal("400"))
    assert first == Decimal("300.0000")
    assert second == Decimal("350.0000")


def test_random_sequences_invariants():
    rng = Random(12345)
    qty = ZERO
    avg = None
    for _ in range(500):
        if rng.randrange(2) == 0 or qty <= 0:
            in_qty = q3(Decimal(str(rng.uniform(1, 10))))
            cost = q4(Decimal(str(rng.uniform(1, 1000))))
            old_qty, old_avg = qty, avg
            avg = after_purchase(old_qty, old_avg, in_qty, cost)
            qty = q3(old_qty + in_qty)
            if old_qty > 0 and old_avg is not None:
                lo = min(old_avg, cost)
                hi = max(old_avg, cost)
                assert lo <= avg <= hi, f"average {avg} not between {old_avg} and {cost}"
                exact = old_qty * old_avg + in_qty * cost
                value = qty * avg
                assert abs(value - exact) <= Decimal("0.00005") * qty
            assert avg is None or avg >= 0
        else:
            out_qty = q3(Decimal(rng.randrange(1, int(qty * 1000) + 1)) / Decimal(1000))
            old_avg = avg
            avg = after_sale(avg)
            qty = q3(qty - out_qty)
            assert avg == old_avg
            assert avg is None or avg >= 0
