"""Read-only ledger selectors for the stock app.

Replays the append-only ``StockMovement`` ledger to recompute a product's
stock position. Never writes; a product whose replay does not match its row is
reported, not fixed.
"""

from dataclasses import dataclass
from decimal import Decimal

from common.money import q3, q4

from apps.catalog.models import Product
from apps.stock.costing import after_purchase, after_purchase_return, opening_average
from apps.stock.models import MovementType, StockMovement


@dataclass
class LedgerVerificationResult:
    """Result of comparing the ledger replay against the product row."""

    ok: bool
    expected_qty: Decimal | None
    expected_avg: Decimal | None
    expected_last_buying_price: Decimal | None
    actual_qty: Decimal | None
    actual_avg: Decimal | None
    actual_last_buying_price: Decimal | None


def recompute_from_ledger(product_id: int) -> tuple[Decimal, Decimal | None, Decimal | None]:
    """Replay all movements of a product in id order.

    Returns ``(qty, avg, last_buying_price)``. Mirrors :class:`StockService`
    exactly so a consistent ledger always reproduces the product row.
    """
    Product.objects.get(pk=product_id)
    movements = StockMovement.objects.filter(product_id=product_id).order_by("id")

    qty = Decimal("0")
    avg: Decimal | None = None
    last_buying_price: Decimal | None = None

    for movement in movements:
        old_qty = qty
        old_avg = avg
        movement_type = movement.movement_type
        quantity = movement.quantity  # signed: positive inflow, negative outflow

        if movement_type == MovementType.OPENING:
            qty = quantity  # absolute; the product had no stock before
            avg = opening_average(movement.unit_cost) if movement.unit_cost is not None else None
        elif movement_type == MovementType.PURCHASE_RETURN:
            out_qty = -quantity
            if old_avg is None and movement.unit_cost is None:
                avg = None
            else:
                return_cost = movement.unit_cost if movement.unit_cost is not None else old_avg
                avg = after_purchase_return(old_qty, old_avg, out_qty, return_cost)
            qty = q3(old_qty + quantity)
        elif movement_type in (
            MovementType.PURCHASE,
            MovementType.SALE_RETURN,
            MovementType.CANCEL_REVERSAL,
        ):
            qty = q3(old_qty + quantity)
            avg = after_purchase(old_qty, old_avg, quantity, movement.unit_cost)
            if movement_type == MovementType.PURCHASE:
                last_buying_price = movement.unit_cost
        elif movement_type == MovementType.ADJ_IN:
            qty = q3(old_qty + quantity)
            if avg is None and movement.unit_cost is not None:
                avg = q4(movement.unit_cost)
            # otherwise the average is unchanged
        else:
            # SALE and ADJ_OUT: outflow, the average never changes
            qty = q3(old_qty + quantity)

    return qty, avg, last_buying_price


def verify_product_ledger(product_id: int) -> LedgerVerificationResult:
    """Replay the ledger and compare it against the product row. Never writes."""
    product = Product.objects.get(pk=product_id)
    qty, avg, last_buying_price = recompute_from_ledger(product_id)
    ok = (
        qty == product.qty_on_hand
        and avg == product.avg_buying_price
        and last_buying_price == product.last_buying_price
    )
    return LedgerVerificationResult(
        ok=ok,
        expected_qty=qty,
        expected_avg=avg,
        expected_last_buying_price=last_buying_price,
        actual_qty=product.qty_on_hand,
        actual_avg=product.avg_buying_price,
        actual_last_buying_price=product.last_buying_price,
    )
