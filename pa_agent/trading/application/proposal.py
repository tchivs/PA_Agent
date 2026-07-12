"""Pre-ticket coordination for durable proposal, evidence, and risk audit facts."""
from __future__ import annotations

from hashlib import sha256

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.evidence_collector import (
    EvidenceCollectionRejection,
    FreshEvidenceCollector,
)
from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.approval import (
    CandidateExecutionIntent,
    ExecutionTarget,
    KillSwitchStatus,
    SourceAnalysisSnapshot,
)
from pa_agent.trading.domain.errors import ConversionRejection, RiskRejectionReason
from pa_agent.trading.domain.risk import RiskAssessment, RiskPolicy
from pa_agent.trading.persistence.sqlite_connection import LedgerStorageError
from pa_agent.trading.ports.ledger import ExecutionLedger
from pa_agent.trading.security.redaction import SecretRedactor, output_redactor


class ProposalService:
    """Persist the complete pre-ticket chain while retaining no submission authority."""

    def __init__(
        self,
        *,
        ledger: ExecutionLedger,
        intent_factory: IntentFactory,
        evidence_collector: FreshEvidenceCollector,
        risk_engine: RiskEngine,
        approval_service: ApprovalService | None = None,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self._ledger = ledger
        self._intent_factory = intent_factory
        self._evidence_collector = evidence_collector
        self._risk_engine = risk_engine
        self._approval_service = approval_service
        self._redactor = redactor or output_redactor()

    def propose(
        self, snapshot: SourceAnalysisSnapshot, target: ExecutionTarget
    ) -> CandidateExecutionIntent | None:
        """Convert and persist a candidate or its controlled conversion rejection."""
        try:
            candidate = self._intent_factory.propose(snapshot, target)
        except ConversionRejection as error:
            self._ledger.record_conversion_rejection(snapshot, target, error.reason)
            return None
        self._ledger.record_candidate(candidate)
        return candidate

    def assess(
        self,
        candidate: CandidateExecutionIntent | None,
        target: ExecutionTarget,
        policy: RiskPolicy,
    ) -> RiskAssessment:
        """Collect fresh evidence once, then persist the complete risk outcome."""
        if candidate is None:
            raise ValueError("a rejected conversion cannot be assessed")
        if self._ledger.get_kill_switch_state().status is not KillSwitchStatus.READY:
            return self._record_kill_switch_rejection(candidate, policy)
        try:
            evidence = self._evidence_collector.collect(candidate, target, policy)
        except EvidenceCollectionRejection as error:
            assessment = RiskAssessment(
                accepted=False,
                reason_codes=error.reasons,
                metrics=(),
                policy_version=policy.policy_version,
                policy_digest=policy.policy_digest,
                evidence_digest=sha256(
                    ",".join(reason.value for reason in error.reasons).encode("utf-8")
                ).hexdigest(),
                fee_estimate=None,
            )
            self._ledger.record_risk_assessment(candidate, assessment)
            return assessment
        self._ledger.record_evidence(candidate, evidence)
        assessment = self._risk_engine.assess(candidate, target, policy, evidence)
        try:
            self._ledger.record_risk_assessment(candidate, assessment)
        except LedgerStorageError:
            if (
                assessment.accepted
                and self._ledger.get_kill_switch_state().status is not KillSwitchStatus.READY
            ):
                return self._record_kill_switch_rejection(candidate, policy)
            raise
        if assessment.accepted and self._approval_service is not None:
            self._approval_service.create_pending_ticket(candidate, assessment)
        return assessment

    def _record_kill_switch_rejection(
        self, candidate: CandidateExecutionIntent, policy: RiskPolicy
    ) -> RiskAssessment:
        """Persist a stable, evidence-free rejection while durable authority is unavailable."""
        reason = RiskRejectionReason.KILL_SWITCH_NOT_READY
        assessment = RiskAssessment(
            accepted=False,
            reason_codes=(reason,),
            metrics=(),
            policy_version=policy.policy_version,
            policy_digest=policy.policy_digest,
            evidence_digest=sha256(
                f"{candidate.intent_digest}:{policy.policy_digest}:{reason.value}".encode()
            ).hexdigest(),
            fee_estimate=None,
        )
        self._ledger.record_risk_assessment(candidate, assessment)
        return assessment
