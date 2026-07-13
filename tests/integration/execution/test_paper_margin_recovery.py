"""Filesystem recovery invariants for pair-isolated Paper margin truth."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.models import (
    ExecutionCommand,
    IsolatedMarginOrderContext,
    Mode,
    ProductType,
    OrderType,
    Side,
)
from pa_agent.trading.domain.paper import DepthLevel, MarketObservation, PaperEconomicPolicy
from pa_agent.trading.gateways.paper.accounting_margin import PaperMarginAccounting
from pa_agent.trading.gateways.paper.gateway import PaperGateway
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.ports.gateway import GatewayUnavailableError
from tests.fixtures.paper_submission import TestLeasedSubmissionVerifier

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _target() -> ExecutionTarget:
    return ExecutionTarget(
        "paper-margin-isolated-primary",
        Mode.PAPER,
        "paper-account",
        ProductType.ISOLATED_MARGIN,
    )


def _policy() -> PaperEconomicPolicy:
    return PaperEconomicPolicy(
        product=ProductType.ISOLATED_MARGIN,
        policy_version="paper-margin-isolated-v1",
        fee_rate="0.001",
        fee_rule_version="margin-fee-v1",
        slippage_rate="0",
        slippage_rule_version="margin-slippage-v1",
        interest_rate="0.025",
        interest_rule_version="margin-interest-v1",
        minimum_margin_health="1.25",
    )


def _account(symbol: str, *, collateral: str, debt: str) -> PaperMarginAccounting:
    return PaperMarginAccounting.from_initial_state(
        isolated_symbol=symbol,
        borrow_asset="USDT",
        collateral=collateral,
        debt_principal=debt,
        accrued_interest="0",
        borrow_available="100",
        repayment_required=True,
        observation_version=1,
    )


def _observation(symbol: str, version: int) -> MarketObservation:
    return MarketObservation(
        observation_id=f"{symbol}-observation-{version}",
        account_id="paper-account",
        product=ProductType.ISOLATED_MARGIN,
        symbol=symbol,
        version=version,
        observed_at=NOW,
        asks=(DepthLevel("100", "1"),),
        bids=(DepthLevel("99", "1"),),
    )


def test_reopened_margin_gateway_keeps_pair_state_and_rejects_cross_pair_queries(tmp_path: Path) -> None:
    """One observation accrues only its own durable pair; reopening cannot offset pairs."""
    path = tmp_path / "paper-margin.sqlite"
    btc = _account("BTCUSDT", collateral="100", debt="20")
    eth = _account("ETHUSDT", collateral="10", debt="9")
    store = PaperStore(path)
    gateway = PaperGateway(
        store,
        policy=_policy(),
        initial_margin_accounts={"BTCUSDT": btc, "ETHUSDT": eth},
    )

    assert gateway.advance_market(_observation("BTCUSDT", 2)) == ()
    before_close = gateway.get_isolated_margin_product_evidence(_target(), "BTCUSDT")
    assert before_close.accrued_interest == Decimal("0.5")
    assert gateway.get_isolated_margin_product_evidence(_target(), "ETHUSDT").accrued_interest == Decimal("0")
    store.close()

    reopened_store = PaperStore(path)
    reopened = PaperGateway(reopened_store, policy=_policy())
    assert reopened.get_isolated_margin_product_evidence(_target(), "BTCUSDT") == before_close
    assert reopened.get_isolated_margin_product_evidence(_target(), "ETHUSDT").margin_health == Decimal(
        "1.111111111111111111111111111"
    )
    assert reopened.advance_market(_observation("BTCUSDT", 1)) == ()
    assert reopened.get_isolated_margin_product_evidence(_target(), "BTCUSDT") == before_close
    with pytest.raises(GatewayUnavailableError):
        reopened.get_isolated_margin_product_evidence(_target(), "XRPUSDT")
    with pytest.raises(ValueError):
        IsolatedMarginOrderContext("BTCUSDT", borrow_asset="", auto_repay=True)
    reopened_store.close()


def test_unhealthy_pair_rejects_before_persisting_a_margin_order_or_fill(tmp_path: Path) -> None:
    """Bad collateral and debt facts cannot be rescued by another pair or reach the matcher."""
    store = PaperStore(tmp_path / "paper-margin-reject.sqlite")
    verifier = TestLeasedSubmissionVerifier()
    gateway = PaperGateway(
        store,
        policy=_policy(),
        initial_margin_accounts={
            "BTCUSDT": _account("BTCUSDT", collateral="100", debt="20"),
            "ETHUSDT": _account("ETHUSDT", collateral="10", debt="9"),
        },
        leased_submission_verifier=verifier,
    )
    gateway.advance_market(_observation("ETHUSDT", 2))
    command = ExecutionCommand(
        command_id="unhealthy-margin-command",
        logical_command_key="unhealthy-margin-logical",
        client_order_id="unhealthy-margin-client",
        mode=Mode.PAPER,
        account_id="paper-account",
        symbol="ETHUSDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        context=IsolatedMarginOrderContext("ETHUSDT", borrow_asset="USDT", auto_repay=True),
    )
    outbound = verifier.lease(command)

    result = gateway.submit_order(outbound)

    assert result.evidence is not None
    assert result.evidence.state.value == "rejected"
    assert store.fetch_order(command.client_order_id) is None
    assert gateway.list_fills(command.command_id) == ()
    assert gateway.get_isolated_margin_product_evidence(_target(), "BTCUSDT").debt_principal == Decimal("20")
    store.close()


def test_margin_sell_fill_repays_its_own_interest_and_principal(tmp_path: Path) -> None:
    """A pair-scoped auto-repay settles interest first without using another pair's collateral."""
    store = PaperStore(tmp_path / "paper-margin-repay.sqlite")
    verifier = TestLeasedSubmissionVerifier()
    gateway = PaperGateway(
        store,
        policy=_policy(),
        initial_margin_accounts={
            "BTCUSDT": _account("BTCUSDT", collateral="1000", debt="20"),
            "ETHUSDT": _account("ETHUSDT", collateral="10", debt="9"),
        },
        leased_submission_verifier=verifier,
    )
    gateway.advance_market(_observation("BTCUSDT", 2))
    command = ExecutionCommand(
        command_id="repay-margin-command",
        logical_command_key="repay-margin-logical",
        client_order_id="repay-margin-client",
        mode=Mode.PAPER,
        account_id="paper-account",
        symbol="BTCUSDT",
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        context=IsolatedMarginOrderContext("BTCUSDT", borrow_asset="USDT", auto_repay=True),
    )
    result = gateway.submit_order(verifier.lease(command))

    assert result.evidence is not None
    assert result.evidence.state.value == "filled"
    assert len(gateway.list_fills(command.command_id)) == 1
    assert gateway.advance_market(_observation("BTCUSDT", 3)) == ()
    evidence = gateway.get_isolated_margin_product_evidence(_target(), "BTCUSDT")
    assert evidence.debt_principal == Decimal("0")
    assert evidence.accrued_interest == Decimal("0")
    assert gateway.get_isolated_margin_product_evidence(_target(), "ETHUSDT").debt_principal == Decimal("9")
    store.close()
