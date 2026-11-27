"""Tests for T-301: StockMovement ledger and StockService.

These tests are written before the implementation (TDD). They import
``apps.stock.models``, ``apps.stock.services`` and ``apps.stock.exceptions``,
which do not exist yet, so the module fails to import until the code is in
place. That is the expected failing state.
"""

import ast
from dataclasses import MISSING
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from re import compile as re_compile
from threading import Thread

from common.errors import (
    INSUFFICIENT_STOCK,
    PACK_CHANGE_NOT_ALLOWED,
    STOCK_NOT_TRACKED,
    VALIDATION_ERROR,
)
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.utils import IntegrityError
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory

from apps.catalog.models import Company, PackUnit, Product
from apps.catalog.serializers import ProductSerializer
from apps.catalog.services import ProductService, has_stock_history
from apps.core.models import AppSettings, AuditLog
from apps.stock.costing import opening_average, outflow_unit_cost
from apps.stock.exceptions import StockError
from apps.stock.models import MovementType, StockMovement
from apps.stock.services import MovementRequest, StockService

User = get_user_model()

OPENING = MovementType.OPENING
SALE = MovementType.SALE
ADJ_OUT = MovementType.ADJ_OUT
PURCHASE = MovementType.PURCHASE
SALE_RETURN = MovementType.SALE_RETURN
CANCEL_REVERSAL = MovementType.CANCEL_REVERSAL
PURCHASE_RETURN = MovementType.PURCHASE_RETURN
ADJ_IN = MovementType.ADJ_IN

TODAY = date(2026, 11, 5)


def _company(name="Berger Paints"):
    company = Company.objects.filter(name__iexact=name).first()
    if company is None:
        company = Company.objects.create(name=name)
    return company


def _product(
    company=None, product_code="STK-1", track_stock=True, allow_fractional_qty=False, **kwargs
):
    if company is None:
        company = _company()
    defaults = {
        "product_code": product_code,
        "company": company,
        "product_type": "Walmasta",
        "pack_size": Decimal("20"),
        "pack_unit": PackUnit.LTR,
        "track_stock": track_stock,
        "allow_fractional_qty": allow_fractional_qty,
    }
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


def _settings(allow_negative_stock=False):
    settings = AppSettings.get_settings()
    settings.allow_negative_stock = allow_negative_stock
    settings.save()
    return settings


def _movement(
    product_id,
    movement_type=SALE,
    quantity=Decimal("1"),
    movement_date=TODAY,
    unit_cost=None,
    reference_type="",
    reference_id="",
    reason="",
):
    return MovementRequest(
        product_id=product_id,
        movement_type=movement_type,
        quantity=quantity,
        movement_date=movement_date,
        unit_cost=unit_cost,
        reference_type=reference_type,
        reference_id=reference_id,
        reason=reason,
    )


class TestCosting(TestCase):
    """Pure costing helpers (costing.py)."""

    def test_outflow_unit_cost_is_average_before(self):
        self.assertEqual(outflow_unit_cost(Decimal("350.0000")), Decimal("350.0000"))
        self.assertIsNone(outflow_unit_cost(None))

    def test_opening_average_quantises_to_4_dp(self):
        self.assertEqual(opening_average(Decimal("100.00005")), Decimal("100.0001"))
        self.assertEqual(opening_average(Decimal("100")), Decimal("100.0000"))


class TestStockMovementModel(TestCase):
    """Model fields, indexes and check constraints."""

    def test_create_valid_movement(self):
        product = _product()
        movement = StockMovement.objects.create(
            product=product,
            movement_type=OPENING,
            quantity=Decimal("5.000"),
            unit_cost=Decimal("100.0000"),
            qty_after=Decimal("5.000"),
            avg_cost_after=Decimal("100.0000"),
            movement_date=TODAY,
        )
        self.assertIsNotNone(movement.id)
        self.assertEqual(movement.quantity, Decimal("5.000"))
        self.assertEqual(movement.unit_cost, Decimal("100.0000"))
        self.assertEqual(movement.qty_after, Decimal("5.000"))
        self.assertEqual(movement.avg_cost_after, Decimal("100.0000"))
        self.assertIsNotNone(movement.created_at)

    def _bulk_create_expect_integrity_error(self, movements):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.bulk_create(movements)

    def test_quantity_nonzero_constraint(self):
        product = _product()
        self._bulk_create_expect_integrity_error(
            [
                StockMovement(
                    product=product,
                    movement_type=SALE,
                    quantity=Decimal("0"),
                    qty_after=Decimal("0"),
                    movement_date=TODAY,
                ),
            ]
        )

    def test_sign_rule_inflow_positive(self):
        product = _product()
        for movement_type in (OPENING, PURCHASE, SALE_RETURN, ADJ_IN, CANCEL_REVERSAL):
            with self.subTest(movement_type=movement_type):
                self._bulk_create_expect_integrity_error(
                    [
                        StockMovement(
                            product=product,
                            movement_type=movement_type,
                            quantity=Decimal("-1"),
                            qty_after=Decimal("0"),
                            movement_date=TODAY,
                        ),
                    ]
                )

    def test_sign_rule_outflow_negative(self):
        product = _product()
        for movement_type in (SALE, PURCHASE_RETURN, ADJ_OUT):
            with self.subTest(movement_type=movement_type):
                self._bulk_create_expect_integrity_error(
                    [
                        StockMovement(
                            product=product,
                            movement_type=movement_type,
                            quantity=Decimal("1"),
                            qty_after=Decimal("0"),
                            movement_date=TODAY,
                        ),
                    ]
                )

    def test_unit_cost_must_be_null_or_non_negative(self):
        product = _product()
        self._bulk_create_expect_integrity_error(
            [
                StockMovement(
                    product=product,
                    movement_type=OPENING,
                    quantity=Decimal("1"),
                    unit_cost=Decimal("-1"),
                    qty_after=Decimal("1"),
                    movement_date=TODAY,
                ),
            ]
        )

    def test_avg_cost_after_must_be_null_or_non_negative(self):
        product = _product()
        self._bulk_create_expect_integrity_error(
            [
                StockMovement(
                    product=product,
                    movement_type=OPENING,
                    quantity=Decimal("1"),
                    unit_cost=Decimal("1"),
                    qty_after=Decimal("1"),
                    avg_cost_after=Decimal("-1"),
                    movement_date=TODAY,
                ),
            ]
        )

    def test_movement_type_must_be_allowed(self):
        product = _product()
        with self.assertRaises(IntegrityError):
            StockMovement.objects.bulk_create(
                [
                    StockMovement(
                        product=product,
                        movement_type="BOGUS",
                        quantity=Decimal("1"),
                        qty_after=Decimal("1"),
                        movement_date=TODAY,
                    ),
                ]
            )

    def test_boundary_values_accepted(self):
        product = _product()
        StockMovement.objects.bulk_create(
            [
                StockMovement(
                    product=product,
                    movement_type=OPENING,
                    quantity=Decimal("0.001"),
                    unit_cost=Decimal("0"),
                    qty_after=Decimal("0.001"),
                    avg_cost_after=Decimal("0"),
                    movement_date=TODAY,
                ),
                StockMovement(
                    product=product,
                    movement_type=SALE,
                    quantity=Decimal("-0.001"),
                    unit_cost=None,
                    qty_after=Decimal("0"),
                    avg_cost_after=None,
                    movement_date=TODAY,
                ),
            ]
        )
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_indexes_exist(self):
        index_fields = [tuple(idx.fields) for idx in StockMovement._meta.indexes]
        self.assertIn(("product", "movement_date"), index_fields)
        self.assertIn(("product", "id"), index_fields)
        self.assertIn(("reference_type", "reference_id"), index_fields)
        self.assertIn(("movement_date",), index_fields)


