"""Contract tests for the canonical execution gateway and admission ports."""
from __future__ import annotations

from abc import ABC
from dataclasses import fields
from inspect import getmembers, isabstract, signature
from typing import Any, get_type_hints

import pytest

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.errors import TradingDomainError
from pa_agent.trading.domain.models import (
    AccountObservation,
    ExecutionCommand,
    Fill,
    GatewayCapabilities,
    GatewayEvidence,
    OrderProjection,
    OrderState,
    ProductType,
    QuoteObservation,
    RuleObservation,
    TimeObservation,
)
from pa_agent.trading.domain.risk import (
    FeeRateObservation,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
)
from pa_agent.trading.ports import ExecutionLedger, OutboundSubmission
from pa_agent.trading.ports.gateway import (
    GatewayAmbiguityError,
    GatewayUnavailableError,
    TradingGateway,
    TradingGatewayError,
)
from pa_agent.trading.ports.ledger import OutboundDispatchPermit, SubmissionAdmission
from tests.fixtures.execution_factories import make_account_observation, make_spot_command


def test_trading_gateway_exposes_the_complete_canonical_operation_surface() -> None:
    """The abstract port carries all evidence, command, and recovery operations."""
    expected_operations = {
        "get_capabilities",
        "get_server_time",
        "get_quote",
        "get_instrument_rules",
        "get_account_snapshot",
        "get_connection",
        "get_open_order_count",
        "get_order_rate_window",
        "get_loss_drawdown",
        "get_fee_rate",
        "submit_order",
        "cancel_order",
        "lookup_order_by_client_id",
        "list_open_orders",
        "list_fills",
        "reconcile",
    }

    public_methods = {
        name
        for name, value in getmembers(TradingGateway)
        if callable(value) and not name.startswith("_")
    }

    assert issubclass(TradingGateway, ABC)
    assert isabstract(TradingGateway)
    assert expected_operations <= public_methods
    assert set(TradingGateway.__abstractmethods__) == expected_operations


def test_trading_gateway_annotations_are_canonical_and_venue_neutral() -> None:
    """Gateway requests/results exclude UI, LLM, chart, and transport payload types."""
    expected_hints: dict[str, dict[str, Any]] = {
        "get_capabilities": {"return": GatewayCapabilities},
        "get_server_time": {"return": TimeObservation},
        "get_quote": {"symbol": str, "return": QuoteObservation},
        "get_instrument_rules": {"symbol": str, "return": RuleObservation},
        "get_account_snapshot": {
            "account_id": str,
            "product": ProductType,
            "return": AccountObservation,
        },
        "get_connection": {"target": ExecutionTarget, "return": TargetConnectionObservation},
        "get_open_order_count": {"target": ExecutionTarget, "return": OpenOrderObservation},
        "get_order_rate_window": {
            "target": ExecutionTarget,
            "window_seconds": int,
            "return": OrderRateObservation,
        },
        "get_loss_drawdown": {"target": ExecutionTarget, "return": LossDrawdownObservation},
        "get_fee_rate": {
            "target": ExecutionTarget,
            "symbol": str,
            "quote_identifier": str,
            "return": FeeRateObservation,
        },
        "submit_order": {"outbound": OutboundSubmission, "return": GatewayEvidence},
        "cancel_order": {"client_order_id": str, "return": GatewayEvidence},
        "lookup_order_by_client_id": {"client_order_id": str},
        "list_open_orders": {"account_id": str, "product": ProductType},
        "list_fills": {"command_id": str},
        "reconcile": {"command": ExecutionCommand},
    }

    for method_name, expected in expected_hints.items():
        hints = get_type_hints(getattr(TradingGateway, method_name))
        for parameter, expected_type in expected.items():
            assert hints[parameter] == expected_type

    assert get_type_hints(TradingGateway.lookup_order_by_client_id)["return"] == GatewayEvidence | None
    assert get_type_hints(TradingGateway.list_open_orders)["return"] == tuple[OrderProjection, ...]
    assert get_type_hints(TradingGateway.list_fills)["return"] == tuple[Fill, ...]
    assert get_type_hints(TradingGateway.reconcile)["return"] == tuple[GatewayEvidence, ...]

    for method_name in TradingGateway.__abstractmethods__:
        annotations = get_type_hints(getattr(TradingGateway, method_name))
        rendered = " ".join(str(value) for value in annotations.values()).lower()
        assert "pyqt" not in rendered
        assert "llm" not in rendered
        assert "chart" not in rendered
        assert "payload" not in rendered

    assert signature(TradingGateway.submit_order).return_annotation != signature(TradingGateway.submit_order).empty


def test_gateway_failures_are_typed_trading_domain_errors() -> None:
    """Future adapters cannot surface untyped transport failure classes at this port."""
    assert issubclass(TradingGatewayError, TradingDomainError)
    assert issubclass(GatewayAmbiguityError, TradingGatewayError)
    assert issubclass(GatewayUnavailableError, TradingGatewayError)



