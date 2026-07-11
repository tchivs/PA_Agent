"""Immutable canonical values for the exchange-neutral trading domain."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum
from typing import Any, TypeAlias

from pa_agent.trading.domain.errors import (
    CanonicalInputError,
    DecimalValueError,
    ProductContextError,
)


class ProductType(StrEnum):
    """Products whose account and position semantics must stay distinct."""

    SPOT = "spot"
    ISOLATED_MARGIN = "isolated_margin"
    USDT_PERPETUAL = "usdt_perpetual"


class Mode(StrEnum):
    """Execution environments represented by the domain."""

    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"


class Side(StrEnum):
    """Order direction."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Canonical order types available before venue-specific capability checks."""

    MARKET = "market"
    LIMIT = "limit"


class OrderState(StrEnum):
    """Durable lifecycle projection states."""

    PROPOSED = "proposed"
    SUBMITTING = "submitting"
    SUBMISSION_UNKNOWN = "submission_unknown"
    ACKNOWLEDGED = "acknowledged"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    CANCEL_REQUESTED = "cancel_requested"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class LifecycleEvent(StrEnum):
    """Events accepted by the pure order lifecycle transition guard."""

    SUBMIT_REQUESTED = "submit_requested"
    ACKNOWLEDGEMENT_OBSERVED = "acknowledgement_observed"
    OPEN_OBSERVED = "open_observed"
    PARTIAL_FILL_OBSERVED = "partial_fill_observed"
    FILL_OBSERVED = "fill_observed"
    REJECTION_OBSERVED = "rejection_observed"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLATION_OBSERVED = "cancellation_observed"
    LOCAL_TIMEOUT = "local_timeout"
    LOCAL_CANCELLATION = "local_cancellation"
    STREAM_GAP = "stream_gap"
    MALFORMED_ACKNOWLEDGEMENT = "malformed_acknowledgement"


def decimal_from_canonical(value: Decimal | str) -> Decimal:
    """Parse an exact finite Decimal, rejecting floats and non-canonical numeric types."""
    if isinstance(value, float):
        raise DecimalValueError("binary float is not a trading-domain value")
    if not isinstance(value, (Decimal, str)):
        raise DecimalValueError("trading Decimal values must be Decimal instances or text")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise DecimalValueError("invalid trading Decimal") from exc
    if not parsed.is_finite():
        raise DecimalValueError("trading Decimal values must be finite")
    return parsed


def decimal_to_canonical(value: Decimal | str) -> str:
    """Return stable fixed-point text for a finite canonical Decimal value."""
    return format(decimal_from_canonical(value), "f")


def _decimal_field(instance: object, name: str) -> None:
    object.__setattr__(instance, name, decimal_from_canonical(getattr(instance, name)))


def _optional_decimal_field(instance: object, name: str) -> None:
    value = getattr(instance, name)
    if value is not None:
        object.__setattr__(instance, name, decimal_from_canonical(value))


def _require_positive(instance: object, name: str) -> None:
    if getattr(instance, name) <= 0:
        raise ProductContextError(f"{name} must be positive")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_nonnegative(instance: object, name: str) -> None:
    if getattr(instance, name) < 0:
        raise CanonicalInputError(f"{name} must be non-negative")


@dataclass(frozen=True)
class SpotOrderContext:
    """Spot order context, deliberately without leverage or borrowing fields."""

    product: ProductType = ProductType.SPOT

    def __post_init__(self) -> None:
        if self.product is not ProductType.SPOT:
            raise ProductContextError("spot context must use the spot product")


@dataclass(frozen=True)
class IsolatedMarginOrderContext:
    """Isolated-margin context with explicit isolated pair and repayment policy."""

    isolated_symbol: str
    borrow_asset: str | None = None
    auto_repay: bool = False
    product: ProductType = ProductType.ISOLATED_MARGIN

    def __post_init__(self) -> None:
        if self.product is not ProductType.ISOLATED_MARGIN:
            raise ProductContextError("isolated margin context must use its product")
        if not self.isolated_symbol:
            raise ProductContextError("isolated_symbol is required")
        if self.auto_repay and not self.borrow_asset:
            raise ProductContextError("auto_repay requires an explicit borrow_asset")


