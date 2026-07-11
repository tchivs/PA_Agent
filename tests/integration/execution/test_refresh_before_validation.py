"""Integration coverage for fresh rule metadata before public validation."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import inspect

import pytest

from pa_agent.trading.application import validation
from pa_agent.trading.application.validation import OrderValidationService
from pa_agent.trading.domain.errors import InstrumentRuleValidationError
from pa_agent.trading.domain.models import InstrumentRules, RuleObservation
from pa_agent.trading.ports.gateway import GatewayUnavailableError
from tests.fixtures.execution_factories import make_spot_command
from tests.fixtures.fake_exchange import ScriptedInstrumentRuleGateway

pytestmark = pytest.mark.integration


def _observation(
    *, symbol: str = "BTCUSDT", price_tick: Decimal = Decimal("0.05")
) -> RuleObservation:
    return RuleObservation(
        rules=InstrumentRules(
            symbol=symbol,
            price_tick=price_tick,
            quantity_step=Decimal("0.001"),
            minimum_quantity=Decimal("0.010"),
            minimum_notional=Decimal("100"),
        ),
        observed_at=datetime(2026, 7, 11, tzinfo=UTC),
    )


def _record_rule_boundary_order(
    monkeypatch: pytest.MonkeyPatch,
    gateway: ScriptedInstrumentRuleGateway,
) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    original_lookup = gateway.get_instrument_rules
    original_helper = validation._validate_command_against_instrument_rules

    def record_lookup(symbol: str) -> RuleObservation:
        events.append(("lookup", symbol))
        return original_lookup(symbol)

    def record_helper(command: object, rules: InstrumentRules) -> None:
        events.append(("helper", rules.symbol))
        original_helper(command, rules)  # type: ignore[arg-type]

    monkeypatch.setattr(gateway, "get_instrument_rules", record_lookup)
    monkeypatch.setattr(validation, "_validate_command_against_instrument_rules", record_helper)
    return events


def test_validate_is_the_only_public_typed_command_operation_and_refreshes_before_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sole public operation receives only a command and looks up rules first."""
    command = make_spot_command(price=Decimal("100.05"), quantity=Decimal("1"))
    gateway = ScriptedInstrumentRuleGateway([_observation()])
    events = _record_rule_boundary_order(monkeypatch, gateway)

    OrderValidationService(gateway=gateway).validate(command)

    assert list(inspect.signature(OrderValidationService.validate).parameters) == ["self", "command"]
    assert events == [("lookup", command.symbol), ("helper", command.symbol)]
    assert gateway.instrument_rule_symbols == [command.symbol]
    assert gateway.submit_call_count == 0


def test_validate_fetches_and_applies_new_rules_on_each_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later observation changes the later outcome instead of reusing prior rules."""
    command = make_spot_command(price=Decimal("100.05"), quantity=Decimal("1"))
    gateway = ScriptedInstrumentRuleGateway([_observation(), _observation(price_tick=Decimal("0.1"))])
    events = _record_rule_boundary_order(monkeypatch, gateway)
    service = OrderValidationService(gateway=gateway)

    service.validate(command)
    with pytest.raises(InstrumentRuleValidationError):
        service.validate(command)

    assert events == [
        ("lookup", command.symbol),
        ("helper", command.symbol),
        ("lookup", command.symbol),
        ("helper", command.symbol),
    ]
    assert gateway.instrument_rule_symbols == [command.symbol, command.symbol]
    assert gateway.submit_call_count == 0


def test_validate_propagates_unavailable_metadata_without_helper_or_cached_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed current lookup is typed, has no helper call, and cannot reuse past rules."""
    command = make_spot_command(price=Decimal("100.05"), quantity=Decimal("1"))
    gateway = ScriptedInstrumentRuleGateway([_observation(), GatewayUnavailableError("offline")])
    events = _record_rule_boundary_order(monkeypatch, gateway)
    service = OrderValidationService(gateway=gateway)

    service.validate(command)
    with pytest.raises(GatewayUnavailableError):
        service.validate(command)

    assert events == [("lookup", command.symbol), ("helper", command.symbol), ("lookup", command.symbol)]
    assert gateway.instrument_rule_symbols == [command.symbol, command.symbol]
    assert gateway.submit_call_count == 0


def test_validate_rejects_mismatched_observation_without_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway response for another symbol fails closed after its one lookup."""
    command = make_spot_command(price=Decimal("100.05"), quantity=Decimal("1"))
    gateway = ScriptedInstrumentRuleGateway([_observation(symbol="ETHUSDT")])
    events = _record_rule_boundary_order(monkeypatch, gateway)

    with pytest.raises(InstrumentRuleValidationError):
        OrderValidationService(gateway=gateway).validate(command)

    assert events == [("lookup", command.symbol), ("helper", "ETHUSDT")]
    assert gateway.instrument_rule_symbols == [command.symbol]
    assert gateway.submit_call_count == 0
