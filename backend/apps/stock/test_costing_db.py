"""Database tests for T-302 weighted-average costing through StockService.

Exercises PURCHASE, SALE_RETURN, CANCEL_REVERSAL, ADJ_IN and PURCHASE_RETURN
against the append-only ledger, plus the read-only ledger selectors.
"""

from datetime import date
from decimal import Decimal

import pytest
from common.errors import INSUFFICIENT_STOCK, VALIDATION_ERROR
from django.db import connection, transaction
from testsupport.factories import give_opening_stock, make_product

from apps.core.models import AppSettings
from apps.stock.exceptions import StockError
from apps.stock.models import MovementType, StockMovement
from apps.stock.selectors import recompute_from_ledger, verify_product_ledger
from apps.stock.services import MovementRequest, StockService

pytestmark = pytest.mark.db

TODAY = date(2026, 11, 5)


def _settings(allow_negative_stock=False):
    settings = AppSettings.get_settings()
    settings.allow_negative_stock = allow_negative_stock
    settings.save()
    return settings


def _movement(
    product_id,
    movement_type,
    quantity=Decimal("1"),
    movement_date=TODAY,
    unit_cost=None,
    reason="",
):
    return MovementRequest(
        product_id=product_id,
        movement_type=movement_type,
        quantity=quantity,
        movement_date=movement_date,
        unit_cost=unit_cost,
        reason=reason,
    )


def _last_movement(product):
    return StockMovement.objects.filter(product=product).order_by("-id").first()


def _assert_row_matches_last_movement(product):
    movement = _last_movement(product)
    product.refresh_from_db()
    assert product.qty_on_hand == movement.qty_after
    assert product.avg_buying_price == movement.avg_cost_after


def _assert_ledger_verifies(product):
    result = verify_product_ledger(product.id)
    assert result.ok is True
    product.refresh_from_db()
    assert result.expected_qty == product.qty_on_hand
    assert result.expected_avg == product.avg_buying_price


def test_purchase_updates_rows_and_last_buying_price():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE, Decimal("10"), TODAY, Decimal("400"))
        )
    assert movement.unit_cost == Decimal("400.0000")
    assert movement.quantity == Decimal("10.000")
    assert movement.qty_after == Decimal("20.000")
    assert movement.avg_cost_after == Decimal("350.0000")
    assert movement.avg_before == Decimal("300.0000")
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("20.000")
    assert product.avg_buying_price == Decimal("350.0000")
    assert product.last_buying_price == Decimal("400.0000")
    _assert_ledger_verifies(product)


def test_last_buying_price_changes_only_on_purchase():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    assert product.last_buying_price is None
    with transaction.atomic():
        StockService.apply_movement(_movement(product.id, MovementType.SALE, Decimal("3"), TODAY))
    product.refresh_from_db()
    assert product.last_buying_price is None
    with transaction.atomic():
        StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE, Decimal("5"), TODAY, Decimal("400"))
        )
    product.refresh_from_db()
    assert product.last_buying_price == Decimal("400.0000")
    with transaction.atomic():
        StockService.apply_movement(
            _movement(product.id, MovementType.ADJ_OUT, Decimal("2"), TODAY, reason="loss")
        )
    product.refresh_from_db()
    assert product.last_buying_price == Decimal("400.0000")
    with transaction.atomic():
        StockService.apply_movement(
            _movement(product.id, MovementType.SALE_RETURN, Decimal("2"), TODAY, Decimal("400"))
        )
    product.refresh_from_db()
    assert product.last_buying_price == Decimal("400.0000")


def test_adj_in_requires_reason():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    before = StockMovement.objects.count()
    with pytest.raises(StockError) as cm:
        with transaction.atomic():
            StockService.apply_movement(
                _movement(product.id, MovementType.ADJ_IN, Decimal("2"), TODAY, reason="")
            )
    assert cm.value.code == VALIDATION_ERROR
    assert StockMovement.objects.count() == before


def test_adj_in_refuses_unit_cost_when_average_exists():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    with pytest.raises(StockError) as cm:
        with transaction.atomic():
            StockService.apply_movement(
                _movement(
                    product.id,
                    MovementType.ADJ_IN,
                    Decimal("2"),
                    TODAY,
                    unit_cost=Decimal("400"),
                    reason="found",
                )
            )
    assert cm.value.code == VALIDATION_ERROR


