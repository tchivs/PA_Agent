"""Integration coverage for non-secret trading settings and safe persisted payloads."""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from pa_agent.config.settings import Settings, TradingSettings, load_settings, save_settings
from pa_agent.trading.security.credentials import CredentialReference
from pa_agent.trading.security.redaction import REDACTION_TOKEN, SecretRedactor
from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.application.proposal import ProposalService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.models import (
    Balance,
    GatewayCapabilities,
    InstrumentRules,
    ProductType,
    QuoteObservation,
    RuleObservation,
    TimeObservation,
)
from pa_agent.trading.domain.risk import (
    FeeRateObservation,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    select_phase2_policy,
)
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from pa_agent.util.logging import MaskingFormatter
from pa_agent.records.pending_writer import PendingWriter
from pa_agent.records.schema import AnalysisRecord, RecordMeta
from pa_agent.records import trade_logger
from pa_agent.notify import feishu_notifier, pushplus_notifier
from tests.fixtures.execution_factories import (
    make_account_observation,
    make_analysis_recommendation,
    make_execution_target,
    make_source_analysis_snapshot,
)
from tests.fixtures.fake_exchange import ScriptedEvidenceGateway

API_KEY = "synthetic-api-key-9f5c"
API_SECRET = "synthetic-api-secret-31bc"
PASSPHRASE = "synthetic-passphrase-7da2"
SIGNATURE = "synthetic-signature-a48e"
AUTHORIZATION = "Bearer synthetic-authorization-594d"
QUERY_SECRET = "synthetic-query-value-b2d7"
EXCEPTION_SECRET = "synthetic-exception-body-f24c"
SECRETS = (API_KEY, API_SECRET, PASSPHRASE, SIGNATURE, AUTHORIZATION, QUERY_SECRET, EXCEPTION_SECRET)
NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


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


def _assert_no_secret(rendered: str) -> None:
    for secret in SECRETS:
        assert secret not in rendered


def _gateway() -> ScriptedEvidenceGateway:
    target = make_execution_target()
    return ScriptedEvidenceGateway(
        capabilities=[GatewayCapabilities(frozenset({ProductType.SPOT}), True)],
        rules=[RuleObservation(InstrumentRules("BTCUSDT", "0.50", "0.001", "0.001", "10"), NOW)],
        accounts=[make_account_observation(observed_at=NOW, balances=(Balance("USDT", "2000", "1500", "0"),), positions=())],
        quotes=[QuoteObservation("BTCUSDT", "7999.50", "8000", NOW)],
        server_times=[TimeObservation(server_time=NOW, observed_at=NOW)],
        connections=[TargetConnectionObservation(target, True, NOW)],
        open_orders=[OpenOrderObservation(target, 2, NOW)],
        order_rates=[OrderRateObservation(target, 4, NOW - timedelta(seconds=60), NOW)],
        loss_drawdowns=[LossDrawdownObservation(target, "99", "0.09", NOW, NOW)],
        fee_rates=[FeeRateObservation(target, "BTCUSDT", "BTCUSDT", "USDT", "0.001", "fees-v1", NOW)],
    )


def test_proposal_service_and_sqlite_audit_do_not_persist_injected_secret_material(tmp_path: Path) -> None:
    """The real proposal/audit path persists canonical facts, not source secret text."""
    database = tmp_path / "execution.sqlite3"
    ledger = SQLiteExecutionLedger(database)
    target = make_execution_target()
    service = ProposalService(
        ledger=ledger,
        intent_factory=IntentFactory(),
        evidence_collector=FreshEvidenceCollector(gateway=_gateway(), utc_now=lambda: NOW),
        risk_engine=RiskEngine(),
    )
    snapshot = make_source_analysis_snapshot(
        recommendation=make_analysis_recommendation(price="8000", quantity="0.125"),
        source_id=f"analysis-{API_KEY}-{API_SECRET}-{PASSPHRASE}-{SIGNATURE}-{QUERY_SECRET}",
    )

    candidate = service.propose(snapshot, target)
    assert candidate is not None
    service.assess(candidate, target, select_phase2_policy(target))
    ledger.close()

    _assert_no_secret(database.read_bytes().decode("utf-8", errors="ignore"))
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute("SELECT summary_json FROM proposal_audit_facts").fetchall()
    finally:
        connection.close()
    _assert_no_secret(repr(rows))


