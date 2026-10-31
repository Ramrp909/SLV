"""Tests for money.py utilities."""

from decimal import Decimal

from django.test import TestCase

from common.money import D, q2, q4, safe_sum


class TestD(TestCase):
    """Tests for D() - Decimal constructor that rejects floats."""

    def test_D_from_string(self):
        assert D("10.50") == Decimal("10.50")

    def test_D_from_int(self):
        assert D(10) == Decimal("10")

    def test_D_from_decimal(self):
        assert D(Decimal("10.50")) == Decimal("10.50")

    def test_D_from_float_raises_type_error(self):
        with self.assertRaises(TypeError):
            D(0.1)

    def test_D_from_float_10_50_raises_type_error(self):
        with self.assertRaises(TypeError):
            D(10.50)


class TestQ2(TestCase):
    """Tests for q2() - quantize to 0.01 with ROUND_HALF_UP."""

    def test_half_up_005(self):
        assert q2(Decimal("0.005")) == Decimal("0.01")

    def test_half_up_2675(self):
        assert q2(Decimal("2.675")) == Decimal("2.68")

    def test_half_up_31665(self):
        assert q2(Decimal("31.665")) == Decimal("31.67")

    def test_half_up_1004(self):
        assert q2(Decimal("1.004")) == Decimal("1.00")

    def test_half_up_1005(self):
        assert q2(Decimal("1.005")) == Decimal("1.01")

    def test_already_quantized(self):
        assert q2(Decimal("1.50")) == Decimal("1.50")


class TestQ4(TestCase):
    """Tests for q4() - quantize to 0.0001 with ROUND_HALF_UP."""

    def test_half_up_case(self):
        assert q4(Decimal("1.23455")) == Decimal("1.2346")

    def test_already_quantized(self):
        assert q4(Decimal("1.2345")) == Decimal("1.2345")


class TestSafeSum(TestCase):
    """Tests for safe_sum() - sum Decimals starting from Decimal('0')."""

    def test_empty_list(self):
        assert safe_sum([]) == Decimal("0")

    def test_single_value(self):
        assert safe_sum([Decimal("1.50")]) == Decimal("1.50")

    def test_multiple_values(self):
        assert safe_sum([Decimal("1.50"), Decimal("2.50"), Decimal("3.00")]) == Decimal("7.00")

    def test_with_strings(self):
        assert safe_sum(["1.50", "2.50"]) == Decimal("4.00")
