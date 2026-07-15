"""Real SQLite regressions for Paper product scopes through the runtime bridge."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pa_agent.trading.application.paper_runtime import PaperTradingRuntime
from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.models import Mode, ProductType
from pa_agent.trading.domain.paper import DepthLevel, MarketObservation, PaperEconomicPolicy
from pa_agent.trading.gateways.paper.accounting_margin import PaperMarginAccounting
from pa_agent.trading.gateways.paper.accounting_perpetual import PaperPerpetualAccounting
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger

pytestmark = pytest.mark.integration
NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _policy(product: ProductType) -> PaperEconomicPolicy:
    return PaperEconomicPolicy(
        product=product,
        policy_version=f"paper-{product.value}-v1",
        fee_rate="0.001",
        fee_rule_version="fee-v1",
        slippage_rate="0",
        slippage_rule_version="slippage-v1",
        interest_rate="0.01",
        minimum_margin_health="1.25",
        maximum_leverage="3",
        maintenance_margin_rate="0.10",
    )


def _observation(product: ProductType, version: int) -> MarketObservation:
    return MarketObservation(
        observation_id=f"{product.value}-{version}",
        account_id="paper-account",
        product=product,
        symbol="BTCUSDT",
        version=version,
        observed_at=NOW,
        asks=(DepthLevel("100", "1"),),
        bids=(DepthLevel("99", "1"),),
        mark_price="100" if product is ProductType.USDT_PERPETUAL else None,
    )


@pytest.mark.parametrize("product", [ProductType.ISOLATED_MARGIN, ProductType.USDT_PERPETUAL])
def test_runtime_preserves_exact_nonspot_scope_truth_through_reopen(product: ProductType, tmp_path: Path) -> None:
    """The one production composition seam must seed each non-Spot Paper account type."""
    ledger_path = tmp_path / f"{product.value}-ledger.sqlite"
    paper_path = tmp_path / f"{product.value}-paper.sqlite"
    kwargs: dict[str, object]
    if product is ProductType.ISOLATED_MARGIN:
        kwargs = {
            "initial_margin_accounts": {
                "BTCUSDT": PaperMarginAccounting.from_initial_state(
                    isolated_symbol="BTCUSDT",
                    collateral="100",
                    debt_principal="20",
                    accrued_interest="0",
                    borrow_available="100",
                    repayment_required=True,
                    observation_version=1,
                )
            }
        }
        version = 2
    else:
        kwargs = {
            "initial_perpetual_accounts": {
                "BTCUSDT": PaperPerpetualAccounting.from_initial_state(
                    symbol="BTCUSDT", available_usdt="1000"
                )
            }
        }
        version = 1

    runtime = PaperTradingRuntime(
        ledger=SQLiteExecutionLedger(ledger_path),
        store=PaperStore(paper_path),
        policy=_policy(product),
        **kwargs,
    )
    try:
        assert runtime.gateway.advance_market(_observation(product, version)) == ()
        target = ExecutionTarget(
            "paper-margin-isolated-primary" if product is ProductType.ISOLATED_MARGIN else "paper-usdt-perpetual-primary",
            Mode.PAPER,
            "paper-account",
            product,
        )
        if product is ProductType.ISOLATED_MARGIN:
            truth = runtime.gateway.get_isolated_margin_product_evidence(target, "BTCUSDT")
            assert truth.isolated_symbol == "BTCUSDT"
            assert truth.observation_version == version
        else:
            truth = runtime.gateway.get_usdt_perpetual_product_evidence(target, "BTCUSDT")
            assert truth.symbol == "BTCUSDT"
            assert truth.observation_version == version
    finally:
        runtime.close()

    reopened = PaperTradingRuntime(
        ledger=SQLiteExecutionLedger(ledger_path),
        store=PaperStore(paper_path),
        policy=_policy(product),
    )
    try:
        assert reopened.gateway.advance_market(_observation(product, version)) == ()
        assert reopened.gateway._submission_invocations == 0  # noqa: SLF001 - recovery never gains submit authority
    finally:
        reopened.close()
