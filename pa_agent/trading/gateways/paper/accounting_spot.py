"""Product-only Decimal reserve, settlement, and release rules for Paper Spot."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from pa_agent.trading.domain.models import ExecutionCommand, ProductType, Side, SpotOrderContext, decimal_from_canonical, decimal_to_canonical
from pa_agent.trading.domain.paper import MarketObservation, PaperEconomicPolicy, PaperFillCandidate


@dataclass(frozen=True)
class PaperSpotBalance:
    """One exact Paper Spot asset balance satisfying total = available + reserved."""

    total: Decimal
    available: Decimal
    reserved: Decimal

    def __post_init__(self) -> None:
        if min(self.total, self.available, self.reserved) < Decimal("0"):
            raise ValueError("paper spot balances cannot be negative")
        if self.total != self.available + self.reserved:
            raise ValueError("paper spot balance must satisfy total = available + reserved")


@dataclass(frozen=True)
class PaperSpotReservation:
    """The product-owned portion of an open order that cannot be re-spent."""

    asset: str
    amount: Decimal
    unit_reserve: Decimal

    def __post_init__(self) -> None:
        if not self.asset or self.amount < 0 or self.unit_reserve <= 0:
            raise ValueError("paper spot reservation must be non-negative and scoped")


@dataclass(frozen=True)
class PaperSpotAccounting:
    """Immutable Spot account projector with no store, matcher, or gateway authority."""

    _balances: Mapping[str, PaperSpotBalance]
    _reservations: Mapping[str, PaperSpotReservation]

    def __post_init__(self) -> None:
        balances = {asset: balance for asset, balance in self._balances.items()}
        if not balances or any(not asset or type(balance) is not PaperSpotBalance for asset, balance in balances.items()):
            raise ValueError("paper spot accounting requires canonical asset balances")
        reservations = {command_id: reservation for command_id, reservation in self._reservations.items()}
        if any(not command_id or type(reservation) is not PaperSpotReservation for command_id, reservation in reservations.items()):
            raise ValueError("paper spot reservations must be canonical")
        object.__setattr__(self, "_balances", MappingProxyType(balances))
        object.__setattr__(self, "_reservations", MappingProxyType(reservations))

    @classmethod
    def from_initial_balances(cls, balances: Mapping[str, Decimal | str]) -> PaperSpotAccounting:
        """Build a fully available Decimal account before its first durable snapshot."""
        canonical = {
            asset: PaperSpotBalance(
                total=decimal_from_canonical(amount),
                available=decimal_from_canonical(amount),
                reserved=Decimal("0"),
            )
            for asset, amount in balances.items()
        }
        return cls(canonical, {})

    @classmethod
    def from_snapshot_payload(cls, payload: Mapping[str, object]) -> PaperSpotAccounting:
        """Reconstruct only canonical Spot truth persisted by the PaperStore."""
        balances_raw = payload.get("balances")
        reservations_raw = payload.get("reservations")
        if type(balances_raw) is not dict or type(reservations_raw) is not dict:
            raise ValueError("paper spot snapshot requires balances and reservations")
        balances: dict[str, PaperSpotBalance] = {}
        for asset, raw in balances_raw.items():
            if type(asset) is not str or type(raw) is not dict or set(raw) != {"total", "available", "reserved"}:
                raise ValueError("paper spot balance snapshot is invalid")
            balances[asset] = PaperSpotBalance(
                total=_snapshot_decimal(raw["total"]),
                available=_snapshot_decimal(raw["available"]),
                reserved=_snapshot_decimal(raw["reserved"]),
            )
        reservations: dict[str, PaperSpotReservation] = {}
        for command_id, raw in reservations_raw.items():
            if type(command_id) is not str or type(raw) is not dict or set(raw) != {"asset", "amount", "unit_reserve"}:
                raise ValueError("paper spot reservation snapshot is invalid")
            asset = raw["asset"]
            if type(asset) is not str:
                raise ValueError("paper spot reservation asset is invalid")
            reservations[command_id] = PaperSpotReservation(
                asset=asset,
                amount=_snapshot_decimal(raw["amount"]),
                unit_reserve=_snapshot_decimal(raw["unit_reserve"]),
            )
        return cls(balances, reservations)

    def to_snapshot_payload(self) -> dict[str, object]:
        """Produce fixed-point store payload without allowing binary float economics."""
        return {
            "balances": {
                asset: {
                    "total": decimal_to_canonical(balance.total),
                    "available": decimal_to_canonical(balance.available),
                    "reserved": decimal_to_canonical(balance.reserved),
                }
                for asset, balance in sorted(self._balances.items())
            },
            "reservations": {
                command_id: {
                    "asset": reservation.asset,
                    "amount": decimal_to_canonical(reservation.amount),
                    "unit_reserve": decimal_to_canonical(reservation.unit_reserve),
                }
                for command_id, reservation in sorted(self._reservations.items())
            },
        }

    def balance(self, asset: str) -> PaperSpotBalance:
        """Return one immutable exact balance or reject an undeclared asset."""
        try:
            return self._balances[asset]
        except KeyError as exc:
            raise ValueError(f"paper spot account has no {asset} balance") from exc

    def open(
        self,
        command: ExecutionCommand,
        *,
        policy: PaperEconomicPolicy,
        observation: MarketObservation,
    ) -> PaperSpotAccounting:
        """Reserve the exact maximum exposure before persisting an open Spot order."""
        self._assert_spot(command, policy, observation)
        if command.command_id in self._reservations:
            raise ValueError("paper spot command is already reserved")
        base_asset, quote_asset = self._assets_for(command.symbol)
        if command.side is Side.BUY:
            unit_reserve = self._buy_unit_reserve(command, policy, observation)
            reservation = PaperSpotReservation(quote_asset, command.quantity * unit_reserve, unit_reserve)
        else:
            reservation = PaperSpotReservation(base_asset, command.quantity, Decimal("1"))
        balance = self.balance(reservation.asset)
        if balance.available < reservation.amount:
            raise ValueError("insufficient available paper spot assets")
        return self._with_changes(
            balances={
                reservation.asset: PaperSpotBalance(
                    total=balance.total,
                    available=balance.available - reservation.amount,
                    reserved=balance.reserved + reservation.amount,
                )
            },
            reservations={command.command_id: reservation},
        )

    def settle(
        self, command: ExecutionCommand, candidates: tuple[PaperFillCandidate, ...]
    ) -> PaperSpotAccounting:
        """Transfer exactly accepted candidate quantities and frozen fee economics."""
        reservation = self._reservations.get(command.command_id)
        if reservation is None:
            raise ValueError("paper spot order has no reservation")
        result = self
        for candidate in candidates:
            if candidate.command_id != command.command_id:
                raise ValueError("paper fill candidate command does not match reservation")
            result = result._settle_one(command, candidate)
        return result

    def release(self, command: ExecutionCommand, *, remaining_quantity: Decimal) -> PaperSpotAccounting:
        """Release only the durable unfilled residual after cancellation evidence wins."""
        reservation = self._reservations.get(command.command_id)
        if reservation is None:
            raise ValueError("paper spot order has no residual reservation")
        expected = reservation.unit_reserve * remaining_quantity
        if expected != reservation.amount:
            raise ValueError("paper spot cancellation residual does not match reservation")
        balance = self.balance(reservation.asset)
        reservations = dict(self._reservations)
        del reservations[command.command_id]
        return PaperSpotAccounting(
            {
                **self._balances,
                reservation.asset: PaperSpotBalance(
                    total=balance.total,
                    available=balance.available + reservation.amount,
                    reserved=balance.reserved - reservation.amount,
                ),
            },
            reservations,
        )

    def _settle_one(self, command: ExecutionCommand, candidate: PaperFillCandidate) -> PaperSpotAccounting:
        reservation = self._reservations[command.command_id]
        base_asset, quote_asset = self._assets_for(command.symbol)
        if command.side is Side.BUY:
            allocation = reservation.unit_reserve * candidate.quantity
            cost = candidate.quantity * candidate.provenance.final_execution_price + candidate.provenance.fee
            if allocation > reservation.amount or cost > allocation:
                raise ValueError("paper spot buy fill exceeds its reserved maximum")
            quote = self.balance(quote_asset)
            base = self.balance(base_asset)
            next_reservation = PaperSpotReservation(
                asset=quote_asset,
                amount=reservation.amount - allocation,
                unit_reserve=reservation.unit_reserve,
            )
            return self._with_settlement(
                command.command_id,
                next_reservation,
                {
                    quote_asset: PaperSpotBalance(
                        total=quote.total - cost,
                        available=quote.available + allocation - cost,
                        reserved=quote.reserved - allocation,
                    ),
                    base_asset: PaperSpotBalance(
                        total=base.total + candidate.quantity,
                        available=base.available + candidate.quantity,
                        reserved=base.reserved,
                    ),
                },
            )
        if candidate.quantity > reservation.amount:
            raise ValueError("paper spot sell fill exceeds its reserved base")
        base = self.balance(base_asset)
        quote = self.balance(quote_asset)
        proceeds = candidate.quantity * candidate.provenance.final_execution_price - candidate.provenance.fee
        if proceeds < 0:
            raise ValueError("paper spot fee exceeds sell proceeds")
        next_reservation = PaperSpotReservation(
            asset=base_asset,
            amount=reservation.amount - candidate.quantity,
            unit_reserve=Decimal("1"),
        )
        return self._with_settlement(
            command.command_id,
            next_reservation,
            {
                base_asset: PaperSpotBalance(
                    total=base.total - candidate.quantity,
                    available=base.available,
                    reserved=base.reserved - candidate.quantity,
                ),
                quote_asset: PaperSpotBalance(
                    total=quote.total + proceeds,
                    available=quote.available + proceeds,
                    reserved=quote.reserved,
                ),
            },
        )

    def _with_settlement(
        self,
        command_id: str,
        reservation: PaperSpotReservation,
        balances: Mapping[str, PaperSpotBalance],
    ) -> PaperSpotAccounting:
        reservations = dict(self._reservations)
        if reservation.amount == 0:
            del reservations[command_id]
        else:
            reservations[command_id] = reservation
        return PaperSpotAccounting({**self._balances, **balances}, reservations)

    def _with_changes(
        self,
        *,
        balances: Mapping[str, PaperSpotBalance],
        reservations: Mapping[str, PaperSpotReservation],
    ) -> PaperSpotAccounting:
        merged_reservations = dict(self._reservations)
        merged_reservations.update(reservations)
        return PaperSpotAccounting({**self._balances, **balances}, merged_reservations)

    def _assert_spot(
        self, command: ExecutionCommand, policy: PaperEconomicPolicy, observation: MarketObservation) -> None:
        if type(command) is not ExecutionCommand or type(command.context) is not SpotOrderContext:
            raise ValueError("paper spot accounting accepts only canonical spot commands")
        if type(policy) is not PaperEconomicPolicy or policy.product is not ProductType.SPOT:
            raise ValueError("paper spot accounting requires a spot economic policy")
        if observation.scope != (command.account_id, ProductType.SPOT, command.symbol):
            raise ValueError("paper spot accounting observation scope differs from command")

    def _assets_for(self, symbol: str) -> tuple[str, str]:
        quote_asset = next((asset for asset in sorted(self._balances, key=len, reverse=True) if symbol.endswith(asset)), None)
        if quote_asset is None:
            raise ValueError("paper spot symbol quote asset is not configured")
        base_asset = symbol[: -len(quote_asset)]
        if not base_asset or base_asset not in self._balances:
            raise ValueError("paper spot symbol base asset is not configured")
        return base_asset, quote_asset

    @staticmethod
    def _buy_unit_reserve(
        command: ExecutionCommand, policy: PaperEconomicPolicy, observation: MarketObservation
    ) -> Decimal:
        raw_maximum = command.price if command.price is not None else max(level.price for level in observation.asks)
        execution_maximum = raw_maximum * (Decimal("1") + policy.slippage_rate)
        return execution_maximum * (Decimal("1") + policy.fee_rate)


def _snapshot_decimal(value: object) -> Decimal:
    if type(value) is not str:
        raise ValueError("paper spot snapshot Decimal must be fixed-point text")
    parsed = decimal_from_canonical(value)
    if decimal_to_canonical(parsed) != value:
        raise ValueError("paper spot snapshot Decimal is noncanonical")
    return parsed