class TestStockMovementAppendOnly(TransactionTestCase):
    """Append-only enforcement in three layers."""

    def setUp(self):
        self.product = _product()
        self.movement = StockMovement.objects.create(
            product=self.product,
            movement_type=OPENING,
            quantity=Decimal("5"),
            unit_cost=Decimal("100"),
            qty_after=Decimal("5"),
            avg_cost_after=Decimal("100"),
            movement_date=TODAY,
        )

    def test_save_existing_row_raises(self):
        self.movement.quantity = Decimal("999")
        with self.assertRaises(ValidationError):
            self.movement.save()

    def test_delete_raises(self):
        with self.assertRaises(ValidationError):
            self.movement.delete()

    def test_queryset_update_blocked(self):
        with self.assertRaises(ValidationError):
            StockMovement.objects.filter(pk=self.movement.pk).update(quantity=Decimal("999"))

    def test_queryset_delete_blocked(self):
        with self.assertRaises(ValidationError):
            StockMovement.objects.filter(pk=self.movement.pk).delete()

    def test_queryset_bulk_update_blocked(self):
        entries = list(StockMovement.objects.all())
        entries[0].quantity = Decimal("999")
        with self.assertRaises(ValidationError):
            StockMovement.objects.bulk_update(entries, ["quantity"])

    def test_raw_sql_update_blocked_by_trigger(self):
        with self.assertRaises(Exception) as cm:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE stock_stockmovement SET quantity = 999 WHERE id = %s",
                        [self.movement.pk],
                    )
        self.assertIn("append-only", str(cm.exception).lower())

    def test_raw_sql_delete_blocked_by_trigger(self):
        with self.assertRaises(Exception) as cm:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM stock_stockmovement WHERE id = %s",
                        [self.movement.pk],
                    )
        self.assertIn("append-only", str(cm.exception).lower())

    def test_truncate_allowed_for_test_cleanup(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE stock_stockmovement RESTART IDENTITY CASCADE")
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_bulk_create_works(self):
        StockMovement.objects.bulk_create(
            [
                StockMovement(
                    product=self.product,
                    movement_type=OPENING,
                    quantity=Decimal("1"),
                    unit_cost=Decimal("10"),
                    qty_after=Decimal("1"),
                    avg_cost_after=Decimal("10"),
                    movement_date=TODAY,
                ),
                StockMovement(
                    product=self.product,
                    movement_type=OPENING,
                    quantity=Decimal("2"),
                    unit_cost=Decimal("20"),
                    qty_after=Decimal("2"),
                    avg_cost_after=Decimal("20"),
                    movement_date=TODAY,
                ),
            ]
        )
        self.assertEqual(StockMovement.objects.count(), 3)


class TestStockServiceValidation(TestCase):
    """Request validation."""

    def setUp(self):
        _settings(allow_negative_stock=False)
        self.product = _product(product_code="VAL-1")

    def test_quantity_must_be_decimal(self):
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(
                            self.product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100")
                        ),
                        _movement(
                            self.product.id, OPENING, 5, TODAY, unit_cost=Decimal("100")
                        ),  # int, not Decimal
                    ]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_quantity_must_be_greater_than_zero(self):
        for bad in (Decimal("0"), Decimal("-1")):
            with self.subTest(quantity=bad):
                with self.assertRaises(StockError) as cm:
                    with transaction.atomic():
                        StockService.apply_movements(
                            [
                                _movement(
                                    self.product.id, OPENING, bad, TODAY, unit_cost=Decimal("100")
                                )
                            ]
                        )
                self.assertEqual(cm.exception.code, VALIDATION_ERROR)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_quantity_must_have_at_most_three_decimals(self):
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(
                            self.product.id,
                            OPENING,
                            Decimal("5.0001"),
                            TODAY,
                            unit_cost=Decimal("100"),
                        ),
                    ]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_quantity_three_decimals_accepted(self):
        with transaction.atomic():
            StockService.apply_movements(
                [
                    _movement(
                        self.product.id, OPENING, Decimal("5.000"), TODAY, unit_cost=Decimal("100")
                    )
                ]
            )
        movement = StockMovement.objects.get()
        self.assertEqual(movement.quantity, Decimal("5.000"))

    def test_movement_date_must_be_a_date_not_datetime(self):
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(
                            self.product.id,
                            OPENING,
                            Decimal("5"),
                            datetime(2026, 11, 5, 10, 0),
                            unit_cost=Decimal("100"),
                        ),
                    ]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)

    def test_unknown_product_refused(self):
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [_movement(999999, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_untracked_product_refused(self):
        product = _product(product_code="VAL-2", track_stock=False)
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [_movement(product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))]
                )
        self.assertEqual(cm.exception.code, STOCK_NOT_TRACKED)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_inactive_product_allowed(self):
        product = _product(product_code="VAL-3", is_active=False)
        with transaction.atomic():
            movement = StockService.apply_movement(
                _movement(product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))
            )
        self.assertEqual(movement.qty_after, Decimal("5"))
        product.refresh_from_db()
        self.assertEqual(product.qty_on_hand, Decimal("5"))
        self.assertFalse(product.is_active)

    def test_fractional_quantity_refused_when_not_allowed(self):
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(
                            self.product.id,
                            OPENING,
                            Decimal("5.5"),
                            TODAY,
                            unit_cost=Decimal("100"),
                        )
                    ]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_fractional_quantity_accepted_when_allowed(self):
        product = _product(product_code="VAL-4", allow_fractional_qty=True)
        with transaction.atomic():
            movement = StockService.apply_movement(
                _movement(product.id, OPENING, Decimal("5.500"), TODAY, unit_cost=Decimal("100"))
            )
        self.assertEqual(movement.qty_after, Decimal("5.500"))

    def test_opening_requires_unit_cost(self):
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [_movement(self.product.id, OPENING, Decimal("5"), TODAY)]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)

    def test_opening_unit_cost_must_be_non_negative(self):
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(
                            self.product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("-1")
                        )
                    ]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)

    def test_opening_refused_when_product_already_has_stock(self):
        # simulates stock history; the stock engine writes this field in production
        Product.objects.filter(pk=self.product.pk).update(qty_on_hand=Decimal("3"))
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(
                            self.product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100")
                        )
                    ]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_opening_refused_when_product_already_has_movements(self):
        with transaction.atomic():
            StockService.apply_movements(
                [_movement(self.product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))]
            )
        # second opening on the same product
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(
                            self.product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100")
                        )
                    ]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_unit_cost_rejected_on_outflow(self):
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(
                            self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("100")
                        ),
                        _movement(
                            self.product.id, SALE, Decimal("3"), TODAY, unit_cost=Decimal("50")
                        ),
                    ]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_adj_out_requires_reason(self):
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(
                            self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("100")
                        ),
                        _movement(self.product.id, ADJ_OUT, Decimal("3"), TODAY, reason=""),
                    ]
                )
        self.assertEqual(cm.exception.code, VALIDATION_ERROR)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_adj_out_with_reason_ok(self):
        with transaction.atomic():
            StockService.apply_movements(
                [
                    _movement(
                        self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("100")
                    ),
                    _movement(self.product.id, ADJ_OUT, Decimal("3"), TODAY, reason="damage"),
                ]
            )
        self.assertEqual(StockMovement.objects.count(), 2)


