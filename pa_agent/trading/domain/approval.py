"""Frozen values that separate completed analysis from execution authority."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
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
    price: Decimal | None
    risk_basis: Decimal
    auto_ticket_eligible: bool = True
    intent_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.order_type is OrderType.LIMIT:
            if self.price is None:
                raise ConversionRejection(ConversionRejectionReason.MISSING_PRICE_BASIS)
            object.__setattr__(self, "price", decimal_from_canonical(self.price))
        elif self.order_type is OrderType.MARKET:
            if self.price is not None:
                raise ConversionRejection(ConversionRejectionReason.SEMANTIC_CONFLICT)
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


class ApprovalTicketStatus(StrEnum):
    """The local review lifecycle for a not-yet-authoritative approval ticket."""

    PENDING = "pending"
    CONSUMED = "consumed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    REVOKED = "revoked"


class TicketTerminalEvent(StrEnum):
    """Distinct, append-only D-12 reasons that end a pending ticket."""

    OPERATOR_REJECTED = "operator_rejected"
    EXPIRED = "expired"
    BINDING_INVALIDATED = "binding_invalidated"
    KILL_SWITCH_REVOKED = "kill_switch_revoked"


class KillSwitchStatus(StrEnum):
    """The one durable global execution authorization state."""

    READY = "ready"
    LATCHED = "latched"
    RECOVERING = "recovering"


@dataclass(frozen=True)
class KillSwitchState:
    """Persisted operator safety state without any gateway capability."""

    status: KillSwitchStatus
    reason: str | None = None
    actor_label: str | None = None
    policy_summary: str | None = None
    evidence_summary: str | None = None
    changed_at: datetime | None = None


@dataclass(frozen=True)
class CancellationWork:
    """A durable cancellation request, deliberately separate from remote outcome evidence."""

    work_id: str
    command_id: str
    client_order_id: str
    status: str
    request_outcome: str | None
    remote_resolution: str | None


@dataclass(frozen=True)
class RecoveryScope:
    """The persisted account/product scope that must be freshly re-evidenced."""

    account_id: str
    product: ProductType


@dataclass(frozen=True)
class TicketRiskResult:
    """The complete persisted risk result displayed to the reviewing operator."""

    accepted: bool
    reason_codes: tuple[str, ...]
    metrics: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class TicketReview:
    """The D-09 execution summary frozen for one approval decision."""

    venue: str
    environment: str
    account_id: str
    product: str
    symbol: str
    side: str
    amount: Decimal
    expected_price: Decimal
    slippage: Decimal
    estimated_fee: Decimal
    fee_currency: str
    fee_rate_version: str
    quote_identifier: str
    leverage_context: str
    borrow_context: str
    position_context: str
    data_observed_at: datetime
    source_provenance: dict[str, str]
    risk_result: TicketRiskResult


@dataclass(frozen=True)
class TicketBinding:
    """Immutable digests and review facts derived solely from persisted proposal data."""

    candidate_digest: str
    source_digest: str
    command_digest: str
    target_digest: str
    policy_version: str
    policy_digest: str
    evidence_digest: str
    quote_digest: str
    fee_rate_digest: str
    data_age_digest: str
    venue: str
    environment: str
    account_id: str
    product: str
    symbol: str
    side: str
    amount: Decimal
    expected_price: Decimal
    slippage: Decimal
    estimated_fee: Decimal
    fee_currency: str
    fee_rate_version: str
    quote_identifier: str
    data_observed_at: datetime
    source_provenance: dict[str, str]
    risk_result: TicketRiskResult

    @classmethod
    def from_persisted_facts(
        cls,
        *,
        candidate: CandidateExecutionIntent,
        policy: object,
        evidence_digest: str,
        quote_observed_at: datetime,
        fee_estimate: object,
        risk_reason_codes: tuple[object, ...],
        risk_metrics: tuple[tuple[str, Decimal], ...],
    ) -> TicketBinding:
        """Create a digest-bound review from accepted, already durable proposal facts."""
        from pa_agent.trading.domain.risk import FeeEstimate, RiskPolicy

        if type(candidate) is not CandidateExecutionIntent:
            raise TypeError("ticket binding requires a canonical persisted candidate")
        if type(policy) is not RiskPolicy or policy.policy_version != "phase2-v1":
            raise ValueError("ticket binding requires the fixed phase2-v1 policy")
        if type(fee_estimate) is not FeeEstimate or fee_estimate.target != candidate.target:
            raise ValueError("ticket binding requires target-bound Decimal fee evidence")
        if not evidence_digest:
            raise ValueError("ticket binding requires persisted evidence")
        if quote_observed_at.tzinfo is None or quote_observed_at.utcoffset() is None:
            raise ValueError("ticket binding requires an aware quote timestamp")
        source_provenance = {
            "source_id": candidate.source_id,
            "completed_at": candidate.source_completed_at.isoformat(),
            "schema_version": candidate.source_schema_version,
            "parser_version": candidate.source_parser_version,
            "decision_digest": candidate.source_decision_digest,
        }
        source_digest = _canonical_digest(source_provenance)
        quote_digest = _canonical_digest(
            {"quote_identifier": fee_estimate.quote_identifier, "expected_price": fee_estimate.expected_quote_price}
        )
        fee_rate_digest = _canonical_digest(
            {
                "fee_currency": fee_estimate.fee_currency,
                "rate": fee_estimate.rate,
                "rate_version": fee_estimate.rate_version,
            }
        )
        return cls(
            candidate_digest=candidate.intent_digest,
            source_digest=source_digest,
            command_digest=candidate.intent_digest,
            target_digest=_canonical_digest(candidate.target),
            policy_version=policy.policy_version,
            policy_digest=policy.policy_digest,
            evidence_digest=evidence_digest,
            quote_digest=quote_digest,
            fee_rate_digest=fee_rate_digest,
            data_age_digest=_canonical_digest(quote_observed_at),
            venue=candidate.target.target_id,
            environment=candidate.target.mode.value,
            account_id=candidate.target.account_id,
            product=candidate.target.product.value,
            symbol=candidate.symbol,
            side=candidate.side.value,
            amount=decimal_from_canonical(candidate.quantity),
            expected_price=fee_estimate.expected_quote_price,
            slippage=next((value for name, value in risk_metrics if name == "slippage"), Decimal("0")),
            estimated_fee=fee_estimate.amount,
            fee_currency=fee_estimate.fee_currency,
            fee_rate_version=fee_estimate.rate_version,
            quote_identifier=fee_estimate.quote_identifier,
            data_observed_at=quote_observed_at,
            source_provenance=source_provenance,
            risk_result=TicketRiskResult(
                accepted=True,
                reason_codes=tuple(str(reason) for reason in risk_reason_codes),
                metrics=risk_metrics,
            ),
        )


def build_ticket_review(binding: TicketBinding) -> TicketReview:
    """Expose the complete immutable D-09 review material without submission authority."""
    return TicketReview(
        venue=binding.venue,
        environment=binding.environment,
        account_id=binding.account_id,
        product=binding.product,
        symbol=binding.symbol,
        side=binding.side,
        amount=binding.amount,
        expected_price=binding.expected_price,
        slippage=binding.slippage,
        estimated_fee=binding.estimated_fee,
        fee_currency=binding.fee_currency,
        fee_rate_version=binding.fee_rate_version,
        quote_identifier=binding.quote_identifier,
        leverage_context="none",
        borrow_context="none",
        position_context="spot",
        data_observed_at=binding.data_observed_at,
        source_provenance=dict(binding.source_provenance),
        risk_result=binding.risk_result,
    )


@dataclass(frozen=True)
class ApprovalTicket:
    """A short-lived review record that cannot admit or submit a command."""

    ticket_id: str
    binding: TicketBinding
    created_at: datetime
    expires_at: datetime
    status: ApprovalTicketStatus
    terminal_event: TicketTerminalEvent | None = None
    terminal_reason: str | None = None
    terminal_at: datetime | None = None

    @classmethod
    def create(cls, *, ticket_id: str, binding: TicketBinding, created_at: datetime) -> ApprovalTicket:
        """Issue exactly one fixed-policy, 60-second pending review ticket."""
        from datetime import timedelta

        if not ticket_id or binding.policy_version != "phase2-v1":
            raise ValueError("pending tickets require an identity and fixed phase2-v1 policy")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("ticket creation time must be timezone-aware")
        return cls(
            ticket_id=ticket_id,
            binding=binding,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=60),
            status=ApprovalTicketStatus.PENDING,
        )

    @property
    def policy_version(self) -> str:
        return self.binding.policy_version

    @property
    def candidate_digest(self) -> str:
        return self.binding.candidate_digest

    @property
    def policy_digest(self) -> str:
        return self.binding.policy_digest

    @property
    def evidence_digest(self) -> str:
        return self.binding.evidence_digest

    @property
    def review(self) -> TicketReview:
        return build_ticket_review(self.binding)

    def requires_invalidation(self, binding: TicketBinding) -> bool:
        """Report whether a caller's current binding differs from the durable ticket."""
        return self.binding != binding

    def terminate(
        self, *, event: TicketTerminalEvent, reason: str, occurred_at: datetime
    ) -> ApprovalTicket:
        """Return a terminal ticket while preserving the original immutable binding."""
        if self.status is not ApprovalTicketStatus.PENDING:
            raise ValueError("only pending tickets can terminate")
        if not reason:
            raise ValueError("ticket terminal events require a reason")
        statuses = {
            TicketTerminalEvent.OPERATOR_REJECTED: ApprovalTicketStatus.REJECTED,
            TicketTerminalEvent.EXPIRED: ApprovalTicketStatus.EXPIRED,
            TicketTerminalEvent.BINDING_INVALIDATED: ApprovalTicketStatus.INVALIDATED,
            TicketTerminalEvent.KILL_SWITCH_REVOKED: ApprovalTicketStatus.REVOKED,
        }
        return replace(
            self,
            status=statuses[event],
            terminal_event=event,
            terminal_reason=reason,
            terminal_at=occurred_at,
        )
