"""Frozen, target-bound policy and evidence values for pure risk evaluation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from pa_agent.trading.domain.approval import CandidateExecutionIntent, ExecutionTarget
from pa_agent.trading.domain.errors import RiskRejection, RiskRejectionReason
from pa_agent.trading.domain.models import (
    AccountObservation,
    GatewayCapabilities,
    InstrumentRules,
    IsolatedMarginOrderContext,
    Mode,
    OrderType,
    ProductType,
    QuoteObservation,
    SpotOrderContext,
    TimeObservation,
    UsdtPerpetualOrderContext,
    canonicalize,
    decimal_from_canonical,
)


def _digest(value: object) -> str:
    encoded = json.dumps(
        canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _decimal(instance: object, name: str) -> None:
    object.__setattr__(instance, name, decimal_from_canonical(getattr(instance, name)))


@dataclass(frozen=True)
class IsolatedMarginPolicyLimits:
    """Immutable isolated-pair limits; leverage cannot be reused by another product."""

    isolated_symbol: str
    borrow_asset: str
    auto_repay_required: bool
    maximum_leverage: Decimal | str
    minimum_margin_health: Decimal | str

    def __post_init__(self) -> None:
        for name in ("maximum_leverage", "minimum_margin_health"):
            _decimal(self, name)
        if (
            not self.isolated_symbol
            or not self.borrow_asset
            or self.auto_repay_required is not True
            or self.maximum_leverage != Decimal("3")
            or self.minimum_margin_health != Decimal("1.25")
        ):
            raise ValueError("isolated margin policy values are fixed")


@dataclass(frozen=True)
class UsdtPerpetualPolicyLimits:
    """Immutable isolated one-way perpetual limits, including protective-exit bounds."""

    symbol: str
    maximum_leverage: Decimal | str
    minimum_maintenance_margin_ratio: Decimal | str
    maximum_protective_exit_loss: Decimal | str

    def __post_init__(self) -> None:
        for name in (
            "maximum_leverage",
            "minimum_maintenance_margin_ratio",
            "maximum_protective_exit_loss",
        ):
            _decimal(self, name)
        if (
            not self.symbol
            or self.maximum_leverage != Decimal("3")
            or self.minimum_maintenance_margin_ratio != Decimal("0.05")
            or self.maximum_protective_exit_loss != Decimal("100")
        ):
            raise ValueError("USDT perpetual policy values are fixed")


ProductPolicyLimits = IsolatedMarginPolicyLimits | UsdtPerpetualPolicyLimits | None


@dataclass(frozen=True)
class RiskPolicy:
    """Immutable Paper policy whose target and optional product limits are exact."""

    policy_id: str
    policy_version: str
    target_id: str
    mode: Mode
    account_id: str
    product: ProductType
    symbols: frozenset[str]
    order_types: frozenset[OrderType]
    maximum_order_notional: Decimal | str
    maximum_total_exposure: Decimal | str
    maximum_price_deviation: Decimal | str
    maximum_bid_ask_slippage: Decimal | str
    maximum_open_orders: int
    maximum_accepted_orders: int
    order_rate_window_seconds: int
    maximum_utc_day_realized_loss: Decimal | str
    maximum_utc_day_drawdown: Decimal | str
    product_limits: ProductPolicyLimits = None
    evidence_max_age_seconds: int = 60
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "maximum_order_notional",
            "maximum_total_exposure",
            "maximum_price_deviation",
            "maximum_bid_ask_slippage",
            "maximum_utc_day_realized_loss",
            "maximum_utc_day_drawdown",
        ):
            _decimal(self, name)
        if not self.policy_id or not self.target_id or not self.account_id or not self.symbols:
            raise ValueError("Paper policy requires stable identity and scope")
        if self.mode is not Mode.PAPER or self.order_types != frozenset({OrderType.MARKET, OrderType.LIMIT}):
            raise ValueError("Paper policy scope is fixed")
        if (
            self.maximum_order_notional != Decimal("1000")
            or self.maximum_total_exposure != Decimal("1000")
            or self.maximum_price_deviation != Decimal("80")
            or self.maximum_bid_ask_slippage != Decimal("4")
            or self.maximum_open_orders != 3
            or self.maximum_accepted_orders != 5
            or self.order_rate_window_seconds != 60
            or self.maximum_utc_day_realized_loss != Decimal("100")
            or self.maximum_utc_day_drawdown != Decimal("0.10")
            or self.evidence_max_age_seconds != 60
        ):
            raise ValueError("Paper policy values are fixed and cannot be overridden")
        if self.policy_version == "phase2-v1":
            if (
                self.policy_id != "phase2-paper-spot-legacy"
                or self.product is not ProductType.SPOT
                or self.target_id != "paper-spot-primary"
                or self.product_limits is not None
            ):
                raise ValueError("legacy policy scope is fixed")
        elif self.policy_id == "paper-spot-primary":
            if self.policy_version != "paper-spot-v1" or self.product is not ProductType.SPOT or self.product_limits is not None:
                raise ValueError("Paper Spot policy scope is fixed")
        elif self.policy_id == "paper-margin-isolated-primary":
            if (
                self.policy_version != "paper-margin-isolated-v1"
                or self.product is not ProductType.ISOLATED_MARGIN
                or type(self.product_limits) is not IsolatedMarginPolicyLimits
            ):
                raise ValueError("Paper isolated-margin policy scope is fixed")
        elif self.policy_id == "paper-usdt-perpetual-primary":
            if (
                self.policy_version != "paper-usdt-perpetual-v1"
                or self.product is not ProductType.USDT_PERPETUAL
                or type(self.product_limits) is not UsdtPerpetualPolicyLimits
            ):
                raise ValueError("Paper perpetual policy scope is fixed")
        else:
            raise ValueError("unknown immutable Paper policy")
        object.__setattr__(self, "policy_digest", _digest(self._digest_material()))

    def _digest_material(self) -> dict[str, object]:
        material = {
            "policy_version": self.policy_version,
            "target_id": self.target_id,
            "mode": self.mode,
            "account_id": self.account_id,
            "product": self.product,
            "symbols": tuple(sorted(self.symbols)),
            "order_types": tuple(sorted(self.order_types)),
            "maximum_order_notional": self.maximum_order_notional,
            "maximum_total_exposure": self.maximum_total_exposure,
            "maximum_price_deviation": self.maximum_price_deviation,
            "maximum_bid_ask_slippage": self.maximum_bid_ask_slippage,
            "maximum_open_orders": self.maximum_open_orders,
            "maximum_accepted_orders": self.maximum_accepted_orders,
            "order_rate_window_seconds": self.order_rate_window_seconds,
            "maximum_utc_day_realized_loss": self.maximum_utc_day_realized_loss,
            "maximum_utc_day_drawdown": self.maximum_utc_day_drawdown,
            "evidence_max_age_seconds": self.evidence_max_age_seconds,
        }
        if self.policy_version != "phase2-v1":
            material["policy_id"] = self.policy_id
            material["product_limits"] = self.product_limits
        return material

    def require_matches(
        self, candidate: CandidateExecutionIntent, selected_target: ExecutionTarget
    ) -> None:
        if candidate.target != selected_target:
            raise RiskRejection(RiskRejectionReason.TARGET_MISMATCH)
        if (
            selected_target.target_id != self.target_id
            or selected_target.mode is not self.mode
            or selected_target.account_id != self.account_id
        ):
            raise RiskRejection(RiskRejectionReason.UNSUPPORTED_TARGET)
        if selected_target.product is not self.product:
            raise RiskRejection(RiskRejectionReason.PRODUCT_NOT_ALLOWED)
        if candidate.symbol not in self.symbols:
            raise RiskRejection(RiskRejectionReason.SYMBOL_NOT_ALLOWED)
        if candidate.order_type not in self.order_types:
            raise RiskRejection(RiskRejectionReason.ORDER_TYPE_NOT_ALLOWED)
        if self.policy_version == "phase2-v1":
            if type(candidate.context) is not SpotOrderContext:
                raise RiskRejection(RiskRejectionReason.UNSUPPORTED_TARGET)
            return
        try:
            selected = select_paper_product_policy(candidate.target, candidate.context)
        except RiskRejection:
            raise
        if selected.policy_id != self.policy_id or selected.policy_digest != self.policy_digest:
            raise RiskRejection(RiskRejectionReason.UNSUPPORTED_TARGET)


def _base_policy(*, policy_id: str, policy_version: str, target_id: str, product: ProductType, product_limits: ProductPolicyLimits = None) -> RiskPolicy:
    return RiskPolicy(
        policy_id=policy_id,
        policy_version=policy_version,
        target_id=target_id,
        mode=Mode.PAPER,
        account_id="paper-account",
        product=product,
        symbols=frozenset({"BTCUSDT"}),
        order_types=frozenset({OrderType.MARKET, OrderType.LIMIT}),
        maximum_order_notional=Decimal("1000"),
        maximum_total_exposure=Decimal("1000"),
        maximum_price_deviation=Decimal("80"),
        maximum_bid_ask_slippage=Decimal("4"),
        maximum_open_orders=3,
        maximum_accepted_orders=5,
        order_rate_window_seconds=60,
        maximum_utc_day_realized_loss=Decimal("100"),
        maximum_utc_day_drawdown=Decimal("0.10"),
        product_limits=product_limits,
    )


PAPER_PRODUCT_POLICIES = (
    _base_policy(
        policy_id="paper-spot-primary",
        policy_version="paper-spot-v1",
        target_id="paper-spot-primary",
        product=ProductType.SPOT,
    ),
    _base_policy(
        policy_id="paper-margin-isolated-primary",
        policy_version="paper-margin-isolated-v1",
        target_id="paper-margin-isolated-primary",
        product=ProductType.ISOLATED_MARGIN,
        product_limits=IsolatedMarginPolicyLimits("BTCUSDT", "USDT", True, Decimal("3"), Decimal("1.25")),
    ),
    _base_policy(
        policy_id="paper-usdt-perpetual-primary",
        policy_version="paper-usdt-perpetual-v1",
        target_id="paper-usdt-perpetual-primary",
        product=ProductType.USDT_PERPETUAL,
        product_limits=UsdtPerpetualPolicyLimits("BTCUSDT", Decimal("3"), Decimal("0.05"), Decimal("100")),
    ),
)


def select_paper_product_policy(target: ExecutionTarget, context: object) -> RiskPolicy:
    """Return only the immutable Paper policy matching exact target and context facts."""
    if type(target) is not ExecutionTarget:
        raise RiskRejection(RiskRejectionReason.UNSUPPORTED_TARGET)
    policy = next((item for item in PAPER_PRODUCT_POLICIES if item.target_id == target.target_id), None)
    if (
        policy is None
        or target.mode is not Mode.PAPER
        or target.account_id != policy.account_id
        or target.product is not policy.product
    ):
        raise RiskRejection(RiskRejectionReason.UNSUPPORTED_TARGET)
    if type(context) is SpotOrderContext:
        context_valid = policy.product is ProductType.SPOT
    elif type(context) is IsolatedMarginOrderContext:
        limits = policy.product_limits
        context_valid = (
            type(limits) is IsolatedMarginPolicyLimits
            and context.isolated_symbol == limits.isolated_symbol
            and context.borrow_asset == limits.borrow_asset
            and context.auto_repay is limits.auto_repay_required
        )
    elif type(context) is UsdtPerpetualOrderContext:
        limits = policy.product_limits
        context_valid = (
            type(limits) is UsdtPerpetualPolicyLimits
            and context.symbol == limits.symbol
            and context.margin_mode == "isolated"
            and context.position_mode == "one_way"
            and context.leverage <= limits.maximum_leverage
            and context.protective_exit is not None
            and context.protective_exit.maximum_loss <= limits.maximum_protective_exit_loss
        )
    else:
        context_valid = False
    if not context_valid:
        raise RiskRejection(RiskRejectionReason.UNSUPPORTED_TARGET)
    return policy


def select_phase2_policy(target: ExecutionTarget) -> RiskPolicy:
    """Resolve only historical Phase 2 Paper Spot records under their old policy identity."""
    if (
        target.target_id != "paper-spot-primary"
        or target.mode is not Mode.PAPER
        or target.account_id != "paper-account"
        or target.product is not ProductType.SPOT
    ):
        raise RiskRejection(RiskRejectionReason.UNSUPPORTED_TARGET)
    return _base_policy(
        policy_id="phase2-paper-spot-legacy",
        policy_version="phase2-v1",
        target_id=target.target_id,
        product=target.product,
    )


@dataclass(frozen=True)
class OpenOrderObservation:
    target: ExecutionTarget
    count: int
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("open order count must be non-negative")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class OrderRateObservation:
    target: ExecutionTarget
    count: int
    window_started_at: datetime
    window_ends_at: datetime

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("order rate count must be non-negative")
        _require_aware(self.window_started_at, "window_started_at")
        _require_aware(self.window_ends_at, "window_ends_at")


@dataclass(frozen=True)
class LossDrawdownObservation:
    target: ExecutionTarget
    realized_loss: Decimal | str
    drawdown: Decimal | str
    utc_day_started_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        _decimal(self, "realized_loss")
        _decimal(self, "drawdown")
        if self.realized_loss < 0 or self.drawdown < 0:
            raise ValueError("loss and drawdown must be non-negative")
        _require_aware(self.utc_day_started_at, "utc_day_started_at")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class FeeRateObservation:
    target: ExecutionTarget
    symbol: str
    quote_identifier: str
    fee_currency: str
    rate: Decimal | str
    rate_version: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _decimal(self, "rate")
        if not all((self.symbol, self.quote_identifier, self.fee_currency, self.rate_version)):
            raise ValueError("fee evidence requires binding identifiers")
        if self.rate < 0:
            raise ValueError("fee rate must be non-negative")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class TargetConnectionObservation:
    """Fresh canonical connectivity evidence bound to the selected target."""

    target: ExecutionTarget
    connected: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        if type(self.connected) is not bool:
            raise ValueError("connected must be a bool")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class FeeEstimate:
    target: ExecutionTarget
    symbol: str
    quote_identifier: str
    expected_quote_price: Decimal
    fee_currency: str
    rate: Decimal
    rate_version: str
    amount: Decimal


def estimate_fee(quantity: Decimal | str, expected_quote_price: Decimal | str, fee_rate: FeeRateObservation) -> FeeEstimate:
    """Estimate fee from finite canonical inputs and evidence-bound quote/rate facts."""
    normalized_quantity = decimal_from_canonical(quantity)
    normalized_price = decimal_from_canonical(expected_quote_price)
    if normalized_quantity <= 0 or normalized_price <= 0:
        raise ValueError("fee estimate quantity and price must be positive")
    return FeeEstimate(
        target=fee_rate.target,
        symbol=fee_rate.symbol,
        quote_identifier=fee_rate.quote_identifier,
        expected_quote_price=normalized_price,
        fee_currency=fee_rate.fee_currency,
        rate=fee_rate.rate,
        rate_version=fee_rate.rate_version,
        amount=normalized_quantity * normalized_price * fee_rate.rate,
    )


@dataclass(frozen=True)
class EvidenceBundle:
    capabilities: GatewayCapabilities
    instrument_rules: InstrumentRules
    rule_observed_at: datetime
    account: AccountObservation
    quote: QuoteObservation
    server_time: TimeObservation
    connection: TargetConnectionObservation
    open_orders: OpenOrderObservation
    order_rate: OrderRateObservation
    loss_drawdown: LossDrawdownObservation
    fee_rate: FeeRateObservation
    evidence_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_aware(self.rule_observed_at, "rule_observed_at")
        object.__setattr__(
            self,
            "evidence_digest",
            _digest(
                {
                    "capabilities": self.capabilities,
                    "instrument_rules": self.instrument_rules,
                    "rule_observed_at": self.rule_observed_at,
                    "account": self.account,
                    "quote": self.quote,
                    "server_time": self.server_time,
                    "connection": self.connection,
                    "open_orders": self.open_orders,
                    "order_rate": self.order_rate,
                    "loss_drawdown": self.loss_drawdown,
                    "fee_rate": self.fee_rate,
                }
            ),
        )


@dataclass(frozen=True)
class RiskAssessment:
    accepted: bool
    reason_codes: tuple[RiskRejectionReason, ...]
    metrics: tuple[tuple[str, Decimal], ...]
    policy_version: str
    policy_digest: str
    evidence_digest: str
    fee_estimate: FeeEstimate | None
