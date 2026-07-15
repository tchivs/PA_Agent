"""Symbol-scoped Decimal accounting for deterministic Paper USDT perpetuals."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Mapping

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.models import (
    ExecutionCommand,
    ProductType,
    Side,
    UsdtPerpetualOrderContext,
    decimal_from_canonical,
    decimal_to_canonical,
)
from pa_agent.trading.domain.paper import (
    MarketObservation,
    PaperEconomicPolicy,
    PaperFillCandidate,
    PaperLiquidationCandidate,
)
from pa_agent.trading.domain.risk import UsdtPerpetualProductEvidence

_PERPETUAL_SNAPSHOT_SCHEMA = "paper-usdt-perpetual-snapshot-v1"


@dataclass(frozen=True)
class PaperPerpetualAccounting:
    """One isolated, one-way position whose values are updated only by observations."""

    symbol: str
    available_usdt: Decimal
    quantity: Decimal
    entry_price: Decimal
    isolated_margin: Decimal
    unrealized_pnl: Decimal
    funding_total: Decimal
    maintenance_margin: Decimal
    observation_version: int
    position_command_id: str | None = None
    liquidated: bool = False

    def __post_init__(self) -> None:
        if not self.symbol or type(self.observation_version) is not int or self.observation_version < 0:
            raise ValueError("perpetual accounting requires a symbol and non-negative observation version")
        if type(self.liquidated) is not bool:
            raise ValueError("perpetual liquidation state must be boolean")
        for name in (
            "available_usdt",
            "quantity",
            "entry_price",
            "isolated_margin",
            "unrealized_pnl",
            "funding_total",
            "maintenance_margin",
        ):
            object.__setattr__(self, name, decimal_from_canonical(getattr(self, name)))
        if self.available_usdt < 0 or self.isolated_margin < 0 or self.maintenance_margin < 0:
            raise ValueError("perpetual available and isolated margin balances cannot be negative")
        if self.quantity == 0:
            if self.entry_price != 0 or self.isolated_margin != 0 or self.position_command_id is not None:
                raise ValueError("closed perpetual positions cannot retain entry exposure")
        elif self.entry_price <= 0 or not self.position_command_id:
            raise ValueError("open perpetual positions require an entry price and originating command")

    @classmethod
    def from_initial_state(
        cls, *, symbol: str, available_usdt: Decimal | str, observation_version: int = 0
    ) -> PaperPerpetualAccounting:
        """Seed a symbol-owned account without an implicit position or clock."""
        return cls(
            symbol=symbol,
            available_usdt=decimal_from_canonical(available_usdt),
            quantity=Decimal("0"),
            entry_price=Decimal("0"),
            isolated_margin=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            funding_total=Decimal("0"),
            maintenance_margin=Decimal("0"),
            observation_version=observation_version,
        )

    @property
    def is_open(self) -> bool:
        return self.quantity != 0

    def validate_open(
        self, command: ExecutionCommand, *, policy: PaperEconomicPolicy, observation: MarketObservation
    ) -> None:
        """Fail closed before a paper order exists for unsafe perpetual context or balance."""
        if self.liquidated:
            raise ValueError("liquidated perpetual positions cannot be reopened")
        self._assert_command(command, policy=policy, observation=observation)
        context = command.context
        assert type(context) is UsdtPerpetualOrderContext
        if context.leverage > policy.maximum_leverage:
            raise ValueError("perpetual leverage exceeds the immutable product policy")
        if context.reduce_only:
            if not self.is_open or command.side is self._position_side or command.quantity > abs(self.quantity):
                raise ValueError("reduce-only command cannot increase or reverse perpetual exposure")
            assert context.protective_exit is not None
            if (
                context.protective_exit.symbol != self.symbol
                or context.protective_exit.exit_side is not command.side
                or context.protective_exit.entry_side is not self._position_side
            ):
                raise ValueError("reduce-only command protective exit does not match the open position")
            return
        if context.protective_exit is None or context.protective_exit.entry_side is not command.side:
            raise ValueError("perpetual entry requires a matching protective exit")
        reference = observation.asks[0].price if command.side is Side.BUY else observation.bids[0].price
        required = command.quantity * reference / context.leverage
        fee = command.quantity * reference * policy.fee_rate
        if self.available_usdt < required + fee:
            raise ValueError("perpetual available USDT cannot lock initial margin and fee")

    def settle(
        self, command: ExecutionCommand, candidates: tuple[PaperFillCandidate, ...], *, policy: PaperEconomicPolicy
    ) -> PaperPerpetualAccounting:
        """Net exact matched fills into one signed position without a hedge or shared margin pool."""
        if not candidates:
            return self
        result = self
        for candidate in candidates:
            if candidate.command_id != command.command_id:
                raise ValueError("perpetual fill belongs to another command")
            result = result._apply_fill(command, candidate, policy)
        return result

    def observe(
        self, observation: MarketObservation, *, policy: PaperEconomicPolicy) -> PaperPerpetualAccounting:
        """Apply one newer explicit mark and signed funding charge, never local elapsed time."""
        if observation.symbol != self.symbol or observation.mark_price is None:
            raise ValueError("perpetual observation requires an explicit matching mark price")
        if observation.version <= self.observation_version:
            raise ValueError("perpetual accounting requires a newer observation version")
        mark = observation.mark_price
        funding_charge = self.quantity * mark * observation.funding_rate
        available = self.available_usdt - funding_charge
        margin = self.isolated_margin
        if available < 0:
            margin = max(Decimal("0"), margin + available)
            available = Decimal("0")
        unrealized = (mark - self.entry_price) * self.quantity if self.is_open else Decimal("0")
        maintenance = abs(self.quantity) * mark * policy.maintenance_margin_rate
        return replace(
            self,
            available_usdt=available,
            isolated_margin=margin,
            unrealized_pnl=unrealized,
            funding_total=self.funding_total + funding_charge,
            maintenance_margin=maintenance,
            observation_version=observation.version,
        )

    def liquidation_candidate(
        self, observation: MarketObservation, *, policy: PaperEconomicPolicy
    ) -> PaperLiquidationCandidate | None:
        """Return an immutable forced-close fill exactly when isolated equity breaches maintenance."""
        if not self.is_open or self.isolated_margin + self.unrealized_pnl >= self.maintenance_margin:
            return None
        assert observation.mark_price is not None and self.position_command_id is not None
        close_price = observation.mark_price * (
            Decimal("1") - policy.liquidation_price_adjustment
            if self.quantity > 0
            else Decimal("1") + policy.liquidation_price_adjustment
        )
        fee = abs(self.quantity) * close_price * policy.liquidation_fee_rate
        fill_id = sha256(
            "|".join(
                (
                    self.position_command_id,
                    observation.observation_id,
                    str(observation.version),
                    decimal_to_canonical(close_price),
                    decimal_to_canonical(fee),
                    policy.liquidation_rule_version,
                )
            ).encode("utf-8")
        ).hexdigest()
        return PaperLiquidationCandidate(
            paper_fill_id=f"paper-liquidation:{fill_id}",
            account_id=observation.account_id,
            symbol=self.symbol,
            origin_command_id=self.position_command_id,
            quantity=abs(self.quantity),
            provenance={
                "observation_id": observation.observation_id,
                "observation_version": observation.version,
                "mark_price": decimal_to_canonical(observation.mark_price),
                "liquidation_price_adjustment": decimal_to_canonical(policy.liquidation_price_adjustment),
                "final_execution_price": decimal_to_canonical(close_price),
                "liquidation_fee_rate": decimal_to_canonical(policy.liquidation_fee_rate),
                "fee": decimal_to_canonical(fee),
                "rule_version": policy.liquidation_rule_version,
                "fee_rule_version": policy.liquidation_fee_rule_version,
                "product_policy_version": policy.policy_version,
            },
        )

    def liquidate(self, candidate: PaperLiquidationCandidate) -> PaperPerpetualAccounting:
        """Resolve margin, realized loss, and fee into a terminal zero-exposure account state."""
        if candidate.origin_command_id != self.position_command_id or candidate.quantity != abs(self.quantity):
            raise ValueError("liquidation candidate does not match the open perpetual position")
        close_price = _provenance_decimal(candidate.provenance, "final_execution_price")
        fee = _provenance_decimal(candidate.provenance, "fee")
        realized = (close_price - self.entry_price) * self.quantity
        available = max(Decimal("0"), self.available_usdt + self.isolated_margin + realized - fee)
        return replace(
            self,
            available_usdt=available,
            quantity=Decimal("0"),
            entry_price=Decimal("0"),
            isolated_margin=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            maintenance_margin=Decimal("0"),
            position_command_id=None,
            liquidated=True,
        )

    def to_snapshot_payload(self) -> dict[str, object]:
        """Serialize complete, independent symbol truth using canonical Decimal text only."""
        return {
            "symbol": self.symbol,
            "available_usdt": decimal_to_canonical(self.available_usdt),
            "quantity": decimal_to_canonical(self.quantity),
            "entry_price": decimal_to_canonical(self.entry_price),
            "isolated_margin": decimal_to_canonical(self.isolated_margin),
            "unrealized_pnl": decimal_to_canonical(self.unrealized_pnl),
            "funding_total": decimal_to_canonical(self.funding_total),
            "maintenance_margin": decimal_to_canonical(self.maintenance_margin),
            "observation_version": self.observation_version,
            "position_command_id": self.position_command_id,
            "liquidated": self.liquidated,
        }

    @classmethod
    def from_snapshot_payload(cls, payload: Mapping[str, object]) -> PaperPerpetualAccounting:
        """Rebuild only complete canonical perpetual state from durable Paper truth."""
        expected = {
            "symbol", "available_usdt", "quantity", "entry_price", "isolated_margin", "unrealized_pnl",
            "funding_total", "maintenance_margin", "observation_version", "position_command_id", "liquidated",
        }
        if set(payload) != expected:
            raise ValueError("paper perpetual snapshot fields are invalid")
        if (
            type(payload["symbol"]) is not str
            or type(payload["observation_version"]) is not int
            or type(payload["liquidated"]) is not bool
        ):
            raise ValueError("paper perpetual snapshot scalar fields are invalid")
        origin = payload["position_command_id"]
        if origin is not None and type(origin) is not str:
            raise ValueError("paper perpetual origin command is invalid")
        return cls(
            symbol=payload["symbol"],
            available_usdt=_snapshot_decimal(payload["available_usdt"]),
            quantity=_snapshot_decimal(payload["quantity"]),
            entry_price=_snapshot_decimal(payload["entry_price"]),
            isolated_margin=_snapshot_decimal(payload["isolated_margin"]),
            unrealized_pnl=_snapshot_decimal(payload["unrealized_pnl"]),
            funding_total=_snapshot_decimal(payload["funding_total"]),
            maintenance_margin=_snapshot_decimal(payload["maintenance_margin"]),
            observation_version=payload["observation_version"],
            position_command_id=origin,
            liquidated=payload["liquidated"],
        )

    def to_evidence(
        self, *, target: ExecutionTarget, observed_at: datetime, mark_price: Decimal, policy: PaperEconomicPolicy
    ) -> UsdtPerpetualProductEvidence:
        """Expose only durable exact-symbol perpetual truth through the typed gateway port."""
        return UsdtPerpetualProductEvidence(
            target=target,
            symbol=self.symbol,
            isolated_margin_confirmed=True,
            one_way_position_confirmed=True,
            maximum_leverage=policy.maximum_leverage,
            available_margin=self.available_usdt,
            initial_margin=self.isolated_margin,
            maintenance_margin=self.maintenance_margin,
            mark_price=mark_price,
            position_quantity=self.quantity,
            observed_at=observed_at,
            observation_version=max(1, self.observation_version),
        )

    @property
    def _position_side(self) -> Side:
        if not self.is_open:
            raise ValueError("closed perpetual position has no side")
        return Side.BUY if self.quantity > 0 else Side.SELL

    def _assert_command(self, command: ExecutionCommand, *, policy: PaperEconomicPolicy, observation: MarketObservation) -> None:
        if type(command) is not ExecutionCommand or type(command.context) is not UsdtPerpetualOrderContext:
            raise ValueError("perpetual accounting accepts only canonical USDT perpetual commands")
        context = command.context
        if (
            policy.product is not ProductType.USDT_PERPETUAL
            or command.symbol != self.symbol
            or context.symbol != self.symbol
            or context.margin_mode != "isolated"
            or context.position_mode != "one_way"
            or observation.scope != (command.account_id, ProductType.USDT_PERPETUAL, self.symbol)
            or observation.mark_price is None
        ):
            raise ValueError("perpetual command context or observation scope is unsafe")

    def _apply_fill(
        self, command: ExecutionCommand, candidate: PaperFillCandidate, policy: PaperEconomicPolicy
    ) -> PaperPerpetualAccounting:
        context = command.context
        assert type(context) is UsdtPerpetualOrderContext
        delta = candidate.quantity if command.side is Side.BUY else -candidate.quantity
        price = candidate.provenance.final_execution_price
        fee_per_unit = candidate.provenance.fee / candidate.quantity
        result = self
        current = result.quantity
        if current and current * delta < 0:
            closing = min(abs(current), abs(delta))
            closing_fee = fee_per_unit * closing
            released = result.isolated_margin * closing / abs(current)
            realized = (price - result.entry_price) * closing * (Decimal("1") if current > 0 else Decimal("-1"))
            remaining = current + (closing if current < 0 else -closing)
            next_margin = result.isolated_margin - released
            next_available = max(Decimal("0"), result.available_usdt + released + realized - closing_fee)
            delta = delta + (closing if delta < 0 else -closing)
            result = replace(
                result,
                available_usdt=next_available,
                quantity=remaining,
                entry_price=Decimal("0") if remaining == 0 else result.entry_price,
                isolated_margin=Decimal("0") if remaining == 0 else next_margin,
                position_command_id=None if remaining == 0 else result.position_command_id,
            )
        if delta:
            opening = abs(delta)
            required = opening * price / context.leverage
            opening_fee = fee_per_unit * opening
            if result.available_usdt < required + opening_fee:
                raise ValueError("perpetual fill would leave negative available USDT")
            same_side = result.quantity and result.quantity * delta > 0
            entry = (
                (abs(result.quantity) * result.entry_price + opening * price) / (abs(result.quantity) + opening)
                if same_side
                else price
            )
            result = replace(
                result,
                available_usdt=result.available_usdt - required - opening_fee,
                quantity=result.quantity + delta,
                entry_price=entry,
                isolated_margin=result.isolated_margin + required,
                position_command_id=result.position_command_id or command.command_id,
            )
        return result


def _snapshot_decimal(value: object) -> Decimal:
    if type(value) is not str:
        raise ValueError("paper perpetual snapshot Decimal fields must be canonical text")
    parsed = decimal_from_canonical(value)
    if decimal_to_canonical(parsed) != value:
        raise ValueError("paper perpetual snapshot Decimal fields are noncanonical")
    return parsed


def _provenance_decimal(provenance: Mapping[str, object], name: str) -> Decimal:
    value = provenance.get(name)
    if type(value) is not str:
        raise ValueError("paper perpetual liquidation provenance is malformed")
    return _snapshot_decimal(value)
