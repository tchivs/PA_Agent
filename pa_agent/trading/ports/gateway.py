"""Canonical, synchronous gateway contract for future trading adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.errors import TradingDomainError
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
from pa_agent.trading.ports.ledger import OutboundSubmission


class TradingGatewayError(TradingDomainError):
    """Base typed failure a gateway may raise without exposing transport details."""


class GatewayUnavailableError(TradingGatewayError):
    """Raised when a gateway cannot obtain requested canonical evidence."""


class GatewayAmbiguityError(TradingGatewayError):
    """Raised when a remote command outcome is uncertain and requires reconciliation."""


@dataclass(frozen=True, slots=True)
class GatewayOperationReference:
    """Opaque durable identity for one gateway operation; it grants read access only."""

    operation_id: str
    client_order_id: str

    def __post_init__(self) -> None:
        if not all((type(self.operation_id) is str, self.operation_id, type(self.client_order_id) is str, self.client_order_id)):
            raise ValueError("gateway operation references require persisted string identities")


@dataclass(frozen=True, slots=True)
class GatewayOperationResult:
    """Immutable normalized result with an opaque reference to durable gateway facts."""

    evidence: GatewayEvidence | None
    reference: GatewayOperationReference


class GatewayOperationObserver(ABC):
    """Read-only post-operation sink; implementations receive no execution authority."""

    @abstractmethod
    def observe_operation(self, result: GatewayOperationResult) -> None:
        """Observe one immutable gateway result after the producer commits its truth."""


class TradingGateway(ABC):
    """Synchronous, canonical-only boundary implemented by future venue adapters.

    Adapters normalize any venue payload before returning from this contract and
    raise only ``TradingGatewayError`` subclasses for expected gateway failures.
    Submission accepts only an irreversible ledger-created authorization, so an
    adapter never receives a free-floating command or a revocable claim check.
    """

    @abstractmethod
    def get_capabilities(self) -> GatewayCapabilities:
        """Return the normalized products and recovery features this gateway supports."""

    @abstractmethod
    def get_server_time(self) -> TimeObservation:
        """Return observed venue server time as canonical UTC evidence."""

    @abstractmethod
    def get_quote(self, symbol: str) -> QuoteObservation:
        """Return the current canonical bid and ask observation for ``symbol``."""

    @abstractmethod
    def get_instrument_rules(self, symbol: str) -> RuleObservation:
        """Return current canonical trading rules for ``symbol``."""

    @abstractmethod
    def get_account_snapshot(
        self, account_id: str, product: ProductType
    ) -> AccountObservation:
        """Return canonical account evidence scoped to one account and product."""

    @abstractmethod
    def get_connection(self, target: ExecutionTarget) -> TargetConnectionObservation:
        """Return fresh normalized connectivity for exactly one execution target."""

    @abstractmethod
    def get_open_order_count(self, target: ExecutionTarget) -> OpenOrderObservation:
        """Return the current target-bound open-order counter."""

    @abstractmethod
    def get_order_rate_window(
        self, target: ExecutionTarget, window_seconds: int
    ) -> OrderRateObservation:
        """Return the current target-bound accepted-order count for one exact window."""

    @abstractmethod
    def get_loss_drawdown(self, target: ExecutionTarget) -> LossDrawdownObservation:
        """Return current target-bound UTC-day realized-loss and drawdown evidence."""

    @abstractmethod
    def get_fee_rate(
        self, target: ExecutionTarget, symbol: str, quote_identifier: str
    ) -> FeeRateObservation:
        """Return the current target/symbol/quote-bound fee rate version."""

    @abstractmethod
    def get_isolated_margin_product_evidence(
        self, target: ExecutionTarget, isolated_symbol: str
    ) -> IsolatedMarginProductEvidence:
        """Return fresh exact-target and exact-pair isolated-margin facts only."""

    @abstractmethod
    def get_usdt_perpetual_product_evidence(
        self, target: ExecutionTarget, symbol: str
    ) -> UsdtPerpetualProductEvidence:
        """Return fresh exact-target and exact-symbol perpetual facts only."""

    @abstractmethod
    def submit_order(self, outbound: OutboundSubmission) -> GatewayOperationResult:
        """Submit exactly the ledger-created irreversible outbound authorization.

        The authorization carries the durable generated client-order ID and its
        reconstructed command. Ambiguous outcomes raise
        :class:`GatewayAmbiguityError`; callers retain the same persisted
        identities and reconcile rather than allocate another command.
        """

    @abstractmethod
    def cancel_order(self, client_order_id: str) -> GatewayOperationResult:
        """Request cancellation by durable client ID and return its immutable operation result."""

    @abstractmethod
    def lookup_order_by_client_id(self, client_order_id: str) -> GatewayOperationResult | None:
        """Return immutable normalized order evidence by durable client ID when observed."""

    @abstractmethod
    def list_open_orders(
        self, account_id: str, product: ProductType
    ) -> tuple[OrderProjection, ...]:
        """Return the gateway's canonical open-order projection for an account scope."""

    @abstractmethod
    def list_fills(self, command_id: str) -> tuple[Fill, ...]:
        """Return normalized fills known for the persisted command ID."""

    @abstractmethod
    def reconcile(self, command: ExecutionCommand) -> tuple[GatewayEvidence, ...]:
        """Return reconciliation evidence using only the command's persisted identities."""
