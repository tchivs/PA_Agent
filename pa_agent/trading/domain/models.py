"""Immutable canonical values for the exchange-neutral trading domain."""
from __future__ import annotations
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum
from hashlib import sha256
import json
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


PRODUCT_CONTEXT_SCHEMA_VERSION = "product-context-v1"
PROTECTIVE_EXIT_SCHEMA_VERSION = "protective-exit-v1"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _load_unique_json(payload: str) -> dict[str, object]:
    if not isinstance(payload, str):
        raise CanonicalInputError("canonical payload must be JSON text")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CanonicalInputError("canonical payload cannot contain duplicate fields")
            result[key] = value
        return result

    try:
        decoded = json.loads(payload, object_pairs_hook=reject_duplicates)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CanonicalInputError("canonical payload must be valid unique-key JSON") from exc
    if type(decoded) is not dict:
        raise CanonicalInputError("canonical payload must be an object")
    return decoded


def _require_exact_fields(data: dict[str, object], fields: frozenset[str]) -> None:
    if frozenset(data) != fields:
        raise CanonicalInputError("canonical payload fields do not match its schema")


def _canonical_decimal_text(value: object) -> Decimal:
    if not isinstance(value, str):
        raise CanonicalInputError("canonical Decimal fields must be text")
    parsed = decimal_from_canonical(value)
    if decimal_to_canonical(parsed) != value:
        raise CanonicalInputError("Decimal text is not canonical")
    return parsed


@dataclass(frozen=True)
class ProtectiveExitPlan:
    """Frozen stop policy bound to a perpetual entry and its durable approval."""

    symbol: str
    entry_side: Side
    trigger_price: Decimal | str
    maximum_loss: Decimal | str
    policy_version: str
    limit_price: Decimal | str | None = None
    reduce_only: bool = True
    schema_version: str = field(default=PROTECTIVE_EXIT_SCHEMA_VERSION, init=False)
    exit_side: Side = field(init=False)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ProductContextError("protective exit requires a symbol")
        if type(self.entry_side) is not Side:
            raise ProductContextError("protective exit entry_side must be a Side")
        if not self.policy_version:
            raise ProductContextError("protective exit requires a policy version")
        if self.reduce_only is not True:
            raise ProductContextError("protective exits must be reduce-only")
        for name in ("trigger_price", "maximum_loss"):
            _decimal_field(self, name)
            _require_positive(self, name)
        _optional_decimal_field(self, "limit_price")
        if self.limit_price is not None:
            _require_positive(self, "limit_price")
        exit_side = Side.SELL if self.entry_side is Side.BUY else Side.BUY
        object.__setattr__(self, "exit_side", exit_side)
        if self.limit_price is not None:
            unsafe = (
                self.entry_side is Side.BUY and self.limit_price > self.trigger_price
            ) or (
                self.entry_side is Side.SELL and self.limit_price < self.trigger_price
            )
            if unsafe:
                raise ProductContextError("protective exit limit is on the unsafe side of trigger")

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "entry_side": self.entry_side.value,
            "exit_side": self.exit_side.value,
            "limit_price": None if self.limit_price is None else decimal_to_canonical(self.limit_price),
            "maximum_loss": decimal_to_canonical(self.maximum_loss),
            "policy_version": self.policy_version,
            "reduce_only": self.reduce_only,
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "trigger_price": decimal_to_canonical(self.trigger_price),
        }

    @property
    def canonical_payload(self) -> str:
        return _canonical_json(self.to_canonical_dict())

    @property
    def digest(self) -> str:
        return sha256(self.canonical_payload.encode("utf-8")).hexdigest()

    @classmethod
    def from_canonical_payload(cls, payload: str) -> ProtectiveExitPlan:
        data = _load_unique_json(payload)
        _require_exact_fields(
            data,
            frozenset(
                {
                    "entry_side", "exit_side", "limit_price", "maximum_loss", "policy_version",
                    "reduce_only", "schema_version", "symbol", "trigger_price",
                }
            ),
        )
        if data["schema_version"] != PROTECTIVE_EXIT_SCHEMA_VERSION:
            raise CanonicalInputError("unsupported protective-exit schema version")
        try:
            plan = cls(
                symbol=_require_string(data["symbol"], "symbol"),
                entry_side=Side(_require_string(data["entry_side"], "entry_side")),
                trigger_price=_canonical_decimal_text(data["trigger_price"]),
                limit_price=(
                    None if data["limit_price"] is None else _canonical_decimal_text(data["limit_price"])
                ),
                maximum_loss=_canonical_decimal_text(data["maximum_loss"]),
                reduce_only=data["reduce_only"],
                policy_version=_require_string(data["policy_version"], "policy_version"),
            )
        except (TypeError, ValueError) as exc:
            raise CanonicalInputError("invalid protective-exit payload") from exc
        if data["exit_side"] != plan.exit_side.value or plan.canonical_payload != payload:
            raise CanonicalInputError("protective-exit payload is not canonical")
        return plan


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CanonicalInputError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class SpotOrderContext:
    """Spot order context, deliberately without leverage or borrowing fields."""

    product: ProductType = ProductType.SPOT

    def __post_init__(self) -> None:
        if self.product is not ProductType.SPOT:
            raise ProductContextError("spot context must use the spot product")


