"""Exceptions for the stock app."""


class StockError(Exception):
    """Business-rule error carrying a standard error code and optional fields.

    The code is one of the constants in ``common.errors`` (VALIDATION_ERROR
    unless a specific code applies, e.g. INSUFFICIENT_STOCK or
    STOCK_NOT_TRACKED).
    """

    def __init__(self, code: str, message: str, fields: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or {}


class CostingNotImplementedError(NotImplementedError):
    """Raised by StockService for costing paths deferred to T-302."""

    def __init__(self, message: str = "pending T-302"):
        super().__init__(message)
