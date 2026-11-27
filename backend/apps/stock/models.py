"""Stock movement ledger: append-only record of every stock change."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CheckConstraint, Index, Q


class MovementType(models.TextChoices):
    OPENING = "OPENING", "Opening stock"
    PURCHASE = "PURCHASE", "Purchase"
    SALE = "SALE", "Sale"
    SALE_RETURN = "SALE_RETURN", "Sale return"
    PURCHASE_RETURN = "PURCHASE_RETURN", "Purchase return"
    ADJ_IN = "ADJ_IN", "Adjustment in"
    ADJ_OUT = "ADJ_OUT", "Adjustment out"
    CANCEL_REVERSAL = "CANCEL_REVERSAL", "Cancellation reversal"


_INFLOW_TYPES = [
    MovementType.OPENING,
    MovementType.PURCHASE,
    MovementType.SALE_RETURN,
    MovementType.ADJ_IN,
    MovementType.CANCEL_REVERSAL,
]
_OUTFLOW_TYPES = [
    MovementType.SALE,
    MovementType.PURCHASE_RETURN,
    MovementType.ADJ_OUT,
]
_ALL_TYPES = [choice.value for choice in MovementType]


class StockMovementQuerySet(models.QuerySet):
    """QuerySet that blocks update, delete and bulk_update (append-only)."""

    def update(self, *args, **kwargs):
        raise ValidationError("Stock movement is append-only; updates are not allowed.")

    def delete(self):
        raise ValidationError("Stock movement is append-only; deletes are not allowed.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Stock movement is append-only; bulk updates are not allowed.")


class StockMovementManager(models.Manager):
    def get_queryset(self):
        return StockMovementQuerySet(self.model, using=self._db)


class StockMovement(models.Model):
    """
    One append-only stock movement.

    quantity is signed: positive for stock coming in, negative for stock going
    out. The sign is implied by movement_type and enforced by a database
    check constraint. Records are never updated or deleted (enforced in three
    layers: save()/delete(), the custom queryset/manager and a PostgreSQL
    trigger). TRUNCATE is not blocked so Django test cleanup can use it.
    """

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="stock_movements"
    )
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    # Signed quantity: positive for inflows, negative for outflows.
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    qty_after = models.DecimalField(max_digits=10, decimal_places=3)
    avg_cost_after = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    reference_type = models.CharField(max_length=100, blank=True, default="")
    reference_id = models.CharField(max_length=100, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    movement_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StockMovementManager()

    class Meta:
        indexes = [
            Index(fields=["product", "movement_date"], name="stock_mvmt_product_date_idx"),
            Index(fields=["product", "id"], name="stock_mvmt_product_id_idx"),
            Index(fields=["reference_type", "reference_id"], name="stock_mvmt_ref_idx"),
            Index(fields=["movement_date"], name="stock_mvmt_date_idx"),
        ]
        constraints = [
            CheckConstraint(check=~Q(quantity=0), name="stock_movement_quantity_nonzero"),
            CheckConstraint(
                check=(
                    Q(movement_type__in=[t.value for t in _INFLOW_TYPES], quantity__gt=0)
                    | Q(movement_type__in=[t.value for t in _OUTFLOW_TYPES], quantity__lt=0)
                ),
                name="stock_movement_sign_rule",
            ),
            CheckConstraint(
                check=Q(movement_type__in=_ALL_TYPES),
                name="stock_movement_type_valid",
            ),
            CheckConstraint(
                check=Q(unit_cost__isnull=True) | Q(unit_cost__gte=0),
                name="stock_movement_unit_cost_nonnegative",
            ),
            CheckConstraint(
                check=Q(avg_cost_after__isnull=True) | Q(avg_cost_after__gte=0),
                name="stock_movement_avg_cost_after_nonnegative",
            ),
        ]
        verbose_name = "Stock movement"
        verbose_name_plural = "Stock movements"

    def __str__(self):
        return f"{self.movement_date} {self.movement_type} {self.quantity} -> {self.qty_after}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError(
                "Stock movement is append-only; existing entries cannot be modified."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Stock movement is append-only; entries cannot be deleted.")