def test_submission_admission_discards_caller_identity_candidates() -> None:
    """The ledger owns the only durable remote identity allocation boundary."""
    hints = get_type_hints(ExecutionLedger.create_or_load_and_claim_submission)
    contract = ExecutionLedger.create_or_load_and_claim_submission.__doc__ or ""

    assert hints == {"command": ExecutionCommand, "return": SubmissionAdmission}
    assert "caller candidate" in contract
    assert "allocates one opaque" in contract
    assert "durable client-order ID" in contract
    assert "repeat and recovery" in contract

    admission = SubmissionAdmission(
        command_id="command-first",
        client_order_id="durable-client-first",
        reconciliation_job_id="job-first",
        lifecycle_state=OrderState.SUBMITTING,
        is_admissible=True,
        claim_token="opaque-first-claim",
    )

    assert admission.is_admissible
    assert admission.client_order_id == "durable-client-first"


def test_begin_outbound_submission_returns_irreversible_durable_authorization() -> None:
    """An admissible claim is consumed into the only gateway submission authority."""
    assert get_type_hints(ExecutionLedger.begin_outbound_submission) == {
        "admission": SubmissionAdmission,
        "return": OutboundSubmission,
    }
    contract = ExecutionLedger.begin_outbound_submission.__doc__ or ""
    assert "atomic durable state change" in contract
    assert "cannot revoke" in contract
    assert "second begin" in contract

    command = make_spot_command(client_order_id="durable-client-first")
    outbound = OutboundSubmission(
        command=command,
        command_id=command.command_id,
        client_order_id="durable-client-first",
        reconciliation_job_id="job-first",
        outbound_attempt_token="opaque-outbound-attempt",
    )

    assert outbound.command is command
    assert outbound.client_order_id == "durable-client-first"
    assert outbound.outbound_attempt_token == "opaque-outbound-attempt"
    with pytest.raises(ValueError):
        OutboundSubmission(
            command=command,
            command_id="replacement-command",
            client_order_id="durable-client-first",
            reconciliation_job_id="job-first",
            outbound_attempt_token="opaque-outbound-attempt",
        )


def test_gateway_submission_requires_the_protected_outbound_authorization() -> None:
    """An adapter accepts no free-floating command or separately checked claim."""
    assert get_type_hints(TradingGateway.submit_order) == {
        "outbound": OutboundSubmission,
        "return": GatewayEvidence,
    }
    gateway_contract = TradingGateway.submit_order.__doc__ or ""

    assert "irreversible" in gateway_contract
    assert "ledger-created" in gateway_contract


def test_ticket_consumption_contract_prepares_a_permit_not_forgery_blocking() -> None:
    """Contract preparation keeps consumption proof separate from gateway authority."""
    hints = get_type_hints(ExecutionLedger.consume_valid_ticket_and_begin_outbound)
    contract = ExecutionLedger.consume_valid_ticket_and_begin_outbound.__doc__ or ""

    assert hints["return"] == OutboundDispatchPermit | None
    assert "contract preparation" in contract.lower()
    assert "future ledger implementation" in contract.lower()

    permit_fields = {field.name: field.type for field in fields(OutboundDispatchPermit)}
    assert permit_fields == {
        "command_id": str,
        "client_order_id": str,
        "reconciliation_job_id": str,
        "outbound_attempt_proof": str,
    }
    forbidden_type_names = (
        "executioncommand",
        "approvalticket",
        "tradinggateway",
        "ui",
        "alert",
        "notification",
        "credential",
    )
    assert all(
        all(term not in str(field_type).lower() for term in forbidden_type_names)
        for field_type in permit_fields.values()
    )


def test_ledger_lease_contract_is_the_only_future_gateway_value_source() -> None:
    """Contract preparation reserves durable proof consumption for the next plan."""
    assert get_type_hints(ExecutionLedger.lease_outbound_submission) == {
        "permit": OutboundDispatchPermit,
        "return": OutboundSubmission,
    }
    contract = ExecutionLedger.lease_outbound_submission.__doc__ or ""

    assert "one-time" in contract
    assert "durable" in contract
    assert "rowcount" in contract
    assert "future ledger implementation" in contract.lower()

    submit_parameters = signature(TradingGateway.submit_order).parameters
    assert tuple(submit_parameters) == ("self", "outbound")


def test_ledger_observation_contract_is_explicitly_typed() -> None:
    """The durable port accepts typed observations rather than arbitrary payload maps."""
    assert get_type_hints(ExecutionLedger.record_account_observation) == {
        "observation": AccountObservation,
        "return": str,
    }
    assert "record_account_observation" in ExecutionLedger.__dict__

    observation = make_account_observation()
    assert observation.product is ProductType.SPOT
