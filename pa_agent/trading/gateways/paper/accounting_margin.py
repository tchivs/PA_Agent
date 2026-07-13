"""Pair-scoped Decimal accounting for deterministic Paper isolated margin."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.models import (
    ExecutionCommand,
    IsolatedMarginOrderContext,
    ProductType,
    Side,
    decimal_from_canonical,
    decimal_to_canonical,
)
from pa_agent.trading.domain.paper import MarketObservation, PaperEconomicPolicy, PaperFillCandidate
from pa_agent.trading.domain.risk import IsolatedMarginProductEvidence

_MARGIN_SNAPSHOT_SCHEMA = "paper-isolated-margin-snapshot-v1"
_NO_DEBT_HEALTH = Decimal("999999999999999999999999999")


@dataclass(frozen=True)
class PaperMarginAccounting:
    """One isolated pair's immutable collateral, credit, and repayment truth."""

    isolated_symbol: str
    borrow_asset: str
    collateral: Decimal
    available_collateral: Decimal
    debt_principal: Decimal
    accrued_interest: Decimal
    borrow_available: Decimal
    repayment_required: bool
    observation_version: int

    def __post_init__(self) -> None:
        if not self.isolated_symbol or not self.borrow_asset:
            raise ValueError("paper margin accounting requires an isolated pair and borrow asset")
        if type(self.repayment_required) is not bool:
            raise ValueError("paper margin repayment policy must be boolean")
        if type(self.observation_version) is not int or self.observation_version <= 0:
            raise ValueError("paper margin observation version must be positive")
        for field_name in (
            "collateral",
            "available_collateral",
            "debt_principal",
            "accrued_interest",
            "borrow_available",
        ):
            value = decimal_from_canonical(getattr(self, field_name))
            if value < 0:
                raise ValueError("paper margin values cannot be negative")
            object.__setattr__(self, field_name, value)
        if self.available_collateral > self.collateral:
            raise ValueError("paper margin available collateral cannot exceed collateral")

    @classmethod
    def from_initial_state(
        cls,
        *,
        isolated_symbol: str,
        collateral: Decimal | str,
        debt_principal: Decimal | str,
        accrued_interest: Decimal | str,
        borrow_available: Decimal | str,
        repayment_required: bool,
        observation_version: int,
        borrow_asset: str = "USDT",
        available_collateral: Decimal | str | None = None,
    ) -> PaperMarginAccounting:
        """Create a pair-owned truth record without any global account pool."""
        canonical_collateral = decimal_from_canonical(collateral)
        canonical_debt = decimal_from_canonical(debt_principal)
        canonical_interest = decimal_from_canonical(accrued_interest)
        available = (
            canonical_collateral - canonical_debt - canonical_interest
            if available_collateral is None
            else decimal_from_canonical(available_collateral)
        )
        return cls(
            isolated_symbol=isolated_symbol,
            borrow_asset=borrow_asset,
            collateral=canonical_collateral,
            available_collateral=available,
            debt_principal=canonical_debt,
            accrued_interest=canonical_interest,
            borrow_available=decimal_from_canonical(borrow_available),
            repayment_required=repayment_required,
            observation_version=observation_version,
        )

    @property
    def total_debt(self) -> Decimal:
        """Return the principal plus explicitly accrued interest for this pair only."""
        return self.debt_principal + self.accrued_interest

    @property
    def margin_health(self) -> Decimal:
        """Return finite pair health from collateral divided by this pair's debt only."""
        return _NO_DEBT_HEALTH if self.total_debt == 0 else self.collateral / self.total_debt

    def admits(self, *, notional: Decimal | str, minimum_health: Decimal | str) -> bool:
        """Check this pair's prospective credit facts without borrowing from another pair."""
        requested = _positive_decimal(notional, "margin order notional")
        threshold = _positive_decimal(minimum_health, "minimum margin health")
        prospective_debt = self.total_debt + requested
        prospective_health = self.collateral / prospective_debt
        return (
            self.available_collateral >= requested
            and self.borrow_available >= requested
            and prospective_health >= threshold
        )

    def accrue_interest(
        self, *, observation_version: int, interest_rate: Decimal | str
    ) -> PaperMarginAccounting:
        """Accrue one policy-versioned Decimal charge from a newer explicit observation."""
        if type(observation_version) is not int or observation_version <= self.observation_version:
            raise ValueError("paper margin interest requires a newer observation version")
        rate = decimal_from_canonical(interest_rate)
        if rate < 0:
            raise ValueError("paper margin interest rate cannot be negative")
        return replace(
            self,
            accrued_interest=self.accrued_interest + self.debt_principal * rate,
            observation_version=observation_version,
        )

    def repay(self, amount: Decimal | str) -> PaperMarginAccounting:
        """Apply an immutable repayment to interest first, then principal, on this pair only."""
        payment = _positive_decimal(amount, "margin repayment")
        interest_repaid = min(payment, self.accrued_interest)
        principal_repaid = min(payment - interest_repaid, self.debt_principal)
        surplus = payment - interest_repaid - principal_repaid
        return replace(
            self,
            accrued_interest=self.accrued_interest - interest_repaid,
            debt_principal=self.debt_principal - principal_repaid,
            collateral=self.collateral + surplus,
            available_collateral=self.available_collateral + surplus,
        )

    def settle(
        self, command: ExecutionCommand, candidates: tuple[PaperFillCandidate, ...]
    ) -> PaperMarginAccounting:
        """Apply matched fill debt and optional auto-repay without crossing pair state."""
        self._assert_command(command)
        result = self
        for candidate in candidates:
            if candidate.command_id != command.command_id:
                raise ValueError("paper margin fill belongs to another command")
            notional = candidate.quantity * candidate.provenance.final_execution_price
            if command.side is Side.BUY:
                result = replace(result, debt_principal=result.debt_principal + notional + candidate.provenance.fee)
            else:
                proceeds = notional - candidate.provenance.fee
                if proceeds < 0:
                    raise ValueError("paper margin sell fee exceeds proceeds")
                result = result.repay(proceeds) if command.context.auto_repay else replace(
                    result, available_collateral=result.available_collateral + proceeds
                )
        return result

    def to_snapshot_payload(self) -> dict[str, object]:
        """Serialize complete pair truth using canonical Decimal text only."""
        return {
            "isolated_symbol": self.isolated_symbol,
            "borrow_asset": self.borrow_asset,
            "collateral": decimal_to_canonical(self.collateral),
            "available_collateral": decimal_to_canonical(self.available_collateral),
            "debt_principal": decimal_to_canonical(self.debt_principal),
            "accrued_interest": decimal_to_canonical(self.accrued_interest),
            "borrow_available": decimal_to_canonical(self.borrow_available),
            "repayment_required": self.repayment_required,
            "observation_version": self.observation_version,
        }

    @classmethod
    def from_snapshot_payload(cls, payload: Mapping[str, object]) -> PaperMarginAccounting:
        """Reconstruct only one complete canonical pair snapshot from PaperStore truth."""
        expected = {
            "isolated_symbol",
            "borrow_asset",
            "collateral",
            "available_collateral",
            "debt_principal",
            "accrued_interest",
            "borrow_available",
            "repayment_required",
            "observation_version",
        }
        if set(payload) != expected:
            raise ValueError("paper margin snapshot fields are invalid")
        symbol = payload["isolated_symbol"]
        borrow_asset = payload["borrow_asset"]
        repayment_required = payload["repayment_required"]
        observation_version = payload["observation_version"]
        if (
            type(symbol) is not str
            or type(borrow_asset) is not str
            or type(repayment_required) is not bool
            or type(observation_version) is not int
        ):
            raise ValueError("paper margin snapshot scalar fields are invalid")
        return cls(
            isolated_symbol=symbol,
            borrow_asset=borrow_asset,
            collateral=_snapshot_decimal(payload["collateral"]),
            available_collateral=_snapshot_decimal(payload["available_collateral"]),
            debt_principal=_snapshot_decimal(payload["debt_principal"]),
            accrued_interest=_snapshot_decimal(payload["accrued_interest"]),
            borrow_available=_snapshot_decimal(payload["borrow_available"]),
            repayment_required=repayment_required,
            observation_version=observation_version,
        )

    def to_evidence(
        self, *, target: ExecutionTarget, observed_at: datetime
    ) -> IsolatedMarginProductEvidence:
        """Expose immutable pair truth through the existing typed read-only evidence contract."""
        return IsolatedMarginProductEvidence(
            target=target,
            isolated_symbol=self.isolated_symbol,
            collateral=self.collateral,
            available_collateral=self.available_collateral,
            debt_principal=self.debt_principal,
            accrued_interest=self.accrued_interest,
            margin_health=self.margin_health,
            borrow_available=self.borrow_available,
            repayment_required=self.repayment_required,
            observed_at=observed_at,
            observation_version=self.observation_version,
        )

    def validate_open(
        self,
        command: ExecutionCommand,
        *,
        policy: PaperEconomicPolicy,
        observation: MarketObservation,
    ) -> None:
        """Reject bad pair/borrow/repay/health facts before creating a Paper order or fill."""
        self._assert_command(command)
        if type(policy) is not PaperEconomicPolicy or policy.product is not ProductType.ISOLATED_MARGIN:
            raise ValueError("paper margin accounting requires an isolated-margin economic policy")
        if observation.scope != (command.account_id, ProductType.ISOLATED_MARGIN, self.isolated_symbol):
            raise ValueError("paper margin observation scope differs from isolated pair")
        reference_price = command.price
        if reference_price is None:
            reference_price = observation.asks[0].price if command.side is Side.BUY else observation.bids[0].price
        notional = command.quantity * reference_price * (Decimal("1") + policy.fee_rate)
        if not self.admits(notional=notional, minimum_health=policy.minimum_margin_health):
            raise ValueError("paper margin collateral, borrow availability, or health is insufficient")

    def _assert_command(self, command: ExecutionCommand) -> None:
        if type(command) is not ExecutionCommand or type(command.context) is not IsolatedMarginOrderContext:
            raise ValueError("paper margin accounting accepts only canonical isolated-margin commands")
        context = command.context
        if (
            command.context.product is not ProductType.ISOLATED_MARGIN
            or command.symbol != self.isolated_symbol
            or context.isolated_symbol != self.isolated_symbol
            or context.borrow_asset != self.borrow_asset
            or context.auto_repay is not self.repayment_required
        ):
            raise ValueError("paper margin command context does not match its isolated pair")


def _positive_decimal(value: Decimal | str, name: str) -> Decimal:
    parsed = decimal_from_canonical(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _snapshot_decimal(value: object) -> Decimal:
    if type(value) is not str:
        raise ValueError("paper margin snapshot Decimal fields must be canonical text")
    parsed = decimal_from_canonical(value)
    if decimal_to_canonical(parsed) != value:
        raise ValueError("paper margin snapshot Decimal fields are noncanonical")
    return parsed