@dataclass(frozen=True)
class IsolatedMarginOrderContext:
    """Isolated-margin context with explicit pair, borrowing, and repayment policy."""

    isolated_symbol: str
    borrow_asset: str | None = None
    auto_repay: bool = False
    product: ProductType = ProductType.ISOLATED_MARGIN

    def __post_init__(self) -> None:
        if self.product is not ProductType.ISOLATED_MARGIN:
            raise ProductContextError("isolated margin context must use its product")
        if not self.isolated_symbol:
            raise ProductContextError("isolated_symbol is required")
        if self.borrow_asset is not None and not self.borrow_asset:
            raise ProductContextError("borrow_asset cannot be empty")
        if self.auto_repay and not self.borrow_asset:
            raise ProductContextError("auto_repay requires an explicit borrow_asset")


@dataclass(frozen=True)
class UsdtPerpetualOrderContext:
    """USDT perpetual context restricted to isolated, one-way, bounded exposure."""

    leverage: Decimal | str
    margin_mode: str
    position_mode: str
    symbol: str | None = None
    protective_exit: ProtectiveExitPlan | None = None
    reduce_only: bool = False
    product: ProductType = ProductType.USDT_PERPETUAL

    def __post_init__(self) -> None:
        if self.product is not ProductType.USDT_PERPETUAL:
            raise ProductContextError("USDT perpetual context must use its product")
        if self.symbol is not None and not self.symbol:
            raise ProductContextError("USDT perpetual context symbol cannot be empty")
        _decimal_field(self, "leverage")
        _require_positive(self, "leverage")
        if self.margin_mode != "isolated":
            raise ProductContextError("USDT perpetual commands require isolated margin mode")
        if self.position_mode != "one_way":
            raise ProductContextError("USDT perpetual commands require one-way position mode")
        if type(self.reduce_only) is not bool:
            raise ProductContextError("reduce_only must be a bool")
        if self.protective_exit is not None and type(self.protective_exit) is not ProtectiveExitPlan:
            raise ProductContextError("perpetual context requires a canonical protective exit")
        if self.protective_exit is not None and self.protective_exit.symbol != self.symbol:
            raise ProductContextError("protective exit symbol must match perpetual context")


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


def product_context_to_canonical_dict(context: ProductContext) -> dict[str, object]:
    """Return the sole product-contract representation used for binding and storage."""
    _require_product_context(context)
    if type(context) is SpotOrderContext:
        return {"product": ProductType.SPOT.value, "schema_version": PRODUCT_CONTEXT_SCHEMA_VERSION}
    if type(context) is IsolatedMarginOrderContext:
        return {
            "auto_repay": context.auto_repay,
            "borrow_asset": context.borrow_asset,
            "isolated_symbol": context.isolated_symbol,
            "product": ProductType.ISOLATED_MARGIN.value,
            "schema_version": PRODUCT_CONTEXT_SCHEMA_VERSION,
        }
    if context.symbol is None:
        raise CanonicalInputError("perpetual product context requires a bound symbol")
    return {
        "leverage": decimal_to_canonical(context.leverage),
        "margin_mode": context.margin_mode,
        "position_mode": context.position_mode,
        "product": ProductType.USDT_PERPETUAL.value,
        "protective_exit": None if context.protective_exit is None else context.protective_exit.to_canonical_dict(),
        "reduce_only": context.reduce_only,
        "schema_version": PRODUCT_CONTEXT_SCHEMA_VERSION,
        "symbol": context.symbol,
    }


