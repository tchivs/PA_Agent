"""Offline contract tests for the immutable analysis-to-intent boundary."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.domain.approval import ExecutionTarget, SourceAnalysisSnapshot
from pa_agent.trading.domain.errors import ConversionRejection, ConversionRejectionReason
from pa_agent.trading.domain.models import Mode, OrderType, ProductType, Side
from tests.fixtures.execution_factories import (
    make_analysis_recommendation,
    make_execution_target,
    make_source_analysis_snapshot,
)


def test_completed_snapshot_produces_paper_spot_candidate_bound_to_source() -> None:
    snapshot = make_source_analysis_snapshot()

    candidate = IntentFactory().propose(snapshot, make_execution_target())

    assert candidate.source_id == snapshot.source_id
    assert candidate.source_completed_at == snapshot.completed_at
    assert candidate.source_schema_version == snapshot.schema_version
    assert candidate.source_parser_version == snapshot.parser_version
    assert candidate.source_decision_digest == snapshot.decision_digest
    assert candidate.target == make_execution_target()
    assert candidate.auto_ticket_eligible is True
    assert candidate.side is Side.BUY
    assert candidate.quantity == Decimal("0.125")


@pytest.mark.parametrize(
    ("snapshot_overrides", "recommendation_overrides", "reason"),
    [
        ({"source_id": ""}, {}, ConversionRejectionReason.MISSING_SOURCE_ID),
        ({"completed_at": datetime(2026, 1, 1)}, {}, ConversionRejectionReason.INVALID_COMPLETION_TIME),
        ({"schema_version": ""}, {}, ConversionRejectionReason.MISSING_SOURCE_VERSION),
        ({"parser_version": ""}, {}, ConversionRejectionReason.MISSING_SOURCE_VERSION),
        ({"decision_digest": ""}, {}, ConversionRejectionReason.MISSING_DECISION_DIGEST),
        ({}, {"side": None}, ConversionRejectionReason.MISSING_DIRECTION),
        ({}, {"price": None}, ConversionRejectionReason.MISSING_PRICE_BASIS),
        ({}, {"quantity": None}, ConversionRejectionReason.MISSING_QUANTITY_BASIS),
        ({}, {"risk_basis": None}, ConversionRejectionReason.MISSING_RISK_BASIS),
        ({}, {"symbol": ""}, ConversionRejectionReason.MISSING_PRODUCT_CONTEXT),
        ({"repaired": True}, {}, ConversionRejectionReason.REPAIRED_SOURCE),
        ({}, {"order_type": "stop"}, ConversionRejectionReason.UNSUPPORTED_ORDER_TYPE),
    ],
)
def test_invalid_snapshot_fails_closed_with_stable_reason(
    snapshot_overrides: dict[str, object],
    recommendation_overrides: dict[str, object],
    reason: ConversionRejectionReason,
) -> None:
    recommendation = make_analysis_recommendation(**recommendation_overrides)
    snapshot = make_source_analysis_snapshot(recommendation=recommendation, **snapshot_overrides)

    with pytest.raises(ConversionRejection) as raised:
        IntentFactory().propose(snapshot, make_execution_target())

    assert raised.value.reason is reason


@pytest.mark.parametrize(
    "target",
    [
        make_execution_target(mode=Mode.TESTNET),
        make_execution_target(mode=Mode.LIVE),
        make_execution_target(product=ProductType.ISOLATED_MARGIN),
        make_execution_target(product=ProductType.USDT_PERPETUAL),
    ],
)
def test_non_paper_spot_targets_reject_before_candidate_creation(target: ExecutionTarget) -> None:
    with pytest.raises(ConversionRejection) as raised:
        IntentFactory().propose(make_source_analysis_snapshot(), target)

    assert raised.value.reason is ConversionRejectionReason.UNSUPPORTED_TARGET


def test_candidate_hash_changes_for_source_decision_target_or_version() -> None:
    factory = IntentFactory()
    baseline = factory.propose(make_source_analysis_snapshot(), make_execution_target())
    changed_decision = factory.propose(
        make_source_analysis_snapshot(recommendation=make_analysis_recommendation(quantity="0.126")),
        make_execution_target(),
    )
    changed_target = factory.propose(
        make_source_analysis_snapshot(), make_execution_target(target_id="paper-spot-secondary")
    )
    changed_version = factory.propose(
        make_source_analysis_snapshot(schema_version="analysis-schema-v2"), make_execution_target()
    )

    assert len(
        {
            baseline.intent_digest,
            changed_decision.intent_digest,
            changed_target.intent_digest,
            changed_version.intent_digest,
        }
    ) == 4


@pytest.mark.parametrize(
    "invalid_snapshot",
    [
        {"source_id": "analysis-001"},
        Path("records/analysis-001.json"),
        object(),
    ],
)
def test_factory_rejects_raw_or_path_analysis_inputs(invalid_snapshot: object) -> None:
    with pytest.raises(ConversionRejection) as raised:
        IntentFactory().propose(invalid_snapshot, make_execution_target())  # type: ignore[arg-type]

    assert raised.value.reason is ConversionRejectionReason.INVALID_SNAPSHOT_TYPE


def test_snapshot_rejects_mutable_decision_material_and_float_ingress() -> None:
    with pytest.raises(ConversionRejection):
        SourceAnalysisSnapshot(
            source_id="analysis-001",
            completed_at=datetime(2026, 1, 1, tzinfo=UTC),
            schema_version="analysis-schema-v1",
            parser_version="parser-v1",
            decision_digest="a" * 64,
            recommendation={"side": "buy"},  # type: ignore[arg-type]
        )
    with pytest.raises(ConversionRejection):
        make_analysis_recommendation(quantity=0.125)


def test_factory_has_no_submission_capability() -> None:
    factory = IntentFactory()

    assert not any("gateway" in name or "submission" in name or "ledger" in name for name in vars(factory))
    assert not hasattr(factory, "submit")
