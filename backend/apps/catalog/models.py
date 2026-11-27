"""Models for catalog app: Company (paint companies / suppliers / local group)."""

import re

from common.errors import DUPLICATE_COMPANY_NAME, DUPLICATE_PRODUCT_CODE
from common.validators import normalize_gstin, normalize_phone
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Exists, F, OuterRef, Q, Value
from django.db.models.functions import Lower, Trim, Upper

from apps.core.models import GstRate
from apps.core.validators import validate_gst_rate

PRODUCT_CODE_RE = re.compile(r"^[A-Z0-9/\-]{1,40}$")
"""Allowed product code pattern: 1-40 uppercase letters, digits, hyphen or slash.
Widened here if the shop ever needs additional characters."""


def _normalise_name(value: str) -> str:
    """Trim and collapse repeated spaces in a company name."""
    return " ".join(str(value).split())


class Company(models.Model):
    """
    A paint company / supplier / local group.

    Company-wise stock, purchases, payments, dues, sales and profit are
    tracked per company (blueprint sections 7.3 and 15.5).

    The name is unique case-insensitively, enforced in the database with a
    functional unique constraint on lower(name), so "Berger" and "berger "
    are the same company.
    """

    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    gstin = models.CharField(max_length=15, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    is_local = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="unique_company_name_lower",
            ),
        ]
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["is_local"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.name:
            self.name = _normalise_name(self.name)
        if self.name:
            qs = Company.objects.annotate(ln=Lower("name")).filter(ln=Lower(Value(self.name)))
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"name": "Company with this name already exists."},
                    code=DUPLICATE_COMPANY_NAME,
                )

    def save(self, *args, **kwargs):
        if self.name:
            self.name = _normalise_name(self.name)
        if self.phone:
            self.phone = normalize_phone(self.phone)
        if self.gstin:
            self.gstin = normalize_gstin(self.gstin)
        super().save(*args, **kwargs)


class PackUnit(models.TextChoices):
    LTR = "LTR", "Litre"
    ML = "ML", "Millilitre"
    KG = "KG", "Kilogram"
    G = "G", "Gram"
    PCS = "PCS", "Piece"
    SET = "SET", "Set"
    MTR = "MTR", "Metre"


def canonicalize_label(field_name: str, value: str) -> str:
    """
    Normalise a label (trim + collapse spaces) and adopt an existing spelling.

    Case-insensitive duplicates map to the spelling that already exists in the
    database (first stored spelling wins). When no match exists the normalised
    value is returned as-is.

    Limitation: there is no unique constraint on the label fields (labels repeat
    by design), so canonicalisation is not race-safe. With a single owner and
    imports running in one transaction this is acceptable; two simultaneous
    writers could store two different spellings for the same case-insensitive
    label.
    """
    normalised = " ".join(str(value).split())
    if not normalised:
        return normalised
    existing = Product.objects.filter(**{f"{field_name}__iexact": normalised}).first()
    if existing is not None:
        return getattr(existing, field_name)
    return normalised


class ProductQuerySet(models.QuerySet):
    def billing_ready(self):
        """Products with selling price, an active approved GST rate and an HSN code."""
        active_rate = Exists(GstRate.objects.filter(rate=OuterRef("gst_rate"), is_active=True))
        return (
            self.filter(selling_price__gt=0, gst_rate__isnull=False)
            .exclude(hsn_code__isnull=True)
            .exclude(hsn_code="")
            .filter(active_rate)
        )

    def not_billing_ready(self):
        """Everything that is not billing ready."""
        return self.exclude(pk__in=self.billing_ready().values("pk"))

    def delete(self):
        raise ValidationError("Products are deactivated, never deleted. Use deactivate_product().")


class ProductManager(models.Manager.from_queryset(ProductQuerySet)):
    pass


