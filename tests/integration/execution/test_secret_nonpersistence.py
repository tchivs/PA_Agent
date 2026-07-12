"""Integration coverage for non-secret trading settings and safe persisted payloads."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pa_agent.config.settings import Settings, TradingSettings, load_settings, save_settings
from pa_agent.trading.security.credentials import CredentialReference
from pa_agent.trading.security.redaction import REDACTION_TOKEN, SecretRedactor

API_KEY = "synthetic-api-key-9f5c"
API_SECRET = "synthetic-api-secret-31bc"
PASSPHRASE = "synthetic-passphrase-7da2"
SIGNATURE = "synthetic-signature-a48e"


def test_settings_round_trip_persists_only_non_secret_trading_reference(tmp_path: Path) -> None:
    """Generic settings persistence retains target metadata but never credential material."""
    path = tmp_path / "settings.json"
    settings = Settings(
        trading=TradingSettings(
            credential_reference=CredentialReference(
                provider="environment", reference_id="paper-spot-default"
            )
        )
    )

    save_settings(settings, path)
    reloaded = load_settings(path)
    persisted = path.read_text(encoding="utf-8")

    assert reloaded.trading.target == "paper-spot"
    assert reloaded.trading.policy_version == "phase2-v1"
    assert reloaded.trading.credential_reference == settings.trading.credential_reference
    assert "paper-spot-default" in persisted
    for secret in (API_KEY, API_SECRET, PASSPHRASE, SIGNATURE):
        assert secret not in persisted


@pytest.mark.parametrize(
    "unsafe_settings",
    (
        {"trading": {"api_key": API_KEY}},
        {"trading": {"secret": API_SECRET}},
        {"trading": {"passphrase": PASSPHRASE}},
        {"trading": {"target": "testnet-spot"}},
        {"trading": {"target": "live-spot"}},
        {"trading": {"credential_reference": {"requested_permissions": ["trade", "withdraw"]}}},
    ),
)
def test_trading_settings_reject_secret_like_or_unavailable_values(
    unsafe_settings: dict[str, object],
) -> None:
    """Secret fields, unsupported targets, and withdrawal requests fail validation."""
    with pytest.raises(ValidationError):
        Settings.model_validate(unsafe_settings)


def test_persisted_audit_payload_uses_recursive_redaction_before_serialization(tmp_path: Path) -> None:
    """A controlled audit payload retains no synthetic request or exception secret."""
    path = tmp_path / "audit.json"
    redactor = SecretRedactor((API_KEY, API_SECRET, PASSPHRASE, SIGNATURE))
    audit_payload = redactor.redact(
        {
            "event": "credential_lookup_failed",
            "headers": {"authorization": f"Bearer {API_KEY}"},
            "query": {"api_key": API_KEY, "signature": SIGNATURE},
            "error": RuntimeError(f"remote failure with {API_SECRET} and {PASSPHRASE}"),
        }
    )
    path.write_text(json.dumps(audit_payload, default=str), encoding="utf-8")

    persisted = path.read_text(encoding="utf-8")

    for secret in (API_KEY, API_SECRET, PASSPHRASE, SIGNATURE):
        assert secret not in persisted
    assert REDACTION_TOKEN in persisted
