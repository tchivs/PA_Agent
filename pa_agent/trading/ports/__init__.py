"""Canonical contracts for gateway, ledger, and time dependencies."""

from pa_agent.trading.ports.clock import UtcClock
from pa_agent.trading.ports.gateway import (
    GatewayAmbiguityError,
    GatewayUnavailableError,
    TradingGateway,
    TradingGatewayError,
)

__all__ = [
    "GatewayAmbiguityError",
    "GatewayUnavailableError",
    "TradingGateway",
    "TradingGatewayError",
    "UtcClock",
]
