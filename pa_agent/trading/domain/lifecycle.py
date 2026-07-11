"""Pure evidence-driven lifecycle transitions for canonical order projections."""
from __future__ import annotations

from collections.abc import Mapping

from pa_agent.trading.domain.errors import LifecycleTransitionError, ReconciliationEvidenceError
from pa_agent.trading.domain.models import GatewayEvidence, LifecycleEvent, OrderState

_TERMINAL_STATES = frozenset({OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED})
_AMBIGUOUS_LOCAL_EVENTS = frozenset(
    {
        LifecycleEvent.LOCAL_TIMEOUT,
        LifecycleEvent.LOCAL_CANCELLATION,
        LifecycleEvent.STREAM_GAP,
        LifecycleEvent.MALFORMED_ACKNOWLEDGEMENT,
    }
)

_TRANSITIONS: Mapping[tuple[OrderState, LifecycleEvent], OrderState] = {
    (OrderState.PROPOSED, LifecycleEvent.SUBMIT_REQUESTED): OrderState.SUBMITTING,
    (OrderState.SUBMITTING, LifecycleEvent.ACKNOWLEDGEMENT_OBSERVED): OrderState.ACKNOWLEDGED,
    (OrderState.SUBMITTING, LifecycleEvent.OPEN_OBSERVED): OrderState.OPEN,
    (OrderState.SUBMITTING, LifecycleEvent.PARTIAL_FILL_OBSERVED): OrderState.PARTIALLY_FILLED,
    (OrderState.SUBMITTING, LifecycleEvent.FILL_OBSERVED): OrderState.FILLED,
    (OrderState.SUBMITTING, LifecycleEvent.REJECTION_OBSERVED): OrderState.REJECTED,
    (OrderState.SUBMISSION_UNKNOWN, LifecycleEvent.ACKNOWLEDGEMENT_OBSERVED): OrderState.ACKNOWLEDGED,
    (OrderState.SUBMISSION_UNKNOWN, LifecycleEvent.OPEN_OBSERVED): OrderState.OPEN,
    (OrderState.SUBMISSION_UNKNOWN, LifecycleEvent.PARTIAL_FILL_OBSERVED): OrderState.PARTIALLY_FILLED,
    (OrderState.SUBMISSION_UNKNOWN, LifecycleEvent.FILL_OBSERVED): OrderState.FILLED,
    (OrderState.SUBMISSION_UNKNOWN, LifecycleEvent.REJECTION_OBSERVED): OrderState.REJECTED,
    (OrderState.SUBMISSION_UNKNOWN, LifecycleEvent.CANCELLATION_OBSERVED): OrderState.CANCELLED,
    (OrderState.ACKNOWLEDGED, LifecycleEvent.OPEN_OBSERVED): OrderState.OPEN,
    (OrderState.ACKNOWLEDGED, LifecycleEvent.PARTIAL_FILL_OBSERVED): OrderState.PARTIALLY_FILLED,
    (OrderState.ACKNOWLEDGED, LifecycleEvent.FILL_OBSERVED): OrderState.FILLED,
    (OrderState.ACKNOWLEDGED, LifecycleEvent.REJECTION_OBSERVED): OrderState.REJECTED,
    (OrderState.ACKNOWLEDGED, LifecycleEvent.CANCELLATION_REQUESTED): OrderState.CANCEL_REQUESTED,
    (OrderState.OPEN, LifecycleEvent.PARTIAL_FILL_OBSERVED): OrderState.PARTIALLY_FILLED,
    (OrderState.OPEN, LifecycleEvent.FILL_OBSERVED): OrderState.FILLED,
    (OrderState.OPEN, LifecycleEvent.REJECTION_OBSERVED): OrderState.REJECTED,
    (OrderState.OPEN, LifecycleEvent.CANCELLATION_REQUESTED): OrderState.CANCEL_REQUESTED,
    (OrderState.PARTIALLY_FILLED, LifecycleEvent.PARTIAL_FILL_OBSERVED): OrderState.PARTIALLY_FILLED,
    (OrderState.PARTIALLY_FILLED, LifecycleEvent.FILL_OBSERVED): OrderState.FILLED,
    (OrderState.PARTIALLY_FILLED, LifecycleEvent.CANCELLATION_REQUESTED): OrderState.CANCEL_REQUESTED,
    (OrderState.CANCEL_REQUESTED, LifecycleEvent.OPEN_OBSERVED): OrderState.OPEN,
    (OrderState.CANCEL_REQUESTED, LifecycleEvent.PARTIAL_FILL_OBSERVED): OrderState.PARTIALLY_FILLED,
    (OrderState.CANCEL_REQUESTED, LifecycleEvent.FILL_OBSERVED): OrderState.FILLED,
    (OrderState.CANCEL_REQUESTED, LifecycleEvent.CANCELLATION_OBSERVED): OrderState.CANCELLED,
}


def is_terminal_state(state: OrderState) -> bool:
    """Return whether an order state is terminal and therefore cannot advance."""
    return state in _TERMINAL_STATES


def assert_transition(
    previous: OrderState,
    event: LifecycleEvent,
    *,
    evidence: GatewayEvidence | None = None,
) -> OrderState:
    """Validate and return the next state without mutating storage or gateway state.

    Local timeout, cancellation, stream-gap, and malformed-acknowledgement events
    only retain an explicitly unresolved state.  Terminal states always require
    normalized external evidence whose state agrees with the requested transition.
    """
    if is_terminal_state(previous):
        raise LifecycleTransitionError(f"terminal state {previous.value} cannot transition")
    if event in _AMBIGUOUS_LOCAL_EVENTS:
        if evidence is not None:
            raise LifecycleTransitionError("local interruption events cannot carry terminal evidence")
        return OrderState.SUBMISSION_UNKNOWN

    next_state = _TRANSITIONS.get((previous, event))
    if next_state is None:
        raise LifecycleTransitionError(
            f"event {event.value} is illegal from state {previous.value}"
        )
    if event is LifecycleEvent.SUBMIT_REQUESTED or event is LifecycleEvent.CANCELLATION_REQUESTED:
        if evidence is not None:
            raise LifecycleTransitionError(f"{event.value} is a local intent and cannot carry evidence")
        return next_state
    _assert_matching_evidence(next_state, evidence)
    return next_state


def _assert_matching_evidence(next_state: OrderState, evidence: GatewayEvidence | None) -> None:
    """Require definitive normalized gateway evidence for every observed transition."""
    if evidence is None:
        raise ReconciliationEvidenceError(
            f"transition to {next_state.value} requires normalized external evidence"
        )
    if evidence.state is not next_state:
        raise ReconciliationEvidenceError(
            f"evidence state {evidence.state.value} cannot establish {next_state.value}"
        )
