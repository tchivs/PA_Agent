"""Typed errors for the independent trading domain."""
from __future__ import annotations


class TradingDomainError(Exception):
    """Base class for canonical execution-domain validation failures."""


class CanonicalInputError(TradingDomainError, TypeError):
    """Raised when a public canonical value receives an invalid runtime shape."""


class DecimalValueError(TradingDomainError, TypeError):
    """Raised when a value is not a finite, exact trading Decimal."""


class ProductContextError(TradingDomainError, ValueError):
    """Raised when a command's product context is internally inconsistent."""


class InstrumentRuleValidationError(TradingDomainError, ValueError):
    """Raised when a canonical command violates current instrument rules."""


class LifecycleTransitionError(TradingDomainError, ValueError):
    """Raised when an order lifecycle event cannot legally advance its state."""


class ReconciliationEvidenceError(LifecycleTransitionError):
    """Raised when normalized external evidence is insufficient or contradictory."""
