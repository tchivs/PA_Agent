"""Unit coverage for credential isolation and recursive output redaction."""
from __future__ import annotations

import pytest

from pa_agent.trading.security.credentials import (
    CredentialCapabilities,
    CredentialReference,
    CredentialSecurityError,
    ProviderCredentialResult,
    deliver_trading_credentials,
)
from pa_agent.trading.security.redaction import REDACTION_TOKEN, SecretRedactor

API_KEY = "synthetic-api-key-9f5c"
API_SECRET = "synthetic-api-secret-31bc"
PASSPHRASE = "synthetic-passphrase-7da2"
SIGNATURE = "synthetic-signature-a48e"


class RecordingExecutionConsumer:
    """Records credential material only when the security boundary permits it."""

    def __init__(self) -> None:
        self.received: list[ProviderCredentialResult] = []

    def receive(self, result: ProviderCredentialResult) -> None:
        self.received.append(result)


def test_reference_only_contract_exposes_no_secret_backend_or_withdrawal_grant() -> None:
    """A store boundary receives opaque metadata and its capability is trade-only."""
    reference = CredentialReference(provider="environment", reference_id="paper-spot-default")
    capabilities = CredentialCapabilities()

    assert reference.provider == "environment"
    assert reference.reference_id == "paper-spot-default"
    assert capabilities.trading_allowed is True
    assert capabilities.withdrawal_allowed is False
    assert not hasattr(reference, "api_key")
    assert not hasattr(reference, "secret")


@pytest.mark.parametrize(
    "result",
    (
        ProviderCredentialResult(
            reference=CredentialReference(provider="environment", reference_id="paper-spot-default"),
            values={"api_key": API_KEY, "secret": API_SECRET},
            declared_permissions=frozenset({"trade", "withdraw"}),
        ),
        ProviderCredentialResult(
            reference=CredentialReference(provider="environment", reference_id="paper-spot-default"),
            values={"api_key": API_KEY, "secret": API_SECRET},
            declared_permissions=frozenset({"withdraw"}),
        ),
    ),
)
def test_withdrawal_capable_provider_result_is_rejected_before_execution_consumer(
    result: ProviderCredentialResult,
) -> None:
    """No execution-facing consumer can receive a withdrawal-capable result."""
    consumer = RecordingExecutionConsumer()

    with pytest.raises(CredentialSecurityError, match="credential_permission_rejected"):
        deliver_trading_credentials(result, consumer.receive)

    assert consumer.received == []


def test_credential_failure_exposes_only_a_controlled_reason_code() -> None:
    """Credential validation never renders resolved material in its public failure."""
    result = ProviderCredentialResult(
        reference=CredentialReference(provider="environment", reference_id="paper-spot-default"),
        values={"api_key": API_KEY, "secret": API_SECRET, "passphrase": PASSPHRASE},
        declared_permissions=frozenset({"trade", "withdraw"}),
    )

    with pytest.raises(CredentialSecurityError) as raised:
        deliver_trading_credentials(result, lambda _: None)

    rendered = str(raised.value)
    assert rendered == "credential_permission_rejected"
    for secret in (API_KEY, API_SECRET, PASSPHRASE):
        assert secret not in rendered


def test_withdrawal_capable_reference_is_rejected_before_provider_lookup() -> None:
    """A reference cannot ask a provider for a withdrawal-capable credential."""
    with pytest.raises(CredentialSecurityError, match="withdraw"):
        CredentialReference(
            provider="environment",
            reference_id="paper-spot-default",
            requested_permissions=frozenset({"trade", "withdraw"}),
        )


def test_recursive_redaction_removes_registered_values_and_sensitive_shapes() -> None:
    """Nested payloads, exceptions, headers, queries, and signature fields are safe."""
    redactor = SecretRedactor((API_KEY, API_SECRET, PASSPHRASE, SIGNATURE))
    payload = {
        "request": {
            "headers": {"Authorization": f"Bearer {API_KEY}", "X-API-KEY": API_KEY},
            "url": f"https://example.invalid/order?api_key={API_KEY}&signature={SIGNATURE}",
            "signature": SIGNATURE,
        },
        "nested": [
            {"secret": API_SECRET, "safe": "visible"},
            (f"failure carrying {PASSPHRASE}", {"passphrase": PASSPHRASE}),
        ],
        "exception": ValueError(f"authorization failed: {API_SECRET}"),
    }

    redacted = redactor.redact(payload)
    rendered = repr(redacted)

    for secret in (API_KEY, API_SECRET, PASSPHRASE, SIGNATURE):
        assert secret not in rendered
    assert redacted["nested"][0]["safe"] == "visible"
    assert redacted["request"]["headers"]["Authorization"] == REDACTION_TOKEN
    assert redacted["request"]["signature"] == REDACTION_TOKEN
    assert REDACTION_TOKEN in rendered
