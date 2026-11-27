"""Db tests for T-302b stock column overflow guards.

Verifies StockService rejects any result that would overflow the Product /
StockMovement decimal columns (qty ``Decimal(10,3)`` ceiling 9999999.999,
unit_cost / average ``Decimal(14,4)`` ceiling 9999999999.9999) with
``StockError(VALIDATION_ERROR, "value too large")`` before anything is
written, and that exact maximum values are accepted.

Pure service behaviour needing the database. Marked db.
"""

from datetime import date
from decimal import Decimal

import pytest
from common.errors import VALIDATION_ERROR
from django.db import transaction
from testsupport.factories import give_opening_stock, make_product

from apps.stock.exceptions import StockError
from apps.stock.models import MovementType, StockMovement
from apps.stock.services import MovementRequest, StockService

pytestmark = pytest.mark.db

TODAY = date(2026, 11, 5)

MAX_QTY = Decimal("9999999.999")  # Decimal(10,3) ceiling
MAX_COST = Decimal("9999999999.9999")  # Decimal(14,4) ceiling


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


def test_purchase_above_max_quantity_refused_writes_nothing():
    product = make_product(allow_fractional_qty=True)
    give_opening_stock(product, MAX_QTY, Decimal("100"), TODAY)
    product.refresh_from_db()
    assert product.qty_on_hand == MAX_QTY
    before = StockMovement.objects.count()
    with pytest.raises(StockError) as cm:
        with transaction.atomic():
            StockService.apply_movement(
                _movement(product.id, MovementType.PURCHASE, Decimal("1"), TODAY, Decimal("100"))
            )
    assert cm.value.code == VALIDATION_ERROR
    assert "quantity" in cm.value.fields
    assert StockMovement.objects.count() == before
    product.refresh_from_db()
    assert product.qty_on_hand == MAX_QTY


def test_unit_cost_above_max_refused_writes_nothing():
    product = make_product()
    give_opening_stock(product, Decimal("5"), Decimal("100"), TODAY)
    before = StockMovement.objects.count()
    with pytest.raises(StockError) as cm:
        with transaction.atomic():
            StockService.apply_movement(
                _movement(
                    product.id,
                    MovementType.PURCHASE,
                    Decimal("5"),
                    TODAY,
                    Decimal("10000000000.0000"),
                )
            )
    assert cm.value.code == VALIDATION_ERROR
    assert "unit_cost" in cm.value.fields
    assert StockMovement.objects.count() == before
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("5.000")


def test_purchase_to_exact_max_quantity_accepted():
    product = make_product(allow_fractional_qty=True)
    give_opening_stock(product, Decimal("9999999.998"), Decimal("100"), TODAY)
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE, Decimal("0.001"), TODAY, Decimal("100"))
        )
    product.refresh_from_db()
    assert product.qty_on_hand == MAX_QTY
    assert movement.qty_after == MAX_QTY


def test_unit_cost_at_exact_max_accepted():
    product = make_product()
    give_opening_stock(product, Decimal("5"), Decimal("100"), TODAY)
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.PURCHASE, Decimal("1"), TODAY, MAX_COST)
        )
    product.refresh_from_db()
    assert movement.unit_cost == MAX_COST
    assert product.last_buying_price == MAX_COST


def test_opening_at_exact_max_values_accepted():
    product = make_product(allow_fractional_qty=True)
    with transaction.atomic():
        movement = StockService.apply_movement(
            _movement(product.id, MovementType.OPENING, MAX_QTY, TODAY, MAX_COST)
        )
    product.refresh_from_db()
    assert product.qty_on_hand == MAX_QTY
    assert product.avg_buying_price == MAX_COST
    assert movement.qty_after == MAX_QTY
    assert movement.avg_cost_after == MAX_COST


def test_failing_batch_saves_nothing_on_overflow():
    product = make_product(allow_fractional_qty=True)
    give_opening_stock(product, Decimal("9999999.998"), Decimal("100"), TODAY)
    before = StockMovement.objects.count()
    try:
        with transaction.atomic():
            StockService.apply_movements(
                [
                    _movement(
                        product.id,
                        MovementType.PURCHASE,
                        Decimal("0.001"),
                        TODAY,
                        Decimal("100"),
                    ),
                    _movement(
                        product.id,
                        MovementType.PURCHASE,
                        Decimal("1"),
                        TODAY,
                        Decimal("100"),
                    ),  # pushes qty over MAX_QTY
                ]
            )
    except StockError:
        pass
    assert StockMovement.objects.count() == before
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("9999999.998")