class TestStockServiceEntryRequirement(TransactionTestCase):
    """apply_movements must be called inside transaction.atomic()."""

    def test_called_outside_transaction_raises_runtime_error_and_writes_nothing(self):
        from django.db import transaction as tx

        conn = tx.get_connection()
        self.assertFalse(conn.in_atomic_block)
        product = _product(product_code="RE-1")
        with self.assertRaises(RuntimeError) as cm:
            StockService.apply_movements(
                [_movement(product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))]
            )
        self.assertIn("transaction.atomic", str(cm.exception))
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(Product.objects.get(pk=product.id).qty_on_hand, Decimal("0"))


class TestStockServiceOpensAndSales(TestCase):
    """OPENING and SALE behaviour."""

    def setUp(self):
        _settings(allow_negative_stock=False)
        self.product = _product(product_code="OS-1")

    def test_opening_sets_quantity_and_average(self):
        with transaction.atomic():
            movement = StockService.apply_movement(
                _movement(
                    self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("350.1234")
                )
            )
        self.assertEqual(movement.quantity, Decimal("10.000"))
        self.assertEqual(movement.unit_cost, Decimal("350.1234"))
        self.assertEqual(movement.qty_after, Decimal("10.000"))
        self.assertEqual(movement.avg_cost_after, Decimal("350.1234"))
        self.assertEqual(movement.avg_before, None)
        self.product.refresh_from_db()
        self.assertEqual(self.product.qty_on_hand, Decimal("10.000"))
        self.assertEqual(self.product.avg_buying_price, Decimal("350.1234"))
        self.assertIsNone(self.product.last_buying_price)

    def test_opening_unit_cost_quantised_to_4_dp(self):
        with transaction.atomic():
            movement = StockService.apply_movement(
                _movement(
                    self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("100.00005")
                )
            )
        self.assertEqual(movement.unit_cost, Decimal("100.0001"))

    def test_sale_reduces_quantity_and_stores_cost_snapshot(self):
        with transaction.atomic():
            StockService.apply_movement(
                _movement(
                    self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("350.0000")
                )
            )
            movement = StockService.apply_movement(
                _movement(self.product.id, SALE, Decimal("4"), TODAY)
            )
        self.assertEqual(movement.quantity, Decimal("-4.000"))
        self.assertEqual(movement.unit_cost, Decimal("350.0000"))  # cost snapshot = average before
        self.assertEqual(movement.avg_cost_after, Decimal("350.0000"))
        self.assertEqual(movement.avg_before, Decimal("350.0000"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.qty_on_hand, Decimal("6.000"))
        self.assertEqual(self.product.avg_buying_price, Decimal("350.0000"))

    def test_sale_when_never_costed_keeps_nulls(self):
        _settings(allow_negative_stock=True)
        with transaction.atomic():
            movement = StockService.apply_movement(
                _movement(self.product.id, SALE, Decimal("1"), TODAY)
            )
        self.assertIsNone(movement.unit_cost)
        self.assertIsNone(movement.avg_cost_after)
        self.assertIsNone(movement.avg_before)
        self.product.refresh_from_db()
        self.assertEqual(self.product.qty_on_hand, Decimal("-1.000"))

    def test_sell_exactly_remaining_quantity_succeeds(self):
        with transaction.atomic():
            StockService.apply_movement(
                _movement(self.product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))
            )
            movement = StockService.apply_movement(
                _movement(self.product.id, SALE, Decimal("5"), TODAY)
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.qty_on_hand, Decimal("0"))
        self.assertEqual(movement.qty_after, Decimal("0"))

    def test_negative_stock_blocked_with_insufficient_stock(self):
        with transaction.atomic():
            StockService.apply_movement(
                _movement(self.product.id, OPENING, Decimal("3"), TODAY, unit_cost=Decimal("100"))
            )
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movement(_movement(self.product.id, SALE, Decimal("5"), TODAY))
        self.assertEqual(cm.exception.code, INSUFFICIENT_STOCK)
        message = cm.exception.message
        self.assertIn(self.product.product_code, message)
        self.assertIn("3", message)  # available
        self.assertIn("5", message)  # requested
        self.product.refresh_from_db()
        self.assertEqual(self.product.qty_on_hand, Decimal("3"))
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_negative_stock_allowed_when_setting_on(self):
        _settings(allow_negative_stock=True)
        with transaction.atomic():
            movement = StockService.apply_movement(
                _movement(self.product.id, SALE, Decimal("5"), TODAY)
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.qty_on_hand, Decimal("-5.000"))
        self.assertEqual(movement.qty_after, Decimal("-5.000"))
        self.assertIsNone(movement.avg_cost_after)

    def test_avg_never_changes_on_outflow(self):
        with transaction.atomic():
            StockService.apply_movement(
                _movement(
                    self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("100.5555")
                )
            )
            StockService.apply_movement(_movement(self.product.id, SALE, Decimal("3"), TODAY))
            StockService.apply_movement(
                _movement(self.product.id, ADJ_OUT, Decimal("2"), TODAY, reason="loss")
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.qty_on_hand, Decimal("5.000"))
        self.assertEqual(self.product.avg_buying_price, Decimal("100.5555"))
        last = StockMovement.objects.last()
        self.assertEqual(last.avg_cost_after, Decimal("100.5555"))


