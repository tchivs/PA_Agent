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
    SOURCE_ANALYSIS_STALE = "source_analysis_stale"
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


class RiskRejectionReason(StrEnum):
    """Stable reasons emitted by the target-bound risk boundary."""

    UNSUPPORTED_TARGET = "unsupported_target"
    TARGET_MISMATCH = "target_mismatch"
    PRODUCT_NOT_ALLOWED = "product_not_allowed"
    SYMBOL_NOT_ALLOWED = "symbol_not_allowed"
    ORDER_TYPE_NOT_ALLOWED = "order_type_not_allowed"
    ORDER_NOTIONAL_LIMIT_EXCEEDED = "order_notional_limit_exceeded"
    OPEN_ORDER_LIMIT_EXCEEDED = "open_order_limit_exceeded"
    ORDER_RATE_LIMIT_EXCEEDED = "order_rate_limit_exceeded"
    REALIZED_LOSS_LIMIT_EXCEEDED = "realized_loss_limit_exceeded"
    DRAWDOWN_LIMIT_EXCEEDED = "drawdown_limit_exceeded"
    QUANTITY_PRECISION_INVALID = "quantity_precision_invalid"
    PRICE_PRECISION_INVALID = "price_precision_invalid"
    MINIMUM_QUANTITY_NOT_MET = "minimum_quantity_not_met"
    MINIMUM_NOTIONAL_NOT_MET = "minimum_notional_not_met"
    INSUFFICIENT_AVAILABLE_BALANCE = "insufficient_available_balance"
    EVIDENCE_TARGET_MISMATCH = "evidence_target_mismatch"
    EVIDENCE_ACCOUNT_MISMATCH = "evidence_account_mismatch"
    EVIDENCE_PRODUCT_MISMATCH = "evidence_product_mismatch"
    EVIDENCE_SYMBOL_MISMATCH = "evidence_symbol_mismatch"
    EVIDENCE_WINDOW_INVALID = "evidence_window_invalid"
    EVIDENCE_UTC_DAY_INVALID = "evidence_utc_day_invalid"
    FEE_EVIDENCE_MISSING = "fee_evidence_missing"
    FEE_EVIDENCE_STALE = "fee_evidence_stale"
    FEE_EVIDENCE_TARGET_MISMATCH = "fee_evidence_target_mismatch"
    FEE_EVIDENCE_SYMBOL_MISMATCH = "fee_evidence_symbol_mismatch"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    EVIDENCE_STALE = "evidence_stale"
    EVIDENCE_FUTURE = "evidence_future"
    EVIDENCE_CLOCK_SKEW = "evidence_clock_skew"
    EVIDENCE_CONNECTION_DEGRADED = "evidence_connection_degraded"
    EVIDENCE_CAPABILITY_MISMATCH = "evidence_capability_mismatch"
    INVALID_ECONOMIC_INPUT = "invalid_economic_input"


class RiskRejection(TradingDomainError, ValueError):
    """A controlled risk failure that carries one stable reason code."""

    def __init__(self, reason: RiskRejectionReason) -> None:
        self.reason = reason
        super().__init__(reason.value)
