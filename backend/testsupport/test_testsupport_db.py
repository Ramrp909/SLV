"""Self-test for testsupport factories and conftest fixtures.

Marked db: every test in this file needs the database.
"""

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from apps.catalog.models import PackUnit
from apps.core.models import AppSettings, GstRate
from apps.stock.models import MovementType, StockMovement
from testsupport.factories import (
    billing_ready_product,
    ensure_seed_data,
    give_opening_stock,
    make_company,
    make_owner,
    make_product,
)

pytestmark = pytest.mark.db

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
PRODUCTION_DIRS = [BACKEND_DIR / "apps", BACKEND_DIR / "config", BACKEND_DIR / "common"]


def _iter_production_python_files():
    for directory in PRODUCTION_DIRS:
        for path in directory.rglob("*.py"):
            name = path.name
            if name.startswith("test_") or name == "tests.py" or name.endswith("_tests.py"):
                continue
            if "tests" in path.relative_to(directory).parts:
                continue
            yield path


def test_factories_produce_unique_codes_across_50_calls():
    codes = {make_product().product_code for _ in range(50)}
    assert len(codes) == 50


def test_make_product_defaults_are_valid():
    product = make_product()
    assert product.product_code.startswith("TEST-")
    assert product.company_id
    assert product.product_type == "TestType"
    assert product.pack_size == Decimal("1")
    assert product.pack_unit == PackUnit.PCS
    assert product.qty_on_hand == Decimal("0")
    assert product.track_stock is True


def test_make_company_unique_names():
    names = {make_company().name for _ in range(10)}
    assert len(names) == 10


def test_make_owner_creates_user():
    user = make_owner()
    assert user.pk
    assert user.username == "factory_owner"


def test_billing_ready_product_is_billing_ready():
    product = billing_ready_product()
    product.refresh_from_db()
    assert product.selling_price == Decimal("100.00")
    assert product.gst_rate == Decimal("18.00")
    assert product.hsn_code == "3208"
    gst_rate = GstRate.objects.get(rate=Decimal("18.00"))
    assert gst_rate.is_active


def test_give_opening_stock_creates_one_movement_and_row_matches():
    product = make_product()
    movement_date = date(2026, 11, 5)
    give_opening_stock(product, Decimal("10"), Decimal("100"), movement_date)
    product.refresh_from_db()
    assert product.qty_on_hand == Decimal("10")
    assert product.avg_buying_price == Decimal("100.0000")
    movements = StockMovement.objects.filter(product=product, movement_type=MovementType.OPENING)
    assert movements.count() == 1
    movement = movements.get()
    assert movement.quantity == Decimal("10.000")
    assert movement.unit_cost == Decimal("100.0000")
    assert movement.qty_after == Decimal("10.000")


def test_ensure_seed_data_restores_rows_after_deletion():
    AppSettings.objects.filter(pk=1).delete()
    GstRate.objects.filter(rate=Decimal("0.00")).delete()
    assert AppSettings.objects.filter(pk=1).count() == 0
    assert GstRate.objects.filter(rate=Decimal("0.00")).count() == 0

    ensure_seed_data()

    assert AppSettings.objects.filter(pk=1).count() == 1
    gst = GstRate.objects.get(rate=Decimal("0.00"))
    assert gst.label == "Exempt"
    assert gst.is_active is True


def test_testsupport_not_imported_by_production_code():
    for path in _iter_production_python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "testsupport" and not alias.name.startswith(
                        "testsupport."
                    ), f"{path} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "testsupport" and not (
                    node.module and node.module.startswith("testsupport.")
                ), f"{path} imports from {node.module}"


def test_testsupport_not_in_installed_apps():
    assert "testsupport" not in settings.INSTALLED_APPS
    assert "backend.testsupport" not in settings.INSTALLED_APPS