def test_adj_in_requires_unit_cost_when_no_average():
    product = make_product()  # no stock, average is null
    with pytest.raises(StockError) as cm:
        with transaction.atomic():
            StockService.apply_movement(
                _movement(product.id, MovementType.ADJ_IN, Decimal("5"), TODAY, reason="found")
            )
    assert cm.value.code == VALIDATION_ERROR
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(
                product.id,
                MovementType.ADJ_IN,
                Decimal("5"),
                TODAY,
                unit_cost=Decimal("250"),
                reason="found",
            )
        )
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("5.000")
    assert product.avg_buying_price == Decimal("250.0000")
    assert movement.unit_cost == Decimal("250.0000")
    assert movement.avg_cost_after == Decimal("250.0000")


def test_adj_in_with_average_leaves_average_unchanged():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.ADJ_IN, Decimal("4"), TODAY, reason="found")
        )
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("14.000")
    assert product.avg_buying_price == Decimal("300.0000")
    assert movement.unit_cost == Decimal("300.0000")
    assert movement.avg_cost_after == Decimal("300.0000")


@pytest.mark.parametrize(
    "movement_type", [MovementType.PURCHASE, MovementType.SALE_RETURN, MovementType.CANCEL_REVERSAL]
)
def test_unit_cost_required(movement_type):
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    with pytest.raises(StockError) as cm:
        with transaction.atomic():
            StockService.apply_movement(_movement(product.id, movement_type, Decimal("5"), TODAY))
    assert cm.value.code == VALIDATION_ERROR


@pytest.mark.parametrize("bad_cost", [Decimal("1.00005"), Decimal("-1")])
def test_unit_cost_rejected_5_decimals_or_negative(bad_cost):
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    with pytest.raises(StockError) as cm:
        with transaction.atomic():
            StockService.apply_movement(
                _movement(product.id, MovementType.PURCHASE, Decimal("5"), TODAY, bad_cost)
            )
    assert cm.value.code == VALIDATION_ERROR


def test_sale_return_raises_average_and_leaves_last_buying_price():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    with transaction.atomic():
        StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE, Decimal("10"), TODAY, Decimal("400"))
        )
    # qty 20 at average 350, last_buying_price 400
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.SALE_RETURN, Decimal("5"), TODAY, Decimal("400"))
        )
    # after_return(20, 350, 5, 400) = (7000 + 2000) / 25 = 360
    assert movement.quantity == Decimal("5.000")
    assert movement.qty_after == Decimal("25.000")
    assert movement.avg_cost_after == Decimal("360.0000")
    assert movement.avg_before == Decimal("350.0000")
    product.refresh_from_db()
    assert product.avg_buying_price == Decimal("360.0000")
    assert product.last_buying_price == Decimal("400.0000")


def test_cancel_reversal_same_costing_as_sale_return():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    with transaction.atomic():
        StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE, Decimal("10"), TODAY, Decimal("400"))
        )
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.CANCEL_REVERSAL, Decimal("5"), TODAY, Decimal("400"))
        )
    assert movement.avg_cost_after == Decimal("360.0000")
    product.refresh_from_db()
    assert product.avg_buying_price == Decimal("360.0000")
    assert product.last_buying_price == Decimal("400.0000")


def test_purchase_return_with_unit_cost():
    product = make_product()
    give_opening_stock(product, Decimal("15"), Decimal("396.6667"), TODAY)
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE_RETURN, Decimal("4"), TODAY, Decimal("420"))
        )
    assert movement.quantity == Decimal("-4.000")
    assert movement.unit_cost == Decimal("420.0000")
    assert movement.qty_after == Decimal("11.000")
    assert movement.avg_cost_after == Decimal("388.1819")
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("11.000")
    assert product.avg_buying_price == Decimal("388.1819")
    assert product.last_buying_price is None
    _assert_ledger_verifies(product)


def test_purchase_return_without_unit_cost_uses_current_average():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE_RETURN, Decimal("4"), TODAY)
        )
    assert movement.unit_cost is None
    assert movement.qty_after == Decimal("6.000")
    assert movement.avg_cost_after == Decimal("300.0000")
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("6.000")
    assert product.avg_buying_price == Decimal("300.0000")


def test_insufficient_stock_on_purchase_return_larger_than_stock():
    _settings(allow_negative_stock=False)
    product = make_product()
    give_opening_stock(product, Decimal("5"), Decimal("100"), TODAY)
    before = StockMovement.objects.count()
    with pytest.raises(StockError) as cm:
        with transaction.atomic():
            StockService.apply_movement(
                _movement(product.id, MovementType.PURCHASE_RETURN, Decimal("10"), TODAY)
            )
    assert cm.value.code == INSUFFICIENT_STOCK
    assert StockMovement.objects.count() == before
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("5.000")


