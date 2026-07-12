"""Strict canonical recovery evidence shared by collection and durable storage."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from pa_agent.trading.domain.approval import ExecutionTarget, RecoveryScope
from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    GatewayCapabilities,
    InstrumentRules,
    Position,
    ProductType,
    QuoteObservation,
    RuleObservation,
    TimeObservation,
    canonicalize,
)
from pa_agent.trading.domain.risk import (
    FeeRateObservation,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    select_phase2_policy,
)

_OBSERVATION_TYPES = {
    "capabilities": GatewayCapabilities,
    "rules": RuleObservation,
    "account": AccountObservation,
    "quote": QuoteObservation,
    "server_time": TimeObservation,
    "connection": TargetConnectionObservation,
    "open_orders": OpenOrderObservation,
    "order_rate": OrderRateObservation,
    "loss_drawdown": LossDrawdownObservation,
    "fee_rate": FeeRateObservation,
}


@dataclass(frozen=True)
class RecoveryEvidence:
    """A complete, canonical, scope-bound recovery evidence bundle."""

    observations: dict[str, object]

    @classmethod
    def from_observations(
        cls, scope: RecoveryScope, observations: dict[str, object], utc_now: datetime
    ) -> RecoveryEvidence:
        """Validate typed service observations before they become durable evidence."""
        _require_aware(utc_now)
        if type(scope) is not RecoveryScope:
            raise ValueError("scope_malformed")
        if set(observations) != set(_OBSERVATION_TYPES):
            missing = sorted(set(_OBSERVATION_TYPES) - set(observations))
            raise ValueError(f"{missing[0] if missing else 'evidence'}_unavailable")
        for name, expected_type in _OBSERVATION_TYPES.items():
            if type(observations[name]) is not expected_type:
                raise ValueError(f"{name}_malformed")
        evidence = cls(dict(observations))
        evidence._validate(scope, utc_now)
        return evidence

    @classmethod
    def from_canonical_json(
        cls,
        evidence_json: str,
        evidence_digest: str,
        scope: RecoveryScope,
        utc_now: datetime,
    ) -> RecoveryEvidence:
        """Rebuild and validate untrusted persisted JSON before recovery ID allocation."""
        _require_aware(utc_now)
        if type(evidence_json) is not str or type(evidence_digest) is not str:
            raise ValueError("evidence_malformed")
        try:
            raw = json.loads(evidence_json)
        except json.JSONDecodeError as exc:
            raise ValueError("evidence_malformed") from exc
        if not isinstance(raw, dict) or set(raw) != set(_OBSERVATION_TYPES):
            raise ValueError("evidence_malformed")
        try:
            observations = {
                "capabilities": _capabilities(raw["capabilities"]),
                "rules": _rules(raw["rules"]),
                "account": _account(raw["account"]),
                "quote": _quote(raw["quote"]),
                "server_time": _time(raw["server_time"]),
                "connection": _connection(raw["connection"]),
                "open_orders": _open_orders(raw["open_orders"]),
                "order_rate": _order_rate(raw["order_rate"]),
                "loss_drawdown": _loss_drawdown(raw["loss_drawdown"]),
                "fee_rate": _fee_rate(raw["fee_rate"]),
            }
            evidence = cls.from_observations(scope, observations, utc_now)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("evidence_malformed") from exc
        if evidence.to_canonical_json() != evidence_json or evidence.digest != evidence_digest:
            raise ValueError("evidence_malformed")
        return evidence

    def to_canonical_json(self) -> str:
        return json.dumps(canonicalize(self.observations), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def digest(self) -> str:
        return sha256(self.to_canonical_json().encode("utf-8")).hexdigest()

    def _validate(self, scope: RecoveryScope, utc_now: datetime) -> None:
        policy = select_phase2_policy(scope.target)
        if policy.policy_version != scope.policy_version or policy.policy_digest != scope.policy_digest:
            raise ValueError("policy_mismatch")
        symbol = next(iter(sorted(policy.symbols)))
        observations = self.observations
        capabilities = observations["capabilities"]
        rules = observations["rules"]
        account = observations["account"]
        quote = observations["quote"]
        connection = observations["connection"]
        open_orders = observations["open_orders"]
        order_rate = observations["order_rate"]
        loss_drawdown = observations["loss_drawdown"]
        fee_rate = observations["fee_rate"]
        if scope.target.product not in capabilities.products:
            raise ValueError("capabilities_target_mismatch")
        if rules.rules.symbol != symbol:
            raise ValueError("rules_symbol_mismatch")
        if account.account_id != scope.target.account_id or account.product is not scope.target.product:
            raise ValueError("account_target_mismatch")
        if quote.symbol != symbol:
            raise ValueError("quote_symbol_mismatch")
        if any(position.quantity != 0 for position in account.positions):
            raise ValueError("unresolved_position")
        for name, observation in (
            ("connection", connection),
            ("open_orders", open_orders),
            ("order_rate", order_rate),
            ("loss_drawdown", loss_drawdown),
            ("fee_rate", fee_rate),
        ):
            if observation.target != scope.target:
                raise ValueError(f"{name}_target_mismatch")
        if not connection.connected:
            raise ValueError("connection_unavailable")
        if open_orders.count != 0:
            raise ValueError("unresolved_open_orders")
        if fee_rate.symbol != symbol or fee_rate.quote_identifier != symbol:
            raise ValueError("fee_rate_target_mismatch")
        for name, observation in observations.items():
            if name == "capabilities":
                continue
            observed_at = observation.window_ends_at if name == "order_rate" else observation.observed_at
            if not _is_fresh(observed_at, utc_now):
                raise ValueError(f"{name}_stale")


def _mapping(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("malformed canonical object")
    return value


def _datetime(value: object) -> datetime:
    if type(value) is not str:
        raise ValueError("timestamp must be text")
    parsed = datetime.fromisoformat(value)
    _require_aware(parsed)
    return parsed


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be aware")


def _target(value: object) -> ExecutionTarget:
    raw = _mapping(value, {"target_id", "mode", "account_id", "product"})
    return ExecutionTarget(
        target_id=_string(raw["target_id"]),
        mode=_enum_value(raw["mode"], "mode"),
        account_id=_string(raw["account_id"]),
        product=ProductType(_string(raw["product"])),
    )


def _enum_value(value: object, name: str) -> object:
    from pa_agent.trading.domain.models import Mode

    if name != "mode":
        raise ValueError("unsupported enum")
    return Mode(_string(value))


def _string(value: object) -> str:
    if type(value) is not str:
        raise ValueError("string required")
    return value


def _decimal(value: object) -> Decimal:
    if type(value) is not str:
        raise ValueError("canonical decimal text required")
    return Decimal(value)


def _capabilities(value: object) -> GatewayCapabilities:
    raw = _mapping(value, {"products", "supports_order_lookup", "supports_fill_lookup", "supports_cancellation", "minimum_leverage", "maximum_leverage"})
    if not isinstance(raw["products"], list) or any(type(item) is not str for item in raw["products"]):
        raise ValueError("products malformed")
    for name in ("supports_order_lookup", "supports_fill_lookup", "supports_cancellation"):
        if type(raw[name]) is not bool:
            raise ValueError("capability flag malformed")
    return GatewayCapabilities(
        products=frozenset(ProductType(item) for item in raw["products"]),
        supports_order_lookup=raw["supports_order_lookup"],
        supports_fill_lookup=raw["supports_fill_lookup"],
        supports_cancellation=raw["supports_cancellation"],
        minimum_leverage=None if raw["minimum_leverage"] is None else _decimal(raw["minimum_leverage"]),
        maximum_leverage=None if raw["maximum_leverage"] is None else _decimal(raw["maximum_leverage"]),
    )


def _rules(value: object) -> RuleObservation:
    raw = _mapping(value, {"rules", "observed_at"})
    rule = _mapping(raw["rules"], {"symbol", "price_tick", "quantity_step", "minimum_quantity", "minimum_notional"})
    return RuleObservation(InstrumentRules(**rule), _datetime(raw["observed_at"]))


def _account(value: object) -> AccountObservation:
    raw = _mapping(value, {"account_id", "product", "observed_at", "balances", "positions"})
    if not isinstance(raw["balances"], list) or not isinstance(raw["positions"], list):
        raise ValueError("account collections malformed")
    balances = tuple(Balance(**_mapping(item, {"asset", "total", "available", "reserved"})) for item in raw["balances"])
    positions = tuple(Position(**_mapping(item, {"symbol", "quantity", "entry_price", "mark_price", "unrealized_pnl", "margin"})) for item in raw["positions"])
    return AccountObservation(_string(raw["account_id"]), ProductType(_string(raw["product"])), _datetime(raw["observed_at"]), balances, positions)


def _quote(value: object) -> QuoteObservation:
    raw = _mapping(value, {"symbol", "bid", "ask", "observed_at"})
    return QuoteObservation(_string(raw["symbol"]), _decimal(raw["bid"]), _decimal(raw["ask"]), _datetime(raw["observed_at"]))


def _time(value: object) -> TimeObservation:
    raw = _mapping(value, {"server_time", "observed_at"})
    return TimeObservation(_datetime(raw["server_time"]), _datetime(raw["observed_at"]))


def _connection(value: object) -> TargetConnectionObservation:
    raw = _mapping(value, {"target", "connected", "observed_at"})
    if type(raw["connected"]) is not bool:
        raise ValueError("connection malformed")
    return TargetConnectionObservation(_target(raw["target"]), raw["connected"], _datetime(raw["observed_at"]))


def _open_orders(value: object) -> OpenOrderObservation:
    raw = _mapping(value, {"target", "count", "observed_at"})
    if type(raw["count"]) is not int:
        raise ValueError("open order count malformed")
    return OpenOrderObservation(_target(raw["target"]), raw["count"], _datetime(raw["observed_at"]))


def _order_rate(value: object) -> OrderRateObservation:
    raw = _mapping(value, {"target", "count", "window_started_at", "window_ends_at"})
    if type(raw["count"]) is not int:
        raise ValueError("order rate count malformed")
    return OrderRateObservation(_target(raw["target"]), raw["count"], _datetime(raw["window_started_at"]), _datetime(raw["window_ends_at"]))


def _loss_drawdown(value: object) -> LossDrawdownObservation:
    raw = _mapping(value, {"target", "realized_loss", "drawdown", "utc_day_started_at", "observed_at"})
    return LossDrawdownObservation(_target(raw["target"]), _decimal(raw["realized_loss"]), _decimal(raw["drawdown"]), _datetime(raw["utc_day_started_at"]), _datetime(raw["observed_at"]))


def _fee_rate(value: object) -> FeeRateObservation:
    raw = _mapping(value, {"target", "symbol", "quote_identifier", "fee_currency", "rate", "rate_version", "observed_at"})
    return FeeRateObservation(_target(raw["target"]), _string(raw["symbol"]), _string(raw["quote_identifier"]), _string(raw["fee_currency"]), _decimal(raw["rate"]), _string(raw["rate_version"]), _datetime(raw["observed_at"]))


def _is_fresh(observed_at: datetime, now: datetime) -> bool:
    age_seconds = (now.astimezone(UTC) - observed_at.astimezone(UTC)).total_seconds()
    return 0 <= age_seconds <= 60
