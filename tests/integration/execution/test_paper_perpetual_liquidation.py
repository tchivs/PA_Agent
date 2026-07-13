"""Restart-safe deterministic liquidation regression for Paper USDT perpetuals."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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


def _observation(version: int, *, mark: str, funding_rate: str = "0") -> MarketObservation:
    return MarketObservation(
        observation_id=f"btc-liquidation-{version}",
        account_id="paper-account",
        product=ProductType.USDT_PERPETUAL,
        symbol="BTCUSDT",
        version=version,
        observed_at=NOW,
        asks=(DepthLevel(mark, "10"),),
        bids=(DepthLevel(mark, "10"),),
        mark_price=mark,
        funding_rate=funding_rate,
    )


def _command() -> ExecutionCommand:
    exit_plan = ProtectiveExitPlan("BTCUSDT", Side.BUY, "90", "100", "exit-v1")
    return ExecutionCommand(
        command_id="liquidated-long-command",
        logical_command_key="liquidated-long-logical",
        client_order_id="liquidated-long-client",
        mode=Mode.PAPER,
        account_id="paper-account",
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity="1",
        context=UsdtPerpetualOrderContext(
            leverage="2",
            margin_mode="isolated",
            position_mode="one_way",
            symbol="BTCUSDT",
            protective_exit=exit_plan,
        ),
    )


def test_liquidation_is_exact_durable_and_cannot_replay_after_reopen(tmp_path: Path) -> None:
    """A maintenance breach records immutable close provenance and converges to a safe zero position."""
    path = tmp_path / "paper-perpetual.sqlite"
    store = PaperStore(path)
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
    gateway.advance_market(_observation(1, mark="100"))
    outbound = verifier.lease(_command())
    submitted = gateway.submit_order(outbound)
    assert submitted.evidence is not None and submitted.evidence.state.value == "filled"

    changes = gateway.advance_market(_observation(2, mark="40"))
    assert len(changes) == 1
    liquidation = store.list_liquidation_fills(account_id="paper-account", symbol="BTCUSDT")
    assert len(liquidation) == 1
    assert liquidation[0].quantity == Decimal("1")
    assert liquidation[0].provenance["final_execution_price"] == "39.20"
    assert liquidation[0].provenance["fee"] == "0.3920"
    assert liquidation[0].provenance["rule_version"] == "perpetual-liquidation-v1"
    assert any(event.event_type == "perpetual_liquidation" for event in store.list_events())
    final = gateway.load_perpetual_accounting("paper-account", "BTCUSDT")
    assert final.quantity == Decimal("0")
    assert final.isolated_margin == Decimal("0")
    assert final.available_usdt >= Decimal("0")
    store.close()

    reopened_store = PaperStore(path)
    reopened = PaperGateway(reopened_store, policy=_policy())
    before = reopened.load_perpetual_accounting("paper-account", "BTCUSDT")
    before_liquidation = reopened_store.list_liquidation_fills(account_id="paper-account", symbol="BTCUSDT")
    assert reopened.advance_market(_observation(2, mark="40")) == ()
    assert reopened.advance_market(_observation(1, mark="100")) == ()
    assert reopened.advance_market(_observation(3, mark="20", funding_rate="0.01")) == ()
    assert reopened.load_perpetual_accounting("paper-account", "BTCUSDT") == before
    assert reopened_store.list_liquidation_fills(account_id="paper-account", symbol="BTCUSDT") == before_liquidation
    assert {incident.kind for incident in reopened_store.list_incidents()} >= {"out_of_order"}
    reopened_store.close()
