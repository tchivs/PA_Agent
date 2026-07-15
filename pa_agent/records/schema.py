"""Pydantic v2 data models for PA Agent records persistence.

Defines the canonical schema for analysis records, followup turns,
alarm payloads, validation errors, and experience entries.
"""

from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Literal

from pydantic import field_validator

from pa_agent.trading.domain.models import (
    OrderType,
    ProductType,
    Side,
    decimal_to_canonical,
)
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RecordMeta(BaseModel):
    """Metadata captured at the moment of analysis submission."""

    model_config = ConfigDict(extra="forbid")

    timestamp_local_iso: str  # Local time ISO string, used for filename
    timestamp_local_ms: int   # Local time in milliseconds
    symbol: str
    timeframe: str
    bar_count: int
    ai_provider: dict         # Sanitized provider config snapshot (no plaintext API key)
    decision_stance: str = "conservative"  # conservative | balanced | aggressive | extreme_aggressive


class ExecutionSafeAnalysisSnapshotV1(BaseModel):
    """The sole persisted, execution-review-safe analysis representation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    schema_version: Literal["analysis-record-execution-v1"]
    parser_version: str
    completed_at: datetime
    binding_digest: str
    repaired: bool
    product: ProductType
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None
    risk_basis: Decimal

    @field_validator("source_id", "parser_version", "binding_digest", "symbol")
    @classmethod
    def _require_nonempty_text(cls, value: str) -> str:
        if not value:
            raise ValueError("execution snapshot text fields must not be empty")
        return value

    @field_validator("completed_at")
    @classmethod
    def _require_aware_completion(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        return value

    @field_validator("quantity", "risk_basis")
    @classmethod
    def _require_positive_decimal(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("execution snapshot Decimal values must be finite and positive")
        return value

    @field_validator("price")
    @classmethod
    def _require_valid_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value <= 0):
            raise ValueError("price must be finite and positive when provided")
        return value

    @staticmethod
    def binding_digest_for(**values: object) -> str:
        """Return the digest binding every execution-review field except itself."""
        completed_at = values["completed_at"]
        if not isinstance(completed_at, datetime):
            raise TypeError("completed_at must be a datetime")
        material = {
            "source_id": values["source_id"],
            "schema_version": values["schema_version"],
            "parser_version": values["parser_version"],
            "completed_at": completed_at.isoformat(),
            "repaired": values["repaired"],
            "product": str(values["product"]),
            "symbol": values["symbol"],
            "side": str(values["side"]),
            "order_type": str(values["order_type"]),
            "quantity": decimal_to_canonical(values["quantity"]),
            "price": (
                None
                if values["price"] is None
                else decimal_to_canonical(values["price"])
            ),
            "risk_basis": decimal_to_canonical(values["risk_basis"]),
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return sha256(encoded.encode("utf-8")).hexdigest()


class AnalysisRecord(BaseModel):
    """Full record of a two-stage AI analysis run."""

    model_config = ConfigDict(extra="forbid")

    meta: RecordMeta
    kline_data: list[dict]              # Same data as sent to AI
    htf_text: str
    stage1_messages: list[dict]
    stage1_response: Optional[dict]     # Raw response (includes reasoning_content)
    stage1_diagnosis: Optional[dict]
    stage2_messages: list[dict]
    stage2_response: Optional[dict]
    stage2_decision: Optional[dict]
    strategy_files_used: list[str]
    experience_loaded: list[dict]
    exception: Optional[dict]           # If error occurred: category + debug info
    usage_total: dict                   # Cumulative usage for audit
    execution_snapshot: ExecutionSafeAnalysisSnapshotV1 | None = None


class FollowupTurn(BaseModel):
    """A single turn in the post-analysis free-chat session."""

    model_config = ConfigDict(extra="forbid")

    turn: int
    ts_ms: int
    user: str
    ai_content: str
    ai_reasoning: Optional[str]
    usage: dict
    cancelled: bool = False


class AlarmPayload(BaseModel):
    """Payload emitted when a JSON validation alarm is triggered (R8.6)."""

    model_config = ConfigDict(extra="forbid")

    category: str                       # 'a'..'e'
    stage: str                          # '阶段一-诊断' or '阶段二-决策'
    timestamp_local_iso: str
    raw_text: str
    parse_position: Optional[str]
    missing_fields: list[str]
    invalid_fields: list[str]
    consecutive_count: int
    history_excerpt: list[dict]


class ValidationError(BaseModel):
    """Structured validation error produced by JsonValidator.

    Note: this is a Pydantic model, not the built-in exception class.
    """

    model_config = ConfigDict(extra="forbid")

    category: str                       # 'a', 'b', 'c', or 'd'
    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    raw_text: str
    parse_position: Optional[str] = None
    allowed_values: dict = {}


class ExperienceEntry(BaseModel):
    """A single entry loaded from the experience library."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    case_type: str                      # 'success' or 'failure'
    cycle_position: str
    timestamp_ms: int
    content: dict                       # Parsed JSON content of the experience file
