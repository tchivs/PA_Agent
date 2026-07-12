"""Trading-only credential references and provider-result validation."""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

_TRADING_PERMISSION = "trade"
_WITHDRAWAL_PERMISSION = "withdraw"


class CredentialSecurityError(ValueError):
    """Raised when a credential reference or provider result exceeds trade-only scope."""


@dataclass(frozen=True)
class CredentialReference:
    """Opaque metadata identifying a credential without containing credential material."""

    provider: str
    reference_id: str
    requested_permissions: frozenset[str] = field(default_factory=lambda: frozenset({_TRADING_PERMISSION}))

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.reference_id.strip():
            raise CredentialSecurityError("credential references require provider and reference_id")
        _require_trading_only_permissions(self.requested_permissions)


@dataclass(frozen=True)
class CredentialCapabilities:
    """The fixed capability contract for a resolved trading credential."""

    trading_allowed: bool = True

    @property
    def withdrawal_allowed(self) -> bool:
        """Withdrawal is deliberately not a grantable capability."""
        return False


@dataclass(frozen=True)
class ProviderCredentialResult:
    """In-memory provider output that must be validated before execution use."""

    reference: CredentialReference
    values: Mapping[str, str]
    declared_permissions: frozenset[str] = field(default_factory=lambda: frozenset({_TRADING_PERMISSION}))
    capabilities: CredentialCapabilities = field(default_factory=CredentialCapabilities)


def _require_trading_only_permissions(permissions: frozenset[str]) -> None:
    if _WITHDRAWAL_PERMISSION in permissions:
        raise CredentialSecurityError("withdrawal permission is forbidden for trading credentials")
    if permissions != frozenset({_TRADING_PERMISSION}):
        raise CredentialSecurityError("credential permissions must be exactly trade-only")


def validate_provider_result(result: ProviderCredentialResult) -> ProviderCredentialResult:
    """Fail closed unless a provider result remains strictly trade-only."""
    _require_trading_only_permissions(result.reference.requested_permissions)
    _require_trading_only_permissions(result.declared_permissions)
    if not result.capabilities.trading_allowed or result.capabilities.withdrawal_allowed:
        raise CredentialSecurityError("credential capabilities must remain trade-only without withdrawal")
    return result


def deliver_trading_credentials(
    result: ProviderCredentialResult,
    consumer: Callable[[ProviderCredentialResult], None],
) -> None:
    """Validate a provider result before an execution-facing consumer can receive it."""
    consumer(validate_provider_result(result))


class UnavailableCredentialStore:
    """Default store that fails closed until Phase 5 injects an approved provider."""

    def resolve(self, reference: CredentialReference) -> ProviderCredentialResult:
        raise CredentialSecurityError(
            f"credential provider {reference.provider!r} is unavailable in Phase 2"
        )


class EnvironmentCredentialStore:
    """Test-only environment provider that keeps returned material in memory."""

    def __init__(self, *, variables_by_reference: Mapping[str, tuple[str, ...]]) -> None:
        self._variables_by_reference = dict(variables_by_reference)

    def resolve(self, reference: CredentialReference) -> ProviderCredentialResult:
        variable_names = self._variables_by_reference.get(reference.reference_id)
        if variable_names is None:
            raise CredentialSecurityError("credential reference is not configured for the environment provider")
        values = {name.lower(): os.environ[name] for name in variable_names if name in os.environ}
        if len(values) != len(variable_names):
            raise CredentialSecurityError("environment credential material is unavailable")
        return validate_provider_result(ProviderCredentialResult(reference=reference, values=values))
