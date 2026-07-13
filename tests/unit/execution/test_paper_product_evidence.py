"""Contracts for scoped product evidence at the read-only gateway boundary."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path
from decimal import Decimal

import pytest

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.errors import DecimalValueError
from pa_agent.trading.domain.models import ProductType
from pa_agent.trading.domain.risk import (
    IsolatedMarginProductEvidence,
    UsdtPerpetualProductEvidence,
)
from pa_agent.trading.gateways.paper.gateway import PaperGateway
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.ports.gateway import GatewayUnavailableError, TradingGateway
from tests.fixtures.fake_exchange import ScriptedEvidenceGateway
from tests.fixtures.execution_factories import make_execution_target

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _margin_target() -> ExecutionTarget:
    return make_execution_target(
        target_id="paper-margin-isolated-primary", product=ProductType.ISOLATED_MARGIN
    )


def _perpetual_target() -> ExecutionTarget:
    return make_execution_target(
        target_id="paper-usdt-perpetual-primary", product=ProductType.USDT_PERPETUAL
    )


def _margin_evidence(*, symbol: str = "BTCUSDT") -> IsolatedMarginProductEvidence:
    return IsolatedMarginProductEvidence(
        target=_margin_target(),
        isolated_symbol=symbol,
        collateral=Decimal("100.00"),
        available_collateral=Decimal("80.00"),
        debt_principal=Decimal("20.00"),
        accrued_interest=Decimal("0.10"),
        margin_health=Decimal("1.50"),
        borrow_available=Decimal("300.00"),
        repayment_required=True,
        observed_at=NOW,
        observation_version=7,
    )


def _perpetual_evidence(*, symbol: str = "BTCUSDT") -> UsdtPerpetualProductEvidence:
    return UsdtPerpetualProductEvidence(
        target=_perpetual_target(),
        symbol=symbol,
        isolated_margin_confirmed=True,
        one_way_position_confirmed=True,
        maximum_leverage=Decimal("3"),
        available_margin=Decimal("200"),
        initial_margin=Decimal("50"),
        maintenance_margin=Decimal("10"),
        mark_price=Decimal("40000"),
        position_quantity=Decimal("0.125"),
        observed_at=NOW,
        observation_version=11,
    )


def _gateway(*, margin: object, perpetual: object) -> ScriptedEvidenceGateway:
    return ScriptedEvidenceGateway(
        capabilities=[],
        rules=[],
        accounts=[],
        quotes=[],
        server_times=[],
        connections=[],
        open_orders=[],
        order_rates=[],
        loss_drawdowns=[],
        fee_rates=[],
        isolated_margin_evidence=[margin],
        perpetual_evidence=[perpetual],
    )


def test_product_evidence_is_frozen_decimal_scoped_and_digest_bound() -> None:
    """Each product truth owns immutable exact scope, freshness, version, and digest."""
    margin = _margin_evidence()
    perpetual = _perpetual_evidence()

    assert margin.collateral == Decimal("100.00")
    assert margin.digest == _margin_evidence().digest
    assert perpetual.position_quantity == Decimal("0.125")
    assert perpetual.digest == _perpetual_evidence().digest
    with pytest.raises(FrozenInstanceError):
        margin.collateral = Decimal("0")  # type: ignore[misc]
    with pytest.raises(ValueError):
        _margin_evidence(symbol="")
    with pytest.raises(DecimalValueError):
        IsolatedMarginProductEvidence(
            target=_margin_target(), isolated_symbol="BTCUSDT", collateral=float("nan"),
            available_collateral=Decimal("80"), debt_principal=Decimal("20"),
            accrued_interest=Decimal("0.1"), margin_health=Decimal("1.5"),
            borrow_available=Decimal("300"), repayment_required=True, observed_at=NOW,
            observation_version=1,
        )
    with pytest.raises(ValueError):
        replace(_perpetual_evidence(), observation_version=0)


def test_scripted_gateway_rejects_cross_pair_and_cross_symbol_substitution() -> None:
    """A same-account response cannot be substituted across its pair or symbol scope."""
    margin_target = _margin_target()
    perpetual_target = _perpetual_target()
    gateway = _gateway(
        margin=_margin_evidence(symbol="ETHUSDT"),
        perpetual=_perpetual_evidence(symbol="ETHUSDT"),
    )

    with pytest.raises(GatewayUnavailableError):
        gateway.get_isolated_margin_product_evidence(margin_target, "BTCUSDT")
    with pytest.raises(GatewayUnavailableError):
        gateway.get_usdt_perpetual_product_evidence(perpetual_target, "BTCUSDT")

    assert gateway.product_evidence_call_order == ["isolated_margin", "usdt_perpetual"]
    assert gateway.isolated_margin_scopes == [(margin_target, "BTCUSDT")]
    assert gateway.perpetual_scopes == [(perpetual_target, "BTCUSDT")]
    assert gateway.submit_call_count == 0


def test_scripted_gateway_returns_only_exact_typed_product_evidence() -> None:
    """Evidence collection has no map input and cannot escalate to submission."""
    margin = _margin_evidence()
    perpetual = _perpetual_evidence()
    gateway = _gateway(margin=margin, perpetual=perpetual)

    assert gateway.get_isolated_margin_product_evidence(margin.target, margin.isolated_symbol) is margin
    assert gateway.get_usdt_perpetual_product_evidence(perpetual.target, perpetual.symbol) is perpetual
    with pytest.raises(AssertionError, match="never submit"):
        gateway.submit_order(object())
    assert gateway.submit_call_count == 1


def test_product_evidence_rejects_cross_product_target_and_noncanonical_facts() -> None:
    """Scope binding rejects product confusion before any permit can be considered."""
    with pytest.raises(ValueError):
        IsolatedMarginProductEvidence(
            target=make_execution_target(), isolated_symbol="BTCUSDT", collateral="100",
            available_collateral="80", debt_principal="20", accrued_interest="0.1",
            margin_health="1.5", borrow_available="300", repayment_required=True,
            observed_at=NOW, observation_version=1,
        )
    with pytest.raises(ValueError):
        UsdtPerpetualProductEvidence(
            target=_perpetual_target(), symbol="BTCUSDT", isolated_margin_confirmed=True,
            one_way_position_confirmed=True, maximum_leverage="3", available_margin="200",
            initial_margin="50", maintenance_margin="10", mark_price="40000",
            position_quantity="0.125", observed_at=datetime(2026, 7, 13, 12, 0),
            observation_version=1,
        )


def test_reopened_paper_gateway_reconstructs_exact_committed_product_evidence(
    tmp_path: Path,
) -> None:
    """A reopened paper authority returns durable typed facts without a central ledger."""
    paper_path = tmp_path / "paper-product-evidence.sqlite"
    margin = _margin_evidence()
    perpetual = _perpetual_evidence()
    store = PaperStore(paper_path)
    store.commit_isolated_margin_product_evidence(margin)
    store.commit_usdt_perpetual_product_evidence(perpetual)
    store.close()

    reopened_store = PaperStore(paper_path)
    gateway = PaperGateway(reopened_store)
    assert isinstance(gateway, TradingGateway)
    assert gateway.get_isolated_margin_product_evidence(margin.target, margin.isolated_symbol) == margin
    assert gateway.get_usdt_perpetual_product_evidence(perpetual.target, perpetual.symbol) == perpetual
    reopened_store.close()


def test_paper_gateway_fails_closed_for_missing_and_cross_scope_product_evidence(
    tmp_path: Path,
) -> None:
    """Pair/symbol substitutions and missing committed records cannot manufacture truth."""
    store = PaperStore(tmp_path / "paper-product-evidence.sqlite")
    margin = _margin_evidence()
    perpetual = _perpetual_evidence()
    store.commit_isolated_margin_product_evidence(margin)
    store.commit_usdt_perpetual_product_evidence(perpetual)
    gateway = PaperGateway(store)

    with pytest.raises(GatewayUnavailableError):
        gateway.get_isolated_margin_product_evidence(margin.target, "ETHUSDT")
    with pytest.raises(GatewayUnavailableError):
        gateway.get_usdt_perpetual_product_evidence(perpetual.target, "ETHUSDT")
    with pytest.raises(GatewayUnavailableError):
        gateway.get_isolated_margin_product_evidence(
            make_execution_target(target_id="paper-margin-other", product=ProductType.ISOLATED_MARGIN),
            margin.isolated_symbol,
        )
    before_events = store.list_events()
    with pytest.raises(GatewayUnavailableError):
        gateway.submit_order(object())
    assert store.list_events() == before_events
    store.close()


def test_paper_store_rejects_stale_or_contradictory_product_evidence(tmp_path: Path) -> None:
    """Persisted evidence versions are append-only and cannot be silently replaced."""
    store = PaperStore(tmp_path / "paper-product-evidence.sqlite")
    evidence = _margin_evidence()
    store.commit_isolated_margin_product_evidence(evidence)
    with pytest.raises(ValueError):
        store.commit_isolated_margin_product_evidence(replace(evidence, observation_version=6))
    with pytest.raises(ValueError):
        store.commit_isolated_margin_product_evidence(replace(evidence, collateral=Decimal("101")))
    assert store.load_isolated_margin_product_evidence(evidence.target, evidence.isolated_symbol) == evidence
    store.close()
