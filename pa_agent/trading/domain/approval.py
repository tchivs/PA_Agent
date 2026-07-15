"""Frozen values that separate completed analysis from execution authority."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from pa_agent.trading.domain.errors import ConversionRejection, ConversionRejectionReason
from pa_agent.trading.domain.models import (
    IsolatedMarginOrderContext,
    Mode,
    OrderType,
    ProductContext,
    ProductType,
    Side,
    SpotOrderContext,
    UsdtPerpetualOrderContext,
    canonicalize,
    decimal_from_canonical,
    product_context_digest,
    product_context_to_canonical_payload,
)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


_EVIDENCE_TIMESTAMP_KEYS = frozenset(
    {
        "observed_at",
        "rule_observed_at",
        "server_time",
        "window_started_at",
        "window_ends_at",
        "utc_day_started_at",
    }
)
_EVIDENCE_NON_AUTHORIZATION_KEYS = _EVIDENCE_TIMESTAMP_KEYS | frozenset({"evidence_digest"})
_FRESHNESS_TIMESTAMP_KEYS = _EVIDENCE_TIMESTAMP_KEYS - frozenset({"utc_day_started_at"})


def _authorization_evidence_material(value: object) -> object:
    """Remove only raw observation-time fields from canonical evidence material."""
    if isinstance(value, dict):
        return {
            key: _authorization_evidence_material(item)
            for key, item in value.items()
            if key not in _EVIDENCE_NON_AUTHORIZATION_KEYS
        }
    if isinstance(value, list):
        return [_authorization_evidence_material(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_authorization_evidence_material(item) for item in value)
    return value


def _evidence_observation_times(value: object) -> tuple[datetime, ...]:
    """Extract every timestamp that must independently pass freshness validation."""
    timestamps: list[datetime] = []

    def collect(node: object) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key in _FRESHNESS_TIMESTAMP_KEYS:
                    if isinstance(item, (str, datetime)):
                        parsed = datetime.fromisoformat(item) if isinstance(item, str) else item
                        if parsed.tzinfo is None or parsed.utcoffset() is None:
                            raise ValueError("authorization evidence timestamps must be timezone-aware")
                        timestamps.append(parsed.astimezone(UTC))
                    else:
                        collect(item)
                else:
                    collect(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                collect(item)

    collect(canonicalize(value))
    if not timestamps:
        raise ValueError("authorization evidence requires observation timestamps")
    return tuple(timestamps)


def authorization_evidence_digest(value: object) -> str:
    """Digest all evidence facts except raw observation timestamps."""
    return _canonical_digest(_authorization_evidence_material(canonicalize(value)))


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
    context: ProductContext = field(default_factory=SpotOrderContext)
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
        try:
            product_context_to_canonical_payload(self.context)
        except Exception as exc:
            raise ConversionRejection(ConversionRejectionReason.UNSUPPORTED_TARGET) from exc
        if self.target.product is not self.context.product:
            raise ConversionRejection(ConversionRejectionReason.UNSUPPORTED_TARGET)
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
            "product_context_payload": product_context_to_canonical_payload(self.context),
            "product_context_digest": product_context_digest(self.context),
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
    """One immutable, ledger-loaded Paper product recovery scope."""

    persistent_scope_id: str
    target: ExecutionTarget
    target_digest: str
    product_context: ProductContext
    product_scope_key: str
    policy_id: str
    policy_version: str
    policy_digest: str
    scope_digest: str

    @classmethod
    def from_ledger_values(
        cls,
        *,
        persistent_scope_id: str,
        target: ExecutionTarget,
        product_context: ProductContext,
        product_scope_key: str,
        policy_id: str,
        policy_version: str,
        policy_digest: str,
    ) -> RecoveryScope:
        """Bind service inputs into the sole canonical durable scope shape."""
        target_digest = _canonical_digest(target)
        scope = cls(
            persistent_scope_id=persistent_scope_id,
            target=target,
            target_digest=target_digest,
            product_context=product_context,
            product_scope_key=product_scope_key,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_digest=policy_digest,
            scope_digest="pending",
        )
        return replace(scope, scope_digest=scope._expected_scope_digest())

    def __post_init__(self) -> None:
        if not all(
            (
                self.persistent_scope_id,
                self.target_digest,
                self.product_scope_key,
                self.policy_id,
                self.policy_version,
                self.policy_digest,
                self.scope_digest,
            )
        ):
            raise ValueError("recovery scope requires durable identity and immutable bindings")
        if type(self.target) is not ExecutionTarget or self.target_digest != _canonical_digest(self.target):
            raise ValueError("recovery scope target digest is not canonical")
        self._require_exact_product_key()
        if self.scope_digest != "pending" and self.scope_digest != self._expected_scope_digest():
            raise ValueError("recovery scope digest is not canonical")

    def _require_exact_product_key(self) -> None:
        if self.target.product is ProductType.SPOT:
            valid = type(self.product_context) is SpotOrderContext
        elif self.target.product is ProductType.ISOLATED_MARGIN:
            valid = (
                type(self.product_context) is IsolatedMarginOrderContext
                and self.product_context.isolated_symbol == self.product_scope_key
            )
        elif self.target.product is ProductType.USDT_PERPETUAL:
            valid = (
                type(self.product_context) is UsdtPerpetualOrderContext
                and self.product_context.symbol == self.product_scope_key
            )
        else:
            valid = False
        if not valid:
            raise ValueError("recovery scope product key does not match its context")

    def _expected_scope_digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": "paper-recovery-scope-v1",
                "persistent_scope_id": self.persistent_scope_id,
                "target_digest": self.target_digest,
                "product_context_digest": product_context_digest(self.product_context),
                "product_scope_key": self.product_scope_key,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "policy_digest": self.policy_digest,
            }
        )

    def is_canonical(self) -> bool:
        """Return whether every durable scope binding still has its canonical value."""
        try:
            self._require_exact_product_key()
            return (
                type(self.target) is ExecutionTarget
                and self.target_digest == _canonical_digest(self.target)
                and self.scope_digest == self._expected_scope_digest()
            )
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True)
class RecoveryAssessment:
    """A clearance fact that cannot represent proposal or outbound authority."""

    recovery_assessment_id: str | None
    persistent_scope_id: str
    scope_digest: str
    target_digest: str
    policy_id: str
    policy_version: str
    policy_digest: str
    evidence_digest: str
    evidence_json: str
    accepted: bool
    reason_codes: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not all(
            (
                self.persistent_scope_id,
                self.scope_digest,
                self.target_digest,
                self.policy_id,
                self.policy_version,
                self.policy_digest,
                self.evidence_digest,
                self.evidence_json,
            )
        ):
            raise ValueError("recovery assessment requires complete scope, policy, and evidence facts")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("recovery assessment time must be timezone-aware")
        if self.accepted and self.reason_codes:
            raise ValueError("accepted recovery assessment cannot carry rejection reasons")
        if not self.accepted and not self.reason_codes:
            raise ValueError("rejected recovery assessment requires a controlled reason")


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
    policy_id: str
    policy_version: str
    policy_digest: str
    evidence_digest: str
    quote_digest: str
    fee_rate_digest: str
    authorization_evidence_digest: str
    data_age_digest: str
    observation_timestamps: tuple[datetime, ...]
    product_context_payload: str
    product_context_digest: str
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
        authorization_evidence_digest: str | None = None,
        observation_timestamps: tuple[datetime, ...] | None = None,
        fee_estimate: object,
        risk_reason_codes: tuple[object, ...],
        risk_metrics: tuple[tuple[str, Decimal], ...],
    ) -> TicketBinding:
        """Create a digest-bound review from accepted, already durable proposal facts."""
        from pa_agent.trading.domain.risk import FeeEstimate, RiskPolicy

        if type(candidate) is not CandidateExecutionIntent:
            raise TypeError("ticket binding requires a canonical persisted candidate")
        if type(policy) is not RiskPolicy:
            raise ValueError("ticket binding requires an immutable Paper policy")
        policy.require_matches(candidate, candidate.target)
        if type(fee_estimate) is not FeeEstimate or fee_estimate.target != candidate.target:
            raise ValueError("ticket binding requires target-bound Decimal fee evidence")
        if not evidence_digest:
            raise ValueError("ticket binding requires persisted evidence")
        if quote_observed_at.tzinfo is None or quote_observed_at.utcoffset() is None:
            raise ValueError("ticket binding requires an aware quote timestamp")
        authorization_digest = authorization_evidence_digest or evidence_digest
        observed_timestamps = observation_timestamps or (quote_observed_at,)
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
            policy_id=policy.policy_id,
            product_context_payload=product_context_to_canonical_payload(candidate.context),
            product_context_digest=product_context_digest(candidate.context),
            policy_version=policy.policy_version,
            policy_digest=policy.policy_digest,
            evidence_digest=evidence_digest,
            quote_digest=quote_digest,
            fee_rate_digest=fee_rate_digest,
            authorization_evidence_digest=authorization_digest,
            data_age_digest=_canonical_digest(quote_observed_at),
            observation_timestamps=observed_timestamps,
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

    def is_authorization_equivalent_to(
        self, current: TicketBinding, *, policy: object, now: datetime
    ) -> bool:
        """Permit only fresh timestamp refreshes with every D-10 fact unchanged."""
        from pa_agent.trading.domain.risk import RiskPolicy

        if type(current) is not TicketBinding or type(policy) is not RiskPolicy:
            return False
        if now.tzinfo is None or now.utcoffset() is None:
            return False
        if (
            policy.policy_id != self.policy_id
            or policy.policy_digest != self.policy_digest
            or current.policy_id != policy.policy_id
            or current.policy_version != policy.policy_version
            or current.policy_digest != policy.policy_digest
        ):
            return False
        for observed_at in current.observation_timestamps:
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                return False
            age = now.astimezone(UTC) - observed_at.astimezone(UTC)
            if age < timedelta(0) or age > timedelta(seconds=policy.evidence_max_age_seconds):
                return False
        ignored_timestamp_fields = {
            "evidence_digest",
            "data_age_digest",
            "data_observed_at",
            "observation_timestamps",
        }
        return all(
            getattr(self, field.name) == getattr(current, field.name)
            for field in self.__dataclass_fields__.values()
            if field.name not in ignored_timestamp_fields
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
        """Issue one 60-second pending review ticket bound to an immutable policy."""
        from datetime import timedelta

        if not ticket_id or not binding.policy_id or not binding.policy_version or not binding.policy_digest:
            raise ValueError("pending tickets require an immutable policy identity")
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
