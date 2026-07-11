"""Contract tests for the canonical execution gateway and admission ports."""
from __future__ import annotations

from abc import ABC
from inspect import getmembers, isabstract, signature
from typing import Any, get_type_hints

import pytest

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
from pa_agent.trading.ports.gateway import (
    GatewayAmbiguityError,
    GatewayUnavailableError,
    TradingGateway,
    TradingGatewayError,
)
from pa_agent.trading.ports.ledger import ExecutionLedger, SubmissionAdmission


def test_trading_gateway_exposes_the_complete_canonical_operation_surface() -> None:
    """The abstract port carries all evidence, command, and recovery operations."""
    expected_operations = {
        "get_capabilities",
        "get_server_time",
        "get_quote",
        "get_instrument_rules",
        "get_account_snapshot",
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
        "submit_order": {"command": ExecutionCommand, "return": GatewayEvidence},
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



def test_submission_admission_is_an_atomic_explicit_claim_result() -> None:
    """One ledger call exposes the decision and every identity a coordinator needs."""
    hints = get_type_hints(ExecutionLedger.create_or_load_and_claim_submission)

    assert hints == {"command": ExecutionCommand, "return": SubmissionAdmission}
    assert "create_or_load_and_claim_submission" in ExecutionLedger.__dict__

    admission = SubmissionAdmission(
        command_id="command-first",
        client_order_id="client-first",
        reconciliation_job_id="job-first",
        lifecycle_state=OrderState.SUBMITTING,
        is_admissible=True,
        claim_token="opaque-first-claim",
    )

    assert admission.is_admissible
    assert admission.claim_token == "opaque-first-claim"


def test_non_admissible_submission_admission_retains_first_identities_without_claim() -> None:
    """A duplicate unresolved command is recoverable but cannot obtain another submit claim."""
    existing = SubmissionAdmission(
        command_id="command-first",
        client_order_id="client-first",
        reconciliation_job_id="job-first",
        lifecycle_state=OrderState.SUBMISSION_UNKNOWN,
        is_admissible=False,
        claim_token=None,
    )

    assert not existing.is_admissible
    assert existing.command_id == "command-first"
    assert existing.client_order_id == "client-first"
    assert existing.reconciliation_job_id == "job-first"
    assert existing.lifecycle_state is OrderState.SUBMISSION_UNKNOWN
    assert existing.claim_token is None

    with pytest.raises(ValueError):
        SubmissionAdmission(
            command_id="command-first",
            client_order_id="client-first",
            reconciliation_job_id="job-first",
            lifecycle_state=OrderState.SUBMISSION_UNKNOWN,
            is_admissible=False,
            claim_token="second-claim-is-invalid",
        )


def test_admission_contract_requires_claim_before_gateway_submission_and_identity_recovery() -> None:
    """Future coordinators are constrained to one claim and persisted recovery identities."""
    gateway_contract = TradingGateway.submit_order.__doc__ or ""
    ledger_contract = ExecutionLedger.mark_submission_ambiguous.__doc__ or ""

    assert "admissible claim" in gateway_contract
    assert "same persisted identities" in ledger_contract
    assert "reconciliation" in ledger_contract
