"""Canonical, synchronous gateway contract for future trading adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod

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
from pa_agent.trading.ports.ledger import OutboundSubmission


class TradingGatewayError(TradingDomainError):
    """Base typed failure a gateway may raise without exposing transport details."""


class GatewayUnavailableError(TradingGatewayError):
    """Raised when a gateway cannot obtain requested canonical evidence."""


class GatewayAmbiguityError(TradingGatewayError):
    """Raised when a remote command outcome is uncertain and requires reconciliation."""


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
    def submit_order(self, outbound: OutboundSubmission) -> GatewayEvidence:
        """Submit exactly the ledger-created irreversible outbound authorization.

        The authorization carries the durable generated client-order ID and its
        reconstructed command. Ambiguous outcomes raise
        :class:`GatewayAmbiguityError`; callers retain the same persisted
        identities and reconcile rather than allocate another command.
        """

    @abstractmethod
    def cancel_order(self, client_order_id: str) -> GatewayEvidence:
        """Request cancellation by the durable client-order ID and return evidence."""

    @abstractmethod
    def lookup_order_by_client_id(self, client_order_id: str) -> GatewayEvidence | None:
        """Return normalized order evidence by durable client-order ID when observed."""

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
