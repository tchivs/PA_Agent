"""Strict persisted completed-analysis reader for the trading boundary."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from pa_agent.records.schema import AnalysisRecord, ExecutionSafeAnalysisSnapshotV1
from pa_agent.trading.domain.approval import AnalysisRecommendation, SourceAnalysisSnapshot
from pa_agent.trading.domain.models import OrderType, ProductType, Side, decimal_to_canonical


_CURRENT_SCHEMA_VERSION = "analysis-record-execution-v1"
_MAX_SOURCE_AGE = timedelta(seconds=60)
_EXECUTION_FIELDS = frozenset(
    {
        "source_id",
        "schema_version",
        "parser_version",
        "completed_at",
        "binding_digest",
        "repaired",
        "product",
        "symbol",
        "side",
        "order_type",
        "quantity",
        "price",
        "risk_basis",
    }
)


@dataclass(frozen=True)
class EligibleAnalysisRecord:
    """A current persisted record whose frozen facts may enter proposal conversion."""

    source_id: str
    snapshot: SourceAnalysisSnapshot


@dataclass(frozen=True)
class IneligibleAnalysisRecord:
    """A controlled, non-authoritative explanation for an unusable persisted record."""

    source_id: str
    reason_code: str
    safe_message: str
    snapshot: None = None


@runtime_checkable
class CompletedAnalysisSnapshotReader(Protocol):
    """Load a completed frozen snapshot by its stable persisted source identifier."""

    def load_completed_snapshot(self, source_id: str) -> SourceAnalysisSnapshot | None:
        """Return one immutable completed snapshot without exposing storage details."""


class AnalysisRecordSnapshotReader:
    """Read only fully conforming current records, without migration or fallback."""

    def __init__(
        self,
        *,
        pending_dir: Path,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        self._pending_dir = pending_dir
        self._utc_now = utc_now or (lambda: datetime.now(UTC))

    def read(self, source_id: str) -> EligibleAnalysisRecord | IneligibleAnalysisRecord:
        """Return a controlled eligibility result after strict durable validation."""
        payloads = self._matching_payloads(source_id)
        if not payloads:
            return self._ineligible(source_id, "RECORD_NOT_FOUND")
        if len(payloads) != 1:
            return self._ineligible(source_id, "DUPLICATE_SOURCE_ID")
        return self._validate(source_id, payloads[0])

    def load_completed_snapshot(self, source_id: str) -> SourceAnalysisSnapshot | None:
        """Satisfy the legacy narrow port without exposing eligibility implementation details."""
        outcome = self.read(source_id)
        if type(outcome) is EligibleAnalysisRecord:
            return outcome.snapshot
        return None

    def _matching_payloads(self, source_id: str) -> list[dict[str, object]]:
        if not self._pending_dir.is_dir():
            return []
        all_payloads: list[dict[str, object]] = []
        matches: list[dict[str, object]] = []
        for path in self._pending_dir.glob("*.json"):
            payload = self._load_json(path)
            if payload is None:
                continue
            all_payloads.append(payload)
            snapshot = payload.get("execution_snapshot")
            if type(snapshot) is dict and snapshot.get("source_id") == source_id:
                matches.append(payload)
        return matches or all_payloads if len(all_payloads) == 1 else matches

    @staticmethod
    def _load_json(path: Path) -> dict[str, object] | None:
        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result

        try:
            payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return payload if type(payload) is dict else None

    def _validate(
        self, source_id: str, payload: dict[str, object]
    ) -> EligibleAnalysisRecord | IneligibleAnalysisRecord:
        raw_snapshot = payload.get("execution_snapshot")
        if raw_snapshot is None:
            return self._ineligible(source_id, "MISSING_EXECUTION_SNAPSHOT")
        if type(raw_snapshot) is not dict or frozenset(raw_snapshot) != _EXECUTION_FIELDS:
            return self._ineligible(source_id, "MALFORMED_EXECUTION_SNAPSHOT")
        if raw_snapshot.get("schema_version") != _CURRENT_SCHEMA_VERSION:
            return self._ineligible(source_id, "UNSUPPORTED_SCHEMA_VERSION")
        if raw_snapshot.get("source_id") != source_id:
            return self._ineligible(source_id, "SOURCE_ID_MISMATCH")
        if raw_snapshot.get("repaired") is not False:
            return self._ineligible(source_id, "REPAIRED_SOURCE")
        if raw_snapshot.get("product") not in {product.value for product in ProductType}:
            return self._ineligible(source_id, "UNSUPPORTED_PRODUCT")
        if raw_snapshot.get("quantity") is None:
            return self._ineligible(source_id, "MISSING_QUANTITY_BASIS")
        if raw_snapshot.get("risk_basis") is None:
            return self._ineligible(source_id, "MISSING_RISK_BASIS")
        if not self._has_canonical_decimals(raw_snapshot):
            return self._ineligible(source_id, "INVALID_CANONICAL_DECIMAL")

        try:
            record = AnalysisRecord.model_validate(payload)
        except ValidationError:
            return self._ineligible(source_id, "MALFORMED_RECORD")
        execution_snapshot = record.execution_snapshot
        if execution_snapshot is None:
            return self._ineligible(source_id, "MISSING_EXECUTION_SNAPSHOT")
        if self._is_stale(execution_snapshot.completed_at):
            return self._ineligible(source_id, "SOURCE_ANALYSIS_STALE")
        expected_digest = ExecutionSafeAnalysisSnapshotV1.binding_digest_for(
            **execution_snapshot.model_dump()
        )
        if execution_snapshot.binding_digest != expected_digest:
            return self._ineligible(source_id, "DECISION_DIGEST_MISMATCH")
        return EligibleAnalysisRecord(
            source_id=source_id,
            snapshot=SourceAnalysisSnapshot(
                source_id=execution_snapshot.source_id,
                completed_at=execution_snapshot.completed_at,
                schema_version=execution_snapshot.schema_version,
                parser_version=execution_snapshot.parser_version,
                decision_digest=execution_snapshot.binding_digest,
                recommendation=AnalysisRecommendation(
                    symbol=execution_snapshot.symbol,
                    side=execution_snapshot.side,
                    order_type=execution_snapshot.order_type,
                    quantity=execution_snapshot.quantity,
                    price=execution_snapshot.price,
                    risk_basis=execution_snapshot.risk_basis,
                ),
                repaired=execution_snapshot.repaired,
            ),
        )

    def _is_stale(self, completed_at: datetime) -> bool:
        now = self._utc_now()
        if now.tzinfo is None or now.utcoffset() is None:
            return True
        age = now.astimezone(UTC) - completed_at.astimezone(UTC)
        return age < timedelta(0) or age > _MAX_SOURCE_AGE

    @staticmethod
    def _has_canonical_decimals(raw_snapshot: dict[str, object]) -> bool:
        for field_name in ("quantity", "risk_basis"):
            value = raw_snapshot[field_name]
            if not isinstance(value, str):
                return False
            try:
                parsed = Decimal(value)
                if not parsed.is_finite() or parsed <= 0 or decimal_to_canonical(value) != value:
                    return False
            except Exception:
                return False
        price = raw_snapshot["price"]
        if price is None:
            return True
        if not isinstance(price, str):
            return False
        try:
            parsed = Decimal(price)
            return parsed.is_finite() and parsed > 0 and decimal_to_canonical(price) == price
        except Exception:
            return False

    @staticmethod
    def _ineligible(source_id: str, reason_code: str) -> IneligibleAnalysisRecord:
        return IneligibleAnalysisRecord(
            source_id=source_id,
            reason_code=reason_code,
            safe_message="该分析记录不满足创建审批单的条件。",
        )
