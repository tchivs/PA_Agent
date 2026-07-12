"""Deterministic execution-domain factories."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pa_agent.trading.domain.approval import (
    AnalysisRecommendation,
    CandidateExecutionIntent,
    ExecutionTarget,
    SourceAnalysisSnapshot,
    digest_analysis_recommendation,
)
from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    ExecutionCommand,
    Mode,
    OrderType,
    Position,
    ProductType,
    Side,
    SpotOrderContext,
)


def make_spot_command(**overrides: object) -> ExecutionCommand:
    """Build a valid immutable spot command with deterministic identifiers."""
    values: dict[str, object] = {
        "command_id": "command-001",
        "logical_command_key": "logical-command-001",
        "client_order_id": "client-order-001",
        "mode": Mode.PAPER,
        "account_id": "paper-account",
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("0.125"),
        "price": Decimal("42000.50"),
        "context": SpotOrderContext(),
    }
    values.update(overrides)
    return ExecutionCommand(**values)  # type: ignore[arg-type]


def make_account_observation(**overrides: object) -> AccountObservation:
    """Build a typed immutable spot account observation for contract tests."""
    values: dict[str, object] = {
        "account_id": "paper-account",
        "product": ProductType.SPOT,
        "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "balances": (
            Balance(asset="USDT", total="1000", available="900", reserved="100"),
        ),
        "positions": (
            Position(
                symbol="BTCUSDT",
                quantity="0.125",
                entry_price="42000",
                mark_price="42001",
                unrealized_pnl="0.125",
                margin="0",
            ),
        ),
    }
    values.update(overrides)
    return AccountObservation(**values)  # type: ignore[arg-type]


def make_execution_target(**overrides: object) -> ExecutionTarget:
    """Build the sole Phase 2 selectable Paper Spot target."""
    values: dict[str, object] = {
        "target_id": "paper-spot-primary",
        "mode": Mode.PAPER,
        "account_id": "paper-account",
        "product": ProductType.SPOT,
    }
    values.update(overrides)
    return ExecutionTarget(**values)  # type: ignore[arg-type]


def make_analysis_recommendation(**overrides: object) -> AnalysisRecommendation:
    """Build immutable executable decision facts without external record shapes."""
    values: dict[str, object] = {
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("0.125"),
        "price": Decimal("42000.50"),
        "risk_basis": Decimal("0.01"),
    }
    values.update(overrides)
    return AnalysisRecommendation(**values)  # type: ignore[arg-type]


def make_source_analysis_snapshot(**overrides: object) -> SourceAnalysisSnapshot:
    """Build a deterministic completed snapshot for intent conversion tests."""
    values: dict[str, object] = {
        "source_id": "analysis-001",
        "completed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "schema_version": "analysis-schema-v1",
        "parser_version": "parser-v1",
        "recommendation": make_analysis_recommendation(),
        "repaired": False,
    }
    values.update(overrides)
    if "decision_digest" not in overrides:
        values["decision_digest"] = digest_analysis_recommendation(
            values["recommendation"]  # type: ignore[arg-type]
        )
    return SourceAnalysisSnapshot(**values)  # type: ignore[arg-type]


def make_candidate_execution_intent(**overrides: object) -> CandidateExecutionIntent:
    """Build a provenance-bound Paper Spot candidate for risk tests."""
    snapshot = make_source_analysis_snapshot()
    recommendation = snapshot.recommendation
    values: dict[str, object] = {
        "source_id": snapshot.source_id,
        "source_completed_at": snapshot.completed_at,
        "source_schema_version": snapshot.schema_version,
        "source_parser_version": snapshot.parser_version,
        "source_decision_digest": snapshot.decision_digest,
        "target": make_execution_target(),
        "symbol": recommendation.symbol,
        "side": recommendation.side,
        "order_type": recommendation.order_type,
        "quantity": recommendation.quantity,
        "price": recommendation.price,
        "risk_basis": recommendation.risk_basis,
    }
    values.update(overrides)
    return CandidateExecutionIntent(**values)  # type: ignore[arg-type]
