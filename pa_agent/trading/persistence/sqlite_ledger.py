"""Transactional SQLite implementation of the durable execution-ledger port."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

from pa_agent.trading.application.zero_scope_clearance import ZeroScopeClearanceCollector
from pa_agent.trading.domain.approval import (
    ApprovalTicket,
    ApprovalTicketStatus,
    CancellationWork,
    CandidateExecutionIntent,
    ExecutionTarget,
    KillSwitchState,
    KillSwitchStatus,
    RecoveryAssessment,
    RecoveryScope,
    SourceAnalysisSnapshot,
    TicketBinding,
    TicketRiskResult,
    TicketTerminalEvent,
    _evidence_observation_times,
    authorization_evidence_digest,
)
from pa_agent.trading.domain.errors import (
    ConversionRejectionReason,
    LifecycleTransitionError,
    ReconciliationEvidenceError,
)
from pa_agent.trading.domain.lifecycle import assert_transition
from pa_agent.trading.domain.models import (
    AccountObservation,
    ExecutionCommand,
    Fill,
    GatewayEvidence,
    IsolatedMarginOrderContext,
    LifecycleEvent,
    Mode,
    OrderState,
    OrderType,
    ProductType,
    Side,
    SpotOrderContext,
    UsdtPerpetualOrderContext,
    canonicalize,
    decimal_to_canonical,
    product_context_digest,
    product_context_from_canonical_payload,
    product_context_to_canonical_payload,
)
from pa_agent.trading.domain.recovery_evidence import RecoveryEvidence
from pa_agent.trading.domain.risk import (
    EvidenceBundle,
    RiskAssessment,
    RiskPolicy,
    select_phase2_policy,
    select_paper_product_policy,
)
from pa_agent.trading.domain.zero_scope_clearance import ZeroScopeClearanceProof
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerStorageError,
    bootstrap_sqlite_connection,
    transaction,
)
from pa_agent.trading.ports.clock import UtcClock
from pa_agent.trading.ports.ledger import (
    ExecutionLedger,
    OutboundDispatchPermit,
    OutboundSubmission,
    ProposalAuditFact,
    ReconciliationJob,
    ReconciliationResult,
)
from pa_agent.trading.security.redaction import SecretRedactor, output_redactor


class SQLiteExecutionLedger(ExecutionLedger):
    """Durably admit exactly one unresolved command submission per logical key.

    This repository persists the command, lifecycle event, projection,
    reconciliation job, and submission claim in one SQLite transaction before a
    future gateway can cause a remote side effect. A zero-scope recovery
    collector may be injected only at construction; without it, empty-scope
    recovery fails closed rather than accepting caller-provided gateway facts.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        clock: UtcClock | None = None,
        failure_injector: Callable[[str], None] | None = None,
        redactor: SecretRedactor | None = None,
        zero_scope_clearance_collector: ZeroScopeClearanceCollector | None = None,
    ) -> None:
        self._connection: sqlite3.Connection | None = bootstrap_sqlite_connection(database_path)
        self._clock = clock
        self._failure_injector = failure_injector
        self._redactor = redactor or output_redactor()
        self._zero_scope_clearance_collector = zero_scope_clearance_collector

    def close(self) -> None:
        """Close the thread-confined SQLite connection deterministically."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def utc_now(self) -> datetime:
        """Return the injected or system UTC time used for durable timestamps."""
        if self._clock is not None:
            return self._clock.utc_now()
        return datetime.now(UTC)

    def consume_valid_ticket_and_begin_outbound(
        self,
        ticket_id: str,
        candidate: CandidateExecutionIntent,
        policy: object,
        evidence: EvidenceBundle,
        assessment: RiskAssessment,
    ) -> OutboundDispatchPermit | None:
        """Consume a re-evidenced ticket and persist one pending dispatch proof."""
        if (
            type(candidate) is not CandidateExecutionIntent
            or type(policy) is not RiskPolicy
            or type(evidence) is not EvidenceBundle
            or type(assessment) is not RiskAssessment
        ):
            raise TypeError("ticket consumption requires canonical current candidate, policy, evidence, and risk")
        if not assessment.accepted or assessment.fee_estimate is None:
            raise LedgerStorageError("rejected current risk cannot consume an approval ticket")
        fresh_binding = TicketBinding.from_persisted_facts(
            candidate=candidate,
            policy=policy,
            evidence_digest=evidence.evidence_digest,
            quote_observed_at=evidence.quote.observed_at,
            authorization_evidence_digest=authorization_evidence_digest(evidence),
            observation_timestamps=_evidence_observation_times(evidence),
            fee_estimate=assessment.fee_estimate,
            risk_reason_codes=assessment.reason_codes,
            risk_metrics=assessment.metrics,
        )
        connection = self._require_connection()
        with transaction(connection):
            self._require_ready_in_transaction()
            row = connection.execute(
                """
                SELECT ticket_id, binding_json, status, created_at_utc, expires_at_utc,
                       terminal_event, terminal_reason, terminal_at_utc
                FROM approval_tickets WHERE ticket_id = ?
                """,
                (ticket_id,),
            ).fetchone()
            if row is None:
                return None
            ticket = _ticket_from_row(row)
            if ticket.status is not ApprovalTicketStatus.PENDING:
                return None
            if self.utc_now() > ticket.expires_at:
                self._terminate_ticket_in_transaction(
                    ticket, TicketTerminalEvent.EXPIRED, "approval_ticket_expired"
                )
                return None
            if not ticket.binding.is_authorization_equivalent_to(
                fresh_binding, policy=policy, now=self.utc_now()
            ):
                self._terminate_ticket_in_transaction(
                    ticket,
                    TicketTerminalEvent.BINDING_INVALIDATED,
                    "current_ticket_binding_mismatch",
                    fresh_binding,
                )
                return None
            self._record_current_refresh_audit(candidate, evidence, assessment)
            consumed = connection.execute(
                "UPDATE approval_tickets SET status = ? WHERE ticket_id = ? AND status = ?",
                (ApprovalTicketStatus.CONSUMED.value, ticket_id, ApprovalTicketStatus.PENDING.value),
            )
            if consumed.rowcount != 1:
                return None
            self._append_approval_ticket_event(
                ticket=ticket,
                event_type="consumed",
                reason="current_evidence_and_risk_verified",
                actor_label="approval_service",
                occurred_at=self.utc_now(),
            )
            command_id = f"ticket-command-{ticket_id}"
            logical_command_key = f"approval-ticket:{ticket_id}"
            client_order_id = _new_id("client-order")
            command = ExecutionCommand(
                command_id=command_id,
                logical_command_key=logical_command_key,
                client_order_id=client_order_id,
                mode=candidate.target.mode,
                account_id=candidate.target.account_id,
                symbol=candidate.symbol,
                side=candidate.side,
                order_type=candidate.order_type,
                quantity=candidate.quantity,
                price=candidate.price,
                context=candidate.context,
            )
            now = _timestamp_text(self.utc_now())
            submitting = assert_transition(OrderState.PROPOSED, LifecycleEvent.SUBMIT_REQUESTED)
            job_id = _new_id("reconciliation")
            claim_token = _new_id("claim-token")
            proof = _new_id("dispatch-proof")
            connection.execute(
                """
                INSERT INTO order_commands(
                    command_id, logical_command_key, client_order_id, command_json,
                    mode, product, account_id, symbol, created_at_utc,
                    product_context_json, product_context_digest,
                    policy_id, policy_version_bound, policy_digest_bound
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command.command_id,
                    command.logical_command_key,
                    command.client_order_id,
                    _canonical_json(command.to_canonical_dict()),
                    command.mode.value,
                    command.context.product.value,
                    command.account_id,
                    command.symbol,
                    now,
                    product_context_to_canonical_payload(command.context),
                    product_context_digest(command.context),
                    policy.policy_id,
                    policy.policy_version,
                    policy.policy_digest,
                ),
            )
            self._append_event(
                command_id=command.command_id,
                previous_state=OrderState.PROPOSED,
                new_state=submitting,
                event=LifecycleEvent.SUBMIT_REQUESTED,
                occurred_at=now,
                detail={"source": "approval_ticket", "ticket_id": ticket_id},
            )
            connection.execute(
                """
                INSERT INTO orders(
                    command_id, exchange_order_id, lifecycle_state, filled_quantity, filled_notional,
                    evidence_cursor
                ) VALUES (?, NULL, ?, ?, ?, NULL)
                """,
                (command.command_id, submitting.value, "0", "0"),
            )
            connection.execute(
                """
                INSERT INTO reconciliation_jobs(
                    job_id, command_id, reason, status, attempt_count, next_action_at_utc
                ) VALUES (?, ?, ?, ?, 0, ?)
                """,
                (job_id, command.command_id, "submission_pending", "queued", now),
            )
            connection.execute(
                """
                INSERT INTO submission_claims(claim_id, command_id, claim_token, admitted_at_utc, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_new_id("claim"), command.command_id, claim_token, now, "outbound_started"),
            )
            connection.execute(
                """
                INSERT INTO outbound_dispatch_attempts(
                    command_id, client_order_id, reconciliation_job_id, outbound_attempt_proof,
                    created_at_utc, expires_at_utc, status, leased_at_utc,
                    policy_id, policy_version_bound, policy_digest_bound
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    command.command_id,
                    client_order_id,
                    job_id,
                    proof,
                    now,
                    _timestamp_text(ticket.expires_at),
                    "pending",
                    policy.policy_id,
                    policy.policy_version,
                    policy.policy_digest,
                ),
            )
            self._inject_failure("before_ticket_consumption")
            return OutboundDispatchPermit(
                command_id=command.command_id,
                client_order_id=client_order_id,
                reconciliation_job_id=job_id,
                outbound_attempt_proof=proof,
            )

    def lease_outbound_submission(self, permit: OutboundDispatchPermit) -> OutboundSubmission:
        """Atomically lease one persisted proof and rebuild the canonical command."""
        if type(permit) is not OutboundDispatchPermit:
            raise TypeError("outbound lease requires a dispatch permit")
        connection = self._require_connection()
        now = _timestamp_text(self.utc_now())
        with transaction(connection):
            self._require_ready_in_transaction()
            row = connection.execute(
                """
                SELECT commands.command_json, commands.client_order_id, jobs.job_id,
                       orders.lifecycle_state, claims.status, attempts.expires_at_utc, attempts.status,
                       commands.product_context_json, commands.product_context_digest,
                       commands.policy_id, commands.policy_version_bound, commands.policy_digest_bound,
                       attempts.policy_id, attempts.policy_version_bound, attempts.policy_digest_bound
                FROM outbound_dispatch_attempts AS attempts
                JOIN order_commands AS commands ON commands.command_id = attempts.command_id
                JOIN reconciliation_jobs AS jobs ON jobs.command_id = commands.command_id
                JOIN orders ON orders.command_id = commands.command_id
                JOIN submission_claims AS claims ON claims.command_id = commands.command_id
                WHERE attempts.command_id = ?
                  AND attempts.client_order_id = ?
                  AND attempts.reconciliation_job_id = ?
                  AND attempts.outbound_attempt_proof = ?
                """,
                (
                    permit.command_id,
                    permit.client_order_id,
                    permit.reconciliation_job_id,
                    permit.outbound_attempt_proof,
                ),
            ).fetchone()
            if row is None:
                raise LedgerStorageError("dispatch permit does not match durable proof")
            if row[6] != "pending":
                raise LedgerStorageError("dispatch proof is no longer pending")
            if row[5] <= now:
                expired = connection.execute(
                    """
                    UPDATE outbound_dispatch_attempts SET status = ?
                    WHERE command_id = ? AND client_order_id = ? AND reconciliation_job_id = ?
                      AND outbound_attempt_proof = ? AND status = ?
                    """,
                    (
                        "expired",
                        permit.command_id,
                        permit.client_order_id,
                        permit.reconciliation_job_id,
                        permit.outbound_attempt_proof,
                        "pending",
                    ),
                )
                if expired.rowcount != 1:
                    raise LedgerStorageError("dispatch proof could not be expired")
                raise LedgerStorageError("dispatch proof has expired")
            if row[3] != OrderState.SUBMITTING.value or row[4] != "outbound_started":
                raise LedgerStorageError("dispatch proof is not backed by durable outbound state")
            command = _command_from_canonical_json(row[0])
            if command.command_id != permit.command_id or command.client_order_id != row[1]:
                raise LedgerStorageError("durable command identity does not match dispatch proof")
            if row[7] is not None and (
                product_context_to_canonical_payload(command.context) != row[7]
                or product_context_digest(command.context) != row[8]
            ):
                raise LedgerStorageError("durable command context does not match its persisted binding")
            _validate_durable_command_policy(command, row[9], row[10], row[11])
            if row[9:12] != row[12:15]:
                raise LedgerStorageError("dispatch policy does not match durable command binding")
            leased = connection.execute(
                """
                UPDATE outbound_dispatch_attempts SET status = ?, leased_at_utc = ?
                WHERE command_id = ? AND client_order_id = ? AND reconciliation_job_id = ?
                  AND outbound_attempt_proof = ? AND status = ? AND expires_at_utc > ?
                """,
                (
                    "leased",
                    now,
                    permit.command_id,
                    permit.client_order_id,
                    permit.reconciliation_job_id,
                    permit.outbound_attempt_proof,
                    "pending",
                    now,
                ),
            )
            if leased.rowcount != 1:
                raise LedgerStorageError("dispatch proof could not be leased")
            return OutboundSubmission(
                command=command,
                command_id=permit.command_id,
                client_order_id=row[1],
                reconciliation_job_id=row[2],
                outbound_attempt_token=permit.outbound_attempt_proof,
            )

    def _mark_leased_outbound_ambiguous(
        self, outbound: OutboundSubmission, *, event: LifecycleEvent = LifecycleEvent.LOCAL_TIMEOUT
    ) -> None:
        """Persist a local interruption for an already leased outbound value."""
        if event not in {
            LifecycleEvent.LOCAL_TIMEOUT,
            LifecycleEvent.LOCAL_CANCELLATION,
            LifecycleEvent.STREAM_GAP,
            LifecycleEvent.MALFORMED_ACKNOWLEDGEMENT,
        }:
            raise ValueError("submission ambiguity requires a local interruption event")
        connection = self._require_connection()
        with transaction(connection):
            row = connection.execute(
                """
                SELECT commands.client_order_id, orders.lifecycle_state, jobs.job_id,
                       claims.claim_token, claims.status
                FROM order_commands AS commands
                JOIN orders ON orders.command_id = commands.command_id
                JOIN reconciliation_jobs AS jobs ON jobs.command_id = commands.command_id
                JOIN submission_claims AS claims ON claims.command_id = commands.command_id
                WHERE commands.command_id = ?
                """,
                (outbound.command_id,),
            ).fetchone()
            if row is None or row[0] != outbound.client_order_id or row[2] != outbound.reconciliation_job_id:
                raise LedgerStorageError("outbound submission does not match durable ledger identities")
            if row[4] != "outbound_started":
                raise LedgerStorageError("outbound submission does not match a durable claim")
            previous_state = OrderState(row[1])
            if previous_state is OrderState.SUBMISSION_UNKNOWN:
                if row[4] != "outbound_started":
                    raise LedgerStorageError("ambiguous submission has an invalid durable claim status")
                return
            if row[4] != "outbound_started":
                raise LedgerStorageError("submission claim is no longer live")
            next_state = assert_transition(previous_state, event)
            now = _timestamp_text(self.utc_now())
            self._append_event(
                command_id=outbound.command_id,
                previous_state=previous_state,
                new_state=next_state,
                event=event,
                occurred_at=now,
                detail={"source": "local", "reason": event.value},
            )
            connection.execute(
                "UPDATE orders SET lifecycle_state = ? WHERE command_id = ?",
                (next_state.value, outbound.command_id),
            )
            connection.execute(
                """
                UPDATE reconciliation_jobs
                SET reason = ?, status = ?, next_action_at_utc = ?
                WHERE job_id = ?
                """,
                (event.value, "queued", now, outbound.reconciliation_job_id),
            )

    def mark_outbound_submission_ambiguous(self, outbound: OutboundSubmission) -> None:
        """Retain recovery work after an authorized outbound gateway exception."""
        if type(outbound) is not OutboundSubmission:
            raise TypeError("outbound ambiguity requires a ledger-produced outbound submission")
        row = self._require_connection().execute(
            """
            SELECT claims.claim_token, orders.lifecycle_state
            FROM submission_claims AS claims
            JOIN orders ON orders.command_id = claims.command_id
            JOIN reconciliation_jobs AS jobs ON jobs.command_id = claims.command_id
            WHERE claims.command_id = ? AND jobs.job_id = ? AND claims.status = ?
            """,
            (outbound.command_id, outbound.reconciliation_job_id, "outbound_started"),
        ).fetchone()
        if row is None or outbound.client_order_id != outbound.command.client_order_id:
            raise LedgerStorageError("outbound submission does not match durable authorization")
        self._mark_leased_outbound_ambiguous(outbound)

    def list_unresolved_reconciliation_jobs(self) -> tuple[ReconciliationJob, ...]:
        """Load queued non-terminal work using the first persisted identities."""
        rows = self._require_connection().execute(
            """
            SELECT commands.command_id, commands.client_order_id, jobs.job_id, orders.lifecycle_state
            FROM reconciliation_jobs AS jobs
            JOIN order_commands AS commands ON commands.command_id = jobs.command_id
            JOIN orders ON orders.command_id = commands.command_id
            WHERE jobs.status = ?
              AND orders.lifecycle_state NOT IN (?, ?, ?)
            ORDER BY jobs.next_action_at_utc, jobs.job_id
            """,
            (
                "queued",
                OrderState.FILLED.value,
                OrderState.CANCELLED.value,
                OrderState.REJECTED.value,
            ),
        ).fetchall()
        try:
            return tuple(
                ReconciliationJob(
                    command_id=row[0],
                    client_order_id=row[1],
                    reconciliation_job_id=row[2],
                    lifecycle_state=OrderState(row[3]),
                )
                for row in rows
            )
        except ValueError as exc:
            raise LedgerStorageError("stored recovery job lifecycle state is invalid") from exc

    def apply_reconciliation_evidence(
        self, job: ReconciliationJob, evidence: GatewayEvidence
    ) -> ReconciliationResult:
        """Append legal canonical evidence while retaining conflicts as incidents."""
        connection = self._require_connection()
        with transaction(connection):
            row = connection.execute(
                """
                SELECT commands.client_order_id, jobs.job_id, orders.lifecycle_state, orders.evidence_cursor,
                       orders.exchange_order_id, orders.filled_quantity, orders.filled_notional
                FROM order_commands AS commands
                JOIN reconciliation_jobs AS jobs ON jobs.command_id = commands.command_id
                JOIN orders ON orders.command_id = commands.command_id
                WHERE commands.command_id = ?
                """,
                (job.command_id,),
            ).fetchone()
            if row is None or row[0] != job.client_order_id or row[1] != job.reconciliation_job_id:
                raise LedgerStorageError("reconciliation job does not match durable ledger identities")
            current_state = OrderState(row[2])
            if evidence.client_order_id != job.client_order_id:
                self._record_incident(
                    command_id=job.command_id,
                    kind="contradictory_client_order_evidence",
                    detail={"expected_client_order_id": job.client_order_id, "evidence": canonicalize(evidence)},
                )
                return ReconciliationResult(current_state, evidence_applied=False)
            if (
                row[4] is not None
                and evidence.exchange_order_id is not None
                and row[4] != evidence.exchange_order_id
            ):
                self._record_incident(
                    command_id=job.command_id,
                    kind="contradictory_exchange_order_evidence",
                    detail={
                        "persisted_exchange_order_id": row[4],
                        "observed_exchange_order_id": evidence.exchange_order_id,
                        "evidence": canonicalize(evidence),
                    },
                )
                return ReconciliationResult(current_state, evidence_applied=False)
            if row[3] == evidence.evidence_id:
                return ReconciliationResult(current_state, evidence_applied=True)
            try:
                event = _lifecycle_event_for_evidence(evidence)
                next_state = assert_transition(current_state, event, evidence=evidence)
            except (LifecycleTransitionError, ReconciliationEvidenceError):
                self._record_incident(
                    command_id=job.command_id,
                    kind="out_of_order_reconciliation_evidence",
                    detail={"evidence": canonicalize(evidence), "current_state": current_state.value},
                )
                return ReconciliationResult(current_state, evidence_applied=False)
            self._append_event(
                command_id=job.command_id,
                previous_state=current_state,
                new_state=next_state,
                event=event,
                occurred_at=_timestamp_text(evidence.observed_at),
                detail={"source": "reconciliation", "evidence": canonicalize(evidence)},
                evidence=evidence,
            )
            filled_quantity = row[5]
            filled_notional = row[6]
            if evidence.state in {OrderState.PARTIALLY_FILLED, OrderState.FILLED}:
                filled_quantity = decimal_to_canonical(evidence.filled_quantity)
                filled_notional = decimal_to_canonical(
                    evidence.filled_quantity * evidence.average_fill_price
                )
            connection.execute(
                """
                UPDATE orders
                SET exchange_order_id = COALESCE(?, exchange_order_id),
                    lifecycle_state = ?, evidence_cursor = ?, filled_quantity = ?, filled_notional = ?
                WHERE command_id = ?
                """,
                (
                    evidence.exchange_order_id,
                    next_state.value,
                    evidence.evidence_id,
                    filled_quantity,
                    filled_notional,
                    job.command_id,
                ),
            )
            terminal = next_state in {
                OrderState.FILLED,
                OrderState.CANCELLED,
                OrderState.REJECTED,
            }
            connection.execute(
                """
                UPDATE reconciliation_jobs
                SET reason = ?, status = ?, attempt_count = attempt_count + 1, next_action_at_utc = ?
                WHERE job_id = ?
                """,
                (
                    "terminal_evidence" if terminal else "reconciliation_required",
                    "completed" if terminal else "queued",
                    _timestamp_text(self.utc_now()),
                    job.reconciliation_job_id,
                ),
            )
            return ReconciliationResult(next_state, evidence_applied=True)

    def record_fill_evidence(self, fill: Fill) -> bool:
        """Persist idempotent fill evidence or record a conflicting-evidence incident.

        Returns ``True`` when the fill is new or exactly repeats prior evidence;
        returns ``False`` when an existing fill ID has contradictory canonical
        values. Contradictions never overwrite the original fill history.
        """
        connection = self._require_connection()
        values = (
            decimal_to_canonical(fill.quantity),
            decimal_to_canonical(fill.price),
            decimal_to_canonical(fill.fee),
            fill.fee_asset,
            _timestamp_text(fill.observed_at),
        )
        with transaction(connection):
            existing = connection.execute(
                """
                SELECT command_id, quantity, price, fee, fee_asset, observed_at_utc
                FROM fills WHERE fill_id = ?
                """,
                (fill.fill_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO fills(
                        fill_id, command_id, venue_fill_id, quantity, price, fee, fee_asset, observed_at_utc
                    ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
                    """,
                    (fill.fill_id, fill.command_id, *values),
                )
                return True
            if tuple(existing) == (fill.command_id, *values):
                return True
            self._record_incident(
                command_id=fill.command_id,
                kind="contradictory_fill_evidence",
                detail={"fill_id": fill.fill_id, "observed": canonicalize(fill)},
            )
            return False

    def record_account_observation(self, observation: AccountObservation) -> str:
        """Persist one typed canonical observation without accepting raw venue payloads."""
        if type(observation) is not AccountObservation:
            raise TypeError("account observation must be an AccountObservation")
        payload_json = _canonical_json(canonicalize(observation))
        observation_id = _new_id("observation")
        with transaction(self._require_connection()):
            self._require_connection().execute(
                """
                INSERT INTO account_observations(
                    observation_id, account_id, product, observed_at_utc, source, payload_json, payload_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    observation.account_id,
                    observation.product.value,
                    _timestamp_text(observation.observed_at),
                    "canonical_account_observation",
                    payload_json,
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                ),
            )
        return observation_id

    def record_conversion_rejection(
        self,
        snapshot: SourceAnalysisSnapshot,
        target: ExecutionTarget,
        reason: ConversionRejectionReason,
    ) -> None:
        """Persist a D-02 rejection using only stable source and target metadata."""
        if type(snapshot) is not SourceAnalysisSnapshot or type(target) is not ExecutionTarget:
            raise TypeError("proposal rejection requires canonical snapshot and target values")
        if type(reason) is not ConversionRejectionReason:
            raise TypeError("proposal rejection requires a stable conversion reason")
        connection = self._require_connection()
        with transaction(connection):
            snapshot_digest = self._record_proposal_source(snapshot, target)
            now = _timestamp_text(self.utc_now())
            self._append_proposal_audit_fact(
                kind="conversion_rejected",
                source_id=snapshot.source_id,
                source_digest=snapshot_digest,
                snapshot_digest=snapshot_digest,
                intent_digest=None,
                policy_digest=None,
                evidence_digest=None,
                reason_code=reason.value,
                fee_amount=None,
                observed_at=_timestamp_text(snapshot.completed_at),
                recorded_at=now,
                summary={
                    "target_id": target.target_id,
                    "mode": target.mode,
                    "account_id": target.account_id,
                    "product": target.product,
                    "reason_code": reason.value,
                },
            )

    def record_candidate(self, candidate: CandidateExecutionIntent) -> None:
        """Persist an accepted candidate and its immutable source provenance."""
        if type(candidate) is not CandidateExecutionIntent:
            raise TypeError("candidate audit requires a CandidateExecutionIntent")
        connection = self._require_connection()
        with transaction(connection):
            snapshot_digest = self._record_candidate_source(candidate)
            now = _timestamp_text(self.utc_now())
            candidate_json = self._safe_canonical_json(_candidate_canonical_data(candidate))
            context_payload = product_context_to_canonical_payload(candidate.context)
            connection.execute(
                """
                INSERT OR IGNORE INTO proposal_candidates(
                    intent_digest, snapshot_digest, candidate_json, recorded_at_utc,
                    product_context_json, product_context_digest
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.intent_digest,
                    snapshot_digest,
                    candidate_json,
                    now,
                    context_payload,
                    product_context_digest(candidate.context),
                ),
            )
            self._append_proposal_audit_fact(
                kind="candidate_accepted",
                source_id=candidate.source_id,
                source_digest=candidate.intent_digest,
                snapshot_digest=snapshot_digest,
                intent_digest=candidate.intent_digest,
                policy_digest=None,
                evidence_digest=None,
                reason_code=None,
                fee_amount=None,
                observed_at=_timestamp_text(candidate.source_completed_at),
                recorded_at=now,
                summary={
                    "target_id": candidate.target.target_id,
                    "mode": candidate.target.mode,
                    "account_id": candidate.target.account_id,
                    "product": candidate.target.product,
                    "symbol": candidate.symbol,
                    "side": candidate.side,
                    "order_type": candidate.order_type,
                },
            )

    def record_evidence(self, candidate: CandidateExecutionIntent, evidence: EvidenceBundle) -> None:
        """Persist a complete canonical bundle tied to an existing accepted candidate."""
        if type(candidate) is not CandidateExecutionIntent or type(evidence) is not EvidenceBundle:
            raise TypeError("evidence audit requires canonical candidate and evidence values")
        connection = self._require_connection()
        with transaction(connection):
            snapshot_digest = self._candidate_snapshot_digest(candidate)
            now = _timestamp_text(self.utc_now())
            evidence_json = self._safe_canonical_json(canonicalize(evidence))
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO proposal_evidence(
                    evidence_digest, intent_digest, evidence_json, observed_at_utc, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_digest,
                    candidate.intent_digest,
                    evidence_json,
                    _timestamp_text(evidence.quote.observed_at),
                    now,
                ),
            )
            if inserted.rowcount:
                self._append_proposal_audit_fact(
                    kind="evidence_recorded",
                    source_id=candidate.source_id,
                    source_digest=candidate.intent_digest,
                    snapshot_digest=snapshot_digest,
                    intent_digest=candidate.intent_digest,
                    policy_digest=None,
                    evidence_digest=evidence.evidence_digest,
                    reason_code=None,
                    fee_amount=None,
                    observed_at=_timestamp_text(evidence.quote.observed_at),
                    recorded_at=now,
                    summary={
                        "target_id": candidate.target.target_id,
                        "symbol": candidate.symbol,
                        "quote_identifier": evidence.fee_rate.quote_identifier,
                        "fee_rate_version": evidence.fee_rate.rate_version,
                    },
                )

    def record_risk_assessment(
        self, candidate: CandidateExecutionIntent, assessment: RiskAssessment
    ) -> None:
        """Persist a redacted, reproducible risk decision without issuing a ticket."""
        if type(candidate) is not CandidateExecutionIntent or type(assessment) is not RiskAssessment:
            raise TypeError("risk audit requires canonical candidate and assessment values")
        connection = self._require_connection()
        with transaction(connection):
            if assessment.accepted:
                self._require_ready_in_transaction()
            policy = _policy_for_assessment(candidate, assessment) if assessment.accepted else None
            snapshot_digest = self._candidate_snapshot_digest(candidate)
            now = _timestamp_text(self.utc_now())
            fee_amount = (
                decimal_to_canonical(assessment.fee_estimate.amount)
                if assessment.fee_estimate is not None
                else None
            )
            assessment_id = _new_id("proposal-assessment")
            reason_codes = tuple(reason.value for reason in assessment.reason_codes)
            connection.execute(
                """
                INSERT INTO proposal_risk_assessments(
                    assessment_id, intent_digest, accepted, policy_version, policy_digest,
                    evidence_digest, reason_codes_json, fee_amount, assessment_json,
                    observed_at_utc, recorded_at_utc,
                    policy_id, policy_version_bound, policy_digest_bound
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment_id,
                    candidate.intent_digest,
                    int(assessment.accepted),
                    assessment.policy_version,
                    assessment.policy_digest,
                    assessment.evidence_digest,
                    _canonical_json(reason_codes),
                    fee_amount,
                    self._safe_canonical_json(canonicalize(assessment)),
                    now,
                    now,
                    policy.policy_id if policy is not None else None,
                    policy.policy_version if policy is not None else None,
                    policy.policy_digest if policy is not None else None,
                ),
            )
            if policy is not None:
                connection.execute(
                    """
                    UPDATE proposal_candidates
                    SET policy_id = ?, policy_version_bound = ?, policy_digest_bound = ?
                    WHERE intent_digest = ?
                    """,
                    (policy.policy_id, policy.policy_version, policy.policy_digest, candidate.intent_digest),
                )
            self._append_proposal_audit_fact(
                kind="risk_assessed" if assessment.accepted else "risk_rejected",
                source_id=candidate.source_id,
                source_digest=candidate.intent_digest,
                snapshot_digest=snapshot_digest,
                intent_digest=candidate.intent_digest,
                policy_digest=assessment.policy_digest,
                evidence_digest=assessment.evidence_digest,
                reason_code=reason_codes[0] if reason_codes else None,
                fee_amount=fee_amount,
                observed_at=now,
                recorded_at=now,
                summary={
                    "accepted": assessment.accepted,
                    "policy_version": assessment.policy_version,
                    "reason_codes": reason_codes,
                    "fee_rate_version": (
                        assessment.fee_estimate.rate_version
                        if assessment.fee_estimate is not None
                        else None
                    ),
                    "quote_identifier": (
                        assessment.fee_estimate.quote_identifier
                        if assessment.fee_estimate is not None
                        else None
                    ),
                },
            )

    def list_proposal_audit_facts(self) -> tuple[ProposalAuditFact, ...]:
        """Load controlled audit facts in durable insertion order for pre-ticket review."""
        rows = self._require_connection().execute(
            """
            SELECT kind, source_id, source_digest, policy_digest, evidence_digest,
                   reason_code, fee_amount, observed_at_utc, recorded_at_utc, summary_json
            FROM proposal_audit_facts
            ORDER BY recorded_at_utc, rowid
            """
        ).fetchall()
        return tuple(
            ProposalAuditFact(
                kind=row[0],
                source_id=row[1],
                source_digest=row[2],
                policy_digest=row[3],
                evidence_digest=row[4],
                reason_code=row[5],
                fee_amount=row[6],
                observed_at=_timestamp_from_text(row[7]),
                recorded_at=_timestamp_from_text(row[8]),
                summary_json=row[9],
            )
            for row in rows
        )

    def create_pending_ticket_if_absent(
        self,
        candidate: CandidateExecutionIntent,
        assessment: RiskAssessment,
        created_at: datetime,
    ) -> ApprovalTicket:
        """Create one ticket only after durable candidate, evidence, and acceptance checks."""
        if type(candidate) is not CandidateExecutionIntent or type(assessment) is not RiskAssessment:
            raise TypeError("ticket issuance requires canonical candidate and assessment values")
        if not assessment.accepted or assessment.fee_estimate is None:
            raise LedgerStorageError("only accepted assessments with fee evidence can issue tickets")
        connection = self._require_connection()
        with transaction(connection):
            self._require_ready_in_transaction()
            existing = self._load_ticket_for_binding(candidate, assessment)
            if existing is not None:
                return existing
            candidate_row = connection.execute(
                "SELECT candidate_json, product_context_json, product_context_digest "
                "FROM proposal_candidates WHERE intent_digest = ?",
                (candidate.intent_digest,),
            ).fetchone()
            evidence_row = connection.execute(
                "SELECT evidence_json FROM proposal_evidence WHERE evidence_digest = ? AND intent_digest = ?",
                (assessment.evidence_digest, candidate.intent_digest),
            ).fetchone()
            assessment_row = connection.execute(
                """
                SELECT assessment_json FROM proposal_risk_assessments
                WHERE intent_digest = ? AND accepted = 1 AND policy_version = ?
                  AND policy_digest = ? AND evidence_digest = ?
                ORDER BY recorded_at_utc DESC, rowid DESC LIMIT 1
                """,
                (
                    candidate.intent_digest,
                    assessment.policy_version,
                    assessment.policy_digest,
                    assessment.evidence_digest,
                ),
            ).fetchone()
            if candidate_row is None or evidence_row is None or assessment_row is None:
                raise LedgerStorageError("ticket issuance requires persisted candidate, evidence, and acceptance")
            if candidate_row[0] != self._safe_canonical_json(_candidate_canonical_data(candidate)):
                raise LedgerStorageError("ticket candidate does not match durable proposal facts")
            if candidate_row[1] is not None and (
                candidate_row[1] != product_context_to_canonical_payload(candidate.context)
                or candidate_row[2] != product_context_digest(candidate.context)
            ):
                raise LedgerStorageError("ticket context does not match durable proposal facts")
            if json.loads(assessment_row[0]) != canonicalize(assessment):
                raise LedgerStorageError("ticket assessment does not match durable proposal facts")
            binding = _ticket_binding_from_persisted_json(
                candidate=candidate, evidence_json=evidence_row[0], assessment=assessment
            )
            ticket = ApprovalTicket.create(
                ticket_id=_new_id("approval-ticket"), binding=binding, created_at=created_at
            )
            try:
                connection.execute(
                    """
                    INSERT INTO approval_tickets(
                        ticket_id, intent_digest, policy_digest, evidence_digest, policy_version,
                        binding_json, status, created_at_utc, expires_at_utc,
                        terminal_event, terminal_reason, terminal_at_utc,
                        product_context_json, product_context_digest,
                        policy_id, policy_version_bound, policy_digest_bound
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, ?)
                    """,
                    (
                        ticket.ticket_id,
                        ticket.candidate_digest,
                        ticket.policy_digest,
                        ticket.evidence_digest,
                        ticket.policy_version,
                        _canonical_json(canonicalize(binding)),
                        ticket.status.value,
                        _timestamp_text(ticket.created_at),
                        _timestamp_text(ticket.expires_at),
                        binding.product_context_payload,
                        binding.product_context_digest,
                        binding.policy_id,
                        binding.policy_version,
                        binding.policy_digest,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = self._load_ticket_for_binding(candidate, assessment)
                if existing is None:
                    raise
                return existing
            self._append_approval_ticket_event(
                ticket=ticket,
                event_type="issued",
                reason="persisted_accepted_proposal",
                actor_label="proposal_service",
                occurred_at=ticket.created_at,
            )
            return ticket

    def list_approval_tickets(self) -> tuple[ApprovalTicket, ...]:
        """Load review tickets without creating command or outbound authority."""
        rows = self._require_connection().execute(
            """
            SELECT ticket_id, binding_json, status, created_at_utc, expires_at_utc,
                   terminal_event, terminal_reason, terminal_at_utc
            FROM approval_tickets ORDER BY created_at_utc, rowid
            """
        ).fetchall()
        return tuple(_ticket_from_row(row) for row in rows)

    def get_kill_switch_state(self) -> KillSwitchState:
        """Load the durable singleton state, which defaults fail-closed after a latch."""
        return self._load_kill_switch_state_in_transaction()

    def latch_kill_switch(
        self,
        *,
        reason: str,
        actor_label: str,
        policy_summary: str,
        evidence_summary: str,
        cancellation_supported: bool,
    ) -> KillSwitchState:
        """Atomically latch, revoke pending review, and enqueue eligible cancellation work."""
        if not all((reason, actor_label, policy_summary, evidence_summary)):
            raise ValueError("kill switch latch requires controlled reason, actor, policy, and evidence")
        connection = self._require_connection()
        with transaction(connection):
            current = self._load_kill_switch_state_in_transaction()
            if current.status is KillSwitchStatus.LATCHED:
                return current
            now = _timestamp_text(self.utc_now())
            connection.execute(
                """
                INSERT INTO kill_switch_state(
                    singleton_id, status, reason, actor_label, policy_summary, evidence_summary, changed_at_utc
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    status = excluded.status, reason = excluded.reason, actor_label = excluded.actor_label,
                    policy_summary = excluded.policy_summary, evidence_summary = excluded.evidence_summary,
                    changed_at_utc = excluded.changed_at_utc
                """,
                (KillSwitchStatus.LATCHED.value, reason, actor_label, policy_summary, evidence_summary, now),
            )
            self._record_kill_switch_event(KillSwitchStatus.LATCHED, reason, actor_label, now)
            self._replace_recovery_scopes_in_transaction(now)
            pending_rows = connection.execute(
                """
                SELECT ticket_id, binding_json, status, created_at_utc, expires_at_utc,
                       terminal_event, terminal_reason, terminal_at_utc
                FROM approval_tickets WHERE status = ?
                """,
                (ApprovalTicketStatus.PENDING.value,),
            ).fetchall()
            for row in pending_rows:
                self._terminate_ticket_in_transaction(
                    _ticket_from_row(row), TicketTerminalEvent.KILL_SWITCH_REVOKED, "kill_switch_latched"
                )
            if cancellation_supported:
                for command_id, client_order_id in connection.execute(
                    """
                    SELECT commands.command_id, commands.client_order_id
                    FROM order_commands AS commands JOIN orders ON orders.command_id = commands.command_id
                    WHERE orders.lifecycle_state IN (?, ?, ?)
                    """,
                    (OrderState.ACKNOWLEDGED.value, OrderState.OPEN.value, OrderState.PARTIALLY_FILLED.value),
                ).fetchall():
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO cancellation_work(
                            work_id, command_id, client_order_id, status, request_outcome,
                            remote_resolution, created_at_utc, processed_at_utc
                        ) VALUES (?, ?, ?, 'queued', NULL, NULL, ?, NULL)
                        """,
                        (_new_id("cancellation-work"), command_id, client_order_id, now),
                    )
            return KillSwitchState(
                KillSwitchStatus.LATCHED, reason, actor_label, policy_summary, evidence_summary,
                _timestamp_from_text(now),
            )

    def list_cancellation_work(self, *, pending_only: bool = False) -> tuple[CancellationWork, ...]:
        """Load cancellation request rows without treating them as remote lifecycle evidence."""
        query = """
            SELECT work_id, command_id, client_order_id, status, request_outcome, remote_resolution
            FROM cancellation_work
        """
        if pending_only:
            query += " WHERE status = 'queued'"
        query += " ORDER BY created_at_utc, work_id"
        return tuple(CancellationWork(*row) for row in self._require_connection().execute(query).fetchall())

    def record_cancellation_work_result(self, work_id: str, outcome: str) -> CancellationWork:
        """Record an attempted cancellation request without claiming it resolved exposure."""
        if outcome not in {"requested", "timeout"}:
            raise ValueError("cancellation request outcome must be requested or timeout")
        connection = self._require_connection()
        with transaction(connection):
            command_row = connection.execute(
                """
                SELECT work.command_id, orders.lifecycle_state
                FROM cancellation_work AS work JOIN orders ON orders.command_id = work.command_id
                WHERE work.work_id = ? AND work.status = 'queued'
                """,
                (work_id,),
            ).fetchone()
            if command_row is None:
                raise LedgerStorageError("cancellation work is no longer queued")
            command_id, lifecycle_state = command_row
            previous_state = OrderState(lifecycle_state)
            if previous_state in {
                OrderState.ACKNOWLEDGED,
                OrderState.OPEN,
                OrderState.PARTIALLY_FILLED,
            }:
                requested_state = assert_transition(
                    previous_state, LifecycleEvent.CANCELLATION_REQUESTED
                )
                self._append_event(
                    command_id=command_id,
                    previous_state=previous_state,
                    new_state=requested_state,
                    event=LifecycleEvent.CANCELLATION_REQUESTED,
                    occurred_at=_timestamp_text(self.utc_now()),
                    detail={"source": "kill_switch", "outcome": outcome},
                )
                connection.execute(
                    "UPDATE orders SET lifecycle_state = ? WHERE command_id = ?",
                    (requested_state.value, command_id),
                )
            changed = connection.execute(
                """
                UPDATE cancellation_work SET status = 'processed', request_outcome = ?, processed_at_utc = ?
                WHERE work_id = ? AND status = 'queued'
                """,
                (outcome, _timestamp_text(self.utc_now()), work_id),
            )
            if changed.rowcount != 1:
                raise LedgerStorageError("cancellation work is no longer queued")
            row = connection.execute(
                """
                SELECT work_id, command_id, client_order_id, status, request_outcome, remote_resolution
                FROM cancellation_work WHERE work_id = ?
                """,
                (work_id,),
            ).fetchone()
            return CancellationWork(*row)

    def _record_recovery_assessment_from_service(
        self, scope: RecoveryScope, assessment: RecoveryAssessment
    ) -> RecoveryAssessment | None:
        """Private service-only recorder for complete, fresh recovery evidence."""
        if type(scope) is not RecoveryScope or type(assessment) is not RecoveryAssessment:
            return None
        connection = self._require_connection()
        with transaction(connection):
            durable_scope = self._load_current_recovery_scope_in_transaction(scope.persistent_scope_id)
            if durable_scope is None or durable_scope != scope:
                return None
            if (
                assessment.persistent_scope_id != scope.persistent_scope_id
                or assessment.scope_digest != scope.scope_digest
                or assessment.target_digest != scope.target_digest
                or assessment.policy_version != scope.policy_version
                or assessment.policy_digest != scope.policy_digest
                or assessment.recovery_assessment_id is not None
                or not assessment.accepted
                or assessment.reason_codes
                or not _is_recovery_timestamp_fresh(assessment.observed_at, self.utc_now())
            ):
                return None
            try:
                RecoveryEvidence.from_canonical_json(
                    assessment.evidence_json,
                    assessment.evidence_digest,
                    durable_scope,
                    self.utc_now(),
                )
            except ValueError:
                return None
            assessment_id = _new_id("recovery-assessment")
            connection.execute(
                """
                INSERT INTO recovery_assessments(
                    recovery_assessment_id, persistent_scope_id, scope_digest, target_digest,
                    policy_version, policy_digest, evidence_digest, evidence_json, accepted,
                    reason_codes_json, observed_at_utc, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment_id,
                    assessment.persistent_scope_id,
                    assessment.scope_digest,
                    assessment.target_digest,
                    assessment.policy_version,
                    assessment.policy_digest,
                    assessment.evidence_digest,
                    assessment.evidence_json,
                    int(assessment.accepted),
                    _canonical_json(assessment.reason_codes),
                    _timestamp_text(assessment.observed_at),
                    _timestamp_text(self.utc_now()),
                ),
            )
            return replace(assessment, recovery_assessment_id=assessment_id)

    def count_recovery_assessments(self) -> int:
        """Expose a test-only count without returning recovery data as authority."""
        return int(
            self._require_connection().execute("SELECT COUNT(*) FROM recovery_assessments").fetchone()[0]
        )

    def begin_kill_switch_recovery(
        self,
        actor_label: str,
        *,
        assessment_ids: tuple[str, ...],
    ) -> bool:
        """Move to RECOVERING only after processed work and normalized terminal evidence."""
        zero_scope_proof = None
        if not self._has_active_recovery_scopes():
            zero_scope_proof = self._collect_zero_scope_clearance()
            if zero_scope_proof is None:
                return False
        connection = self._require_connection()
        with transaction(connection):
            if not actor_label or self._load_kill_switch_state_in_transaction().status is not KillSwitchStatus.LATCHED:
                return False
            if not self._recovery_facts_are_clear_in_transaction():
                return False
            if not self._recovery_clearance_matches_current_scopes_in_transaction(
                assessment_ids, zero_scope_proof, zero_scope_requires_challenge=False
            ):
                return False
            now = self.utc_now()
            begin_event_id = self._set_kill_switch_status_in_transaction(
                KillSwitchStatus.RECOVERING,
                actor_label,
                _timestamp_text(now),
                assessment_ids,
                zero_scope_proof,
            )
            if zero_scope_proof is not None:
                self._create_zero_scope_recovery_transition_in_transaction(
                    begin_event_id, zero_scope_proof, now
                )
            return True

    def list_kill_switch_recovery_scopes(self) -> tuple[RecoveryScope, ...]:
        """Return only active immutable scopes created at the durable latch boundary."""
        rows = self._require_connection().execute(
            """
            SELECT persistent_scope_id, target_json, target_digest, policy_version, policy_digest, scope_digest
            FROM recovery_scopes WHERE active = 1 ORDER BY persistent_scope_id
            """
        ).fetchall()
        return tuple(_recovery_scope_from_row(row) for row in rows)

    def _pending_zero_scope_recovery_challenge(self) -> str | None:
        """Load the internal-only pending recovery binding before fresh collection."""
        connection = self._require_connection()
        if self._load_kill_switch_state_in_transaction().status is not KillSwitchStatus.RECOVERING:
            return None
        rows = connection.execute(
            """
            SELECT transition_challenge, challenge_expires_at_utc
            FROM zero_scope_recovery_transitions
            WHERE status = 'pending'
            """
        ).fetchall()
        if len(rows) != 1:
            return None
        challenge, expires_at = rows[0]
        try:
            expires = _timestamp_from_text(str(expires_at))
        except LedgerStorageError:
            return None
        if self.utc_now() >= expires:
            return None
        return str(challenge)

    def complete_kill_switch_recovery(
        self,
        actor_label: str,
        *,
        assessment_ids: tuple[str, ...],
    ) -> bool:
        """Return READY only after explicit operator action and a fresh accepted assessment."""
        zero_scope_proof = None
        if not self._has_active_recovery_scopes():
            challenge = self._pending_zero_scope_recovery_challenge()
            if challenge is None:
                return False
            zero_scope_proof = self._collect_zero_scope_clearance(transition_challenge=challenge)
            if zero_scope_proof is None:
                return False
        connection = self._require_connection()
        with transaction(connection):
            if (
                not actor_label
                or self._load_kill_switch_state_in_transaction().status is not KillSwitchStatus.RECOVERING
                or not self._recovery_facts_are_clear_in_transaction()
                or not self._recovery_clearance_matches_current_scopes_in_transaction(
                    assessment_ids, zero_scope_proof, zero_scope_requires_challenge=True
                )
            ):
                return False
            now = self.utc_now()
            if zero_scope_proof is not None and not self._consume_zero_scope_recovery_transition_in_transaction(
                zero_scope_proof, now
            ):
                return False
            self._set_kill_switch_status_in_transaction(
                KillSwitchStatus.READY,
                actor_label,
                _timestamp_text(now),
                assessment_ids,
                zero_scope_proof,
            )
            return True

    def terminate_approval_ticket(
        self,
        ticket_id: str,
        event: TicketTerminalEvent,
        reason: str,
        binding: TicketBinding | None = None,
    ) -> ApprovalTicket:
        """Append one terminal D-12 event and retain its immutable binding snapshot."""
        if type(event) is not TicketTerminalEvent:
            raise TypeError("ticket termination requires a canonical terminal event")
        connection = self._require_connection()
        with transaction(connection):
            row = connection.execute(
                """
                SELECT ticket_id, binding_json, status, created_at_utc, expires_at_utc,
                       terminal_event, terminal_reason, terminal_at_utc
                FROM approval_tickets WHERE ticket_id = ?
                """,
                (ticket_id,),
            ).fetchone()
            if row is None:
                raise LedgerStorageError("approval ticket does not exist")
            ticket = _ticket_from_row(row)
            if event is TicketTerminalEvent.BINDING_INVALIDATED:
                if binding is None or not ticket.requires_invalidation(binding):
                    raise LedgerStorageError("invalidation requires a changed binding snapshot")
            elif binding is not None:
                raise LedgerStorageError("only invalidation accepts a supplied binding snapshot")
            terminal = ticket.terminate(event=event, reason=reason, occurred_at=self.utc_now())
            changed = connection.execute(
                """
                UPDATE approval_tickets
                SET status = ?, terminal_event = ?, terminal_reason = ?, terminal_at_utc = ?
                WHERE ticket_id = ? AND status = ?
                """,
                (
                    terminal.status.value,
                    event.value,
                    reason,
                    _timestamp_text(terminal.terminal_at),
                    ticket_id,
                    ApprovalTicketStatus.PENDING.value,
                ),
            )
            if changed.rowcount != 1:
                raise LedgerStorageError("approval ticket is no longer pending")
            self._append_approval_ticket_event(
                ticket=terminal,
                event_type=event.value,
                reason=reason,
                actor_label="operator" if event is TicketTerminalEvent.OPERATOR_REJECTED else "system",
                occurred_at=terminal.terminal_at,
                binding=binding,
            )
            return terminal

    def _terminate_ticket_in_transaction(
        self,
        ticket: ApprovalTicket,
        event: TicketTerminalEvent,
        reason: str,
        binding: TicketBinding | None = None,
    ) -> ApprovalTicket:
        """Append a conditional terminal event while the caller owns one immediate transaction."""
        if event is TicketTerminalEvent.BINDING_INVALIDATED and (
            binding is None or not ticket.requires_invalidation(binding)
        ):
            raise LedgerStorageError("invalidation requires a changed binding snapshot")
        terminal = ticket.terminate(event=event, reason=reason, occurred_at=self.utc_now())
        changed = self._require_connection().execute(
            """
            UPDATE approval_tickets
            SET status = ?, terminal_event = ?, terminal_reason = ?, terminal_at_utc = ?
            WHERE ticket_id = ? AND status = ?
            """,
            (
                terminal.status.value,
                event.value,
                reason,
                _timestamp_text(terminal.terminal_at),
                ticket.ticket_id,
                ApprovalTicketStatus.PENDING.value,
            ),
        )
        if changed.rowcount != 1:
            raise LedgerStorageError("approval ticket is no longer pending")
        self._append_approval_ticket_event(
            ticket=terminal,
            event_type=event.value,
            reason=reason,
            actor_label="system",
            occurred_at=terminal.terminal_at,
            binding=binding,
        )
        return terminal

    def _record_current_refresh_audit(
        self,
        candidate: CandidateExecutionIntent,
        evidence: EvidenceBundle,
        assessment: RiskAssessment,
    ) -> None:
        """Append the exact successful refresh facts inside the consume transaction."""
        connection = self._require_connection()
        snapshot_digest = self._candidate_snapshot_digest(candidate)
        now = _timestamp_text(self.utc_now())
        evidence_json = self._safe_canonical_json(canonicalize(evidence))
        inserted = connection.execute(
            """
            INSERT OR IGNORE INTO proposal_evidence(
                evidence_digest, intent_digest, evidence_json, observed_at_utc, recorded_at_utc
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                evidence.evidence_digest,
                candidate.intent_digest,
                evidence_json,
                _timestamp_text(evidence.quote.observed_at),
                now,
            ),
        )
        if inserted.rowcount:
            self._append_proposal_audit_fact(
                kind="evidence_recorded",
                source_id=candidate.source_id,
                source_digest=candidate.intent_digest,
                snapshot_digest=snapshot_digest,
                intent_digest=candidate.intent_digest,
                policy_digest=None,
                evidence_digest=evidence.evidence_digest,
                reason_code=None,
                fee_amount=None,
                observed_at=_timestamp_text(evidence.quote.observed_at),
                recorded_at=now,
                summary={
                    "target_id": candidate.target.target_id,
                    "symbol": candidate.symbol,
                    "quote_identifier": evidence.fee_rate.quote_identifier,
                    "fee_rate_version": evidence.fee_rate.rate_version,
                },
            )
        fee_amount = decimal_to_canonical(assessment.fee_estimate.amount)
        reason_codes = tuple(reason.value for reason in assessment.reason_codes)
        connection.execute(
            """
            INSERT INTO proposal_risk_assessments(
                assessment_id, intent_digest, accepted, policy_version, policy_digest,
                evidence_digest, reason_codes_json, fee_amount, assessment_json,
                observed_at_utc, recorded_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("proposal-assessment"),
                candidate.intent_digest,
                1,
                assessment.policy_version,
                assessment.policy_digest,
                assessment.evidence_digest,
                _canonical_json(reason_codes),
                fee_amount,
                self._safe_canonical_json(canonicalize(assessment)),
                now,
                now,
            ),
        )
        self._append_proposal_audit_fact(
            kind="risk_assessed",
            source_id=candidate.source_id,
            source_digest=candidate.intent_digest,
            snapshot_digest=snapshot_digest,
            intent_digest=candidate.intent_digest,
            policy_digest=assessment.policy_digest,
            evidence_digest=assessment.evidence_digest,
            reason_code=reason_codes[0] if reason_codes else None,
            fee_amount=fee_amount,
            observed_at=now,
            recorded_at=now,
            summary={
                "accepted": True,
                "policy_version": assessment.policy_version,
                "reason_codes": reason_codes,
                "fee_rate_version": assessment.fee_estimate.rate_version,
                "quote_identifier": assessment.fee_estimate.quote_identifier,
            },
        )

    def _load_ticket_for_binding(
        self, candidate: CandidateExecutionIntent, assessment: RiskAssessment
    ) -> ApprovalTicket | None:
        """Load the one durable ticket selected by candidate and accepted-assessment identity."""
        row = self._require_connection().execute(
            """
            SELECT ticket_id, binding_json, status, created_at_utc, expires_at_utc,
                   terminal_event, terminal_reason, terminal_at_utc
            FROM approval_tickets
            WHERE intent_digest = ? AND policy_digest = ? AND evidence_digest = ?
            """,
            (candidate.intent_digest, assessment.policy_digest, assessment.evidence_digest),
        ).fetchone()
        return None if row is None else _ticket_from_row(row)

    def _append_approval_ticket_event(
        self,
        *,
        ticket: ApprovalTicket,
        event_type: str,
        reason: str,
        actor_label: str,
        occurred_at: datetime | None,
        binding: TicketBinding | None = None,
    ) -> None:
        """Append one immutable ticket event inside the active transaction."""
        if occurred_at is None:
            raise LedgerStorageError("ticket event timestamp is required")
        event_binding = binding or ticket.binding
        self._require_connection().execute(
            """
            INSERT INTO approval_ticket_events(
                event_id, ticket_id, event_type, reason, actor_label, binding_json, occurred_at_utc,
                policy_id, policy_version_bound, policy_digest_bound
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("approval-ticket-event"),
                ticket.ticket_id,
                event_type,
                reason,
                actor_label,
                _canonical_json(canonicalize(event_binding)),
                _timestamp_text(occurred_at),
                event_binding.policy_id,
                event_binding.policy_version,
                event_binding.policy_digest,
            ),
        )

    def _record_proposal_source(
        self, snapshot: SourceAnalysisSnapshot, target: ExecutionTarget
    ) -> str:
        """Insert one immutable source snapshot projection and return its digest."""
        snapshot_digest = hashlib.sha256(
            _canonical_json(canonicalize(snapshot)).encode("utf-8")
        ).hexdigest()
        self._require_connection().execute(
            """
            INSERT OR IGNORE INTO proposal_sources(
                snapshot_digest, source_id, completed_at_utc, schema_version,
                parser_version, decision_digest, target_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_digest,
                self._safe_string(snapshot.source_id),
                _timestamp_text(snapshot.completed_at),
                snapshot.schema_version,
                snapshot.parser_version,
                snapshot.decision_digest,
                self._safe_canonical_json(canonicalize(target)),
            ),
        )
        return snapshot_digest

    def _record_candidate_source(self, candidate: CandidateExecutionIntent) -> str:
        """Persist source metadata reconstructed from the candidate's frozen provenance."""
        snapshot_digest = self._candidate_snapshot_digest(candidate)
        self._require_connection().execute(
            """
            INSERT OR IGNORE INTO proposal_sources(
                snapshot_digest, source_id, completed_at_utc, schema_version,
                parser_version, decision_digest, target_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_digest,
                self._safe_string(candidate.source_id),
                _timestamp_text(candidate.source_completed_at),
                candidate.source_schema_version,
                candidate.source_parser_version,
                candidate.source_decision_digest,
                self._safe_canonical_json(canonicalize(candidate.target)),
            ),
        )
        return snapshot_digest

    @staticmethod
    def _candidate_snapshot_digest(candidate: CandidateExecutionIntent) -> str:
        """Hash only the frozen analysis provenance retained by a candidate."""
        return hashlib.sha256(
            _canonical_json(
                canonicalize(
                    {
                        "source_id": candidate.source_id,
                        "source_completed_at": candidate.source_completed_at,
                        "source_schema_version": candidate.source_schema_version,
                        "source_parser_version": candidate.source_parser_version,
                        "source_decision_digest": candidate.source_decision_digest,
                        "target": candidate.target,
                    }
                )
            ).encode("utf-8")
        ).hexdigest()

    def _append_proposal_audit_fact(
        self,
        *,
        kind: str,
        source_id: str,
        source_digest: str,
        snapshot_digest: str,
        intent_digest: str | None,
        policy_digest: str | None,
        evidence_digest: str | None,
        reason_code: str | None,
        fee_amount: str | None,
        observed_at: str,
        recorded_at: str,
        summary: Mapping[str, Any],
    ) -> None:
        """Append one allowlisted fact while the caller's transaction is active."""
        self._require_connection().execute(
            """
            INSERT INTO proposal_audit_facts(
                fact_id, kind, source_id, source_digest, source_snapshot_digest,
                intent_digest, policy_digest, evidence_digest, reason_code, fee_amount,
                observed_at_utc, recorded_at_utc, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("proposal-audit"),
                kind,
                self._safe_string(source_id),
                source_digest,
                snapshot_digest,
                intent_digest,
                policy_digest,
                evidence_digest,
                reason_code,
                fee_amount,
                observed_at,
                recorded_at,
                self._safe_canonical_json(dict(summary)),
            ),
        )

    def _safe_string(self, value: str) -> str:
        """Serialize one bounded audit value after central output redaction."""
        return self._redactor.redact(value)

    def _safe_canonical_json(self, value: Any) -> str:
        """Canonicalize a redacted, JSON-compatible audit value."""
        return _canonical_json(self._redactor.redact(value))

    def _require_ready_in_transaction(self) -> None:
        """Fail closed at every durable path that could create outbound authority."""
        if self._load_kill_switch_state_in_transaction().status is not KillSwitchStatus.READY:
            raise LedgerStorageError("kill switch is not ready for new authorization")

    def _load_kill_switch_state_in_transaction(self) -> KillSwitchState:
        """Read the singleton under the caller's immediate transaction."""
        row = self._require_connection().execute(
            """
            SELECT status, reason, actor_label, policy_summary, evidence_summary, changed_at_utc
            FROM kill_switch_state WHERE singleton_id = 1
            """
        ).fetchone()
        if row is None:
            return KillSwitchState(KillSwitchStatus.READY)
        try:
            return KillSwitchState(
                status=KillSwitchStatus(row[0]),
                reason=row[1],
                actor_label=row[2],
                policy_summary=row[3],
                evidence_summary=row[4],
                changed_at=_timestamp_from_text(row[5]),
            )
        except ValueError as exc:
            raise LedgerStorageError("stored kill switch state is invalid") from exc

    def _recovery_facts_are_clear_in_transaction(self) -> bool:
        """Check only persisted work and normalized evidence, never request outcomes."""
        connection = self._require_connection()
        pending_work = connection.execute(
            "SELECT COUNT(*) FROM cancellation_work WHERE status != 'processed'"
        ).fetchone()[0]
        unresolved = connection.execute(
            """
            SELECT COUNT(*) FROM orders
            WHERE lifecycle_state NOT IN (?, ?, ?)
            """,
            (OrderState.FILLED.value, OrderState.CANCELLED.value, OrderState.REJECTED.value),
        ).fetchone()[0]
        unresolved_claims = connection.execute(
            """
            SELECT COUNT(*)
            FROM submission_claims AS claims
            JOIN orders ON orders.command_id = claims.command_id
            WHERE claims.status = 'outbound_started'
              AND orders.lifecycle_state NOT IN (?, ?, ?)
            """,
            (OrderState.FILLED.value, OrderState.CANCELLED.value, OrderState.REJECTED.value),
        ).fetchone()[0]
        return pending_work == 0 and unresolved == 0 and unresolved_claims == 0

    def _has_active_recovery_scopes(self) -> bool:
        """Read the durable scope selector before any ledger-owned gateway collection."""
        count = self._require_connection().execute(
            "SELECT COUNT(*) FROM recovery_scopes WHERE active = 1"
        ).fetchone()[0]
        return bool(count)

    def _collect_zero_scope_clearance(
        self, *, transition_challenge: str | None = None
    ) -> ZeroScopeClearanceProof | None:
        """Collect zero-scope facts only from the constructor-owned collaborator."""
        collector = self._zero_scope_clearance_collector
        if collector is None:
            return None
        return collector.collect(transition_challenge=transition_challenge)

    def _recovery_clearance_matches_current_scopes_in_transaction(
        self,
        assessment_ids: tuple[str, ...],
        zero_scope_proof: ZeroScopeClearanceProof | None,
        *,
        zero_scope_requires_challenge: bool,
    ) -> bool:
        """Select the sole admissible clearance form from the transaction-loaded scope set."""
        active_scope_count = self._require_connection().execute(
            "SELECT COUNT(*) FROM recovery_scopes WHERE active = 1"
        ).fetchone()[0]
        if active_scope_count == 0:
            return assessment_ids == () and self._zero_scope_proof_matches_current_state_in_transaction(
                zero_scope_proof, requires_transition_challenge=zero_scope_requires_challenge
            )
        if zero_scope_proof is not None:
            return False
        return self._recovery_assessments_match_current_scopes_in_transaction(assessment_ids)

    def _zero_scope_proof_matches_current_state_in_transaction(
        self, proof: ZeroScopeClearanceProof | None, *, requires_transition_challenge: bool
    ) -> bool:
        """Reject forged, stale, malformed, or non-empty ID-free proof facts."""
        if type(proof) is not ZeroScopeClearanceProof:
            return False
        if (proof.transition_challenge is not None) != requires_transition_challenge:
            return False
        try:
            canonical_proof = proof.to_canonical_json()
            if ZeroScopeClearanceProof.from_canonical_json(canonical_proof) != proof:
                return False
        except (TypeError, ValueError):
            return False
        now = self.utc_now()
        return all(
            _is_recovery_timestamp_fresh(observed_at, now)
            for observed_at in (
                proof.account.observed_at,
                proof.open_orders.observed_at,
                proof.connection.observed_at,
                proof.server_time.server_time,
                proof.server_time.observed_at,
                proof.collected_at,
            )
        )

    def _create_zero_scope_recovery_transition_in_transaction(
        self, begin_event_id: str, proof: ZeroScopeClearanceProof, began_at: datetime
    ) -> None:
        """Create the pending recovery-only binding beside its RECOVERING event."""
        if proof.transition_challenge is not None:
            raise LedgerStorageError("zero-scope begin proof cannot carry a transition challenge")
        canonical_proof = proof.to_canonical_json()
        self._require_connection().execute(
            """
            INSERT INTO zero_scope_recovery_transitions(
                transition_id, begin_event_id, begin_proof_digest, transition_challenge,
                began_at_utc, challenge_expires_at_utc, status, consumed_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)
            """,
            (
                _new_id("zero-scope-transition"),
                begin_event_id,
                _digest_text(canonical_proof),
                token_urlsafe(32),
                _timestamp_text(began_at),
                _timestamp_text(began_at + timedelta(seconds=60)),
            ),
        )

    def _consume_zero_scope_recovery_transition_in_transaction(
        self, proof: ZeroScopeClearanceProof, now: datetime
    ) -> bool:
        """Verify and conditionally consume one current proof before writing READY."""
        if proof.transition_challenge is None:
            return False
        rows = self._require_connection().execute(
            """
            SELECT transition_id, begin_proof_digest, transition_challenge, began_at_utc,
                   challenge_expires_at_utc
            FROM zero_scope_recovery_transitions
            WHERE status = 'pending'
            """
        ).fetchall()
        if len(rows) != 1:
            return False
        transition_id, begin_digest, expected_challenge, began_at, expires_at = rows[0]
        try:
            began = _timestamp_from_text(str(began_at))
            expires = _timestamp_from_text(str(expires_at))
        except LedgerStorageError:
            return False
        canonical_proof = proof.to_canonical_json()
        if (
            proof.transition_challenge != expected_challenge
            or _digest_text(canonical_proof) == begin_digest
            or proof.collected_at <= began
            or now >= expires
        ):
            return False
        consumed = self._require_connection().execute(
            """
            UPDATE zero_scope_recovery_transitions
            SET status = 'consumed', consumed_at_utc = ?
            WHERE transition_id = ? AND status = 'pending' AND transition_challenge = ?
              AND challenge_expires_at_utc > ?
            """,
            (_timestamp_text(now), transition_id, proof.transition_challenge, _timestamp_text(now)),
        )
        return consumed.rowcount == 1

    def _replace_recovery_scopes_in_transaction(self, created_at: str) -> None:
        """Snapshot the fixed target/policy set at each latch, never from a recovery caller."""
        connection = self._require_connection()
        connection.execute("UPDATE recovery_scopes SET active = 0 WHERE active = 1")
        command_rows = connection.execute(
            "SELECT DISTINCT mode, account_id, product FROM order_commands ORDER BY mode, account_id, product"
        ).fetchall()
        for mode, account_id, product in command_rows:
            try:
                target = ExecutionTarget(
                    target_id="paper-spot-primary",
                    mode=Mode(str(mode)),
                    account_id=str(account_id),
                    product=ProductType(str(product)),
                )
                policy = select_phase2_policy(target)
            except (TypeError, ValueError) as exc:
                raise LedgerStorageError("durable recovery scope is not a fixed Phase 2 target") from exc
            target_json = _canonical_json(canonicalize(target))
            target_digest = _digest_text(target_json)
            scope_digest = _digest_text(
                _canonical_json(
                    {
                        "target_digest": target_digest,
                        "policy_version": policy.policy_version,
                        "policy_digest": policy.policy_digest,
                    }
                )
            )
            connection.execute(
                """
                INSERT INTO recovery_scopes(
                    persistent_scope_id, target_json, target_digest, policy_version, policy_digest,
                    scope_digest, active, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    _new_id("recovery-scope"),
                    target_json,
                    target_digest,
                    policy.policy_version,
                    policy.policy_digest,
                    scope_digest,
                    created_at,
                ),
            )

    def _load_current_recovery_scope_in_transaction(
        self, persistent_scope_id: str
    ) -> RecoveryScope | None:
        """Load exactly one active scope using the opaque ledger-issued identity."""
        row = self._require_connection().execute(
            """
            SELECT persistent_scope_id, target_json, target_digest, policy_version, policy_digest, scope_digest
            FROM recovery_scopes WHERE persistent_scope_id = ? AND active = 1
            """,
            (persistent_scope_id,),
        ).fetchone()
        return None if row is None else _recovery_scope_from_row(row)

    @staticmethod
    def _recovery_evidence_is_complete(evidence_json: str, evidence_digest: str) -> bool:
        """Require canonical storage of every recovery observation before clearance is durable."""
        try:
            evidence = json.loads(evidence_json)
        except (TypeError, json.JSONDecodeError):
            return False
        required_observations = {
            "capabilities",
            "rules",
            "account",
            "quote",
            "server_time",
            "connection",
            "open_orders",
            "order_rate",
            "loss_drawdown",
            "fee_rate",
        }
        if (
            not isinstance(evidence, dict)
            or set(evidence) != required_observations
            or _canonical_json(evidence) != evidence_json
            or _digest_text(evidence_json) != evidence_digest
        ):
            return False
        return all(isinstance(evidence[name], dict) and evidence[name] for name in required_observations)

    def _recovery_assessments_match_current_scopes_in_transaction(
        self, assessment_ids: tuple[str, ...]
    ) -> bool:
        """Verify exact active-scope coverage and all clearance predicates in this transaction."""
        if not assessment_ids or len(set(assessment_ids)) != len(assessment_ids):
            return False
        connection = self._require_connection()
        scopes = connection.execute(
            """
            SELECT persistent_scope_id, target_json, target_digest, policy_version, policy_digest, scope_digest
            FROM recovery_scopes WHERE active = 1 ORDER BY persistent_scope_id
            """
        ).fetchall()
        if len(scopes) != len(assessment_ids):
            return False
        placeholders = ", ".join("?" for _ in assessment_ids)
        rows = connection.execute(
            f"""
            SELECT assessment.recovery_assessment_id, assessment.persistent_scope_id,
                   assessment.scope_digest, assessment.target_digest, assessment.policy_version,
                   assessment.policy_digest, assessment.evidence_digest, assessment.evidence_json,
                   assessment.accepted, assessment.observed_at_utc,
                   scope.target_digest, scope.policy_version, scope.policy_digest, scope.scope_digest
            FROM recovery_assessments AS assessment
            JOIN recovery_scopes AS scope ON scope.persistent_scope_id = assessment.persistent_scope_id
            WHERE scope.active = 1 AND assessment.recovery_assessment_id IN ({placeholders})
            """,
            assessment_ids,
        ).fetchall()
        if len(rows) != len(assessment_ids) or {row[0] for row in rows} != set(assessment_ids):
            return False
        expected_scope_ids = {row[0] for row in scopes}
        now = self.utc_now()
        for row in rows:
            (
                _,
                persistent_scope_id,
                scope_digest,
                target_digest,
                policy_version,
                policy_digest,
                evidence_digest,
                evidence_json,
                accepted,
                observed_at,
                durable_target_digest,
                durable_policy_version,
                durable_policy_digest,
                durable_scope_digest,
            ) = row
            if persistent_scope_id not in expected_scope_ids or accepted != 1:
                return False
            if (
                scope_digest != durable_scope_digest
                or target_digest != durable_target_digest
                or policy_version != durable_policy_version
                or policy_digest != durable_policy_digest
                or not self._recovery_evidence_is_complete(str(evidence_json), str(evidence_digest))
            ):
                return False
            try:
                observed = _timestamp_from_text(str(observed_at))
            except LedgerStorageError:
                return False
            age_seconds = (now.astimezone(UTC) - observed).total_seconds()
            if age_seconds < 0 or age_seconds > 60:
                return False
        return {row[1] for row in rows} == expected_scope_ids

    def _set_kill_switch_status_in_transaction(
        self,
        status: KillSwitchStatus,
        actor_label: str,
        occurred_at: str,
        recovery_assessment_ids: tuple[str, ...] | None = None,
        zero_scope_proof: ZeroScopeClearanceProof | None = None,
    ) -> str:
        """Transition the singleton and append a bounded operator audit event."""
        changed = self._require_connection().execute(
            "UPDATE kill_switch_state SET status = ?, actor_label = ?, changed_at_utc = ? WHERE singleton_id = 1",
            (status.value, actor_label, occurred_at),
        )
        if changed.rowcount != 1:
            raise LedgerStorageError("kill switch state is missing")
        return self._record_kill_switch_event(
            status, None, actor_label, occurred_at, recovery_assessment_ids, zero_scope_proof
        )

    def _record_kill_switch_event(
        self,
        status: KillSwitchStatus,
        reason: str | None,
        actor_label: str,
        occurred_at: str,
        recovery_assessment_ids: tuple[str, ...] | None = None,
        zero_scope_proof: ZeroScopeClearanceProof | None = None,
    ) -> str:
        """Append one bounded safety-state event while an immediate transaction is active."""
        event_id = _new_id("kill-switch-event")
        self._require_connection().execute(
            """INSERT INTO kill_switch_events(
                event_id, status, reason, actor_label, occurred_at_utc, recovery_assessment_ids_json,
                zero_scope_clearance_proof_json, zero_scope_clearance_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                status.value,
                reason,
                actor_label,
                occurred_at,
                _canonical_json(recovery_assessment_ids) if recovery_assessment_ids is not None else None,
                zero_scope_proof.to_canonical_json() if zero_scope_proof is not None else None,
                zero_scope_proof.clearance_summary if zero_scope_proof is not None else None,
            ),
        )
        return event_id

    def _append_event(
        self,
        *,
        command_id: str,
        previous_state: OrderState,
        new_state: OrderState,
        event: LifecycleEvent,
        occurred_at: str,
        detail: Mapping[str, Any],
        evidence: GatewayEvidence | None = None,
    ) -> None:
        """Append one sequence-checked lifecycle event inside the active transaction."""
        expected = assert_transition(previous_state, event, evidence=evidence)
        if expected is not new_state:
            raise LedgerStorageError("event projection does not match lifecycle transition")
        sequence = self._require_connection().execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM order_events WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0]
        self._require_connection().execute(
            """
            INSERT INTO order_events(
                event_id, command_id, sequence, previous_state, new_state, event_type, observed_at_utc, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("event"),
                command_id,
                sequence,
                previous_state.value,
                new_state.value,
                event.value,
                occurred_at,
                _canonical_json(dict(detail)),
            ),
        )

    def _record_incident(self, *, command_id: str, kind: str, detail: Mapping[str, Any]) -> None:
        """Append a sanitized reconciliation incident without rewriting evidence history."""
        self._require_connection().execute(
            """
            INSERT INTO reconciliation_incidents(
                incident_id, command_id, kind, detail_json, observed_at_utc
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                _new_id("incident"),
                command_id,
                kind,
                _canonical_json(canonicalize(dict(detail))),
                _timestamp_text(self.utc_now()),
            ),
        )

    def _inject_failure(self, stage: str) -> None:
        """Invoke deterministic integration fault injection inside the active transaction."""
        if self._failure_injector is not None:
            self._failure_injector(stage)

    def _require_connection(self) -> sqlite3.Connection:
        """Return the open connection or reject post-close ledger use."""
        if self._connection is None:
            raise LedgerStorageError("execution ledger is closed")
        return self._connection



def _lifecycle_event_for_evidence(evidence: GatewayEvidence) -> LifecycleEvent:
    """Map a normalized external state to the sole corresponding lifecycle event."""
    events = {
        OrderState.ACKNOWLEDGED: LifecycleEvent.ACKNOWLEDGEMENT_OBSERVED,
        OrderState.OPEN: LifecycleEvent.OPEN_OBSERVED,
        OrderState.PARTIALLY_FILLED: LifecycleEvent.PARTIAL_FILL_OBSERVED,
        OrderState.FILLED: LifecycleEvent.FILL_OBSERVED,
        OrderState.REJECTED: LifecycleEvent.REJECTION_OBSERVED,
        OrderState.CANCELLED: LifecycleEvent.CANCELLATION_OBSERVED,
    }
    try:
        return events[evidence.state]
    except KeyError as exc:
        raise ReconciliationEvidenceError(
            f"evidence state {evidence.state.value} is not a remote lifecycle observation"
        ) from exc
def _command_from_canonical_json(command_json: str) -> ExecutionCommand:
    """Rebuild the sole ledger-persisted command without accepting caller input."""
    try:
        data = json.loads(command_json)
        context_data = data["context"]
        if type(context_data) is not dict:
            raise ValueError("command context must be an object")
        if "schema_version" not in context_data:
            if ProductType(context_data["product"]) is not ProductType.SPOT:
                raise ValueError("only legacy Spot contexts are supported")
            context = SpotOrderContext()
        else:
            context = product_context_from_canonical_payload(_canonical_json(context_data))
        return ExecutionCommand(
            command_id=data["command_id"],
            logical_command_key=data["logical_command_key"],
            client_order_id=data["client_order_id"],
            mode=Mode(data["mode"]),
            account_id=data["account_id"],
            symbol=data["symbol"],
            side=Side(data["side"]),
            order_type=OrderType(data["order_type"]),
            quantity=data["quantity"],
            context=context,
            price=data.get("price"),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LedgerStorageError("stored command JSON is invalid") from exc


def _recovery_scope_from_row(row: tuple[object, ...]) -> RecoveryScope:
    """Rebuild a scope only from its immutable persisted snapshot."""
    try:
        target_data = json.loads(str(row[1]))
        target = ExecutionTarget(
            target_id=str(target_data["target_id"]),
            mode=Mode(str(target_data["mode"])),
            account_id=str(target_data["account_id"]),
            product=ProductType(str(target_data["product"])),
        )
        return RecoveryScope(
            persistent_scope_id=str(row[0]),
            target=target,
            target_digest=str(row[2]),
            policy_version=str(row[3]),
            policy_digest=str(row[4]),
            scope_digest=str(row[5]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LedgerStorageError("stored recovery scope is invalid") from exc


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    """Serialize canonical values deterministically for durable comparison and auditing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _new_id(prefix: str) -> str:
    """Generate an opaque durable local identity without venue semantics."""
    return f"{prefix}-{uuid4().hex}"


def _timestamp_text(value: datetime) -> str:
    """Require explicit timezone-aware timestamps before durable persistence."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ledger timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _candidate_canonical_data(candidate: CandidateExecutionIntent) -> dict[str, Any]:
    """Store the candidate with the same strict context payload used by command binding."""
    data = canonicalize(candidate)
    data["context"] = json.loads(product_context_to_canonical_payload(candidate.context))
    return data


def _timestamp_from_text(value: str) -> datetime:
    """Restore a persisted UTC timestamp for an audit-query value object."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LedgerStorageError("stored audit timestamp is not timezone-aware")
    return parsed.astimezone(UTC)


def _is_recovery_timestamp_fresh(observed_at: datetime, now: datetime) -> bool:
    """Return whether a recovery fact remains inside its fixed 60-second window."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return False
    age_seconds = (now.astimezone(UTC) - observed_at.astimezone(UTC)).total_seconds()
    return 0 <= age_seconds <= 60


def _validate_durable_command_policy(
    command: ExecutionCommand, policy_id: object, policy_version: object, policy_digest: object
) -> None:
    """Validate durable command policy/context facts before issuing a lease."""
    if policy_id is None and policy_version is None and policy_digest is None:
        if type(command.context) is not SpotOrderContext:
            raise LedgerStorageError("legacy policy decoding is restricted to Spot commands")
        return
    if not all(isinstance(value, str) and value for value in (policy_id, policy_version, policy_digest)):
        raise LedgerStorageError("durable command policy identity is incomplete")
    target = ExecutionTarget(
        "paper-spot-primary" if policy_version == "phase2-v1" else policy_id,
        command.mode,
        command.account_id,
        command.context.product,
    )
    try:
        policy = (
            select_phase2_policy(target)
            if policy_version == "phase2-v1"
            else select_paper_product_policy(target, command.context)
        )
    except Exception as exc:
        raise LedgerStorageError("durable command policy/context is unsupported") from exc
    if (
        policy.policy_id != policy_id
        or policy.policy_version != policy_version
        or policy.policy_digest != policy_digest
    ):
        raise LedgerStorageError("durable command policy/context identity mismatch")


def _policy_for_assessment(
    candidate: CandidateExecutionIntent, assessment: RiskAssessment
) -> RiskPolicy:
    """Resolve the sole durable policy allowed by an accepted assessment."""
    policy = (
        select_phase2_policy(candidate.target)
        if assessment.policy_version == "phase2-v1"
        else select_paper_product_policy(candidate.target, candidate.context)
    )
    if policy.policy_version != assessment.policy_version or policy.policy_digest != assessment.policy_digest:
        raise ValueError("stored assessment policy does not match durable candidate context")
    return policy


def _validate_ticket_binding_policy(binding: TicketBinding) -> None:
    """Reject policy/context substitutions while reconstructing a durable ticket."""
    context = product_context_from_canonical_payload(binding.product_context_payload)
    if product_context_digest(context) != binding.product_context_digest:
        raise ValueError("ticket context digest does not match durable payload")
    target = ExecutionTarget(
        binding.venue,
        Mode(binding.environment),
        binding.account_id,
        ProductType(binding.product),
    )
    policy = (
        select_phase2_policy(target)
        if binding.policy_version == "phase2-v1"
        else select_paper_product_policy(target, context)
    )
    if (
        policy.policy_id != binding.policy_id
        or policy.policy_version != binding.policy_version
        or policy.policy_digest != binding.policy_digest
    ):
        raise ValueError("ticket policy does not match durable context")


def _ticket_binding_from_persisted_json(
    *, candidate: CandidateExecutionIntent, evidence_json: str, assessment: RiskAssessment
) -> TicketBinding:
    """Build ticket review facts from canonical persisted evidence and assessment data."""
    try:
        evidence = json.loads(evidence_json)
        quote = evidence["quote"]
        fee = assessment.fee_estimate
        if fee is None:
            raise ValueError("accepted assessment has no fee estimate")
        policy = _policy_for_assessment(candidate, assessment)
        return TicketBinding.from_persisted_facts(
            candidate=candidate,
            policy=policy,
            evidence_digest=assessment.evidence_digest,
            quote_observed_at=_timestamp_from_text(quote["observed_at"]),
            authorization_evidence_digest=authorization_evidence_digest(evidence),
            observation_timestamps=_evidence_observation_times(evidence),
            fee_estimate=fee,
            risk_reason_codes=assessment.reason_codes,
            risk_metrics=assessment.metrics,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LedgerStorageError("stored proposal facts cannot build an approval ticket") from exc


def _ticket_from_row(row: tuple[object, ...]) -> ApprovalTicket:
    """Restore a ticket projection exclusively from its durable canonical row."""
    try:
        binding_data = json.loads(str(row[1]))
        risk_data = binding_data["risk_result"]
        binding = TicketBinding(
            candidate_digest=binding_data["candidate_digest"],
            source_digest=binding_data["source_digest"],
            command_digest=binding_data["command_digest"],
            target_digest=binding_data["target_digest"],
            policy_id=binding_data.get("policy_id", "phase2-paper-spot-legacy"),
            policy_version=binding_data["policy_version"],
            policy_digest=binding_data["policy_digest"],
            evidence_digest=binding_data["evidence_digest"],
            quote_digest=binding_data["quote_digest"],
            fee_rate_digest=binding_data["fee_rate_digest"],
            authorization_evidence_digest=binding_data["authorization_evidence_digest"],
            data_age_digest=binding_data["data_age_digest"],
            observation_timestamps=tuple(
                _timestamp_from_text(value) for value in binding_data["observation_timestamps"]
            ),
            product_context_payload=binding_data.get(
                "product_context_payload", product_context_to_canonical_payload(SpotOrderContext())
            ),
            product_context_digest=binding_data.get(
                "product_context_digest", product_context_digest(SpotOrderContext())
            ),
            venue=binding_data["venue"],
            environment=binding_data["environment"],
            account_id=binding_data["account_id"],
            product=binding_data["product"],
            symbol=binding_data["symbol"],
            side=binding_data["side"],
            amount=Decimal(binding_data["amount"]),
            expected_price=Decimal(binding_data["expected_price"]),
            slippage=Decimal(binding_data["slippage"]),
            estimated_fee=Decimal(binding_data["estimated_fee"]),
            fee_currency=binding_data["fee_currency"],
            fee_rate_version=binding_data["fee_rate_version"],
            quote_identifier=binding_data["quote_identifier"],
            data_observed_at=_timestamp_from_text(binding_data["data_observed_at"]),
            source_provenance=dict(binding_data["source_provenance"]),
            risk_result=TicketRiskResult(
                accepted=bool(risk_data["accepted"]),
                reason_codes=tuple(risk_data["reason_codes"]),
                metrics=tuple((name, Decimal(value)) for name, value in risk_data["metrics"]),
            ),
        )
        _validate_ticket_binding_policy(binding)
        return ApprovalTicket(
            ticket_id=str(row[0]),
            binding=binding,
            status=ApprovalTicketStatus(str(row[2])),
            created_at=_timestamp_from_text(str(row[3])),
            expires_at=_timestamp_from_text(str(row[4])),
            terminal_event=TicketTerminalEvent(str(row[5])) if row[5] is not None else None,
            terminal_reason=str(row[6]) if row[6] is not None else None,
            terminal_at=_timestamp_from_text(str(row[7])) if row[7] is not None else None,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LedgerStorageError("stored approval ticket is invalid") from exc
