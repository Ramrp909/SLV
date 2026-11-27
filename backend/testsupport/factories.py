"""Test-support factories: plain functions, no external library.

All values are fake or illustrative. GST rates and HSN codes used here are
test-only and must never be treated as real business data.

Functions:
- make_company(**overrides): company with a unique fake name.
- make_product(**overrides): product with the five required fields only and a
  unique product_code from a counter.
- make_owner(): owner user with a fake username and secrets-generated password.
- approve_gst_rate(rate_value, label="test"): create/activate a test-only GST rate.
- billing_ready_product(**overrides): product that is billing-ready (approved
  test-only rate, price and HSN all set).
- give_opening_stock(product, quantity, unit_cost, movement_date): one OPENING
  movement via StockService inside transaction.atomic.
- ensure_seed_data(): recreate the migration-seeded AppSettings row (pk=1) and
  the 0.00 GST rate if missing.

testsupport must never be imported by production code (apps/, config/, common/).
"""

from decimal import Decimal
from itertools import count

from django.db import transaction

from apps.catalog.models import Company, PackUnit, Product
from apps.core.models import AppSettings, GstRate
from apps.stock.models import MovementType
from apps.stock.services import MovementRequest, StockService

_product_counter = count(1)
_company_counter = count(1)


def make_company(**overrides):
    """Create a company with a unique fake name. Overrides merge into defaults."""
    defaults = {"name": f"Test Co {next(_company_counter)}"}
    defaults.update(overrides)
    return Company.objects.create(**defaults)


def make_product(**overrides):
    """Create a product with the five required fields only and a unique code.

    Defaults: product_code (unique counter), company, product_type, pack_size,
    pack_unit. All other fields take their model defaults.
    """
    defaults = {
        "product_code": f"TEST-{next(_product_counter):04d}",
        "company": make_company(),
        "product_type": "TestType",
        "pack_size": Decimal("1"),
        "pack_unit": PackUnit.PCS,
    }
    defaults.update(overrides)
    return Product.objects.create(**defaults)


def make_owner():
    """Create an owner user with a fake username and secrets-generated password."""
    import secrets

    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(username="factory_owner", password=secrets.token_urlsafe(16))


def approve_gst_rate(rate_value, label="test"):
    """Approve (create or activate) a test-only GST rate.

    Returns the GstRate row. rate_value is treated as illustrative test data.
    """
    rate = Decimal(str(rate_value))
    obj, created = GstRate.objects.get_or_create(
        rate=rate, defaults={"label": label, "is_active": True}
    )
    if not created and not obj.is_active:
        obj.is_active = True
        obj.save()
    return obj


def billing_ready_product(**overrides):
    """Create a product that is billing-ready: an approved test-only rate, price
    and HSN code are all set.
    """
    approve_gst_rate("18.00", label="test")
    defaults = {
        "product_code": f"TEST-{next(_product_counter):04d}",
        "company": make_company(),
        "product_type": "TestType",
        "pack_size": Decimal("1"),
        "pack_unit": PackUnit.PCS,
        "selling_price": Decimal("100.00"),
        "gst_rate": Decimal("18.00"),
        "hsn_code": "3208",
    }
    defaults.update(overrides)
    return Product.objects.create(**defaults)


def give_opening_stock(product, quantity, unit_cost, movement_date):
    """Create one OPENING movement for ``product`` via StockService, inside
    transaction.atomic. Refreshes and returns the product so the row matches
    the movement.
    """
    from datetime import date, datetime

    if isinstance(movement_date, datetime) or not isinstance(movement_date, date):
        raise ValueError("movement_date must be a date, not a datetime")
    with transaction.atomic():
        StockService.apply_movement(
            MovementRequest(
                product_id=product.id,
                movement_type=MovementType.OPENING,
                quantity=quantity,
                movement_date=movement_date,
                unit_cost=unit_cost,
            )
        )
    product.refresh_from_db()
    return product


def ensure_seed_data():
    """Recreate the two migration-seeded rows if they are missing.

    - AppSettings row with pk=1 (default allow_negative_stock=False).
    - GstRate 0.00 "Exempt", is_active=True.

    Mirrors migration apps/core/migrations/0002_create_default_settings_and_gst_rate.py.
    Useful after a TransactionTestCase flush removes them.
    """
    from decimal import Decimal

    AppSettings.objects.get_or_create(pk=1)
    if not GstRate.objects.filter(rate=Decimal("0.00")).exists():
        GstRate.objects.create(rate=Decimal("0.00"), label="Exempt", is_active=True)
    else:
        obj = GstRate.objects.get(rate=Decimal("0.00"))
        if not obj.is_active:
            obj.is_active = True
            obj.save()
