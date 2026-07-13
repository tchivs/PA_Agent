"""Deterministic, durable Paper Spot gateway with no independent submission authority."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from typing import Mapping

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    ExecutionCommand,
    Fill,
    GatewayCapabilities,
    GatewayEvidence,
    InstrumentRules,
    OrderProjection,
    OrderState,
    ProductType,
    QuoteObservation,
    RuleObservation,
    Side,
    SpotOrderContext,
    TimeObservation,
)
from pa_agent.trading.domain.risk import (
    FeeRateObservation,
    IsolatedMarginProductEvidence,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    UsdtPerpetualProductEvidence,
)
from pa_agent.trading.domain.paper import MarketObservation, PaperEconomicPolicy, PaperFillCandidate
from pa_agent.trading.gateways.paper.accounting_spot import PaperSpotAccounting
from pa_agent.trading.gateways.paper.faults import FaultPlan
from pa_agent.trading.gateways.paper.matching import match_order, sort_fill_candidates
from pa_agent.trading.gateways.paper.store import (
    CancellationDisposition,
    ObservationDisposition,
    PaperOrder,
    PaperProductSnapshot,
    PaperStore,
)
from pa_agent.trading.ports.gateway import GatewayUnavailableError, TradingGateway
from pa_agent.trading.ports.ledger import OutboundSubmission

_PAPER_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SPOT_SNAPSHOT_SCHEMA = "paper-spot-snapshot-v1"


class PaperGateway(TradingGateway):
    """Own Paper Spot simulation truth while accepting only ledger-leased submissions."""

    def __init__(
        self,
        store: PaperStore,
        *,
        policy: PaperEconomicPolicy | None = None,
        initial_balances: Mapping[str, Decimal | str] | None = None,
        fault_plan: FaultPlan | None = None,
    ) -> None:
        if type(store) is not PaperStore:
            raise TypeError("PaperGateway requires its independent PaperStore")
        if policy is not None and (type(policy) is not PaperEconomicPolicy or policy.product is not ProductType.SPOT):
            raise TypeError("PaperGateway requires a canonical Spot policy")
        if fault_plan is not None and type(fault_plan) is not FaultPlan:
            raise TypeError("PaperGateway fault plan must be canonical")
        self._store = store
        self._policy = policy
        self._fault_plan = fault_plan
        self._submission_invocations = 0
        if initial_balances is not None:
            accounting = PaperSpotAccounting.from_initial_balances(initial_balances)
            self._store.ensure_snapshot(self._snapshot("paper-account", "BTCUSDT", accounting))

    def get_capabilities(self) -> GatewayCapabilities:
        return GatewayCapabilities(frozenset(ProductType), True, True, True)

    def get_server_time(self) -> TimeObservation:
        observed_at = self._any_observed_at()
        return TimeObservation(observed_at, observed_at)

    def get_quote(self, symbol: str) -> QuoteObservation:
        observation = self._store.load_latest_observation(
            account_id="paper-account", product=ProductType.SPOT, symbol=symbol
        )
        if observation is None:
            raise _unavailable("quote")
        return QuoteObservation(symbol, observation.bids[0].price, observation.asks[0].price, observation.observed_at)

    def get_instrument_rules(self, symbol: str) -> RuleObservation:
        return RuleObservation(
            InstrumentRules(symbol, Decimal("0.01"), Decimal("0.001"), Decimal("0.001"), Decimal("0")),
            self._any_observed_at(),
        )

    def get_account_snapshot(self, account_id: str, product: ProductType) -> AccountObservation:
        if product is not ProductType.SPOT:
            raise _unavailable("non-Spot account snapshot")
        snapshot = self._load_spot_snapshot(account_id)
        balances = tuple(
            Balance(asset, balance.total, balance.available, balance.reserved)
            for asset, balance in sorted(snapshot._balances.items())
        )
        return AccountObservation(account_id, ProductType.SPOT, self._observed_at(account_id), balances, ())

    def get_connection(self, target: ExecutionTarget) -> TargetConnectionObservation:
        self._require_spot_target(target)
        return TargetConnectionObservation(target, True, self._observed_at(target.account_id))

    def get_open_order_count(self, target: ExecutionTarget) -> OpenOrderObservation:
        self._require_spot_target(target)
        count = len(self._store.list_open_orders(account_id=target.account_id, product=ProductType.SPOT.value))
        return OpenOrderObservation(target, count, self._observed_at(target.account_id))

    def get_order_rate_window(self, target: ExecutionTarget, window_seconds: int) -> OrderRateObservation:
        self._require_spot_target(target)
        if type(window_seconds) is not int or window_seconds <= 0:
            raise ValueError("paper order-rate window must be a positive integer")
        observed_at = self._observed_at(target.account_id)
        return OrderRateObservation(target, 0, observed_at - timedelta(seconds=window_seconds), observed_at)

    def get_loss_drawdown(self, target: ExecutionTarget) -> LossDrawdownObservation:
        self._require_spot_target(target)
        observed_at = self._observed_at(target.account_id)
        return LossDrawdownObservation(target, Decimal("0"), Decimal("0"), observed_at.replace(hour=0, minute=0, second=0, microsecond=0), observed_at)

    def get_fee_rate(self, target: ExecutionTarget, symbol: str, quote_identifier: str) -> FeeRateObservation:
        self._require_spot_target(target)
        policy = self._require_policy()
        return FeeRateObservation(
            target,
            symbol,
            symbol,
            quote_identifier,
            policy.fee_rate,
            policy.fee_rule_version,
            self._observed_at(target.account_id),
        )

    def get_isolated_margin_product_evidence(
        self, target: ExecutionTarget, isolated_symbol: str
    ) -> IsolatedMarginProductEvidence:
        evidence = self._store.load_isolated_margin_product_evidence(target, isolated_symbol)
        if evidence is None:
            raise _unavailable("isolated-margin product evidence")
        return evidence

    def get_usdt_perpetual_product_evidence(
        self, target: ExecutionTarget, symbol: str
    ) -> UsdtPerpetualProductEvidence:
        evidence = self._store.load_usdt_perpetual_product_evidence(target, symbol)
        if evidence is None:
            raise _unavailable("perpetual product evidence")
        return evidence

    def submit_order(self, outbound: OutboundSubmission) -> GatewayEvidence:
        """Open one durable Spot order only from the coordinator's ledger lease."""
        if type(outbound) is not OutboundSubmission:
            raise TypeError("PaperGateway accepts only a leased OutboundSubmission")
        command = outbound.command
        self._assert_spot_submission(command)
        existing = self._store.fetch_order(outbound.client_order_id)
        if existing is not None:
            return self._evidence_for_order(existing)
        observation = self._store.load_latest_observation(
            account_id=command.account_id, product=ProductType.SPOT, symbol=command.symbol
        )
        if observation is None:
            return self._rejected_evidence(command.client_order_id)
        accounting = self._load_spot_snapshot(command.account_id, command.symbol)
        try:
            opened = accounting.open(command, policy=self._require_policy(), observation=observation)
        except ValueError:
            return self._rejected_evidence(command.client_order_id)

        def candidates_for(sequence: int) -> tuple[PaperFillCandidate, ...]:
            return match_order(
                command=command,
                observation=observation,
                policy=self._require_policy(),
                paper_event_sequence=sequence,
            ).candidates

        def settled_snapshot(_: int, candidates: tuple[PaperFillCandidate, ...]) -> PaperProductSnapshot:
            return self._snapshot(command.account_id, command.symbol, opened.settle(command, candidates))

        order = self._store.create_order_with_snapshot(
            command,
            self._snapshot(command.account_id, command.symbol, opened),
            candidate_factory=candidates_for,
            snapshot_factory=settled_snapshot,
        )
        self._submission_invocations += 1
        if self._fault_plan is not None:
            self._fault_plan.raise_if_planned(self._submission_invocations)
        return self._evidence_for_order(order)

    def cancel_order(self, client_order_id: str) -> GatewayEvidence:
        """Persist cancellation intent; this method never invents terminal cancellation."""
        order = self._require_order(client_order_id)
        outcome = self._store.request_cancellation(client_order_id, cancellation_id=f"cancel:{client_order_id}")
        if outcome.disposition is CancellationDisposition.REJECTED_TERMINAL:
            return self._evidence_for_order(order)
        return GatewayEvidence(
            evidence_id=f"paper-cancel-request:{outcome.paper_event_sequence}:{client_order_id}",
            client_order_id=client_order_id,
            state=OrderState.CANCEL_REQUESTED,
            observed_at=self._observed_at(order.account_id, order.symbol),
        )

    def resolve_cancellation(self, client_order_id: str) -> GatewayEvidence:
        """Scenario control for terminal cancellation after a request has durable sequence precedence."""
        order = self._require_order(client_order_id)
        if order.lifecycle_state in {"FILLED", "CANCELLED", "REJECTED"}:
            return self._evidence_for_order(order)
        command = next(
            command
            for command in self._store.list_open_commands(
                account_id=order.account_id, product=ProductType(order.product), symbol=order.symbol
            )
            if command.client_order_id == client_order_id
        )
        accounting = self._load_spot_snapshot(order.account_id, order.symbol)
        released = accounting.release(command, remaining_quantity=command.quantity - order.filled_quantity)
        outcome = self._store.persist_cancellation_evidence(
            client_order_id,
            cancellation_id=f"cancel:{client_order_id}",
            snapshot=self._snapshot(order.account_id, order.symbol, released),
        )
        if outcome.disposition is CancellationDisposition.REJECTED_TERMINAL:
            return self._evidence_for_order(self._require_order(client_order_id))
        return self._evidence_for_order(self._require_order(client_order_id))

    def lookup_order_by_client_id(self, client_order_id: str) -> GatewayEvidence | None:
        order = self._store.fetch_order(client_order_id)
        return None if order is None else self._evidence_for_order(order)

    def list_open_orders(self, account_id: str, product: ProductType) -> tuple[OrderProjection, ...]:
        return tuple(
            self._projection(order)
            for order in self._store.list_open_orders(account_id=account_id, product=product.value)
        )

    def list_fills(self, command_id: str) -> tuple[Fill, ...]:
        fills: list[Fill] = []
        for paper_fill in self._store.list_fills(command_id):
            provenance = json.loads(paper_fill.provenance_json)
            observed_at = self._observed_at_from_provenance(provenance)
            fills.append(
                Fill(
                    fill_id=paper_fill.paper_fill_id,
                    command_id=paper_fill.command_id,
                    quantity=paper_fill.quantity,
                    price=Decimal(provenance["final_execution_price"]),
                    fee=Decimal(provenance["fee"]),
                    fee_asset="USDT",
                    observed_at=observed_at,
                )
            )
        return tuple(fills)

    def reconcile(self, command: ExecutionCommand) -> tuple[GatewayEvidence, ...]:
        if type(command) is not ExecutionCommand:
            raise TypeError("PaperGateway reconciliation requires a canonical command")
        evidence = self.lookup_order_by_client_id(command.client_order_id)
        return () if evidence is None else (evidence,)

    def advance_market(self, observation: MarketObservation) -> tuple[GatewayEvidence, ...]:
        """Advance only an explicit typed market fact; no polling, sleep, or outbound route exists."""
        if type(observation) is not MarketObservation:
            raise TypeError("PaperGateway advance_market requires a MarketObservation")
        if observation.product is not ProductType.SPOT:
            raise ValueError("PaperGateway currently projects only Spot observations")
        accounting = self._load_spot_snapshot(observation.account_id, observation.symbol)
        changed_client_order_ids: set[str] = set()

        def candidates_for(sequence: int) -> tuple[PaperFillCandidate, ...]:
            candidates: list[PaperFillCandidate] = []
            for command in self._store.list_open_commands(
                account_id=observation.account_id, product=ProductType.SPOT, symbol=observation.symbol
            ):
                order = self._require_order(command.client_order_id)
                residual = command.quantity - order.filled_quantity
                if residual <= 0:
                    continue
                matched = match_order(
                    command=replace(command, quantity=residual),
                    observation=observation,
                    policy=self._require_policy(),
                    paper_event_sequence=sequence,
                ).candidates
                if matched:
                    changed_client_order_ids.add(command.client_order_id)
                    candidates.extend(matched)
            return sort_fill_candidates(tuple(candidates))

        def settled_snapshot(_: int, candidates: tuple[PaperFillCandidate, ...]) -> PaperProductSnapshot:
            next_accounting = accounting
            by_command: dict[str, list[PaperFillCandidate]] = {}
            for candidate in candidates:
                by_command.setdefault(candidate.command_id, []).append(candidate)
            for command in self._store.list_open_commands(
                account_id=observation.account_id, product=ProductType.SPOT, symbol=observation.symbol
            ):
                command_candidates = tuple(by_command.get(command.command_id, ()))
                if command_candidates:
                    next_accounting = next_accounting.settle(command, command_candidates)
            return self._snapshot(observation.account_id, observation.symbol, next_accounting)

        result = self._store.apply_observation(
            observation=observation,
            candidate_factory=candidates_for,
            snapshot_factory=settled_snapshot,
        )
        if result.disposition is not ObservationDisposition.ACCEPTED:
            return ()
        return tuple(
            self._evidence_for_order(self._require_order(client_order_id))
            for client_order_id in sorted(changed_client_order_ids)
        )

    def _projection(self, order: PaperOrder) -> OrderProjection:
        fills = self.list_fills(order.command_id)
        return OrderProjection(
            command_id=order.command_id,
            state=OrderState(order.lifecycle_state.lower()),
            exchange_order_id=order.client_order_id,
            filled_quantity=order.filled_quantity,
            filled_notional=sum((fill.quantity * fill.price for fill in fills), Decimal("0")),
        )

    def _evidence_for_order(self, order: PaperOrder) -> GatewayEvidence:
        fills = self.list_fills(order.command_id)
        state = OrderState(order.lifecycle_state.lower())
        if state in {OrderState.PARTIALLY_FILLED, OrderState.FILLED}:
            notional = sum((fill.quantity * fill.price for fill in fills), Decimal("0"))
            average = notional / order.filled_quantity
            return GatewayEvidence(
                evidence_id=f"paper-order:{order.paper_event_sequence}:{order.client_order_id}",
                client_order_id=order.client_order_id,
                state=state,
                observed_at=self._observed_at(order.account_id, order.symbol),
                exchange_order_id=order.client_order_id,
                filled_quantity=order.filled_quantity,
                average_fill_price=average,
            )
        return GatewayEvidence(
            evidence_id=f"paper-order:{order.paper_event_sequence}:{order.client_order_id}",
            client_order_id=order.client_order_id,
            state=state,
            observed_at=self._observed_at(order.account_id, order.symbol),
            exchange_order_id=order.client_order_id,
        )

    def _rejected_evidence(self, client_order_id: str) -> GatewayEvidence:
        return GatewayEvidence(
            evidence_id=f"paper-rejected:{client_order_id}",
            client_order_id=client_order_id,
            state=OrderState.REJECTED,
            observed_at=self._any_observed_at(),
        )

    def _snapshot(self, account_id: str, symbol: str, accounting: PaperSpotAccounting) -> PaperProductSnapshot:
        return PaperProductSnapshot(
            account_id=account_id,
            product=ProductType.SPOT.value,
            scope=symbol,
            schema_version=_SPOT_SNAPSHOT_SCHEMA,
            payload=accounting.to_snapshot_payload(),
        )

    def _load_spot_snapshot(self, account_id: str, symbol: str = "BTCUSDT") -> PaperSpotAccounting:
        snapshot = self._store.load_snapshot(account_id=account_id, product=ProductType.SPOT.value, scope=symbol)
        if snapshot is None:
            raise _unavailable("paper Spot account snapshot")
        if snapshot.schema_version != _SPOT_SNAPSHOT_SCHEMA:
            raise ValueError("stored paper Spot snapshot schema is unsupported")
        return PaperSpotAccounting.from_snapshot_payload(snapshot.payload)

    def _observed_at(self, account_id: str, symbol: str = "BTCUSDT") -> datetime:
        observation = self._store.load_latest_observation(
            account_id=account_id, product=ProductType.SPOT, symbol=symbol
        )
        return _PAPER_EPOCH if observation is None else observation.observed_at

    def _any_observed_at(self) -> datetime:
        return _PAPER_EPOCH

    def _observed_at_from_provenance(self, provenance: Mapping[str, object]) -> datetime:
        observation = self._store.load_latest_observation(
            account_id="paper-account", product=ProductType.SPOT, symbol="BTCUSDT"
        )
        return _PAPER_EPOCH if observation is None else observation.observed_at

    def _require_order(self, client_order_id: str) -> PaperOrder:
        order = self._store.fetch_order(client_order_id)
        if order is None:
            raise _unavailable("paper order")
        return order

    def _require_policy(self) -> PaperEconomicPolicy:
        if self._policy is None:
            raise _unavailable("Spot economic policy")
        return self._policy

    def _assert_spot_submission(self, command: ExecutionCommand) -> None:
        if command.context.product is not ProductType.SPOT or type(command.context) is not SpotOrderContext:
            raise ValueError("PaperGateway only accepts Paper Spot submissions")

    @staticmethod
    def _require_spot_target(target: ExecutionTarget) -> None:
        if type(target) is not ExecutionTarget or target.product is not ProductType.SPOT:
            raise _unavailable("non-Spot target")


def _unavailable(fact: str) -> GatewayUnavailableError:
    return GatewayUnavailableError(f"PaperGateway has no committed {fact} fact")
