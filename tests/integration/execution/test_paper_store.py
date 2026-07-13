"""Integration contracts for independent, durable paper simulation truth."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pa_agent.trading.domain.paper import DepthLevel
from pa_agent.trading.gateways.paper.matching import match_order
from pa_agent.trading.gateways.paper.store import (
    CancellationDisposition,
    ObservationDisposition,
    PaperProductSnapshot,
    PaperStore,
)
from tests.fixtures.paper_scenarios import make_command, make_observation, make_policy


def _snapshot_payload(*, available_quote: str = "899.799800") -> PaperProductSnapshot:
    return PaperProductSnapshot(
        account_id="paper-account",
        product="spot",
        scope="BTCUSDT",
        schema_version="paper-spot-snapshot-v1",
        payload={
            "available_quote": available_quote,
            "reserved_quote": "0",
            "base_balance": "1",
        },
    )


def _apply_accepted_observation(store: PaperStore) -> tuple[str, str]:
    command = make_command(quantity=Decimal("1"))
    observation = make_observation(version=2)
    store.create_order(command)
    candidates = match_order(
        command=command,
        observation=observation,
        policy=make_policy(),
        paper_event_sequence=1,
    ).candidates
    outcome = store.apply_observation(
        observation=observation,
        candidates=candidates,
        snapshot=_snapshot_payload(),
    )

    assert outcome.disposition is ObservationDisposition.ACCEPTED
    assert outcome.paper_event_sequence == 1
    return command.client_order_id, command.command_id


def test_paper_truth_reopens_from_its_own_filesystem_sqlite_database(tmp_path: Path) -> None:
    """The central execution ledger is neither opened nor needed to query paper truth."""
    paper_path = tmp_path / "paper-truth.sqlite"
    store = PaperStore(paper_path)
    client_order_id, command_id = _apply_accepted_observation(store)

    before_close = (
        store.fetch_order(client_order_id),
        store.list_fills(command_id),
        store.list_open_orders(account_id="paper-account", product="spot"),
        store.load_snapshot(account_id="paper-account", product="spot", scope="BTCUSDT"),
    )
    assert store.database_path == paper_path.resolve()
    assert before_close[0] is not None
    assert before_close[0].paper_event_sequence == 1
    assert len(before_close[1]) == 1
    assert before_close[2] == ()
    assert before_close[3].payload["available_quote"] == "899.799800"
    store.close()

    reopened = PaperStore(paper_path)
    assert reopened.fetch_order(client_order_id) == before_close[0]
    assert reopened.list_fills(command_id) == before_close[1]
    assert reopened.list_open_orders(account_id="paper-account", product="spot") == before_close[2]
    assert (
        reopened.load_snapshot(account_id="paper-account", product="spot", scope="BTCUSDT")
        == before_close[3]
    )
    assert reopened.list_events()[-1].sequence == 1
    reopened.close()


def test_duplicate_stale_and_conflicting_observations_preserve_durable_projection(tmp_path: Path) -> None:
    """Version/digest cursors record no-op or incident outcomes without mutating accepted truth."""
    store = PaperStore(tmp_path / "paper-truth.sqlite")
    client_order_id, command_id = _apply_accepted_observation(store)
    accepted_truth = (
        store.fetch_order(client_order_id),
        store.list_fills(command_id),
        store.load_snapshot(account_id="paper-account", product="spot", scope="BTCUSDT"),
    )
    accepted_observation = make_observation(version=2)

    duplicate = store.apply_observation(
        observation=accepted_observation,
        candidates=(),
        snapshot=_snapshot_payload(available_quote="0"),
    )
    stale = store.apply_observation(
        observation=make_observation(observation_id="btc-book-000", version=1),
        candidates=(),
        snapshot=_snapshot_payload(available_quote="0"),
    )
    conflict = store.apply_observation(
        observation=make_observation(
            version=2,
            asks=(DepthLevel(price=Decimal("100"), quantity=Decimal("2")),),
        ),
        candidates=(),
        snapshot=_snapshot_payload(available_quote="0"),
    )

    assert duplicate.disposition is ObservationDisposition.IDEMPOTENT
    assert stale.disposition is ObservationDisposition.REJECTED_OUT_OF_ORDER
    assert conflict.disposition is ObservationDisposition.REJECTED_CONFLICT
    assert (
        store.fetch_order(client_order_id),
        store.list_fills(command_id),
        store.load_snapshot(account_id="paper-account", product="spot", scope="BTCUSDT"),
    ) == accepted_truth
    assert [incident.kind for incident in store.list_incidents()] == ["out_of_order", "conflict"]
    store.close()


def test_cancel_request_and_observation_share_one_sequence_without_terminal_regression(tmp_path: Path) -> None:
    """Cancellation intent is durable evidence; terminal cancellation wins only when persisted."""
    store = PaperStore(tmp_path / "paper-truth.sqlite")
    command = make_command(quantity=Decimal("4"))
    store.create_order(command)

    cancellation = store.request_cancellation(command.client_order_id, cancellation_id="cancel-001")
    assert cancellation.disposition is CancellationDisposition.REQUESTED
    assert cancellation.paper_event_sequence == 1
    assert store.fetch_order(command.client_order_id).lifecycle_state == "OPEN"

    observation = make_observation()
    candidates = match_order(
        command=command,
        observation=observation,
        policy=make_policy(),
        paper_event_sequence=2,
    ).candidates
    accepted = store.apply_observation(
        observation=observation,
        candidates=candidates,
        snapshot=_snapshot_payload(),
    )
    assert accepted.disposition is ObservationDisposition.ACCEPTED
    assert accepted.paper_event_sequence == 2

    cancellation_evidence = store.persist_cancellation_evidence(
        command.client_order_id,
        cancellation_id="cancel-001",
    )
    assert cancellation_evidence.disposition is CancellationDisposition.CANCELLED
    assert cancellation_evidence.paper_event_sequence == 3
    terminal_truth = (store.fetch_order(command.client_order_id), store.list_fills(command.command_id))
    assert terminal_truth[0].lifecycle_state == "CANCELLED"

    late_observation = store.apply_observation(
        observation=make_observation(observation_id="btc-book-002", version=2),
        candidates=(),
        snapshot=_snapshot_payload(available_quote="0"),
    )
    assert late_observation.disposition is ObservationDisposition.REJECTED_TERMINAL
    assert (store.fetch_order(command.client_order_id), store.list_fills(command.command_id)) == terminal_truth
    assert [event.sequence for event in store.list_events()] == [1, 2, 3]
    store.close()
