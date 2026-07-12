"""Reference-only credential lookup contract for future trading adapters."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pa_agent.trading.security.credentials import CredentialReference, ProviderCredentialResult


@runtime_checkable
class CredentialStore(Protocol):
    """Looks up runtime credential material from an opaque, non-secret reference."""

    def resolve(self, reference: CredentialReference) -> ProviderCredentialResult:
        """Return a provider result for a validated trading-only reference."""