@dataclass(frozen=True)
class UsdtPerpetualOrderContext:
    """USDT perpetual context restricted to isolated, one-way product semantics."""

    leverage: Decimal | str
    margin_mode: str
    position_mode: str
    product: ProductType = ProductType.USDT_PERPETUAL

    def __post_init__(self) -> None:
        if self.product is not ProductType.USDT_PERPETUAL:
            raise ProductContextError("USDT perpetual context must use its product")
        _decimal_field(self, "leverage")
        _require_positive(self, "leverage")
        if self.margin_mode != "isolated":
            raise ProductContextError("USDT perpetual commands require isolated margin mode")
        if self.position_mode != "one_way":
            raise ProductContextError("USDT perpetual commands require one-way position mode")


ProductContext: TypeAlias = SpotOrderContext | IsolatedMarginOrderContext | UsdtPerpetualOrderContext


_PRODUCT_CONTEXT_TYPES = {
    SpotOrderContext: ProductType.SPOT,
    IsolatedMarginOrderContext: ProductType.ISOLATED_MARGIN,
    UsdtPerpetualOrderContext: ProductType.USDT_PERPETUAL,
}


def _require_product_context(value: object) -> None:
    expected_product = _PRODUCT_CONTEXT_TYPES.get(type(value))
    if expected_product is None or value.product is not expected_product:
        raise CanonicalInputError("command context must be a matching canonical product context")


@dataclass(frozen=True)
class ExecutionCommand:
    """Immutable canonical command before gateway execution.

    ``client_order_id`` remains a non-authoritative caller candidate until the
    ledger allocates one durable identity; it is never a submission authority.
    """

    command_id: str
    logical_command_key: str
    client_order_id: str
    mode: Mode
    account_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal | str
    context: ProductContext
    price: Decimal | str | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.command_id,
                self.logical_command_key,
                self.client_order_id,
                self.account_id,
                self.symbol,
            )
        ):
            raise ValueError("command identifiers, account_id, and symbol are required")
        if type(self.mode) is not Mode:
            raise CanonicalInputError("mode must be a Mode instance")
        if type(self.side) is not Side:
            raise CanonicalInputError("side must be a Side instance")
        if type(self.order_type) is not OrderType:
            raise CanonicalInputError("order_type must be an OrderType instance")
        _require_product_context(self.context)
        _decimal_field(self, "quantity")
        _require_positive(self, "quantity")
        _optional_decimal_field(self, "price")
        if self.order_type is OrderType.LIMIT and self.price is None:
            raise ValueError("limit orders require a price")
        if self.order_type is OrderType.MARKET and self.price is not None:
            raise ValueError("market orders cannot include a price")

    def to_canonical_dict(self) -> dict[str, Any]:
        """Serialize recursively into canonical JSON-compatible domain values."""
        return canonicalize(self)


@dataclass(frozen=True)
class OrderProjection:
    """Current immutable local projection of an order's evidence-driven lifecycle."""

    command_id: str
    state: OrderState
    exchange_order_id: str | None = None
    filled_quantity: Decimal | str = Decimal("0")
    filled_notional: Decimal | str = Decimal("0")

    def __post_init__(self) -> None:
        _decimal_field(self, "filled_quantity")
        _decimal_field(self, "filled_notional")


@dataclass(frozen=True)
class Fill:
    """Immutable normalized fill observation."""

    fill_id: str
    command_id: str
    quantity: Decimal | str
    price: Decimal | str
    fee: Decimal | str
    fee_asset: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in ("quantity", "price", "fee"):
            _decimal_field(self, name)
        _require_positive(self, "quantity")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class Balance:
    """Immutable account balance snapshot for one asset."""

    asset: str
    total: Decimal | str
    available: Decimal | str
    reserved: Decimal | str

    def __post_init__(self) -> None:
        for name in ("total", "available", "reserved"):
            _decimal_field(self, name)


@dataclass(frozen=True)
class Position:
    """Immutable product-specific position snapshot."""

    symbol: str
    quantity: Decimal | str
    entry_price: Decimal | str
    mark_price: Decimal | str
    unrealized_pnl: Decimal | str
    margin: Decimal | str

    def __post_init__(self) -> None:
        for name in ("quantity", "entry_price", "mark_price", "unrealized_pnl", "margin"):
            _decimal_field(self, name)


