"""Read-only Paper product-evidence adapter with no execution authority."""
from __future__ import annotations

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.models import (
    AccountObservation,
    ExecutionCommand,
    Fill,
    GatewayCapabilities,
    GatewayEvidence,
    OrderProjection,
    ProductType,
    QuoteObservation,
    RuleObservation,
    TimeObservation,
)
from pa_agent.trading.domain.risk import (
    FeeRateObservation,
    IsolatedMarginProductEvidence,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    UsdtPerpetualProductEvidence,
)
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.ports.gateway import GatewayUnavailableError, TradingGateway
from pa_agent.trading.ports.ledger import OutboundSubmission


class PaperGateway(TradingGateway):
    """Expose committed Paper truth through read-only gateway queries only.

    This adapter deliberately has no facility to issue an order, permit, lease,
    command, or submission. Product evidence is reconstructed exclusively from
    the independently durable :class:`PaperStore`.
    """

    def __init__(self, store: PaperStore) -> None:
        if type(store) is not PaperStore:
            raise TypeError("PaperGateway requires its independent PaperStore")
        self._store = store

    def get_capabilities(self) -> GatewayCapabilities:
        """Declare the fixed offline products without invoking a venue."""
        return GatewayCapabilities(
            products=frozenset(ProductType),
            supports_order_lookup=False,
            supports_fill_lookup=False,
            supports_cancellation=False,
        )

    def get_server_time(self) -> TimeObservation:
        raise _unavailable("server time")

    def get_quote(self, symbol: str) -> QuoteObservation:
        del symbol
        raise _unavailable("quote")

    def get_instrument_rules(self, symbol: str) -> RuleObservation:
        del symbol
        raise _unavailable("instrument rules")

    def get_account_snapshot(
        self, account_id: str, product: ProductType
    ) -> AccountObservation:
        del account_id, product
        raise _unavailable("account snapshot")

    def get_connection(self, target: ExecutionTarget) -> TargetConnectionObservation:
        del target
        raise _unavailable("connection")

    def get_open_order_count(self, target: ExecutionTarget) -> OpenOrderObservation:
        del target
        raise _unavailable("open order count")

    def get_order_rate_window(
        self, target: ExecutionTarget, window_seconds: int
    ) -> OrderRateObservation:
        del target, window_seconds
        raise _unavailable("order rate window")

    def get_loss_drawdown(self, target: ExecutionTarget) -> LossDrawdownObservation:
        del target
        raise _unavailable("loss drawdown")

    def get_fee_rate(
        self, target: ExecutionTarget, symbol: str, quote_identifier: str
    ) -> FeeRateObservation:
        del target, symbol, quote_identifier
        raise _unavailable("fee rate")

    def get_isolated_margin_product_evidence(
        self, target: ExecutionTarget, isolated_symbol: str
    ) -> IsolatedMarginProductEvidence:
        """Return exactly one committed target/account/pair fact or fail closed."""
        evidence = self._store.load_isolated_margin_product_evidence(target, isolated_symbol)
        if evidence is None:
            raise _unavailable("isolated-margin product evidence")
        return evidence

    def get_usdt_perpetual_product_evidence(
        self, target: ExecutionTarget, symbol: str
    ) -> UsdtPerpetualProductEvidence:
        """Return exactly one committed target/account/symbol fact or fail closed."""
        evidence = self._store.load_usdt_perpetual_product_evidence(target, symbol)
        if evidence is None:
            raise _unavailable("perpetual product evidence")
        return evidence

    def submit_order(self, outbound: OutboundSubmission) -> GatewayEvidence:
        """Reject all submission attempts; this read adapter has no authority."""
        del outbound
        raise _unavailable("order submission")

    def cancel_order(self, client_order_id: str) -> GatewayEvidence:
        del client_order_id
        raise _unavailable("order cancellation")

    def lookup_order_by_client_id(self, client_order_id: str) -> GatewayEvidence | None:
        del client_order_id
        raise _unavailable("order lookup")

    def list_open_orders(
        self, account_id: str, product: ProductType
    ) -> tuple[OrderProjection, ...]:
        del account_id, product
        raise _unavailable("open-order projection")

    def list_fills(self, command_id: str) -> tuple[Fill, ...]:
        del command_id
        raise _unavailable("fill lookup")

    def reconcile(self, command: ExecutionCommand) -> tuple[GatewayEvidence, ...]:
        del command
        raise _unavailable("reconciliation")


def _unavailable(fact: str) -> GatewayUnavailableError:
    return GatewayUnavailableError(f"PaperGateway has no committed {fact} fact")
