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
    IsolatedMarginPolicyLimits,
    IsolatedMarginProductEvidence,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    UsdtPerpetualPolicyLimits,
    UsdtPerpetualProductEvidence,
    select_paper_product_policy,
    select_phase2_policy,
)

_BASE_OBSERVATION_TYPES = {
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


def _expected_observation_types(scope: RecoveryScope) -> dict[str, type[object]]:
    if not scope.is_canonical():
        raise ValueError("scope_malformed")
    expected = dict(_BASE_OBSERVATION_TYPES)
    if scope.target.product is ProductType.ISOLATED_MARGIN:
        expected["isolated_margin"] = IsolatedMarginProductEvidence
    elif scope.target.product is ProductType.USDT_PERPETUAL:
        expected["usdt_perpetual"] = UsdtPerpetualProductEvidence
    elif scope.target.product is not ProductType.SPOT:
        raise ValueError("scope_malformed")
    return expected


@dataclass(frozen=True)
class RecoveryEvidence:
    """A complete, immutable, exact-scope recovery evidence bundle."""

    items: tuple[tuple[str, object], ...]

    @property
    def observations(self) -> dict[str, object]:
        """Return a detached view; callers cannot alter the frozen evidence material."""
        return dict(self.items)

    @classmethod
    def from_observations(
        cls, scope: RecoveryScope, observations: dict[str, object], utc_now: datetime
    ) -> RecoveryEvidence:
        """Validate only service-collected typed facts before they become durable evidence."""
        _require_aware(utc_now)
        if type(scope) is not RecoveryScope or type(observations) is not dict:
            raise ValueError("scope_malformed")
        expected = _expected_observation_types(scope)
        if set(observations) != set(expected):
            missing = sorted(set(expected) - set(observations))
            raise ValueError(f"{missing[0] if missing else 'evidence'}_unavailable")
        for name, expected_type in expected.items():
            if type(observations[name]) is not expected_type:
                raise ValueError(f"{name}_malformed")
        evidence = cls(tuple((name, observations[name]) for name in sorted(expected)))
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
        """Rebuild and validate persisted JSON before any recovery ID allocation."""
        _require_aware(utc_now)
        if type(evidence_json) is not str or type(evidence_digest) is not str:
            raise ValueError("evidence_malformed")
        try:
            raw = json.loads(evidence_json)
            expected = _expected_observation_types(scope)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("evidence_malformed") from exc
        if not isinstance(raw, dict) or set(raw) != set(expected):
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
            if scope.target.product is ProductType.ISOLATED_MARGIN:
                observations["isolated_margin"] = _isolated_margin(raw["isolated_margin"])
            elif scope.target.product is ProductType.USDT_PERPETUAL:
                observations["usdt_perpetual"] = _usdt_perpetual(raw["usdt_perpetual"])
            evidence = cls.from_observations(scope, observations, utc_now)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("evidence_malformed") from exc
        if evidence.to_canonical_json() != evidence_json or evidence.digest != evidence_digest:
            raise ValueError("evidence_malformed")
        return evidence

    def to_canonical_json(self) -> str:
        return json.dumps(
            canonicalize(self.observations), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )

    @property
    def digest(self) -> str:
        return sha256(self.to_canonical_json().encode("utf-8")).hexdigest()

    def _validate(self, scope: RecoveryScope, utc_now: datetime) -> None:
        try:
            policy = (
                select_phase2_policy(scope.target)
                if scope.target.product is ProductType.SPOT
                and scope.policy_id == "phase2-paper-spot-legacy"
                else select_paper_product_policy(scope.target, scope.product_context)
            )
        except Exception as exc:
            raise ValueError("policy_mismatch") from exc
        if (
            policy.policy_id != scope.policy_id
            or policy.policy_version != scope.policy_version
            or policy.policy_digest != scope.policy_digest
        ):
            raise ValueError("policy_mismatch")
        observations = self.observations
        key = scope.product_scope_key
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
        if rules.rules.symbol != key:
            raise ValueError("rules_symbol_mismatch")
        if account.account_id != scope.target.account_id or account.product is not scope.target.product:
            raise ValueError("account_target_mismatch")
        if quote.symbol != key:
            raise ValueError("quote_symbol_mismatch")
        if any(position.quantity != 0 for position in account.positions):
            raise ValueError("unresolved_position")
        if scope.target.product is ProductType.SPOT and any(balance.reserved != 0 for balance in account.balances):
            raise ValueError("unresolved_reservation")
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
        if fee_rate.symbol != key or fee_rate.quote_identifier != key:
            raise ValueError("fee_rate_target_mismatch")
        self._validate_product_clearance(scope, policy.product_limits, observations)
        for name, observation in observations.items():
            if name == "capabilities":
                continue
            observed_at = observation.window_ends_at if name == "order_rate" else observation.observed_at
            if not _is_fresh(observed_at, utc_now):
                raise ValueError(f"{name}_stale")

    @staticmethod
    def _validate_product_clearance(
        scope: RecoveryScope, product_limits: object, observations: dict[str, object]
    ) -> None:
        if scope.target.product is ProductType.SPOT:
            return
        if scope.target.product is ProductType.ISOLATED_MARGIN:
            fact = observations["isolated_margin"]
            if type(fact) is not IsolatedMarginProductEvidence:
                raise ValueError("isolated_margin_malformed")
            if fact.target != scope.target or fact.isolated_symbol != scope.product_scope_key:
                raise ValueError("isolated_margin_scope_mismatch")
            if type(product_limits) is not IsolatedMarginPolicyLimits:
                raise ValueError("isolated_margin_policy_mismatch")
            if not fact.is_recovery_clear(product_limits.minimum_margin_health):
                raise ValueError("unresolved_isolated_margin")
            return
        fact = observations["usdt_perpetual"]
        if type(fact) is not UsdtPerpetualProductEvidence:
            raise ValueError("usdt_perpetual_malformed")
        if fact.target != scope.target or fact.symbol != scope.product_scope_key:
            raise ValueError("usdt_perpetual_scope_mismatch")
        if type(product_limits) is not UsdtPerpetualPolicyLimits:
            raise ValueError("usdt_perpetual_policy_mismatch")
        if not fact.is_recovery_clear(product_limits.maximum_leverage):
            raise ValueError("unresolved_usdt_perpetual")


def _mapping(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("malformed canonical object")
    normalized = {key: item for key, item in value.items() if key != "digest"}
    if set(normalized) != keys:
        raise ValueError("malformed canonical object")
    return normalized


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


def _isolated_margin(value: object) -> IsolatedMarginProductEvidence:
    raw = _mapping(
        value,
        {
            "target", "isolated_symbol", "collateral", "available_collateral", "debt_principal",
            "accrued_interest", "margin_health", "borrow_available", "repayment_required",
            "observed_at", "observation_version",
        },
    )
    if type(raw["repayment_required"]) is not bool or type(raw["observation_version"]) is not int:
        raise ValueError("isolated margin evidence malformed")
    return IsolatedMarginProductEvidence(
        target=_target(raw["target"]),
        isolated_symbol=_string(raw["isolated_symbol"]),
        collateral=_decimal(raw["collateral"]),
        available_collateral=_decimal(raw["available_collateral"]),
        debt_principal=_decimal(raw["debt_principal"]),
        accrued_interest=_decimal(raw["accrued_interest"]),
        margin_health=_decimal(raw["margin_health"]),
        borrow_available=_decimal(raw["borrow_available"]),
        repayment_required=raw["repayment_required"],
        observed_at=_datetime(raw["observed_at"]),
        observation_version=raw["observation_version"],
    )


def _usdt_perpetual(value: object) -> UsdtPerpetualProductEvidence:
    raw = _mapping(
        value,
        {
            "target", "symbol", "isolated_margin_confirmed", "one_way_position_confirmed",
            "maximum_leverage", "available_margin", "initial_margin", "maintenance_margin",
            "mark_price", "position_quantity", "observed_at", "observation_version",
        },
    )
    if (
        type(raw["isolated_margin_confirmed"]) is not bool
        or type(raw["one_way_position_confirmed"]) is not bool
        or type(raw["observation_version"]) is not int
    ):
        raise ValueError("perpetual evidence malformed")
    return UsdtPerpetualProductEvidence(
        target=_target(raw["target"]),
        symbol=_string(raw["symbol"]),
        isolated_margin_confirmed=raw["isolated_margin_confirmed"],
        one_way_position_confirmed=raw["one_way_position_confirmed"],
        maximum_leverage=_decimal(raw["maximum_leverage"]),
        available_margin=_decimal(raw["available_margin"]),
        initial_margin=_decimal(raw["initial_margin"]),
        maintenance_margin=_decimal(raw["maintenance_margin"]),
        mark_price=_decimal(raw["mark_price"]),
        position_quantity=_decimal(raw["position_quantity"]),
        observed_at=_datetime(raw["observed_at"]),
        observation_version=raw["observation_version"],
    )


def _is_fresh(observed_at: datetime, now: datetime) -> bool:
    age_seconds = (now.astimezone(UTC) - observed_at.astimezone(UTC)).total_seconds()
    return 0 <= age_seconds <= 60
