"""Unit invariants for isolated-margin Paper accounting."""
from decimal import Decimal

import pytest

from pa_agent.trading.gateways.paper.accounting_margin import PaperMarginAccounting


def test_pair_scoped_collateral_debt_interest_and_health_never_offset() -> None:
    """A healthy BTC pair must not make an unhealthy ETH pair admissible."""
    btc = PaperMarginAccounting.from_initial_state(
        isolated_symbol="BTCUSDT",
        collateral="100",
        debt_principal="20",
        accrued_interest="0",
        borrow_available="80",
        repayment_required=True,
        observation_version=1,
    )
    eth = PaperMarginAccounting.from_initial_state(
        isolated_symbol="ETHUSDT",
        collateral="10",
        debt_principal="9",
        accrued_interest="0",
        borrow_available="0",
        repayment_required=True,
        observation_version=1,
    )

    assert btc.margin_health == Decimal("5")
    assert eth.margin_health == Decimal("1.111111111111111111111111111")
    assert btc.admits(notional="30", minimum_health="1.5") is True
    assert eth.admits(notional="1", minimum_health="1.5") is False

    advanced = btc.accrue_interest(observation_version=2, interest_rate="0.025")
    repaid = advanced.repay("5")

    assert advanced.accrued_interest == Decimal("0.5")
    assert repaid.accrued_interest == Decimal("0")
    assert repaid.debt_principal == Decimal("15.5")
    assert eth.debt_principal == Decimal("9")
    assert eth.accrued_interest == Decimal("0")
    with pytest.raises(ValueError, match="newer"):
        advanced.accrue_interest(observation_version=1, interest_rate="0.025")