def test_masking_formatter_redacts_registered_values_and_exception_text() -> None:
    """Configured root-format output cannot retain sensitive message or exception data."""
    formatter = MaskingFormatter("%(message)s", api_key=API_KEY)
    record = logging.LogRecord(
        "secret-test", logging.ERROR, __file__, 1,
        "failure %s %s %s %s", (API_SECRET, PASSPHRASE, SIGNATURE, QUERY_SECRET), None,
    )
    record.exc_info = (RuntimeError, RuntimeError(f"{AUTHORIZATION} {EXCEPTION_SECRET}"), None)

    rendered = formatter.format(record)

    _assert_no_secret(rendered)
    assert REDACTION_TOKEN in rendered


def _analysis_record() -> AnalysisRecord:
    return AnalysisRecord(
        meta=RecordMeta(
            timestamp_local_iso="2026-07-12T12:00:00+00:00",
            timestamp_local_ms=1_784_000_000_000,
            symbol="BTCUSDT",
            timeframe="1h",
            bar_count=1,
            ai_provider={"authorization": AUTHORIZATION},
        ),
        kline_data=[], htf_text=EXCEPTION_SECRET, stage1_messages=[{"api_key": API_KEY}],
        stage1_response={"secret": API_SECRET}, stage1_diagnosis=None,
        stage2_messages=[{"passphrase": PASSPHRASE}], stage2_response={"signature": SIGNATURE},
        stage2_decision=None, strategy_files_used=[], experience_loaded=[],
        exception={"message": f"{EXCEPTION_SECRET} {QUERY_SECRET}"}, usage_total={},
    )


def test_pending_writer_generated_json_does_not_retain_secrets(tmp_path: Path) -> None:
    """PendingWriter sanitizes the concrete JSON file it produces."""
    path = PendingWriter(pending_dir=tmp_path, api_key=API_KEY).save_full(_analysis_record())

    rendered = path.read_text(encoding="utf-8")
    _assert_no_secret(rendered)
    assert REDACTION_TOKEN in rendered


def test_trade_logger_generated_csv_does_not_retain_decision_secrets(tmp_path: Path) -> None:
    """save_trade_record sanitizes its concrete CSV output before writing it."""
    decision = {
        "reasoning": f"{API_KEY} {API_SECRET} {PASSPHRASE} {SIGNATURE} {QUERY_SECRET}",
        "watch_points": [AUTHORIZATION, EXCEPTION_SECRET],
    }
    with patch.object(trade_logger, "_TRADE_RECORDS_DIR", tmp_path), patch.object(
        trade_logger, "_render_chart", return_value=False
    ), patch.dict(sys.modules, {"pa_agent.ai.decision_continuity": SimpleNamespace(
        audit_relation_fields=lambda *_args, **_kwargs: {}, load_last_trade_csv_row=lambda *_args: None
    )}):
        trade_logger.save_trade_record(
            decision_inner=decision, stage2_full={}, stage1_diagnosis=None, frame=None,
            meta_symbol="BTCUSDT", meta_timeframe="1h", decision_stance="advisory", model_name="test",
        )

    rendered = (tmp_path / "BTCUSDT_1h.csv").read_text(encoding="utf-8-sig")
    _assert_no_secret(rendered)
    assert REDACTION_TOKEN in rendered


def test_feishu_and_pushplus_payloads_do_not_forward_secret_bearing_decisions() -> None:
    """Both real notification entry points produce advisory-only redacted payloads."""
    requests = SimpleNamespace(post=lambda *_args, **_kwargs: SimpleNamespace(json=lambda: {"code": 0}))
    captured: list[dict[str, object]] = []

    def post(*args: object, **kwargs: object) -> SimpleNamespace:
        captured.append(kwargs["json"])
        return SimpleNamespace(json=lambda: {"code": 200 if "pushplus" in str(args[0]) else 0})

    requests.post = post
    decision = {"reasoning": " ".join(SECRETS), "watch_points": list(SECRETS)}
    feishu_settings = SimpleNamespace(feishu=SimpleNamespace(model_dump=lambda: {"enabled": True, "webhook_url": "https://example.invalid", "secret": API_SECRET}))
    pushplus_settings = SimpleNamespace(pushplus=SimpleNamespace(model_dump=lambda: {"enabled": True, "token": API_KEY}))
    with patch.dict(sys.modules, {"requests": requests}):
        assert feishu_notifier.send_order_signal(decision_inner=decision, stage2_full={}, symbol="BTCUSDT", timeframe="1h", settings=feishu_settings) is True
        assert pushplus_notifier.send_order_signal(decision_inner=decision, stage2_full={}, symbol="BTCUSDT", timeframe="1h", settings=pushplus_settings) is True

    assert len(captured) == 2
    _assert_no_secret(repr(captured))
    assert REDACTION_TOKEN in repr(captured)