class TestStockServiceBatch(TestCase):
    """Batch behaviour: atomicity, ordering, locking visibility."""

    def setUp(self):
        _settings(allow_negative_stock=False)
        self.product = _product(product_code="BT-1")

    def test_requests_for_same_product_see_each_other(self):
        with transaction.atomic():
            StockService.apply_movement(
                _movement(self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("100"))
            )
        with self.assertRaises(StockError) as cm:
            with transaction.atomic():
                StockService.apply_movements(
                    [
                        _movement(self.product.id, SALE, Decimal("6"), TODAY),
                        _movement(
                            self.product.id, SALE, Decimal("5"), TODAY
                        ),  # only 4 left after the first
                    ]
                )
        self.assertEqual(cm.exception.code, INSUFFICIENT_STOCK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.qty_on_hand, Decimal("10"))  # whole batch rolled back
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_batch_all_or_nothing_when_later_request_fails(self):
        with transaction.atomic():
            StockService.apply_movement(
                _movement(self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("100"))
            )
        try:
            with transaction.atomic():  # outer transaction keeps being used
                StockService.apply_movements(
                    [
                        _movement(self.product.id, SALE, Decimal("2"), TODAY),
                        _movement(self.product.id, SALE, Decimal("9"), TODAY),  # fails
                    ]
                )
        except StockError:
            pass
        # outer transaction still usable
        with transaction.atomic():
            StockService.apply_movement(_movement(self.product.id, SALE, Decimal("1"), TODAY))
        self.product.refresh_from_db()
        self.assertEqual(
            self.product.qty_on_hand, Decimal("9")
        )  # 10 - 1, nothing from failed batch
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_movements_returned_in_request_order(self):
        with transaction.atomic():
            StockService.apply_movement(
                _movement(self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("100"))
            )
            movements = StockService.apply_movements(
                [
                    _movement(self.product.id, SALE, Decimal("2"), TODAY),
                    _movement(self.product.id, ADJ_OUT, Decimal("1"), TODAY, reason="r"),
                ]
            )
        self.assertEqual(len(movements), 2)
        self.assertEqual(movements[0].quantity, Decimal("-2.000"))
        self.assertEqual(movements[1].quantity, Decimal("-1.000"))
        self.assertEqual(movements[0].avg_before, Decimal("100.0000"))
        self.assertEqual(movements[1].avg_before, Decimal("100.0000"))

    def test_product_row_matches_last_movement(self):
        with transaction.atomic():
            StockService.apply_movement(
                _movement(
                    self.product.id, OPENING, Decimal("10"), TODAY, unit_cost=Decimal("100.5555")
                )
            )
            m1 = StockService.apply_movement(_movement(self.product.id, SALE, Decimal("3"), TODAY))
        product = Product.objects.get(pk=self.product.id)
        self.assertEqual(product.qty_on_hand, m1.qty_after)
        self.assertEqual(product.avg_buying_price, m1.avg_cost_after)

    def test_updated_at_changes_and_other_columns_untouched(self):
        self.product.selling_price = Decimal("450")
        self.product.save()
        before = Product.objects.get(pk=self.product.id).updated_at
        with transaction.atomic():
            StockService.apply_movement(
                _movement(self.product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))
            )
        product = Product.objects.get(pk=self.product.id)
        self.assertNotEqual(product.updated_at, before)
        self.assertEqual(product.selling_price, Decimal("450"))
        self.assertEqual(product.last_buying_price, None)


