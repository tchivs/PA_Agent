"""The sole production composition seam for Paper operation observation and audit projection."""
from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from pa_agent.trading.application.paper_projection import (
    PaperEvidenceProjector,
    PaperProjectionBridge,
)
from pa_agent.trading.application.recovery import RecoveryService
from pa_agent.trading.application.submission import SubmissionCoordinator
from pa_agent.trading.domain.paper import PaperEconomicPolicy
from pa_agent.trading.gateways.paper.accounting_margin import PaperMarginAccounting
from pa_agent.trading.gateways.paper.accounting_perpetual import PaperPerpetualAccounting
from pa_agent.trading.gateways.paper.faults import FaultPlan
from pa_agent.trading.gateways.paper.gateway import PaperGateway, PaperOperationBatch
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.ports.ledger import ExecutionLedger
from pa_agent.trading.ports.gateway import GatewayOperationReference


class _BoundPaperReader:
    """One-time runtime binding that exposes only committed operation reads to the bridge."""

    def __init__(self) -> None:
        self._gateway: PaperGateway | None = None

    def bind(self, gateway: PaperGateway) -> None:
        if self._gateway is not None:
            raise RuntimeError("Paper projection reader is bound once")
        self._gateway = gateway

    def read_operation(self, reference: GatewayOperationReference) -> PaperOperationBatch:
        if self._gateway is None:
            raise RuntimeError("Paper projection reader is not composed")
        return self._gateway.read_operation(reference)


class PaperTradingRuntime:
    """Compose one read-only projection bridge into every Paper operation owner."""

    def __init__(
        self,
        *,
        ledger: ExecutionLedger,
        store: PaperStore,
        policy: PaperEconomicPolicy | None = None,
        initial_balances: Mapping[str, Decimal | str] | None = None,
        initial_margin_accounts: Mapping[str, PaperMarginAccounting] | None = None,
        initial_perpetual_accounts: Mapping[str, PaperPerpetualAccounting] | None = None,
        fault_plan: FaultPlan | None = None,
    ) -> None:
        reader = _BoundPaperReader()
        projector = PaperEvidenceProjector(ledger=ledger)
        bridge = PaperProjectionBridge(reader=reader, projector=projector)
        gateway = PaperGateway(
            store,
            policy=policy,
            initial_balances=initial_balances,
            initial_margin_accounts=initial_margin_accounts,
            initial_perpetual_accounts=initial_perpetual_accounts,
            fault_plan=fault_plan,
            leased_submission_verifier=ledger,
            operation_observer=bridge,
        )
        reader.bind(gateway)
        self.gateway = gateway
        self.submission = SubmissionCoordinator(ledger=ledger, gateway=gateway, operation_observer=bridge)
        self.recovery = RecoveryService(ledger=ledger, gateway=gateway, operation_observer=bridge)
        self.ledger = ledger
        self._store = store

    def close(self) -> None:
        """Close independently durable Paper and central audit connections deterministically."""
        self._store.close()
        close = getattr(self.ledger, "close", None)
        if callable(close):
            close()