def product_context_to_canonical_payload(context: ProductContext) -> str:
    return _canonical_json(product_context_to_canonical_dict(context))


def product_context_digest(context: ProductContext) -> str:
    return sha256(product_context_to_canonical_payload(context).encode("utf-8")).hexdigest()


def product_context_from_canonical_payload(payload: str) -> ProductContext:
    """Rebuild a product context only from strict versioned durable JSON."""
    data = _load_unique_json(payload)
    if data.get("schema_version") != PRODUCT_CONTEXT_SCHEMA_VERSION:
        raise CanonicalInputError("unsupported product-context schema version")
    try:
        product = ProductType(_require_string(data.get("product"), "product"))
    except ValueError as exc:
        raise CanonicalInputError("unsupported product context") from exc
    if product is ProductType.SPOT:
        _require_exact_fields(data, frozenset({"product", "schema_version"}))
        context: ProductContext = SpotOrderContext()
    elif product is ProductType.ISOLATED_MARGIN:
        _require_exact_fields(
            data, frozenset({"auto_repay", "borrow_asset", "isolated_symbol", "product", "schema_version"})
        )
        if data["borrow_asset"] is not None and not isinstance(data["borrow_asset"], str):
            raise CanonicalInputError("borrow_asset must be text or null")
        context = IsolatedMarginOrderContext(
            isolated_symbol=_require_string(data["isolated_symbol"], "isolated_symbol"),
            borrow_asset=data["borrow_asset"],
            auto_repay=data["auto_repay"],
        )
    else:
        _require_exact_fields(
            data,
            frozenset(
                {
                    "leverage", "margin_mode", "position_mode", "product", "protective_exit",
                    "reduce_only", "schema_version", "symbol",
                }
            ),
        )
        exit_data = data["protective_exit"]
        exit_plan = None if exit_data is None else ProtectiveExitPlan.from_canonical_payload(_canonical_json(exit_data))
        context = UsdtPerpetualOrderContext(
            symbol=_require_string(data["symbol"], "symbol"),
            leverage=_canonical_decimal_text(data["leverage"]),
            margin_mode=_require_string(data["margin_mode"], "margin_mode"),
            position_mode=_require_string(data["position_mode"], "position_mode"),
            protective_exit=exit_plan,
            reduce_only=data["reduce_only"],
        )
    if product_context_to_canonical_payload(context) != payload:
        raise CanonicalInputError("product-context payload is not canonical")
    return context
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
        if type(self.context) is IsolatedMarginOrderContext and self.context.isolated_symbol != self.symbol:
            raise ProductContextError("isolated margin context symbol must match command symbol")
        if type(self.context) is UsdtPerpetualOrderContext:
            if self.context.symbol != self.symbol:
                raise ProductContextError("perpetual context symbol must match command symbol")
            if not self.context.reduce_only:
                if self.context.protective_exit is None:
                    raise ProductContextError("perpetual exposure-increasing commands require a protective exit")
                if self.context.protective_exit.entry_side is not self.side:
                    raise ProductContextError("protective exit entry side must match command side")
        _decimal_field(self, "quantity")
        _require_positive(self, "quantity")
        _optional_decimal_field(self, "price")
        if self.order_type is OrderType.LIMIT and self.price is None:
            raise ValueError("limit orders require a price")
        if self.order_type is OrderType.MARKET and self.price is not None:
            raise ValueError("market orders cannot include a price")

    def to_canonical_dict(self) -> dict[str, Any]:
        """Serialize with the strict context contract used by durable reconstruction."""
        serialized = canonicalize(self)
        serialized["context"] = json.loads(product_context_to_canonical_payload(self.context))
        return serialized


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
