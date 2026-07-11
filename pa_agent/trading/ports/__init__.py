"""Canonical contracts for gateway, ledger, and time dependencies."""

from pa_agent.trading.ports.clock import UtcClock
from pa_agent.trading.ports.gateway import (
    GatewayAmbiguityError,
    GatewayUnavailableError,
    TradingGateway,
    TradingGatewayError,
)
from pa_agent.trading.ports.ledger import (
    ExecutionLedger,
    OutboundSubmission,
    ReconciliationJob,
    ReconciliationResult,
    SubmissionAdmission,
)

__all__ = [
    "ExecutionLedger",
    "GatewayAmbiguityError",
    "GatewayUnavailableError",
    "OutboundSubmission",
    "ReconciliationJob",
    "ReconciliationResult",
    "SubmissionAdmission",
    "TradingGateway",
    "TradingGatewayError",
    "UtcClock",
]
