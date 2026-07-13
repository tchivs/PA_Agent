"""Canonical product-context and protective-exit contract tests."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from pa_agent.trading.domain.approval import CandidateExecutionIntent
from pa_agent.trading.domain.errors import CanonicalInputError, DecimalValueError, ProductContextError
from pa_agent.trading.domain.models import (
    IsolatedMarginOrderContext,
    ProtectiveExitPlan,
    ProductType,
    Side,
    SpotOrderContext,
    UsdtPerpetualOrderContext,
    product_context_from_canonical_payload,
    product_context_to_canonical_payload,
)
from tests.fixtures.execution_factories import make_candidate_execution_intent


def _protective_exit(**overrides: object) -> ProtectiveExitPlan:
    values: dict[str, object] = {
        "symbol": "BTCUSDT",
        "entry_side": Side.BUY,
        "trigger_price": "39000.00",
        "limit_price": "38900.00",
        "maximum_loss": "250.00",
        "policy_version": "paper-perp-v1",
    }
    values.update(overrides)
    return ProtectiveExitPlan(**values)  # type: ignore[arg-type]


def test_protective_exit_is_frozen_decimal_only_and_canonically_digest_bound() -> None:
    """One validated exit plan has stable, exact canonical material."""
    plan = _protective_exit()

    assert plan.exit_side is Side.SELL
    assert plan.trigger_price == Decimal("39000.00")
    assert plan.limit_price == Decimal("38900.00")
    assert plan.maximum_loss == Decimal("250.00")
    assert plan.reduce_only is True
    assert plan.canonical_payload == (
        '{"entry_side":"buy","exit_side":"sell","limit_price":"38900.00",'
        '"maximum_loss":"250.00","policy_version":"paper-perp-v1",'
        '"reduce_only":true,"schema_version":"protective-exit-v1",'
        '"symbol":"BTCUSDT","trigger_price":"39000.00"}'
    )
    assert plan.digest == _protective_exit().digest
    with pytest.raises(FrozenInstanceError):
        plan.trigger_price = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    (
        {"trigger_price": "0"},
        {"maximum_loss": "NaN"},
        {"limit_price": "39000.01"},
        {"entry_side": Side.SELL, "trigger_price": "41000", "limit_price": "40999"},
        {"reduce_only": False},
        {"symbol": ""},
    ),
)
def test_protective_exit_rejects_unsafe_or_noncanonical_values(overrides: dict[str, object]) -> None:
    """Unsafe exits and nonfinite inputs never become durable product facts."""
    with pytest.raises((CanonicalInputError, DecimalValueError, ProductContextError)):
        _protective_exit(**overrides)


def test_product_context_payload_round_trip_is_exact_and_rejects_schema_tampering() -> None:
    """Contexts use one sorted payload and reject caller-controlled schema changes."""
    context = IsolatedMarginOrderContext(
        isolated_symbol="BTCUSDT", borrow_asset="USDT", auto_repay=True
    )
    payload = product_context_to_canonical_payload(context)

    assert payload == (
        '{"auto_repay":true,"borrow_asset":"USDT","isolated_symbol":"BTCUSDT",'
        '"product":"isolated_margin","schema_version":"product-context-v1"}'
    )
    assert product_context_from_canonical_payload(payload) == context
    for malformed in (
        payload.replace('"schema_version":"product-context-v1"', '"schema_version":"product-context-v2"'),
        payload.replace('"product":"isolated_margin",', '"unknown":true,"product":"isolated_margin",'),
        payload.replace('"auto_repay":true,', '"auto_repay":true,"auto_repay":false,'),
        payload.replace('"BTCUSDT",', '"BTCUSDT" ,'),
    ):
        with pytest.raises((CanonicalInputError, ProductContextError)):
            product_context_from_canonical_payload(malformed)


def test_candidate_digest_changes_for_every_product_context_or_protective_exit_change() -> None:
    """Approval binding cannot survive a context, leverage, borrow, or exit mutation."""
    spot = make_candidate_execution_intent(context=SpotOrderContext())
    margin = make_candidate_execution_intent(
        target=replace(spot.target, target_id="paper-margin", product=ProductType.ISOLATED_MARGIN),
        context=IsolatedMarginOrderContext("BTCUSDT", "USDT", True),
    )
    changed_margin = replace(margin, context=IsolatedMarginOrderContext("BTCUSDT", "BTC", False))
    perpetual = make_candidate_execution_intent(
        target=replace(spot.target, target_id="paper-perp", product=ProductType.USDT_PERPETUAL),
        context=UsdtPerpetualOrderContext(
            symbol="BTCUSDT",
            leverage="3.00",
            margin_mode="isolated",
            position_mode="one_way",
            protective_exit=_protective_exit(),
        ),
    )
    changed_exit = replace(
        perpetual,
        context=replace(perpetual.context, protective_exit=_protective_exit(maximum_loss="251.00")),
    )
    changed_leverage = replace(
        perpetual,
        context=replace(perpetual.context, leverage="4.00"),
    )

    assert isinstance(margin, CandidateExecutionIntent)
    assert len({spot.intent_digest, margin.intent_digest, changed_margin.intent_digest}) == 3
    assert perpetual.intent_digest != changed_exit.intent_digest
    assert perpetual.intent_digest != changed_leverage.intent_digest


def test_perpetual_context_rejects_unsafe_generic_or_mismatched_entry_forms() -> None:
    """Only isolated one-way, symbol-bound perpetual entries carry a matching exit."""
    with pytest.raises(ProductContextError):
        UsdtPerpetualOrderContext(
            symbol="BTCUSDT",
            leverage="3",
            margin_mode="cross",
            position_mode="one_way",
            protective_exit=_protective_exit(),
        )
    with pytest.raises(ProductContextError):
        UsdtPerpetualOrderContext(
            symbol="BTCUSDT",
            leverage="3",
            margin_mode="isolated",
            position_mode="hedge",
            protective_exit=_protective_exit(symbol="ETHUSDT"),
        )
