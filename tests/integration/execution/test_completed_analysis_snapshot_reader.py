"""Integration contracts for strict persisted completed-analysis snapshot reads."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.records.pending_writer import PendingWriter
from pa_agent.records.schema import (
    AnalysisRecord,
    ExecutionSafeAnalysisSnapshotV1,
    RecordMeta,
)
from pa_agent.trading.domain.models import OrderType, ProductType, Side
from pa_agent.trading.ports.analysis_records import (
    AnalysisRecordSnapshotReader,
    EligibleAnalysisRecord,
    IneligibleAnalysisRecord,
)


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
SOURCE_ID = "analysis:btc-usdt:2026-07-15T12:00:00Z"


def _execution_snapshot(**overrides: object) -> ExecutionSafeAnalysisSnapshotV1:
    values: dict[str, object] = {
        "source_id": SOURCE_ID,
        "schema_version": "analysis-record-execution-v1",
        "parser_version": "stage2-parser-v1",
        "completed_at": NOW,
        "repaired": False,
        "product": ProductType.SPOT,
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("1.25"),
        "price": Decimal("100"),
        "risk_basis": Decimal("10"),
    }
    values.update(overrides)
    values["binding_digest"] = ExecutionSafeAnalysisSnapshotV1.binding_digest_for(
        **values
    )
    return ExecutionSafeAnalysisSnapshotV1(**values)


def _record(snapshot: ExecutionSafeAnalysisSnapshotV1) -> AnalysisRecord:
    return AnalysisRecord(
        meta=RecordMeta(
            timestamp_local_iso=NOW.isoformat(),
            timestamp_local_ms=int(NOW.timestamp() * 1000),
            symbol="BTCUSDT",
            timeframe="1h",
            bar_count=100,
            ai_provider={"provider": "test"},
        ),
        kline_data=[],
        htf_text="",
        stage1_messages=[],
        stage1_response=None,
        stage1_diagnosis=None,
        stage2_messages=[],
        stage2_response=None,
        stage2_decision=None,
        strategy_files_used=[],
        experience_loaded=[],
        exception=None,
        usage_total={},
        execution_snapshot=snapshot,
    )


def _persist(tmp_path: Path, snapshot: ExecutionSafeAnalysisSnapshotV1) -> Path:
    return PendingWriter(pending_dir=tmp_path).save_full(_record(snapshot))


def _reader(tmp_path: Path) -> AnalysisRecordSnapshotReader:
    return AnalysisRecordSnapshotReader(pending_dir=tmp_path, utc_now=lambda: NOW)


def _rewrite(path: Path, mutate: callable) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_reader_reopens_only_a_complete_current_canonical_record_without_side_effects(
    tmp_path: Path,
) -> None:
    """The sole accepted input is a persisted current-schema immutable snapshot."""
    path = _persist(tmp_path, _execution_snapshot())
    before_read = path.read_bytes()

    reader = _reader(tmp_path)
    outcome = reader.read(SOURCE_ID)

    assert type(outcome) is EligibleAnalysisRecord
    assert outcome.source_id == SOURCE_ID
    assert outcome.snapshot.source_id == SOURCE_ID
    assert outcome.snapshot.completed_at == NOW
    assert outcome.snapshot.schema_version == "analysis-record-execution-v1"
    assert outcome.snapshot.parser_version == "stage2-parser-v1"
    assert outcome.snapshot.recommendation.quantity == Decimal("1.25")
    assert outcome.snapshot.recommendation.price == Decimal("100")
    assert outcome.snapshot.recommendation.risk_basis == Decimal("10")
    assert reader.load_completed_snapshot(SOURCE_ID) == outcome.snapshot
    assert path.read_bytes() == before_read
    assert not any(
        forbidden in attribute
        for attribute in vars(AnalysisRecordSnapshotReader)
        for forbidden in ("candidate", "ticket", "permit", "lease", "submit", "gateway")
    )


@pytest.mark.parametrize(
    ("name", "mutate", "reason_code"),
    (
        (
            "missing execution snapshot",
            lambda payload: payload.pop("execution_snapshot"),
            "MISSING_EXECUTION_SNAPSHOT",
        ),
        (
            "old execution schema",
            lambda payload: payload["execution_snapshot"].update(
                {"schema_version": "analysis-record-execution-v0"}
            ),
            "UNSUPPORTED_SCHEMA_VERSION",
        ),
        (
            "incomplete execution snapshot",
            lambda payload: payload["execution_snapshot"].pop("risk_basis"),
            "MALFORMED_EXECUTION_SNAPSHOT",
        ),
        (
            "binary float quantity",
            lambda payload: payload["execution_snapshot"].update({"quantity": 1.25}),
            "INVALID_CANONICAL_DECIMAL",
        ),
        (
            "malformed execution snapshot",
            lambda payload: payload.update({"execution_snapshot": "not-an-object"}),
            "MALFORMED_EXECUTION_SNAPSHOT",
        ),
        (
            "stale completed analysis",
            lambda payload: payload["execution_snapshot"].update(
                {"completed_at": (NOW - timedelta(seconds=61)).isoformat()}
            ),
            "SOURCE_ANALYSIS_STALE",
        ),
        (
            "repaired analysis",
            lambda payload: payload["execution_snapshot"].update({"repaired": True}),
            "REPAIRED_SOURCE",
        ),
        (
            "binding digest mismatch",
            lambda payload: payload["execution_snapshot"].update({"binding_digest": "forged"}),
            "DECISION_DIGEST_MISMATCH",
        ),
        (
            "missing Decimal quantity",
            lambda payload: payload["execution_snapshot"].update({"quantity": None}),
            "MISSING_QUANTITY_BASIS",
        ),
        (
            "unsupported product",
            lambda payload: payload["execution_snapshot"].update({"product": "options"}),
            "UNSUPPORTED_PRODUCT",
        ),
    ),
)
def test_reader_fails_closed_for_each_nonconforming_persisted_shape(
    tmp_path: Path,
    name: str,
    mutate: callable,
    reason_code: str,
) -> None:
    """Malformed durable data cannot gain a snapshot through defaults, migration, or inference."""
    path = _persist(tmp_path, _execution_snapshot())
    _rewrite(path, mutate)

    reader = _reader(tmp_path)
    outcome = reader.read(SOURCE_ID)

    assert type(outcome) is IneligibleAnalysisRecord, name
    assert outcome.source_id == SOURCE_ID
    assert outcome.reason_code == reason_code
    assert outcome.snapshot is None
    assert reader.load_completed_snapshot(SOURCE_ID) is None
