"""Pure costing helpers for stock movements (T-301).

Only outflow costing is implemented here. Weighted-average costing for the
inflow types that need it (PURCHASE, SALE_RETURN, CANCEL_REVERSAL,
PURCHASE_RETURN, ADJ_IN) is intentionally not implemented: the service
raises CostingNotImplementedError("pending T-302") for them until T-302.
The tests for that pending behaviour are temporary and will be replaced by
T-302.
"""

from common.money import q4

COSTING_PENDING_TYPES = [
    "PURCHASE",
    "SALE_RETURN",
    "CANCEL_REVERSAL",
    "PURCHASE_RETURN",
    "ADJ_IN",
]


def outflow_unit_cost(avg_before):
    """Cost at which a unit leaves stock: the running average before the move.

    Outflows never change the average, so the unit leaves at avg_before
    (this is the cost snapshot billing copies on the invoice line).
    """
    return avg_before


def opening_average(unit_cost):
    """Validated opening average cost, quantised to 4 decimals."""
    return q4(unit_cost)
