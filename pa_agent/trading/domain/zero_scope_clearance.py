"""ID-free, non-authorizing proof that a fixed Paper Spot scope is empty."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    Mode,
    Position,
    ProductType,
    TimeObservation,
    canonicalize,
)
from pa_agent.trading.domain.risk import OpenOrderObservation, TargetConnectionObservation

ZERO_SCOPE_TARGET = ExecutionTarget(
    target_id="paper-spot-primary",
    mode=Mode.PAPER,
    account_id="paper-account",
    product=ProductType.SPOT,
)
_SUMMARY = "zero_scope_clear"


@dataclass(frozen=True)
class ZeroScopeClearanceProof:
    """Canonical current facts only; this value cannot authorize a submission."""

    target: ExecutionTarget
    account: AccountObservation
    open_orders: OpenOrderObservation
    connection: TargetConnectionObservation
    server_time: TimeObservation
    collected_at: datetime
    clearance_summary: str = _SUMMARY

    def __post_init__(self) -> None:
        if (
            type(self.target) is not ExecutionTarget
            or self.target != ZERO_SCOPE_TARGET
            or type(self.account) is not AccountObservation
            or type(self.open_orders) is not OpenOrderObservation
            or type(self.connection) is not TargetConnectionObservation
            or type(self.server_time) is not TimeObservation
            or not self.clearance_summary
        ):
            raise ValueError("zero-scope proof requires fixed canonical facts")
        if (
            self.account.account_id != self.target.account_id
            or self.account.product is not self.target.product
            or self.open_orders.target != self.target
            or self.connection.target != self.target
            or not self.connection.connected
            or self.open_orders.count != 0
            or self.account.positions
        ):
            raise ValueError("zero-scope proof contains residual target exposure")
        if self.collected_at.tzinfo is None or self.collected_at.utcoffset() is None:
            raise ValueError("zero-scope proof collection time must be timezone-aware")

    def to_canonical_json(self) -> str:
        """Serialize the proof deterministically for audit and transaction revalidation."""
        return json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def canonical_payload(self) -> dict[str, object]:
        """Return the controlled, ID-free durable payload."""
        return {
            "account": canonicalize(self.account),
            "clearance_summary": self.clearance_summary,
            "collected_at": self.collected_at.astimezone(UTC).isoformat(),
            "connection": canonicalize(self.connection),
            "open_orders": canonicalize(self.open_orders),
            "positions": canonicalize(self.account.positions),
            "server_time": canonicalize(self.server_time),
            "target": canonicalize(self.target),
        }

    @classmethod
    def from_canonical_json(cls, value: str) -> ZeroScopeClearanceProof:
        """Parse only an exact canonical proof representation."""
        try:
            payload = json.loads(value)
            if set(payload) != {
                "account",
                "clearance_summary",
                "collected_at",
                "connection",
                "open_orders",
                "positions",
                "server_time",
                "target",
            }:
                raise ValueError("zero-scope proof fields are incomplete")
            target_raw = payload["target"]
            target = ExecutionTarget(
                target_id=target_raw["target_id"],
                mode=Mode(target_raw["mode"]),
                account_id=target_raw["account_id"],
                product=ProductType(target_raw["product"]),
            )
            account_raw = payload["account"]
            account = AccountObservation(
                account_id=account_raw["account_id"],
                product=ProductType(account_raw["product"]),
                observed_at=_parse_timestamp(account_raw["observed_at"]),
                balances=tuple(Balance(**balance) for balance in account_raw["balances"]),
                positions=tuple(Position(**position) for position in account_raw["positions"]),
            )
            open_orders_raw = payload["open_orders"]
            connection_raw = payload["connection"]
            server_time_raw = payload["server_time"]
            proof = cls(
                target=target,
                account=account,
                open_orders=OpenOrderObservation(
                    target=target,
                    count=open_orders_raw["count"],
                    observed_at=_parse_timestamp(open_orders_raw["observed_at"]),
                ),
                connection=TargetConnectionObservation(
                    target=target,
                    connected=connection_raw["connected"],
                    observed_at=_parse_timestamp(connection_raw["observed_at"]),
                ),
                server_time=TimeObservation(
                    server_time=_parse_timestamp(server_time_raw["server_time"]),
                    observed_at=_parse_timestamp(server_time_raw["observed_at"]),
                ),
                collected_at=_parse_timestamp(payload["collected_at"]),
                clearance_summary=payload["clearance_summary"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("zero-scope proof is not canonical") from exc
        if proof.to_canonical_json() != value or payload["positions"] != canonicalize(account.positions):
            raise ValueError("zero-scope proof does not round-trip canonically")
        return proof


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("zero-scope timestamp must be text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("zero-scope timestamp must be timezone-aware")
    return parsed.astimezone(UTC)
