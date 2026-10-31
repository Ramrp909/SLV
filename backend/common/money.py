"""Money utilities for precise decimal arithmetic.

All monetary calculations must use Decimal, never float.
Rounding: ROUND_HALF_UP to 2 decimals at line level (q2),
4 decimals for average costs (q4).
"""

from decimal import ROUND_HALF_UP, Decimal

# Quantization constants
Q2_QUANTIZER = Decimal("0.01")
Q4_QUANTIZER = Decimal("0.0001")


def D(value) -> Decimal:
    """
    Build a Decimal from a string, int, or Decimal.

    Args:
        value: A string, int, or Decimal. Float is explicitly rejected.

    Returns:
        Decimal: The converted value.

    Raises:
        TypeError: If value is a float.
        ValueError: If value cannot be converted to Decimal.
    """
    if isinstance(value, float):
        raise TypeError(
            "Float values are not allowed. Use strings, integers, or Decimal objects. "
            f"Received float: {value}"
        )
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q2(value) -> Decimal:
    """
    Quantize a Decimal to 2 decimal places (0.01) using ROUND_HALF_UP.

    Args:
        value: A string, int, or Decimal.

    Returns:
        Decimal: Value quantized to 0.01.
    """
    return D(value).quantize(Q2_QUANTIZER, rounding=ROUND_HALF_UP)


def q4(value) -> Decimal:
    """
    Quantize a Decimal to 4 decimal places (0.0001) using ROUND_HALF_UP.

    Args:
        value: A string, int, or Decimal.

    Returns:
        Decimal: Value quantized to 0.0001.
    """
    return D(value).quantize(Q4_QUANTIZER, rounding=ROUND_HALF_UP)


def safe_sum(iterable) -> Decimal:
    """
    Sum an iterable of Decimals starting from Decimal('0').

    Args:
        iterable: An iterable of strings, ints, or Decimals.

    Returns:
        Decimal: The sum, or Decimal('0') if iterable is empty.
    """
    total = Decimal("0")
    for item in iterable:
        total += D(item)
    return total
