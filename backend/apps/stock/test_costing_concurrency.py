"""Concurrency tests for T-302 weighted-average costing.

Real threads buying/selling on the same product to prove fixed lock order is
deadlock-safe and never oversells. Uses TransactionTestCase so data committed
by the main thread is visible to worker threads on separate connections.
"""

from datetime import date
from decimal import Decimal
from threading import Thread

import pytest
from common.errors import INSUFFICIENT_STOCK
from django.db import connection, transaction
from django.test import TransactionTestCase
from testsupport.factories import give_opening_stock, make_product

from apps.stock.exceptions import StockError
from apps.stock.models import MovementType, StockMovement
from apps.stock.selectors import recompute_from_ledger, verify_product_ledger
from apps.stock.services import MovementRequest, StockService

pytestmark = pytest.mark.concurrency

TODAY = date(2026, 11, 5)


def _movement(
    product_id, movement_type, quantity=Decimal("1"), movement_date=TODAY, unit_cost=None
):
    return MovementRequest(
        product_id=product_id,
        movement_type=movement_type,
        quantity=quantity,
        movement_date=movement_date,
        unit_cost=unit_cost,
    )


class TestConcurrentPurchases(TransactionTestCase):
    """10 purchase threads on one product: final quantity exact, average near the weighted mean."""

    def test_ten_purchase_threads_same_product(self):
        product = make_product(product_code="CC-1")
        give_opening_stock(product, Decimal("100"), Decimal("100"), TODAY)
        costs = [Decimal(str(100 + i * 10)) for i in range(10)]
        exact_mean = (Decimal("100") * Decimal("100") + sum(costs)) / Decimal("110")
        errors = []
        results = []

        def worker(cost):
            try:
                connection.close_if_unusable_or_obsolete()
                with transaction.atomic():
                    movements = StockService.apply_movements(
                        [_movement(product.id, MovementType.PURCHASE, Decimal("1"), TODAY, cost)]
                    )
                    results.append(len(movements))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connection.close()

        threads = [Thread(target=worker, args=(cost,)) for cost in costs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [], f"Errors occurred: {errors}")
        self.assertEqual(len(results), 10)
        product.refresh_from_db()
        self.assertEqual(product.qty_on_hand, Decimal("110.000"))
        self.assertLess(
            abs(product.avg_buying_price - exact_mean),
            Decimal("0.001"),
            f"avg {product.avg_buying_price} not within 0.001 of {exact_mean}",
        )
        last = StockMovement.objects.order_by("-id").first()
        self.assertEqual(product.qty_on_hand, last.qty_after)
        self.assertEqual(product.avg_buying_price, last.avg_cost_after)
        self.assertTrue(verify_product_ledger(product.id).ok)
        qty, avg, _lbp = recompute_from_ledger(product.id)
        self.assertEqual(qty, product.qty_on_hand)
        self.assertEqual(avg, product.avg_buying_price)


class TestMixedPurchaseSaleThreads(TransactionTestCase):
    """5 purchase and 5 sale threads on one product: never oversell."""

    def test_five_purchase_and_five_sale_threads_never_oversell(self):
        product = make_product(product_code="CC-2")
        give_opening_stock(product, Decimal("5"), Decimal("100"), TODAY)
        errors = []
        results = []

        def worker(kind):
            try:
                connection.close_if_unusable_or_obsolete()
                with transaction.atomic():
                    if kind == "purchase":
                        request = _movement(
                            product.id, MovementType.PURCHASE, Decimal("1"), TODAY, Decimal("100")
                        )
                    else:
                        request = _movement(product.id, MovementType.SALE, Decimal("1"), TODAY)
                    movements = StockService.apply_movements([request])
                    results.append((kind, len(movements)))
            except StockError as exc:
                if exc.code == INSUFFICIENT_STOCK:
                    results.append((kind, "oversold"))
                else:
                    errors.append(exc)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connection.close()

        kinds = ["purchase"] * 5 + ["sale"] * 5
        threads = [Thread(target=worker, args=(kind,)) for kind in kinds]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [], f"Errors occurred: {errors}")
        self.assertEqual(len(results), 10)
        self.assertTrue(all(result[1] != "oversold" for result in results), f"Oversold: {results}")
        product.refresh_from_db()
        self.assertEqual(product.qty_on_hand, Decimal("5.000"))
        self.assertEqual(StockMovement.objects.count(), 11)
