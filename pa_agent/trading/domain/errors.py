"""Typed errors for the independent trading domain."""
from __future__ import annotations

from enum import StrEnum


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


class ConversionRejectionReason(StrEnum):
    """Stable reasons for rejecting advisory input at the intent boundary."""

    INVALID_SNAPSHOT_TYPE = "invalid_snapshot_type"
    MISSING_SOURCE_ID = "missing_source_id"
    INVALID_COMPLETION_TIME = "invalid_completion_time"
    MISSING_SOURCE_VERSION = "missing_source_version"
    MISSING_DECISION_DIGEST = "missing_decision_digest"
    DECISION_DIGEST_MISMATCH = "decision_digest_mismatch"
    MISSING_DIRECTION = "missing_direction"
    MISSING_PRICE_BASIS = "missing_price_basis"
    MISSING_QUANTITY_BASIS = "missing_quantity_basis"
    MISSING_RISK_BASIS = "missing_risk_basis"
    MISSING_PRODUCT_CONTEXT = "missing_product_context"
    SEMANTIC_CONFLICT = "semantic_conflict"
    REPAIRED_SOURCE = "repaired_source"
    UNSUPPORTED_ORDER_TYPE = "unsupported_order_type"
    UNSUPPORTED_TARGET = "unsupported_target"
    INVALID_DECIMAL = "invalid_decimal"


class ConversionRejection(TradingDomainError, ValueError):
    """A controlled conversion failure that carries a stable reason code."""

    def __init__(self, reason: ConversionRejectionReason) -> None:
        self.reason = reason
        super().__init__(reason.value)
