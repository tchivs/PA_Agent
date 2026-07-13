"""Deterministic, invocation-indexed Paper gateway fault seam."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from pa_agent.trading.ports.gateway import GatewayAmbiguityError


@dataclass(frozen=True)
class FaultPlan:
    """Raise only configured ambiguity faults at stable one-based invocation indexes."""

    ambiguity_at: Mapping[int, str]

    def __post_init__(self) -> None:
        values = dict(self.ambiguity_at)
        if any(type(index) is not int or index <= 0 or type(reason) is not str or not reason for index, reason in values.items()):
            raise ValueError("paper fault plan indexes and reasons must be canonical")
        object.__setattr__(self, "ambiguity_at", MappingProxyType(values))

    def raise_if_planned(self, invocation: int) -> None:
        """Raise a reproducible post-acceptance ambiguity without random behavior."""
        reason = self.ambiguity_at.get(invocation)
        if reason is not None:
            raise GatewayAmbiguityError(reason)