@dataclass(frozen=True)
class InstrumentRules:
    """Canonical venue rules used by later deterministic validation."""

    symbol: str
    price_tick: Decimal | str
    quantity_step: Decimal | str
    minimum_quantity: Decimal | str = Decimal("0")
    minimum_notional: Decimal | str = Decimal("0")

    def __post_init__(self) -> None:
        for name in ("price_tick", "quantity_step", "minimum_quantity", "minimum_notional"):
            _decimal_field(self, name)
        _require_positive(self, "price_tick")
        _require_positive(self, "quantity_step")
        _require_nonnegative(self, "minimum_quantity")
        _require_nonnegative(self, "minimum_notional")


@dataclass(frozen=True)
class GatewayCapabilities:
    """Normalized product and recovery capabilities declared by a future gateway."""

    products: frozenset[ProductType]
    supports_order_lookup: bool
    supports_fill_lookup: bool = False
    supports_cancellation: bool = False
    minimum_leverage: Decimal | str | None = None
    maximum_leverage: Decimal | str | None = None

    def __post_init__(self) -> None:
        _optional_decimal_field(self, "minimum_leverage")
        _optional_decimal_field(self, "maximum_leverage")
        if self.minimum_leverage is not None:
            _require_positive(self, "minimum_leverage")
        if self.maximum_leverage is not None:
            _require_positive(self, "maximum_leverage")
        if (
            self.minimum_leverage is not None
            and self.maximum_leverage is not None
            and self.minimum_leverage > self.maximum_leverage
        ):
            raise ProductContextError("minimum_leverage cannot exceed maximum_leverage")


@dataclass(frozen=True)
class AccountObservation:
    """Typed timestamped account evidence without venue payload leakage."""

    account_id: str
    product: ProductType
    observed_at: datetime
    balances: tuple[Balance, ...] = ()
    positions: tuple[Position, ...] = ()

    def __post_init__(self) -> None:
        if not self.account_id:
            raise CanonicalInputError("account_id is required")
        if type(self.product) is not ProductType:
            raise CanonicalInputError("product must be a ProductType instance")
        if type(self.balances) is not tuple or type(self.positions) is not tuple:
            raise CanonicalInputError("account records must use immutable tuples")
        if any(type(balance) is not Balance for balance in self.balances):
            raise CanonicalInputError("balances must contain only canonical Balance values")
        if any(type(position) is not Position for position in self.positions):
            raise CanonicalInputError("positions must contain only canonical Position values")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class QuoteObservation:
    """Timestamped canonical bid and ask observation."""

    symbol: str
    bid: Decimal | str
    ask: Decimal | str
    observed_at: datetime

    def __post_init__(self) -> None:
        _decimal_field(self, "bid")
        _decimal_field(self, "ask")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class TimeObservation:
    """Timestamped server-clock observation."""

    server_time: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.server_time, "server_time")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class RuleObservation:
    """Timestamped immutable instrument-rule observation."""

    rules: InstrumentRules
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class GatewayEvidence:
    """Normalized external observation used to advance an order projection."""

    evidence_id: str
    client_order_id: str
    state: OrderState
    observed_at: datetime
    exchange_order_id: str | None = None
    filled_quantity: Decimal | str | None = None
    average_fill_price: Decimal | str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.client_order_id:
            raise ValueError("evidence_id and client_order_id are required")
        if type(self.state) is not OrderState:
            raise CanonicalInputError("state must be an OrderState instance")
        _optional_decimal_field(self, "filled_quantity")
        _optional_decimal_field(self, "average_fill_price")
        _require_aware(self.observed_at, "observed_at")
        if self.state in {OrderState.PARTIALLY_FILLED, OrderState.FILLED}:
            if self.filled_quantity is None or self.average_fill_price is None:
                raise CanonicalInputError(
                    "partial and filled evidence require quantity and average fill price"
                )
            if self.filled_quantity <= 0 or self.average_fill_price <= 0:
                raise CanonicalInputError(
                    "partial and filled evidence require positive fill values"
                )


def canonicalize(value: Any) -> Any:
    """Convert canonical domain data into immutable-friendly JSON primitives."""
    if isinstance(value, Decimal):
        return decimal_to_canonical(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: canonicalize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple | list | frozenset):
        return [canonicalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): canonicalize(item) for key, item in value.items()}
    return value
