"""Unit contracts for isolated one-way USDT-perpetual Paper accounting."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pa_agent.trading.domain.models import (
    ExecutionCommand,
    Mode,
    OrderType,
    ProductType,
    ProtectiveExitPlan,
    Side,
    UsdtPerpetualOrderContext,
)
from pa_agent.trading.domain.paper import DepthLevel, MarketObservation, PaperEconomicPolicy
from pa_agent.trading.gateways.paper.accounting_perpetual import PaperPerpetualAccounting
from pa_agent.trading.gateways.paper.gateway import PaperGateway
from pa_agent.trading.gateways.paper.store import PaperStore
from tests.fixtures.paper_submission import TestLeasedSubmissionVerifier

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _policy() -> PaperEconomicPolicy:
    return PaperEconomicPolicy(
        product=ProductType.USDT_PERPETUAL,
        policy_version="paper-perpetual-isolated-v1",
        fee_rate="0.001",
        fee_rule_version="perpetual-fee-v1",
        slippage_rate="0",
        slippage_rule_version="perpetual-slippage-v1",
        maximum_leverage="3",
        maintenance_margin_rate="0.10",
        maintenance_rule_version="perpetual-maintenance-v1",
        funding_rule_version="perpetual-funding-v1",
        liquidation_price_adjustment="0.02",
        liquidation_rule_version="perpetual-liquidation-v1",
        liquidation_fee_rate="0.01",
        liquidation_fee_rule_version="perpetual-liquidation-fee-v1",
    )


def _observation(*, version: int, mark: str = "100", funding_rate: str = "0") -> MarketObservation:
    return MarketObservation(
        observation_id=f"btc-perpetual-{version}",
        account_id="paper-account",
        product=ProductType.USDT_PERPETUAL,
        symbol="BTCUSDT",
        version=version,
        observed_at=NOW,
        asks=(DepthLevel("100", "10"),),
        bids=(DepthLevel("99", "10"),),
        mark_price=mark,
        funding_rate=funding_rate,
    )


def _context(*, side: Side, leverage: str = "2", reduce_only: bool = False, exit_plan: ProtectiveExitPlan | None = None) -> UsdtPerpetualOrderContext:
    if exit_plan is None:
        exit_plan = ProtectiveExitPlan(
            symbol="BTCUSDT",
            entry_side=side if not reduce_only else (Side.BUY if side is Side.SELL else Side.SELL),
            trigger_price="90" if side is Side.BUY else "110",
            maximum_loss="20",
            policy_version="exit-v1",
        )
    return UsdtPerpetualOrderContext(
        symbol="BTCUSDT",
        leverage=leverage,
        margin_mode="isolated",
        position_mode="one_way",
        protective_exit=exit_plan,
        reduce_only=reduce_only,
    )


def _command(*, command_id: str, side: Side, quantity: str = "1", context: UsdtPerpetualOrderContext | None = None) -> ExecutionCommand:
    return ExecutionCommand(
        command_id=command_id,
        logical_command_key=f"{command_id}-logical",
        client_order_id=f"{command_id}-client",
        mode=Mode.PAPER,
        account_id="paper-account",
        symbol="BTCUSDT",
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        context=context or _context(side=side),
    )


def _gateway(tmp_path: object) -> tuple[PaperGateway, PaperStore, TestLeasedSubmissionVerifier]:
    store = PaperStore(tmp_path / "paper-perpetual.sqlite")  # type: ignore[operator]
    verifier = TestLeasedSubmissionVerifier()
    gateway = PaperGateway(
        store,
        policy=_policy(),
        initial_perpetual_accounts={
            "BTCUSDT": PaperPerpetualAccounting.from_initial_state(
                symbol="BTCUSDT", available_usdt="1000", observation_version=0
            )
        },
        leased_submission_verifier=verifier,
    )
    gateway.advance_market(_observation(version=1))
    return gateway, store, verifier


def test_isolated_one_way_entry_locks_exact_margin_and_updates_mark_and_funding(tmp_path: object) -> None:
    """A long and a short use one symbol-scoped signed position and observation-only economics."""
    gateway, store, verifier = _gateway(tmp_path)
    try:
        long = verifier.lease(_command(command_id="long-entry", side=Side.BUY))
        assert gateway.submit_order(long).evidence is not None
        accounting = gateway.load_perpetual_accounting("paper-account", "BTCUSDT")
        assert accounting.quantity == Decimal("1")
        assert accounting.isolated_margin == Decimal("50")
        assert accounting.available_usdt == Decimal("949.9")

        gateway.advance_market(_observation(version=2, mark="110", funding_rate="0.01"))
        valued = gateway.get_usdt_perpetual_product_evidence(gateway.perpetual_target("paper-account"), "BTCUSDT")
        assert valued.mark_price == Decimal("110")
        assert valued.position_quantity == Decimal("1")
        assert valued.initial_margin == Decimal("50")
        assert valued.available_margin == Decimal("948.8")
        assert gateway.load_perpetual_accounting("paper-account", "BTCUSDT").unrealized_pnl == Decimal("10")
        assert gateway.load_perpetual_accounting("paper-account", "BTCUSDT").funding_total == Decimal("1.1")
    finally:
        store.close()


def test_short_position_uses_signed_mark_pnl_and_funding_credit(tmp_path: object) -> None:
    """A short remains one signed symbol position and receives a positive-rate funding credit."""
    gateway, store, verifier = _gateway(tmp_path)
    try:
        short = verifier.lease(_command(command_id="short-entry", side=Side.SELL))
        result = gateway.submit_order(short)
        assert result.evidence is not None and result.evidence.state.value == "filled"
        opened = gateway.load_perpetual_accounting("paper-account", "BTCUSDT")
        assert opened.quantity == Decimal("-1")
        assert opened.entry_price == Decimal("99")
        assert opened.isolated_margin == Decimal("49.5")

        gateway.advance_market(_observation(version=2, mark="90", funding_rate="0.01"))
        valued = gateway.load_perpetual_accounting("paper-account", "BTCUSDT")
        assert valued.unrealized_pnl == Decimal("9")
        assert valued.funding_total == Decimal("-0.9")
        assert valued.available_usdt == Decimal("951.301")
    finally:
        store.close()


def test_unsafe_contexts_reject_before_order_or_fill(tmp_path: object) -> None:
    """Unsupported leverage, missing exits, and unsafe reduce-only commands cannot reach matching."""
    gateway, store, verifier = _gateway(tmp_path)
    try:
        over_leverage = UsdtPerpetualOrderContext(
            "4", "isolated", "one_way", symbol="BTCUSDT", protective_exit=_context(side=Side.BUY).protective_exit
        )
        outbound = verifier.lease(_command(command_id="unsafe-leverage", side=Side.BUY, context=over_leverage))
        result = gateway.submit_order(outbound)
        assert result.evidence is not None and result.evidence.state.value == "rejected"
        assert store.fetch_order(outbound.client_order_id) is None
        assert gateway.list_fills(outbound.command_id) == ()
        with pytest.raises(Exception, match="protective exit"):
            _command(
                command_id="missing-exit",
                side=Side.BUY,
                context=UsdtPerpetualOrderContext("2", "isolated", "one_way", symbol="BTCUSDT"),
            )
        reduce_only = verifier.lease(
            _command(command_id="unsafe-reduce-only", side=Side.SELL, context=_context(side=Side.SELL, reduce_only=True))
        )
        result = gateway.submit_order(reduce_only)
        assert result.evidence is not None and result.evidence.state.value == "rejected"
        assert store.fetch_order(reduce_only.client_order_id) is None
        assert gateway.list_fills(reduce_only.command_id) == ()
    finally:
        store.close()


def test_reduce_only_exit_cannot_increase_or_reverse_exposure(tmp_path: object) -> None:
    gateway, store, verifier = _gateway(tmp_path)
    try:
        gateway.submit_order(verifier.lease(_command(command_id="entry", side=Side.BUY, quantity="1")))
        exit_plan = ProtectiveExitPlan("BTCUSDT", Side.BUY, "90", "20", "exit-v1")
        reduced = verifier.lease(
            _command(
                command_id="exit",
                side=Side.SELL,
                quantity="1",
                context=_context(side=Side.SELL, reduce_only=True, exit_plan=exit_plan),
            )
        )
        assert gateway.submit_order(reduced).evidence is not None
        assert gateway.load_perpetual_accounting("paper-account", "BTCUSDT").quantity == Decimal("0")

        oversized = verifier.lease(
            _command(
                command_id="oversized-exit",
                side=Side.SELL,
                quantity="1",
                context=_context(side=Side.SELL, reduce_only=True, exit_plan=exit_plan),
            )
        )
        assert gateway.submit_order(oversized).evidence is not None
        assert store.fetch_order(oversized.client_order_id) is None
    finally:
        store.close()