class Product(models.Model):
    """
    One sellable item with one size (blueprint sections 6.1, 7.3 and 15.3).

    Stock fields (qty_on_hand, avg_buying_price, last_buying_price) are
    editable=False and must only ever be changed by the future stock engine
    (T-301). Products are deactivated, never deleted.
    """

    product_code = models.CharField(max_length=40)
    company = models.ForeignKey("Company", on_delete=models.PROTECT, related_name="products")
    category = models.CharField(max_length=200, blank=True, null=True)
    product_type = models.CharField(max_length=200)
    sub_type = models.CharField(max_length=200, blank=True, null=True)
    sub_sub_type = models.CharField(max_length=200, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    pack_size = models.DecimalField(max_digits=10, decimal_places=3)
    pack_unit = models.CharField(max_length=10, choices=PackUnit.choices)
    # Stock engine only - editable=False, never touched by normal saves.
    qty_on_hand = models.DecimalField(max_digits=10, decimal_places=3, default=0, editable=False)
    avg_buying_price = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True, editable=False
    )
    last_buying_price = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True, editable=False
    )
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    hsn_code = models.CharField(max_length=8, blank=True, null=True)
    min_stock = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    allow_fractional_qty = models.BooleanField(default=False)
    track_stock = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    custom_fields = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductManager()

    class Meta:
        ordering = ["product_code"]
        indexes = [
            models.Index(fields=["company", "is_active"], name="cat_prod_comp_act_idx"),
            models.Index(fields=["product_type"], name="cat_prod_type_idx"),
            models.Index(fields=["sub_type"], name="cat_prod_sub_type_idx"),
        ]
        constraints = [
            models.UniqueConstraint(Lower("product_code"), name="unique_product_code_lower"),
            models.CheckConstraint(check=Q(pack_size__gt=0), name="product_pack_size_positive"),
            models.CheckConstraint(
                check=Q(selling_price__isnull=True) | Q(selling_price__gt=0),
                name="product_selling_price_gt_zero",
            ),
            models.CheckConstraint(
                check=Q(min_stock__isnull=True) | Q(min_stock__gte=0),
                name="product_min_stock_gte_zero",
            ),
            models.CheckConstraint(
                check=Q(avg_buying_price__isnull=True) | Q(avg_buying_price__gte=0),
                name="product_avg_cost_gte_zero",
            ),
            models.CheckConstraint(
                check=Q(last_buying_price__isnull=True) | Q(last_buying_price__gte=0),
                name="product_last_cost_gte_zero",
            ),
            models.CheckConstraint(
                check=Q(gst_rate__isnull=True) | (Q(gst_rate__gte=0) & Q(gst_rate__lte=100)),
                name="product_gst_rate_0_to_100",
            ),
            models.CheckConstraint(
                check=Q(pack_unit__in=PackUnit.values),
                name="product_pack_unit_valid",
            ),
            models.CheckConstraint(
                check=~Q(product_code=""),
                name="product_code_min_length_1",
            ),
            models.CheckConstraint(
                check=~Q(product_code__regex=r".{41,}"),
                name="product_code_max_length_40",
            ),
            models.CheckConstraint(
                check=Q(product_code=Upper(Trim(F("product_code")))),
                name="product_code_upper_trimmed",
            ),
        ]

    def __str__(self):
        return self.product_code

    def _validate_product_code(self):
        """Normalise (trim/uppercase) and validate product_code pattern + length.

        The character pattern (PRODUCT_CODE_RE) is enforced in code only, not in a
        database constraint, so widening it later needs no migration. Length (1-40)
        and the upper/trimmed form are also enforced by database check constraints so
        bulk_create()/update() (which bypass save()) cannot store invalid codes.
        """
        if self.product_code is None:
            return
        self.product_code = str(self.product_code).strip().upper()
        if not PRODUCT_CODE_RE.match(self.product_code):
            raise ValidationError(
                {
                    "product_code": (
                        "Product code must contain 1-40 uppercase letters, "
                        "digits, hyphens or slashes only (no spaces)."
                    )
                }
            )

    def clean(self):
        self._validate_product_code()
        if self.product_code:
            qs = Product.objects.filter(product_code__iexact=self.product_code)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"product_code": "Product code already exists (case-insensitive)."},
                    code=DUPLICATE_PRODUCT_CODE,
                )
        for field in ("product_type", "sub_type", "sub_sub_type", "category"):
            value = getattr(self, field)
            if value:
                setattr(self, field, canonicalize_label(field, value))
        if self.pack_size is not None and self.pack_size <= 0:
            raise ValidationError({"pack_size": "Pack size must be greater than zero."})
        if self.pack_unit and self.pack_unit not in PackUnit.values:
            raise ValidationError(
                {"pack_unit": (f"Pack unit must be one of {', '.join(PackUnit.values)}.")}
            )
        if self.selling_price is not None and self.selling_price <= 0:
            raise ValidationError(
                {"selling_price": "Selling price must be greater than zero when set."}
            )
        if self.gst_rate is not None:
            if self.pk:
                original = (
                    Product.objects.filter(pk=self.pk).values_list("gst_rate", flat=True).first()
                )
                if original is None or original != self.gst_rate:
                    validate_gst_rate(self.gst_rate)
            else:
                validate_gst_rate(self.gst_rate)
        if self.hsn_code:
            hsn = str(self.hsn_code).strip()
            if not hsn.isdigit() or not (2 <= len(hsn) <= 8):
                raise ValidationError({"hsn_code": "HSN code must be 2 to 8 digits."})
            self.hsn_code = hsn
        if self.min_stock is not None and self.min_stock < 0:
            raise ValidationError({"min_stock": "Minimum stock must be zero or more."})
        if self.custom_fields is not None and not isinstance(self.custom_fields, dict):
            raise ValidationError({"custom_fields": "Custom fields must be a JSON object (dict)."})

    def save(self, *args, **kwargs):
        self._validate_product_code()
        for field in ("product_type", "sub_type", "sub_sub_type", "category"):
            value = getattr(self, field)
            if value:
                setattr(self, field, canonicalize_label(field, value))
        if self.hsn_code:
            self.hsn_code = str(self.hsn_code).strip()

        update_fields = kwargs.get("update_fields")
        stock_fields = {"qty_on_hand", "avg_buying_price", "last_buying_price"}

        if update_fields is not None:
            requested_stock = [f for f in update_fields if f in stock_fields]
            if requested_stock:
                raise ValueError(
                    "Stock fields "
                    + ", ".join(sorted(requested_stock))
                    + " may only be written by StockService; "
                    "use StockService.apply_movements() instead of Product.save()."
                )

        if (
            self.pk is not None
            and not self._state.adding
            and not kwargs.get("force_insert", False)
            and update_fields is None
        ):
            # Plain save() on an existing row: write only editable concrete
            # fields plus updated_at, so a stale copy cannot overwrite the
            # stock fields that StockService manages.
            editable_fields = [
                f.name
                for f in self._meta.concrete_fields
                if f.editable and f.name not in ("id",) and f.name != "updated_at"
            ] + ["updated_at"]
            kwargs["update_fields"] = sorted(set(editable_fields))

        super().save(*args, **kwargs)

    @property
    def billing_ready(self):
        if self.selling_price is None or self.selling_price <= 0:
            return False
        if self.gst_rate is None:
            return False
        if not GstRate.objects.filter(rate=self.gst_rate, is_active=True).exists():
            return False
        return bool(self.hsn_code)

    def display_name(self, include_company=False):
        parts = []
        if include_company and self.company_id:
            parts.append(self.company.name)
        if self.product_type:
            parts.append(self.product_type)
        if self.sub_type:
            parts.append(self.sub_type)
        if self.sub_sub_type:
            parts.append(self.sub_sub_type)
        if self.pack_size is not None:
            size_text = format(self.pack_size, "f")
            if "." in size_text:
                size_text = size_text.rstrip("0").rstrip(".")
            parts.append(size_text)
        if self.pack_unit:
            parts.append(self.pack_unit)
        return " ".join(parts)

    def find_duplicate_variants(self):
        """Other products with the same company, type, sub-types, size and unit (warning only)."""
        qs = Product.objects.filter(
            company=self.company,
            pack_size=self.pack_size,
            pack_unit=self.pack_unit,
        )
        for field in ("product_type", "sub_type", "sub_sub_type"):
            value = getattr(self, field)
            if value is None:
                qs = qs.filter(**{field: None})
            else:
                qs = qs.filter(**{f"{field}__iexact": value})
        return qs.exclude(pk=self.pk)

    def delete(self, *args, **kwargs):
        raise ValidationError("Products are deactivated, never deleted. Use deactivate_product().")
