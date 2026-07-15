"""Generated convergence checks for deterministic offline Paper lifecycle evidence."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from decimal import Decimal
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test
import pytest

from pa_agent.trading.application.paper_runtime import PaperTradingRuntime
from pa_agent.trading.domain.models import OrderState, ProductType
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.paper_scenarios import make_observation, make_policy
from tests.integration.execution.test_paper_spot_recovery import _leased_permit, _shallow_observation


class PaperLifecycleMachine(RuleBasedStateMachine):
    """Exercise only explicit Paper facts and assert durable convergence at every step."""

    def __init__(self) -> None:
        super().__init__()
        self._directory = TemporaryDirectory()
        root = Path(self._directory.name)
        self._ledger_path = root / "ledger.sqlite"
        self._paper_path = root / "paper.sqlite"
        ledger, self.permit = _leased_permit(self._ledger_path)
        self.runtime = PaperTradingRuntime(
            ledger=ledger,
            store=PaperStore(self._paper_path),
            policy=make_policy(),
            initial_balances={"USDT": "1000", "BTC": "0"},
        )
        self.runtime.gateway.advance_market(_shallow_observation())
        self.submitted = False
        self.cancel_requested = False
        self.terminal_state: OrderState | None = None

    @precondition(lambda machine: not machine.submitted)
    @rule()
    def submit_once(self) -> None:
        result = self.runtime.submission.submit(self.permit)
        assert result.evidence is not None
        self.submitted = True

    @precondition(lambda machine: machine.submitted)
    @rule(version=st.integers(min_value=1, max_value=4), duplicate=st.booleans())
    def apply_explicit_or_stale_observation(self, version: int, duplicate: bool) -> None:
        observation = _shallow_observation(
            observation_id=("btc-book-001" if duplicate else f"btc-book-{version}"),
            version=version,
            asks=(make_observation().asks[1],),
        )
        self.runtime.gateway.advance_market(observation)

    @precondition(lambda machine: machine.submitted and not machine.cancel_requested and (order := machine.runtime.gateway._store.fetch_order(machine.permit.client_order_id)) is not None and order.lifecycle_state not in {"FILLED", "CANCELLED", "REJECTED"})  # noqa: SLF001
    @rule()
    def request_cancellation(self) -> None:
        result = self.runtime.gateway.cancel_order(self.permit.client_order_id)
        assert result.evidence is not None
        assert result.evidence.state is OrderState.CANCEL_REQUESTED
        self.cancel_requested = True

    @precondition(lambda machine: machine.submitted and machine.cancel_requested)
    @rule()
    def resolve_cancellation_only_from_paper_evidence(self) -> None:
        result = self.runtime.gateway.resolve_cancellation(self.permit.client_order_id)
        assert result.evidence is not None
        self.terminal_state = result.evidence.state if result.evidence.state in {
            OrderState.CANCELLED,
            OrderState.FILLED,
            OrderState.REJECTED,
        } else None

    @precondition(lambda machine: machine.submitted)
    @rule()
    def restart_and_reconcile_by_persisted_client_id(self) -> None:
        self.runtime.close()
        self.runtime = PaperTradingRuntime(
            ledger=SQLiteExecutionLedger(self._ledger_path),
            store=PaperStore(self._paper_path),
            policy=make_policy(),
        )
        self.runtime.recovery.recover_startup()

    @invariant()
    def persisted_paper_truth_and_projection_never_regress(self) -> None:
        store = self.runtime.gateway._store  # noqa: SLF001 - independently durable test authority
        events = store.list_events()
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        order = store.fetch_order(self.permit.client_order_id)
        if order is not None:
            assert order.filled_quantity <= Decimal("2")
            if self.terminal_state is not None:
                assert OrderState(order.lifecycle_state.lower()) is self.terminal_state
            operation = self.runtime.gateway.lookup_order_by_client_id(self.permit.client_order_id)
            assert operation is not None
            assert operation.evidence is not None
            assert operation.evidence.client_order_id == self.permit.client_order_id
            assert operation.evidence.state is OrderState(order.lifecycle_state.lower())
        assert self.runtime.gateway._submission_invocations <= 1  # noqa: SLF001 - no second outbound call

    def teardown(self) -> None:
        self.runtime.close()
        self._directory.cleanup()


def test_generated_paper_lifecycle_schedules_converge_without_local_time() -> None:
    """Bounded submit/observe/cancel/restart schedules preserve Paper event ordering."""
    run_state_machine_as_test(PaperLifecycleMachine, settings=None)


@pytest.mark.integration
def test_duplicate_and_out_of_order_observations_preserve_paper_projection_truth(tmp_path: Path) -> None:
    """A central retry consumes independent Paper evidence and never changes it."""
    ledger, permit = _leased_permit(tmp_path / "ledger.sqlite")
    runtime = PaperTradingRuntime(
        ledger=ledger,
        store=PaperStore(tmp_path / "paper.sqlite"),
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
    )
    try:
        runtime.gateway.advance_market(_shallow_observation())
        runtime.submission.submit(permit)
        truth = runtime.gateway.read_operation(
            runtime.gateway.lookup_order_by_client_id(permit.client_order_id).reference  # type: ignore[union-attr]
        )
        sequence_before = truth.snapshots[0].paper_event_sequence
        assert sequence_before is not None

        assert runtime.gateway.advance_market(_shallow_observation()) == ()
        assert runtime.gateway.advance_market(
            _shallow_observation(observation_id="stale-book", version=1)
        ) == ()
        replayed = runtime.gateway.read_operation(truth.reference)
        assert replayed == truth
        assert runtime.gateway._store.list_incidents()  # noqa: SLF001 - durable out-of-order audit
        assert runtime.gateway._submission_invocations == 1  # noqa: SLF001
    finally:
        runtime.close()
