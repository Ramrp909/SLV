"""Pure costing helpers for stock movements (T-301 + T-302).

All functions are pure: no Django imports, no database, Decimal only.
Average cost is stored with 4 decimals (ROUND_HALF_UP); quantities with 3.

Weighted-average costing rules (blueprint 6.3):
- The caller passes the final *inventory cost per unit*: recoverable GST is
  excluded and non-recoverable GST is included before this module sees it.
  This module never handles GST.
- Purchase / sale return / cancellation reversal (inflows that revalue):
    if old_qty <= 0 (zero or negative stock): new average = incoming cost
    else: new_avg = q4((old_qty * old_avg + in_qty * cost) / (old_qty + in_qty))
    if old_qty > 0 and old_avg is None: StockError (existing stock has no cost)
- Outflows (sale, adjustment out): average never changes.
- Adjustment in: average never changes (the service seeds a null average via
  the unit cost when the product has no cost yet).
- Purchase return (provisional rule, open item 13.14, pending accountant
  approval): new_qty = old_qty - out_qty; if new_qty > 0 revalue at the
  return cost and reject a negative remaining value; if new_qty <= 0 keep the
  previous average.
"""

from decimal import Decimal

from common.errors import VALIDATION_ERROR
from common.money import q2, q4

from apps.stock.exceptions import StockError


def opening_average(unit_cost):
    """Validated opening average cost, quantised to 4 decimals."""
    return q4(unit_cost)


def outflow_unit_cost(avg_before):
    """Cost at which a unit leaves stock: the running average before the move.

    Outflows never change the average, so the unit leaves at avg_before
    (this is the cost snapshot billing copies on the invoice line).
    """
    return avg_before


def after_purchase(
    old_qty: Decimal, old_avg: Decimal | None, in_qty: Decimal, unit_cost: Decimal
) -> Decimal:
    """New average after adding ``in_qty`` units at ``unit_cost``."""
    if old_qty > 0 and old_avg is None:
        raise StockError(
            VALIDATION_ERROR,
            "existing stock has no cost",
            fields={"unit_cost": "existing stock has no cost"},
        )
    if old_qty <= 0:
        return q4(unit_cost)
    return q4((old_qty * old_avg + in_qty * unit_cost) / (old_qty + in_qty))


def after_return(
    old_qty: Decimal, old_avg: Decimal | None, in_qty: Decimal, original_cost_snapshot: Decimal
) -> Decimal:
    """New average after a return at the original cost snapshot.

    Identical formula to :func:`after_purchase`, kept as a separate named
    function so the return-valuation rule can change independently.
    """
    return after_purchase(old_qty, old_avg, in_qty, original_cost_snapshot)


def after_adjustment_in(old_avg: Decimal | None) -> Decimal | None:
    """Average after an adjustment in: unchanged."""
    return old_avg


def after_sale(old_avg: Decimal | None) -> Decimal | None:
    """Average after a sale: unchanged."""
    return old_avg


def after_adjustment_out(old_avg: Decimal | None) -> Decimal | None:
    """Average after an adjustment out: unchanged."""
    return old_avg


def after_purchase_return(
    old_qty: Decimal, old_avg: Decimal | None, out_qty: Decimal, return_cost: Decimal
) -> Decimal | None:
    """Provisional purchase-return valuation (open item 13.14, pending accountant approval).

    Stock leaves at ``return_cost``. If any stock remains, revalue the
    remainder; if nothing remains, keep the previous average. A negative
    remaining value is rejected.
    """
    new_qty = old_qty - out_qty
    if new_qty > 0:
        if old_avg is None:
            raise StockError(
                VALIDATION_ERROR,
                "existing stock has no cost",
                fields={"unit_cost": "existing stock has no cost"},
            )
        new_avg = q4((old_qty * old_avg - out_qty * return_cost) / new_qty)
        if new_avg < 0:
            raise StockError(
                VALIDATION_ERROR,
                "return cost exceeds the value of the remaining stock",
                fields={"unit_cost": "return cost exceeds the value of the remaining stock"},
            )
        return new_avg
    return old_avg


def stock_value(qty: Decimal, avg: Decimal | None) -> Decimal | None:
    """Stock value for reporting: quantity x average cost, quantised to 2 decimals."""
    if avg is None:
        return None
    return q2(qty * avg)