def test_batch_two_purchases_sees_running_average():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("300"), TODAY)
    with transaction.atomic():
        movements = StockService.apply_movements(
            [
                _movement(product.id, MovementType.PURCHASE, Decimal("10"), TODAY, Decimal("400")),
                _movement(product.id, MovementType.PURCHASE, Decimal("10"), TODAY, Decimal("500")),
            ]
        )
    assert movements[0].qty_after == Decimal("20.000")
    assert movements[0].avg_cost_after == Decimal("350.0000")
    assert movements[1].qty_after == Decimal("30.000")
    assert movements[1].avg_cost_after == Decimal("400.0000")
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("30.000")
    assert product.avg_buying_price == Decimal("400.0000")


def test_failing_batch_saves_nothing_and_average_unchanged():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("100"), TODAY)
    before = StockMovement.objects.count()
    try:
        with transaction.atomic():
            StockService.apply_movements(
                [
                    _movement(
                        product.id, MovementType.PURCHASE, Decimal("5"), TODAY, Decimal("200")
                    ),
                    _movement(
                        product.id, MovementType.PURCHASE, Decimal("5"), TODAY, Decimal("1.00005")
                    ),
                ]
            )
    except StockError:
        pass
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("10.000")
    assert product.avg_buying_price == Decimal("100.0000")
    assert StockMovement.objects.count() == before


def test_purchase_into_negative_stock_takes_incoming_cost():
    _settings(allow_negative_stock=True)
    product = make_product()
    with transaction.atomic():
        StockService.apply_movement(_movement(product.id, MovementType.SALE, Decimal("5"), TODAY))
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("-5.000")
    assert product.avg_buying_price is None
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE, Decimal("3"), TODAY, Decimal("100"))
        )
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("-2.000")
    assert product.avg_buying_price == Decimal("100.0000")
    assert movement.avg_cost_after == Decimal("100.0000")
    assert product.last_buying_price == Decimal("100.0000")


def test_realistic_sequence_row_equals_last_movement_and_ledger_matches():
    product = make_product(product_code="SEQ-1")
    steps = [
        (MovementType.OPENING, Decimal("10"), Decimal("300"), ""),
        (MovementType.PURCHASE, Decimal("10"), Decimal("400"), ""),
        (MovementType.SALE, Decimal("15"), None, ""),
        (MovementType.SALE_RETURN, Decimal("5"), Decimal("300"), ""),
        (MovementType.ADJ_OUT, Decimal("2"), None, "damage"),
        (MovementType.PURCHASE_RETURN, Decimal("3"), Decimal("325"), ""),
    ]
    expected = [
        (Decimal("10.000"), Decimal("300.0000")),
        (Decimal("20.000"), Decimal("350.0000")),
        (Decimal("5.000"), Decimal("350.0000")),
        (Decimal("10.000"), Decimal("325.0000")),
        (Decimal("8.000"), Decimal("325.0000")),
        (Decimal("5.000"), Decimal("325.0000")),
    ]
    for (movement_type, quantity, unit_cost, reason), (exp_qty, exp_avg) in zip(
        steps, expected, strict=False
    ):
        with transaction.atomic():
            movement = StockService.apply_movement(
                _movement(product.id, movement_type, quantity, TODAY, unit_cost, reason)
            )
        assert (
            movement.qty_after == exp_qty
        ), f"{movement_type}: qty_after {movement.qty_after} != {exp_qty}"
        assert (
            movement.avg_cost_after == exp_avg
        ), f"{movement_type}: avg_cost_after {movement.avg_cost_after} != {exp_avg}"
        _assert_row_matches_last_movement(product)
        _assert_ledger_verifies(product)


def test_recompute_from_ledger_matches_product_row():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("100"), TODAY)
    with transaction.atomic():
        StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE, Decimal("5"), TODAY, Decimal("200"))
        )
    qty, avg, lbp = recompute_from_ledger(product.id)
    product.refresh_from_db()
    assert qty == product.qty_on_hand == Decimal("15.000")
    assert avg == product.avg_buying_price == Decimal("133.3333")
    assert lbp == product.last_buying_price == Decimal("200.0000")


def test_verify_product_ledger_reports_mismatch_and_writes_nothing():
    product = make_product()
    give_opening_stock(product, Decimal("10"), Decimal("100"), TODAY)
    before = StockMovement.objects.count()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE catalog_product SET qty_on_hand = 999 WHERE id = %s", [product.id]
            )
    result = verify_product_ledger(product.id)
    assert result.ok is False
    assert result.expected_qty == Decimal("10.000")
    assert result.actual_qty == Decimal("999")
    assert result.expected_avg == Decimal("100.0000")
    # writes nothing
    assert StockMovement.objects.count() == before