class TestStockServiceDeadlockSafe(TransactionTestCase):
    """Fixed lock order must not deadlock, even with reversed request order."""

    def setUp(self):
        _settings(allow_negative_stock=False)
        self.product_a = _product(product_code="DL-A")
        self.product_b = _product(product_code="DL-B")
        with transaction.atomic():
            StockService.apply_movement(
                _movement(
                    self.product_a.id, OPENING, Decimal("100000"), TODAY, unit_cost=Decimal("100")
                )
            )
            StockService.apply_movement(
                _movement(
                    self.product_b.id, OPENING, Decimal("100000"), TODAY, unit_cost=Decimal("100")
                )
            )

    def _worker(self, first_id, second_id, errors, results):
        try:
            connection.close_if_unusable_or_obsolete()
            for _ in range(20):
                with transaction.atomic():
                    movements = StockService.apply_movements(
                        [
                            _movement(first_id, SALE, Decimal("1"), TODAY),
                            _movement(second_id, SALE, Decimal("1"), TODAY),
                        ]
                    )
                    results.append(len(movements))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    def test_reverse_lock_order_does_not_deadlock(self):
        errors = []
        results_a = []
        results_b = []
        t1 = Thread(
            target=self._worker, args=(self.product_a.id, self.product_b.id, errors, results_a)
        )
        t2 = Thread(
            target=self._worker, args=(self.product_b.id, self.product_a.id, errors, results_b)
        )
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(results_a), 20)
        self.assertEqual(len(results_b), 20)
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.qty_on_hand, Decimal("99960"))
        self.assertEqual(self.product_b.qty_on_hand, Decimal("99960"))
        self.assertEqual(StockMovement.objects.count(), 82)


