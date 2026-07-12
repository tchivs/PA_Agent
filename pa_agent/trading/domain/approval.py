"""Frozen values that separate completed analysis from execution authority."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from pa_agent.trading.domain.errors import ConversionRejection, ConversionRejectionReason
from pa_agent.trading.domain.models import (
    Mode,
    OrderType,
    ProductType,
    Side,
    canonicalize,
    decimal_from_canonical,
)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AnalysisRecommendation:
    """Typed immutable execution facts extracted from a completed analysis."""

    symbol: str
    side: Side | None
    order_type: OrderType | object
    quantity: Decimal | str | None
    price: Decimal | str | None
    risk_basis: Decimal | str | None

    def __post_init__(self) -> None:
        for name in ("quantity", "price", "risk_basis"):
            value = getattr(self, name)
            if value is None:
                continue
            try:
                object.__setattr__(self, name, decimal_from_canonical(value))
            except Exception as exc:
                raise ConversionRejection(ConversionRejectionReason.INVALID_DECIMAL) from exc


def digest_analysis_recommendation(recommendation: AnalysisRecommendation) -> str:
    """Return a reproducible digest of the exact frozen recommendation facts."""
    if type(recommendation) is not AnalysisRecommendation:
        raise ConversionRejection(ConversionRejectionReason.INVALID_SNAPSHOT_TYPE)
    return _canonical_digest(recommendation)


@dataclass(frozen=True)
class SourceAnalysisSnapshot:
    """A completed persisted analysis with no path, alert, or mutable DTO payload."""

    source_id: str
    completed_at: datetime
    schema_version: str
    parser_version: str
    decision_digest: str
    recommendation: AnalysisRecommendation
    repaired: bool = False

    def __post_init__(self) -> None:
        if type(self.recommendation) is not AnalysisRecommendation:
            raise ConversionRejection(ConversionRejectionReason.INVALID_SNAPSHOT_TYPE)


@dataclass(frozen=True)
class ExecutionTarget:
    """Explicit target facts selected before a candidate can be proposed."""

    target_id: str
    mode: Mode
    account_id: str
    product: ProductType


@dataclass(frozen=True)
class CandidateExecutionIntent:
    """A deterministic proposal that has no command or submission authority."""

    source_id: str
    source_completed_at: datetime
    source_schema_version: str
    source_parser_version: str
    source_decision_digest: str
    target: ExecutionTarget
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    price: Decimal
    risk_basis: Decimal
    auto_ticket_eligible: bool = True
    intent_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_digest", _canonical_digest(self._hash_material()))

    def _hash_material(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_completed_at": self.source_completed_at,
            "source_schema_version": self.source_schema_version,
            "source_parser_version": self.source_parser_version,
            "source_decision_digest": self.source_decision_digest,
            "target": self.target,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "price": self.price,
            "risk_basis": self.risk_basis,
        }
