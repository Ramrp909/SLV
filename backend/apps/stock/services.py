"""Stock service: the only code allowed to change Product stock fields.

Product.qty_on_hand, avg_buying_price and last_buying_price are editable=False
and must only ever be changed from here, with a single UPDATE of those
columns (never save()). Every public entry point must be called inside
transaction.atomic(); the service wraps its work in a nested atomic block
(savepoint), so if any request in a batch fails, NOTHING from that batch is
saved even when the caller catches the exception and keeps using the outer
transaction.

All affected product rows are locked once with select_for_update, ordered by
primary key (fixed order, deadlock-safe), and the requests are processed
sequentially in the order given against the running state of each locked row.

Weighted-average costing for all movement types is implemented in
``apps/stock/costing.py`` (T-302): PURCHASE, SALE_RETURN, CANCEL_REVERSAL,
ADJ_IN and PURCHASE_RETURN revalue the running average; SALE and ADJ_OUT leave
it unchanged.

No audit entries are written per movement: the business document that causes
the movement writes one audit entry for the whole document.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from common.errors import INSUFFICIENT_STOCK, STOCK_NOT_TRACKED, VALIDATION_ERROR
from common.money import q3, q4
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.models import AppSettings
from apps.stock.costing import (
    after_purchase,
    after_purchase_return,
    opening_average,
    outflow_unit_cost,
)
from apps.stock.exceptions import StockError
from apps.stock.models import MovementType, StockMovement

_INFLOW_TYPES = frozenset(
    {
        MovementType.OPENING,
        MovementType.PURCHASE,
        MovementType.SALE_RETURN,
        MovementType.ADJ_IN,
        MovementType.CANCEL_REVERSAL,
    }
)
_OUTFLOW_TYPES = frozenset({MovementType.SALE, MovementType.ADJ_OUT})

# Stock column limits (see apps/stock/models.py): quantity Decimal(10,3) fits
# [-9999999.999, 9999999.999]; unit_cost / average Decimal(14,4) fits
# [-9999999999.9999, 9999999999.9999]. Any result outside these bounds is
# rejected with StockError before anything is written.
MAX_QTY = Decimal("9999999.999")
MAX_COST = Decimal("9999999999.9999")


@dataclass
class MovementRequest:
    """A stock movement request.

    quantity is always the positive magnitude; the service applies the sign
    implied by movement_type.
    """

    product_id: int
    movement_type: str
    quantity: Decimal
    movement_date: date
    unit_cost: Decimal | None = None
    reference_type: str = ""
    reference_id: str = ""
    reason: str = ""


class StockService:
    """Write operations for the stock movement ledger."""

    @classmethod
    def apply_movements(cls, requests: list[MovementRequest]) -> list[StockMovement]:
        """Apply a batch of movement requests atomically.

        Must be called inside transaction.atomic(). All affected product rows
        are locked once (select_for_update, ordered by primary key) and the
        requests are processed sequentially against the running state of each
        locked row. If any request fails the whole batch is rolled back.
        """
        if not transaction.get_connection().in_atomic_block:
            raise RuntimeError(
                "StockService.apply_movements must be called inside transaction.atomic()"
            )
        with transaction.atomic():
            return cls._apply(list(requests))

    @classmethod
    def apply_movement(cls, request: MovementRequest) -> StockMovement:
        """Convenience for applying a single movement."""
        return cls.apply_movements([request])[0]

    @classmethod
    def _apply(cls, requests: list[MovementRequest]) -> list[StockMovement]:
        settings = AppSettings.get_settings()
        allow_negative_stock = settings.allow_negative_stock

        # Structural validation of every request before any lock is taken.
        for request in requests:
            cls._validate_structural(request)

        product_ids = {request.product_id for request in requests}
        products = Product.objects.filter(pk__in=product_ids).select_for_update().order_by("pk")
        product_by_id = {product.id: product for product in products}

        state: dict[int, dict] = {}
        for product in products:
            state[product.id] = {
                "id": product.id,
                "qty": product.qty_on_hand,
                "avg": product.avg_buying_price,
                "code": product.product_code,
                "track_stock": product.track_stock,
                "fractional": product.allow_fractional_qty,
            }

        created: list[StockMovement] = []
        for request in requests:
            movement = cls._process_one(request, product_by_id, state, allow_negative_stock)
            created.append(movement)

        if created:
            StockMovement.objects.bulk_create(created)
        return created

    @classmethod
    def _validate_structural(cls, request: MovementRequest) -> None:
        if not isinstance(request.quantity, Decimal):
            raise StockError(
                VALIDATION_ERROR,
                "quantity must be a Decimal",
                fields={"quantity": "must be a Decimal"},
            )
        if request.quantity <= 0:
            raise StockError(
                VALIDATION_ERROR,
                "quantity must be greater than zero",
                fields={"quantity": "must be greater than zero"},
            )
        if request.quantity.as_tuple().exponent < -3:
            raise StockError(
                VALIDATION_ERROR,
                "quantity must have at most 3 decimal places",
                fields={"quantity": "at most 3 decimal places"},
            )
        if request.quantity > MAX_QTY:
            raise StockError(
                VALIDATION_ERROR,
                "value too large",
                fields={"quantity": "value too large"},
            )
        request.quantity = q3(request.quantity)
        if isinstance(request.movement_date, datetime) or not isinstance(
            request.movement_date, date
        ):
            raise StockError(
                VALIDATION_ERROR,
                "movement_date must be a date, not a datetime",
                fields={"movement_date": "must be a date"},
            )

    @classmethod
    def _process_one(
        cls,
        request: MovementRequest,
        product_by_id: dict[int, Product],
        state: dict[int, dict],
        allow_negative_stock: bool,
    ) -> StockMovement:
        pid = request.product_id
        st = state.get(pid)
        if st is None:
            raise StockError(
                VALIDATION_ERROR,
                f"Unknown product id {pid}",
                fields={"product_id": str(pid)},
            )
        if not st["track_stock"]:
            raise StockError(
                STOCK_NOT_TRACKED,
                f"Product {st['code']} does not track stock",
                fields={"product_id": str(pid), "product_code": st["code"]},
            )

        magnitude = request.quantity
        if not st["fractional"] and magnitude != magnitude.to_integral_value():
            raise StockError(
                VALIDATION_ERROR,
                "quantity must be a whole number",
                fields={"quantity": "must be a whole number"},
            )

        qty_before = st["qty"]
        avg_before = st["avg"]
        magnitude = request.quantity

        if request.movement_type == MovementType.OPENING:
            new_qty, new_avg, unit_cost, avg_cost_after = cls._process_opening(
                pid, st, qty_before, avg_before, request
            )
            signed_qty = new_qty
        elif request.movement_type == MovementType.PURCHASE_RETURN:
            new_qty, new_avg, unit_cost, avg_cost_after = cls._process_purchase_return(
                st, qty_before, avg_before, request
            )
            signed_qty = -magnitude
        elif request.movement_type in (
            MovementType.PURCHASE,
            MovementType.SALE_RETURN,
            MovementType.CANCEL_REVERSAL,
        ):
            new_qty, new_avg, unit_cost, avg_cost_after = cls._process_revaluing_inflow(
                pid, st, qty_before, avg_before, request
            )
            signed_qty = magnitude
        elif request.movement_type == MovementType.ADJ_IN:
            new_qty, new_avg, unit_cost, avg_cost_after = cls._process_adj_in(
                pid, st, qty_before, avg_before, request
            )
            signed_qty = magnitude
        elif request.movement_type in _OUTFLOW_TYPES:
            new_qty, new_avg, unit_cost, avg_cost_after = cls._process_outflow(
                st, qty_before, avg_before, request
            )
            signed_qty = -magnitude
        else:
            raise StockError(
                VALIDATION_ERROR,
                f"Unknown movement type {request.movement_type}",
                fields={"movement_type": "unknown movement type"},
            )

        if new_qty > MAX_QTY:
            raise StockError(
                VALIDATION_ERROR,
                "value too large",
                fields={"quantity": "value too large"},
            )
        if (
            (new_avg is not None and new_avg > MAX_COST)
            or (unit_cost is not None and unit_cost > MAX_COST)
            or (avg_cost_after is not None and avg_cost_after > MAX_COST)
        ):
            raise StockError(
                VALIDATION_ERROR,
                "value too large",
                fields={"unit_cost": "value too large"},
            )

        if new_qty < 0 and not allow_negative_stock:
            raise StockError(
                INSUFFICIENT_STOCK,
                (
                    f"Insufficient stock for {st['code']}: "
                    f"available {qty_before}, requested {magnitude}"
                ),
                fields={
                    "product_id": str(pid),
                    "product_code": st["code"],
                    "available": str(qty_before),
                    "requested": str(magnitude),
                },
            )

        movement = StockMovement(
            product_id=pid,
            movement_type=request.movement_type,
            quantity=signed_qty,
            unit_cost=unit_cost,
            qty_after=new_qty,
            avg_cost_after=avg_cost_after,
            reference_type=request.reference_type,
            reference_id=request.reference_id,
            reason=request.reason,
            movement_date=request.movement_date,
        )
        movement.avg_before = avg_before

        # Single UPDATE of only the stock columns; never save().
        if request.movement_type == MovementType.PURCHASE:
            Product.objects.filter(pk=pid).update(
                qty_on_hand=new_qty,
                avg_buying_price=new_avg,
                last_buying_price=unit_cost,
                updated_at=timezone.now(),
            )
        else:
            Product.objects.filter(pk=pid).update(
                qty_on_hand=new_qty,
                avg_buying_price=new_avg,
                updated_at=timezone.now(),
            )
        st["qty"] = new_qty
        st["avg"] = new_avg
        return movement

    @classmethod
    def _process_opening(
        cls, pid: int, st: dict, qty_before: Decimal, avg_before: Decimal, request: MovementRequest
    ):
        if StockMovement.objects.filter(product_id=pid).exists() or qty_before != 0:
            raise StockError(
                VALIDATION_ERROR,
                (
                    f"Opening stock not allowed for {st['code']}: the product "
                    f"already has stock or stock movements"
                ),
                fields={"product_id": str(pid), "product_code": st["code"]},
            )
        if request.unit_cost is None:
            raise StockError(
                VALIDATION_ERROR,
                "unit_cost is required for opening stock",
                fields={"unit_cost": "required"},
            )
        if request.unit_cost < 0:
            raise StockError(
                VALIDATION_ERROR,
                "unit_cost must be zero or more",
                fields={"unit_cost": "must be >= 0"},
            )
        unit_cost = q4(request.unit_cost)
        new_qty = request.quantity
        new_avg = opening_average(unit_cost)
        return new_qty, new_avg, unit_cost, unit_cost

    @classmethod
    def _process_outflow(
        cls, st: dict, qty_before: Decimal, avg_before: Decimal, request: MovementRequest
    ):
        if request.unit_cost is not None:
            raise StockError(
                VALIDATION_ERROR,
                "unit_cost must not be supplied for a sale or adjustment out",
                fields={"unit_cost": "must not be supplied"},
            )
        if request.movement_type == MovementType.ADJ_OUT and not request.reason.strip():
            raise StockError(
                VALIDATION_ERROR,
                "reason is required for an adjustment out",
                fields={"reason": "required"},
            )
        new_qty = q3(qty_before - request.quantity)
        new_avg = avg_before  # outflows never change the average
        unit_cost = outflow_unit_cost(avg_before)
        return new_qty, new_avg, unit_cost, unit_cost

    @classmethod
    def _validate_unit_cost(cls, request: MovementRequest, required: bool) -> Decimal | None:
        """Validate ``unit_cost`` for types that accept it: Decimal, >= 0, at most 4 decimals.

        Rejects more than 4 decimals; never rounds silently.
        """
        if request.unit_cost is None:
            if required:
                raise StockError(
                    VALIDATION_ERROR,
                    f"unit_cost is required for {request.movement_type}",
                    fields={"unit_cost": "required"},
                )
            return None
        if not isinstance(request.unit_cost, Decimal):
            raise StockError(
                VALIDATION_ERROR,
                "unit_cost must be a Decimal",
                fields={"unit_cost": "must be a Decimal"},
            )
        if request.unit_cost < 0:
            raise StockError(
                VALIDATION_ERROR,
                "unit_cost must be zero or more",
                fields={"unit_cost": "must be >= 0"},
            )
        if request.unit_cost.as_tuple().exponent < -4:
            raise StockError(
                VALIDATION_ERROR,
                "unit_cost must have at most 4 decimal places",
                fields={"unit_cost": "at most 4 decimal places"},
            )
        if request.unit_cost > MAX_COST:
            raise StockError(
                VALIDATION_ERROR,
                "value too large",
                fields={"unit_cost": "value too large"},
            )
        return q4(request.unit_cost)

    @classmethod
    def _process_revaluing_inflow(
        cls,
        pid: int,
        st: dict,
        qty_before: Decimal,
        avg_before: Decimal | None,
        request: MovementRequest,
    ):
        """PURCHASE, SALE_RETURN and CANCEL_REVERSAL: revalue at the incoming cost."""
        unit_cost = cls._validate_unit_cost(request, required=True)
        new_avg = after_purchase(qty_before, avg_before, request.quantity, unit_cost)
        new_qty = q3(qty_before + request.quantity)
        return new_qty, new_avg, unit_cost, new_avg

    @classmethod
    def _process_adj_in(
        cls,
        pid: int,
        st: dict,
        qty_before: Decimal,
        avg_before: Decimal | None,
        request: MovementRequest,
    ):
        """ADJ_IN: reason required; unit_cost only to seed a null average."""
        if not request.reason.strip():
            raise StockError(
                VALIDATION_ERROR,
                "reason is required for an adjustment in",
                fields={"reason": "required"},
            )
        if avg_before is None:
            unit_cost = cls._validate_unit_cost(request, required=True)
            movement_unit_cost = unit_cost
            new_avg = q4(unit_cost)
        else:
            unit_cost = cls._validate_unit_cost(request, required=False)
            if unit_cost is not None:
                raise StockError(
                    VALIDATION_ERROR,
                    "unit_cost must not be supplied when the product already has an average",
                    fields={"unit_cost": "must not be supplied"},
                )
            movement_unit_cost = avg_before
            new_avg = avg_before
        new_qty = q3(qty_before + request.quantity)
        return new_qty, new_avg, movement_unit_cost, new_avg

    @classmethod
    def _process_purchase_return(
        cls,
        st: dict,
        qty_before: Decimal,
        avg_before: Decimal | None,
        request: MovementRequest,
    ):
        """PURCHASE_RETURN: stock out at the return cost (provisional, 13.14)."""
        unit_cost = cls._validate_unit_cost(request, required=False)
        if avg_before is None and unit_cost is None:
            new_avg = None
            movement_unit_cost = None
        else:
            return_cost = unit_cost if unit_cost is not None else avg_before
            new_avg = after_purchase_return(qty_before, avg_before, request.quantity, return_cost)
            movement_unit_cost = unit_cost
        new_qty = q3(qty_before - request.quantity)
        return new_qty, new_avg, movement_unit_cost, new_avg