class TestHasStockHistoryWithMovement(TestCase):
    """has_stock_history must see StockMovement rows."""

    def test_true_when_movement_exists_even_with_zero_quantity_and_null_average(self):
        _settings(allow_negative_stock=True)
        product = _product(product_code="HS-1")
        self.assertFalse(has_stock_history(product))
        with transaction.atomic():
            StockService.apply_movement(_movement(product.id, SALE, Decimal("1"), TODAY))
        product.refresh_from_db()
        self.assertEqual(product.qty_on_hand, Decimal("-1.000"))
        self.assertIsNone(product.avg_buying_price)
        self.assertTrue(has_stock_history(product))

    def test_true_after_opening_and_sale_to_zero(self):
        product = _product(product_code="HS-2")
        with transaction.atomic():
            StockService.apply_movement(
                _movement(product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))
            )
            StockService.apply_movement(_movement(product.id, SALE, Decimal("5"), TODAY))
        product.refresh_from_db()
        self.assertEqual(product.qty_on_hand, Decimal("0"))
        self.assertEqual(product.avg_buying_price, Decimal("100.0000"))
        self.assertTrue(has_stock_history(product))

    def test_pack_change_refused_through_api_after_movement(self):
        _settings(allow_negative_stock=True)
        product = _product(product_code="HS-3")
        with transaction.atomic():
            StockService.apply_movement(_movement(product.id, SALE, Decimal("1"), TODAY))
        client = APIClient()
        user = User.objects.create_user(username="owner", password="SecurePass123!")
        client.force_authenticate(user)
        url = f"/api/v1/products/{product.id}/"
        response = client.patch(url, {"pack_size": "10"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        data = response.json()
        self.assertEqual(data["code"], PACK_CHANGE_NOT_ALLOWED)
        self.assertIn("pack_size", data["fields"])


class TestLostUpdateProtection(TestCase):
    """A stale Product copy must not overwrite stock fields written by StockService."""

    def setUp(self):
        _settings()
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.factory = APIRequestFactory()

    def _request(self):
        request = self.factory.post("/api/v1/products/x/")
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        return request

    def test_service_update_with_explicit_update_fields_keeps_stock_quantity(self):
        product = _product(product_code="LU-1")
        with transaction.atomic():
            StockService.apply_movement(
                _movement(product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))
            )
        product.refresh_from_db()
        self.assertEqual(product.qty_on_hand, Decimal("5"))

        # Stale in-memory copy carries an outdated qty_on_hand; only the name
        # is updated through the service, so the quantity must survive.
        stale = Product.objects.get(pk=product.id)
        stale.qty_on_hand = Decimal("0")
        serializer = ProductSerializer(
            instance=stale, data={"product_code": "LU-1-RENAMED"}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        ProductService.update_product_with_audit(stale, serializer, self._request())

        product.refresh_from_db()
        self.assertEqual(product.qty_on_hand, Decimal("5"))  # unchanged by the name update
        self.assertEqual(product.product_code, "LU-1-RENAMED")
        self.assertEqual(product.avg_buying_price, Decimal("100.0000"))


class TestNoAuditEntriesByStockService(TestCase):
    """StockService writes no audit entries per movement."""

    def test_no_audit_entry_per_movement(self):
        before = AuditLog.objects.count()
        product = _product(product_code="NA-1")
        with transaction.atomic():
            StockService.apply_movement(
                _movement(product.id, OPENING, Decimal("5"), TODAY, unit_cost=Decimal("100"))
            )
            StockService.apply_movement(_movement(product.id, SALE, Decimal("2"), TODAY))
        self.assertEqual(AuditLog.objects.count(), before)


class TestStockFieldWriteScan(TestCase):
    """AST-based scan: stock fields are written ONLY by StockService.

    Parses every .py file under apps/ with the ast module (excluding tests,
    test files, migrations and apps/stock/services.py) and flags any of
    qty_on_hand, avg_buying_price, last_buying_price involved in:
      (a) assignment / augmented assignment / annotated assignment to an
          attribute with that name
      (b) keyword argument with that name in any call
      (c) setattr/getattr with a string constant of that name as an argument
      (d) string constants containing the name inside a list or tuple passed
          as update_fields or fields (bulk_update, save(update_fields=...))
      (e) string constant containing SQL UPDATE + product table + the name
      (f) F() / Value() expressions referencing a stock field inside an update

    Allowlist is keyed by (file, line text) with a reason, so a new write in
    an allowlisted file is still caught. Each allowlisted hit is printed.
    """

    STOCK_FIELDS = frozenset({"qty_on_hand", "avg_buying_price", "last_buying_price"})
    WRITE_KWARGS = frozenset({"update_fields", "fields"})

    # (file_path, stripped_line_text) -> reason
    ALLOWLIST = {
        (
            "apps/catalog/models.py",
            "qty_on_hand = models.DecimalField(max_digits=10, decimal_places=3, default=0, editable=False)",
        ): "stock field model definition (editable=False; stock engine only)",
        (
            "apps/catalog/models.py",
            "avg_buying_price = models.DecimalField(",
        ): "stock field model definition (editable=False; stock engine only)",
        (
            "apps/catalog/models.py",
            "last_buying_price = models.DecimalField(",
        ): "stock field model definition (editable=False; stock engine only)",
        (
            "apps/catalog/serializers.py",
            'STOCK_READ_ONLY_FIELDS = ("qty_on_hand", "avg_buying_price", "last_buying_price")',
        ): "read-only serializer declaration (STOCK_READ_ONLY_FIELDS tuple)",
        (
            "apps/catalog/serializers.py",
            '"qty_on_hand",',
        ): "read-only serializer declaration (fields / read_only_fields list)",
        (
            "apps/catalog/serializers.py",
            '"avg_buying_price",',
        ): "read-only serializer declaration (fields / read_only_fields list)",
        (
            "apps/catalog/serializers.py",
            '"last_buying_price",',
        ): "read-only serializer declaration (fields / read_only_fields list)",
        (
            "apps/catalog/services.py",
            "product.qty_on_hand != 0",
        ): "read-only read of stock field in has_stock_history()",
        (
            "apps/catalog/services.py",
            "product.avg_buying_price is not None",
        ): "read-only read of stock field in has_stock_history()",
        (
            "apps/catalog/services.py",
            "product.last_buying_price is not None",
        ): "read-only read of stock field in has_stock_history()",
        (
            "apps/catalog/views.py",
            '"qty_on_hand",',
        ): "read-only reference in PRODUCT_ORDERING_FIELDS list",
        (
            "apps/catalog/views.py",
            "qty_on_hand__gt=0",
        ): "read-only filter in stock_status queryset (not a write)",
        (
            "apps/catalog/views.py",
            "qty_on_hand__lte=0",
        ): "read-only filter in stock_status queryset (not a write)",
        (
            "apps/catalog/views.py",
            'qty_on_hand__lte=F("min_stock")',
        ): "read-only filter in stock_status queryset (not a write)",
    }

    @classmethod
    def _scan_source(cls, source: str, filename: str) -> list[tuple[int, str]]:
        """Return [(line_no, description)] of stock-field write violations in source."""
        stock_fields = cls.STOCK_FIELDS
        write_kwargs = cls.WRITE_KWARGS
        violations: list[tuple[int, str]] = []

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.violations = violations

            def _add(self, node: ast.AST, desc: str) -> None:
                self.violations.append((node.lineno, desc))

            def _call_name(self, node: ast.AST) -> str:
                if isinstance(node, ast.Attribute):
                    return self._call_name(node.value) + "." + node.attr
                if isinstance(node, ast.Name):
                    return node.id
                return "?"

            def visit_Assign(self, node: ast.Assign) -> None:
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in stock_fields:
                        self._add(node, f"assignment to attribute {target.attr!r}")
                self.generic_visit(node)

            def visit_AugAssign(self, node: ast.AugAssign) -> None:
                if isinstance(node.target, ast.Attribute) and node.target.attr in stock_fields:
                    self._add(node, f"augmented assignment to attribute {node.target.attr!r}")
                self.generic_visit(node)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                if (
                    node.target is not None
                    and isinstance(node.target, ast.Attribute)
                    and node.target.attr in stock_fields
                ):
                    self._add(node, f"annotated assignment to attribute {node.target.attr!r}")
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                call_name = self._call_name(node.func)

                for kw in node.keywords:
                    if kw.arg in stock_fields:
                        self._add(node, f"keyword argument {kw.arg!r} in call to {call_name}")

                # setattr/getattr as built-in Name or as attribute
                is_setattr_getattr = False
                if isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "setattr",
                    "getattr",
                ):
                    is_setattr_getattr = True
                    func_attr = node.func.attr
                elif isinstance(node.func, ast.Name) and node.func.id in ("setattr", "getattr"):
                    is_setattr_getattr = True
                    func_attr = node.func.id
                if is_setattr_getattr:
                    for arg in node.args:
                        if (
                            isinstance(arg, ast.Constant)
                            and isinstance(arg.value, str)
                            and arg.value in stock_fields
                        ):
                            self._add(
                                node,
                                f"{func_attr}() with string constant {arg.value!r}",
                            )

                for kw in node.keywords:
                    if kw.arg in write_kwargs and isinstance(kw.value, ast.List | ast.Tuple):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                for sf in stock_fields:
                                    if sf in elt.value:
                                        self._add(
                                            node,
                                            f"string constant {elt.value!r} containing stock field in {kw.arg}={call_name}",
                                        )

                if isinstance(node.func, ast.Attribute) and node.func.attr == "bulk_update":
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.List | ast.Tuple):
                        for elt in node.args[1].elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                for sf in stock_fields:
                                    if sf in elt.value:
                                        self._add(
                                            node,
                                            f"string constant {elt.value!r} containing stock field in bulk_update fields",
                                        )

                if isinstance(node.func, ast.Attribute) and node.func.attr == "update":
                    for arg in list(node.args) + [kw.value for kw in node.keywords]:
                        self._check_f_value_refs(arg)

                self.generic_visit(node)

            def _check_f_value_refs(self, node: ast.AST) -> None:
                if isinstance(node, ast.Call):
                    func_name = self._call_name(node.func)
                    if func_name in ("F", "Value"):
                        for arg in node.args:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                for sf in stock_fields:
                                    if sf == arg.value:
                                        self._add(
                                            node,
                                            f"{func_name}({arg.value!r}) references stock field inside update",
                                        )
                    for child in ast.iter_child_nodes(node):
                        self._check_f_value_refs(child)
                elif isinstance(node, ast.List | ast.Tuple | ast.Set | ast.Dict):
                    for child in ast.iter_child_nodes(node):
                        self._check_f_value_refs(child)
                elif isinstance(node, ast.BinOp):
                    self._check_f_value_refs(node.left)
                    self._check_f_value_refs(node.right)
                elif isinstance(node, ast.UnaryOp):
                    self._check_f_value_refs(node.operand)

        tree = ast.parse(source, filename=filename)
        Visitor().visit(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
                # Rule (e): only flag string constants that look like real SQL
                # UPDATE statements (not docstrings or comments mentioning update).
                if re_compile(r"\bUPDATE\s+\w+\s+SET\b").search(text) and "product" in text.lower():
                    for sf in stock_fields:
                        if sf in text:
                            violations.append(
                                (
                                    node.lineno,
                                    f"SQL UPDATE string with product table and stock field {sf!r}",
                                )
                            )

        return violations

    @classmethod
    def _iter_app_files(cls, backend_dir: Path):
        for path in sorted(backend_dir.rglob("apps/**/*.py")):
            rel = path.relative_to(backend_dir)
            parts = rel.parts
            if parts[0] != "apps":
                continue
            if "tests" in parts:
                continue
            name = parts[-1]
            if name == "tests.py" or name.startswith("test_") or name.endswith("_tests.py"):
                continue
            if "migrations" in parts:
                continue
            key = rel.as_posix()
            if key == "apps/stock/services.py":
                continue
            yield path, key

    def test_no_stock_field_assignments_outside_stock_service(self):
        backend_dir = Path(__file__).resolve().parent.parent.parent  # backend/
        violations = []
        allowlisted_hits = []
        for path, key in self._iter_app_files(backend_dir):
            text = path.read_text(encoding="utf-8")
            file_violations = self._scan_source(text, key)
            for line_no, desc in file_violations:
                line_text = text.splitlines()[line_no - 1].strip()
                hit = f"{key}:{line_no}: {line_text!r} ({desc})"
                allow_key = (key, line_text)
                if allow_key in self.ALLOWLIST:
                    allowlisted_hits.append((hit, self.ALLOWLIST[allow_key]))
                else:
                    violations.append(hit)
        print("\nAllowlisted stock-field hits:")  # noqa: T201 - required by task: report allowlisted hits
        for hit, reason in sorted(allowlisted_hits):
            print(f"  {hit}  # {reason}")  # noqa: T201 - required by task: report allowlisted hits
        self.assertFalse(
            violations,
            "Stock fields written outside StockService (only apps/stock/services.py may write them):\n"
            + "\n".join(sorted(violations)),
        )

    def test_scan_flags_attribute_assignment(self):
        source = "product.qty_on_hand = Decimal('5')\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("assignment to attribute", violations[0][1])

    def test_scan_flags_augmented_assignment(self):
        source = "product.qty_on_hand += Decimal('1')\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("augmented assignment", violations[0][1])

    def test_scan_flags_annotated_assignment(self):
        source = "product.qty_on_hand: Decimal = Decimal('5')\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("annotated assignment", violations[0][1])

    def test_scan_flags_keyword_arg_in_update(self):
        source = "Product.objects.update(qty_on_hand=Decimal('5'))\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("keyword argument", violations[0][1])

    def test_scan_flags_keyword_arg_in_create(self):
        source = "Product.objects.create(qty_on_hand=Decimal('5'))\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("keyword argument", violations[0][1])

    def test_scan_flags_keyword_arg_in_product_constructor(self):
        source = "Product(qty_on_hand=Decimal('5'))\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("keyword argument", violations[0][1])

    def test_scan_flags_setattr_string_constant(self):
        source = "setattr(product, 'qty_on_hand', Decimal('5'))\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("setattr()", violations[0][1])

    def test_scan_flags_getattr_string_constant(self):
        source = "getattr(product, 'avg_buying_price')\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("getattr()", violations[0][1])

    def test_scan_flags_update_fields_string(self):
        source = "product.save(update_fields=['qty_on_hand'])\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("update_fields", violations[0][1])

    def test_scan_flags_bulk_update_fields_string(self):
        source = "Product.objects.bulk_update(objs, ['last_buying_price'])\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("bulk_update", violations[0][1])

    def test_scan_flags_sql_update_string(self):
        source = 'sql = "UPDATE catalog_product SET qty_on_hand = 5"\n'
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(len(violations), 1)
        self.assertIn("SQL UPDATE", violations[0][1])

    def test_scan_flags_f_expression_in_update(self):
        source = 'Product.objects.filter(pk=1).update(qty_on_hand=F("qty_on_hand") + 1)\n'
        violations = self._scan_source(source, "<snippet>")
        self.assertGreaterEqual(len(violations), 1)
        descs = " | ".join(d for _, d in violations)
        self.assertIn("stock field", descs)

    def test_scan_flags_value_expression_in_update(self):
        source = 'Product.objects.filter(pk=1).update(quantity=Value("qty_on_hand"))\n'
        violations = self._scan_source(source, "<snippet>")
        self.assertGreaterEqual(len(violations), 1)
        descs = " | ".join(d for _, d in violations)
        self.assertIn("stock field", descs)

    def test_scan_does_not_flag_plain_read(self):
        source = "print(product.qty_on_hand)\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(violations, [])

    def test_scan_does_not_flag_comment(self):
        source = "# product.qty_on_hand = 5  # not a real write\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(violations, [])

    def test_scan_does_not_flag_docstring(self):
        source = '"""This sets product.qty_on_hand = 5 but is just a docstring."""\n'
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(violations, [])

    def test_scan_does_not_flag_filter_lookup(self):
        source = "Product.objects.filter(qty_on_hand__gt=0)\n"
        violations = self._scan_source(source, "<snippet>")
        self.assertEqual(violations, [])


class TestNoNowInStockApp(TestCase):
    """Stock app modules must never default movement_date to now/today."""

    def test_movement_request_has_no_default_for_movement_date(self):
        # movement_date is a required dataclass field with no default
        from apps.stock.services import MovementRequest

        f = MovementRequest.__dataclass_fields__["movement_date"]
        self.assertIs(f.default, MISSING)
        self.assertIs(f.default_factory, MISSING)

    def test_service_uses_requested_movement_date_not_now_or_today(self):
        """StockService must use movement_date from the request, never now/today."""
        from datetime import date
        from decimal import Decimal

        from django.db import transaction

        from apps.stock.services import MovementRequest, StockService

        product = _product(product_code="NN-1")
        with transaction.atomic():
            StockService.apply_movement(
                MovementRequest(
                    product_id=product.id,
                    movement_type=OPENING,
                    quantity=Decimal("10"),
                    movement_date=date(2026, 1, 1),
                    unit_cost=Decimal("100"),
                )
            )
        movement = StockMovement.objects.get()
        self.assertEqual(movement.movement_date, date(2026, 1, 1))

    def test_no_timezone_now_date_today_datetime_now_alias_in_stock_services(self):
        """AST scan: apps/stock/services.py must not use timezone.now, date.today
        or datetime.now anywhere except the single updated_at line (allowlisted
        by text). Also flags aliases (import alias or assignment of these names)."""
        backend_dir = Path(__file__).resolve().parent.parent.parent
        services_path = backend_dir / "apps" / "stock" / "services.py"
        text = services_path.read_text(encoding="utf-8")

        # Flag any import alias or assignment of timezone.now / date.today / datetime.now
        tree = ast.parse(text, filename="apps/stock/services.py")

        class AliasVisitor(ast.NodeVisitor):
            def __init__(self):
                self.violations = []

            def visit_ImportFrom(self, node):
                for alias in node.names:
                    if node.module == "django.utils" and alias.name == "timezone" and alias.asname:
                        self.violations.append(
                            (node.lineno, f"import alias timezone as {alias.asname!r}")
                        )
                    if (
                        node.module == "datetime"
                        and alias.name in ("date", "datetime")
                        and alias.asname
                    ):
                        self.violations.append(
                            (node.lineno, f"import alias {alias.name} as {alias.asname!r}")
                        )
                self.generic_visit(node)

            def visit_Assign(self, node):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if isinstance(node.value, ast.Attribute):
                            attr_chain = ""
                            cur = node.value
                            while isinstance(cur, ast.Attribute):
                                attr_chain = cur.attr + ("." + attr_chain if attr_chain else "")
                                cur = cur.value
                            if isinstance(cur, ast.Name):
                                full = cur.id + ("." + attr_chain if attr_chain else "")
                                if full in ("timezone.now", "date.today", "datetime.now"):
                                    self.violations.append(
                                        (node.lineno, f"assignment {target.id} = {full}")
                                    )
                self.generic_visit(node)

        visitor = AliasVisitor()
        visitor.visit(tree)
        self.assertEqual(
            visitor.violations,
            [],
            "Found banned name aliases in apps/stock/services.py:\n"
            + "\n".join(f"{ln}: {d}" for ln, d in visitor.violations),
        )

        # Flag any use of timezone.now, date.today, datetime.now except the
        # single updated_at line, which is allowlisted by text.
        now_re = re_compile(r"\b(timezone\.now|date\.today|datetime\.now)\s*\(")
        violations = []
        allowlisted_line = "updated_at=timezone.now(),"
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped == allowlisted_line:
                continue  # allowlisted by text: the single updated_at assignment
            for match in now_re.finditer(line):
                violations.append(f"{line_no}: {match.group(0)!r}")
        self.assertFalse(
            violations,
            "banned now/today calls in apps/stock/services.py outside the updated_at line:\n"
            + "\n".join(sorted(violations)),
        )


class TestNoGstOrHsnInStockApp(TestCase):
    """No tax-rule values hard-coded in the stock app."""

    def test_no_gst_rate_or_hsn_values(self):
        backend_dir = Path(__file__).resolve().parent.parent.parent
        bad_re = re_compile(r"gst_rate|hsn_code|IGST|CGST|SGST")
        violations = []
        for path in sorted((backend_dir / "apps" / "stock").glob("*.py")):
            if path.name == "test_stock_service.py":
                continue
            text = path.read_text(encoding="utf-8")
            for match in bad_re.finditer(text):
                line_no = text[: match.start()].count("\n") + 1
                violations.append(f"{path.name}:{line_no}: {match.group(0)!r}")
        self.assertFalse(
            violations,
            "tax-rule values must not appear in apps/stock:\n" + "\n".join(sorted(violations)),
        )
