"""Collection of current ID-free zero-scope recovery clearance facts."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pa_agent.trading.domain.models import AccountObservation, TimeObservation
from pa_agent.trading.domain.risk import OpenOrderObservation, TargetConnectionObservation
from pa_agent.trading.domain.zero_scope_clearance import ZERO_SCOPE_TARGET, ZeroScopeClearanceProof
from pa_agent.trading.ports.gateway import TradingGateway

_MAX_AGE_SECONDS = 60


class ZeroScopeClearanceCollector:
    """Build a proof only from a complete, current selected-target gateway read."""

    def __init__(self, *, gateway: TradingGateway, utc_now: Callable[[], datetime]) -> None:
        self._gateway = gateway
        self._utc_now = utc_now

    def collect(self) -> ZeroScopeClearanceProof | None:
        """Return current empty-scope facts, or fail closed without allocating authority."""
        now = self._utc_now()
        if not _is_aware(now):
            return None
        try:
            account = self._gateway.get_account_snapshot(
                ZERO_SCOPE_TARGET.account_id, ZERO_SCOPE_TARGET.product
            )
            open_orders = self._gateway.get_open_order_count(ZERO_SCOPE_TARGET)
            listed_orders = self._gateway.list_open_orders(
                ZERO_SCOPE_TARGET.account_id, ZERO_SCOPE_TARGET.product
            )
            connection = self._gateway.get_connection(ZERO_SCOPE_TARGET)
            server_time = self._gateway.get_server_time()
            proof = ZeroScopeClearanceProof(
                target=ZERO_SCOPE_TARGET,
                account=account,
                open_orders=open_orders,
                connection=connection,
                server_time=server_time,
                collected_at=now.astimezone(UTC),
            )
        except Exception:
            return None
        if listed_orders or not _facts_are_current(proof, now):
            return None
        return proof


def _facts_are_current(proof: ZeroScopeClearanceProof, now: datetime) -> bool:
    if not all(
        (
            type(proof.account) is AccountObservation,
            type(proof.open_orders) is OpenOrderObservation,
            type(proof.connection) is TargetConnectionObservation,
            type(proof.server_time) is TimeObservation,
        )
    ):
        return False
    return all(
        _is_current(observed_at, now)
        for observed_at in (
            proof.account.observed_at,
            proof.open_orders.observed_at,
            proof.connection.observed_at,
            proof.server_time.server_time,
            proof.server_time.observed_at,
            proof.collected_at,
        )
    )


def _is_current(observed_at: datetime, now: datetime) -> bool:
    if not _is_aware(observed_at):
        return False
    age_seconds = (now.astimezone(UTC) - observed_at.astimezone(UTC)).total_seconds()
    return 0 <= age_seconds <= _MAX_AGE_SECONDS


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None
