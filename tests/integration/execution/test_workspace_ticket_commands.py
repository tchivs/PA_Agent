"""Regression contracts for the workspace's ticket and kill-switch commands.

The future Qt facade may request these application commands, but it must never
accept a gateway-facing value or make submission authority available to alerts,
notifications, or widget-local state.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest

from pa_agent.trading.application.workspace_commands import TradingWorkspaceCommands
from pa_agent.trading.domain.approval import ApprovalTicketStatus, KillSwitchStatus
from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
from pa_agent.trading.application.kill_switch import KillSwitchService
from pa_agent.trading.application.submission import SubmissionCoordinator
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.integration.execution.test_approval_consumption import (
    NOW,
    _Clock,
    _EvidenceAndSubmissionGateway,
    _issue_ticket,
)
from tests.integration.execution.test_kill_switch import _CancellationGateway, _create_open_order

pytestmark = pytest.mark.integration


def _commands(database_path: Path, clock: _Clock, gateway: _EvidenceAndSubmissionGateway) -> TradingWorkspaceCommands:
    ledger = SQLiteExecutionLedger(database_path, clock=clock)
    approval = ApprovalService(
        ledger=ledger,
        utc_now=clock.utc_now,
        evidence_collector=FreshEvidenceCollector(gateway=gateway, utc_now=clock.utc_now),
        risk_engine=RiskEngine(),
    )
    return TradingWorkspaceCommands(
        approval_service=approval,
        submission_coordinator=SubmissionCoordinator(ledger=ledger, gateway=gateway),
    )


def test_workspace_replayed_and_concurrent_approval_consumes_one_ticket_and_submits_once(
    execution_database_path: Path,
) -> None:
    """Double-click/replay callers have one durable ticket → permit → lease → submit path."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    capabilities_before_approval = gateway.call_order.count("capabilities")
    barrier = Barrier(2)

    def approve_once() -> object:
        commands = _commands(execution_database_path, clock, gateway)
        try:
            barrier.wait(timeout=2)
            return commands.approve_ticket(
                ticket_id=ticket.ticket_id,
                candidate=candidate,
                target=candidate.target,
                policy=policy,
            )
        finally:
            commands.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: approve_once(), range(2)))

    assert sum(result.submitted for result in results) == 1
    assert sum(result.reason == "ticket_not_pending" for result in results) == 1
    assert len(gateway.outbound_submissions) == 1
    assert gateway.call_order.count("capabilities") == capabilities_before_approval + 1
    assert gateway.outbound_submissions[0].command.logical_command_key == f"approval-ticket:{ticket.ticket_id}"

    replay = _commands(execution_database_path, clock, gateway)
    try:
        result = replay.approve_ticket(
            ticket_id=ticket.ticket_id,
            candidate=candidate,
            target=candidate.target,
            policy=policy,
        )
    finally:
        replay.close()
    assert result.submitted is False
    assert result.reason == "ticket_not_pending"
    assert len(gateway.outbound_submissions) == 1


def test_workspace_expired_revoked_and_rejected_tickets_remain_durable_read_only(
    execution_database_path: Path,
) -> None:
    """Terminal ticket states cannot make a second authority or a gateway call."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)

    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        rejected = ApprovalService(ledger=ledger, utc_now=clock.utc_now).reject_ticket(
            ticket.ticket_id, "operator_declined"
        )
        assert rejected.status is ApprovalTicketStatus.REJECTED
    finally:
        ledger.close()

    commands = _commands(execution_database_path, clock, gateway)
    try:
        terminal = commands.approve_ticket(
            ticket_id=ticket.ticket_id,
            candidate=candidate,
            target=candidate.target,
            policy=policy,
        )
        displayed = commands.ticket_state(ticket.ticket_id)
    finally:
        commands.close()

    assert terminal.submitted is False
    assert terminal.reason == "ticket_not_pending"
    assert displayed.status is ApprovalTicketStatus.REJECTED
    assert displayed.is_read_only is True
    assert len(gateway.outbound_submissions) == 0



def test_workspace_expired_ticket_remains_durable_read_only(
    execution_database_path: Path,
) -> None:
    """An expired ticket cannot mint another durable submission path."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    clock.now = NOW + timedelta(seconds=61)
    commands = _commands(execution_database_path, clock, gateway)
    try:
        result = commands.approve_ticket(
            ticket_id=ticket.ticket_id,
            candidate=candidate,
            target=candidate.target,
            policy=policy,
        )
    finally:
        commands.close()
    assert result.submitted is False
    assert result.reason == "ticket_expired"
    assert len(gateway.outbound_submissions) == 0


def test_workspace_revoked_ticket_remains_durable_read_only(
    execution_database_path: Path,
) -> None:
    """A persisted latch revokes pending review and prevents a later approval replay."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        ledger.latch_kill_switch(
            reason="operator-stop",
            actor_label="operator",
            policy_summary="paper-spot-primary",
            evidence_summary="workspace confirmation",
            cancellation_supported=False,
        )
    finally:
        ledger.close()
    commands = _commands(execution_database_path, clock, gateway)
    try:
        result = commands.approve_ticket(
            ticket_id=ticket.ticket_id,
            candidate=candidate,
            target=candidate.target,
            policy=policy,
        )
    finally:
        commands.close()
    assert result.submitted is False
    assert result.reason == "ticket_not_pending"
    assert result.state is not None
    assert result.state.status is ApprovalTicketStatus.REVOKED
    assert len(gateway.outbound_submissions) == 0


def test_workspace_kill_switch_reads_durable_latch_and_never_upgrades_cancellation_to_ready(
    execution_database_path: Path,
) -> None:
    """Local READY state is invalid while the persisted latch/recovery evidence blocks it."""
    clock = _Clock(NOW)
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        client_order_id = _create_open_order(ledger)
        gateway = _CancellationGateway({client_order_id: None})
        commands = TradingWorkspaceCommands(
            kill_switch_service=KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)
        )
        latched = commands.trigger_kill_switch(
            actor_label="operator",
            reason="operator-stop",
            policy_summary="paper-spot-primary",
            evidence_summary="workspace confirmation",
        )
        assert latched.state.status is KillSwitchStatus.LATCHED
        assert latched.approval_available is False
        assert commands.process_cancellation_work().requests[0].remote_resolution is None
        assert commands.begin_kill_switch_recovery(actor_label="operator").accepted is False
    finally:
        ledger.close()

    reopened = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        projection = TradingWorkspaceCommands(ledger=reopened).kill_switch_state()
        assert projection.state.status is KillSwitchStatus.LATCHED
        assert projection.approval_available is False
        assert projection.recovery_allowed is False
        assert projection.cancellation_requests[0].is_terminal is False
    finally:
        reopened.close()
