"""Deterministic, durable Paper Spot gateway with no independent submission authority."""
from __future__ import annotations

from dataclasses import dataclass, replace
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
    IsolatedMarginOrderContext,
    Mode,
    SpotOrderContext,
    UsdtPerpetualOrderContext,
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
from pa_agent.trading.gateways.paper.accounting_margin import PaperMarginAccounting
from pa_agent.trading.gateways.paper.accounting_perpetual import PaperPerpetualAccounting
from pa_agent.trading.gateways.paper.faults import FaultPlan
from pa_agent.trading.gateways.paper.matching import match_order, sort_fill_candidates
from pa_agent.trading.gateways.paper.store import (
    CancellationDisposition,
    ObservationDisposition,
    PaperOrder,
    PaperProductSnapshot,
    PaperFill,
    PaperStore,
)
from pa_agent.trading.ports.gateway import (
    GatewayOperationObserver,
    GatewayOperationReference,
    GatewayOperationResult,
    GatewayUnavailableError,
    TradingGateway,
)
from pa_agent.trading.ports.ledger import LeasedSubmissionVerifier
from pa_agent.trading.ports.ledger import OutboundSubmission

_PAPER_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SPOT_SNAPSHOT_SCHEMA = "paper-spot-snapshot-v1"


@dataclass(frozen=True, slots=True)
class PaperOperationBatch:
    """Committed Paper facts resolved from an opaque operation reference."""

    reference: GatewayOperationReference
    evidence: GatewayEvidence
    fills: tuple[Fill, ...]
    snapshots: tuple[PaperProductSnapshot, ...]
    paper_fills: tuple[PaperFill, ...] = ()


class PaperGateway(TradingGateway):
    """Own durable Paper Spot or one isolated-margin product truth without submission authority."""

    def __init__(
        self,
        store: PaperStore,
        *,
        policy: PaperEconomicPolicy | None = None,
        initial_balances: Mapping[str, Decimal | str] | None = None,
        initial_margin_accounts: Mapping[str, PaperMarginAccounting] | None = None,
        initial_perpetual_accounts: Mapping[str, PaperPerpetualAccounting] | None = None,
        fault_plan: FaultPlan | None = None,
        operation_observer: GatewayOperationObserver | None = None,
        leased_submission_verifier: LeasedSubmissionVerifier | None = None,
    ) -> None:
        if type(store) is not PaperStore:
            raise TypeError("PaperGateway requires its independent PaperStore")
        if policy is not None and type(policy) is not PaperEconomicPolicy:
            raise TypeError("PaperGateway requires a canonical Paper economic policy")
        if fault_plan is not None and type(fault_plan) is not FaultPlan:
            raise TypeError("PaperGateway fault plan must be canonical")
        if operation_observer is not None and not isinstance(operation_observer, GatewayOperationObserver):
            raise TypeError("PaperGateway operation observer must implement GatewayOperationObserver")
        if leased_submission_verifier is not None and not isinstance(leased_submission_verifier, LeasedSubmissionVerifier):
            raise TypeError("PaperGateway leased submission verifier must implement the durable lease contract")
        self._store = store
        self._policy = policy
        self._fault_plan = fault_plan
        self._operation_observer = operation_observer
        self._leased_submission_verifier = leased_submission_verifier
        self._submission_invocations = 0
        if initial_balances is not None:
            if self._policy is not None and self._policy.product is not ProductType.SPOT:
                raise TypeError("Spot balances require a Spot economic policy")
            accounting = PaperSpotAccounting.from_initial_balances(initial_balances)
            self._store.ensure_snapshot(self._snapshot("paper-account", "BTCUSDT", accounting))
        if initial_margin_accounts is not None:
            if self._policy is None or self._policy.product is not ProductType.ISOLATED_MARGIN:
                raise TypeError("isolated margin accounts require an isolated-margin policy")
            for symbol, accounting in initial_margin_accounts.items():
                if type(symbol) is not str or type(accounting) is not PaperMarginAccounting or symbol != accounting.isolated_symbol:
                    raise TypeError("paper margin account seeds must be exact isolated-pair accounting")
                self._store.ensure_snapshot(self._margin_snapshot("paper-account", accounting))
                self._store.commit_isolated_margin_product_evidence(
                    accounting.to_evidence(target=self._margin_target("paper-account"), observed_at=_PAPER_EPOCH)
                )
        if initial_perpetual_accounts is not None:
            if self._policy is None or self._policy.product is not ProductType.USDT_PERPETUAL:
                raise TypeError("USDT perpetual accounts require a USDT-perpetual policy")
            for symbol, accounting in initial_perpetual_accounts.items():
                if (
                    type(symbol) is not str
                    or type(accounting) is not PaperPerpetualAccounting
                    or symbol != accounting.symbol
                ):
                    raise TypeError("paper perpetual account seeds must be exact symbol accounting")
                self._store.ensure_snapshot(self._perpetual_snapshot("paper-account", accounting))

    def get_capabilities(self) -> GatewayCapabilities:
        return GatewayCapabilities(frozenset(ProductType), True, True, True)

    def get_server_time(self) -> TimeObservation:
        observed_at = self._any_observed_at()
        return TimeObservation(observed_at, observed_at)

    def get_quote(self, symbol: str) -> QuoteObservation:
        observation = self._store.load_latest_observation(
            account_id="paper-account", product=self._product(), symbol=symbol
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
        if product is ProductType.SPOT:
            snapshot = self._load_spot_snapshot(account_id)
            balances = tuple(
                Balance(asset, balance.total, balance.available, balance.reserved)
                for asset, balance in sorted(snapshot._balances.items())
            )
            return AccountObservation(account_id, ProductType.SPOT, self._observed_at(account_id), balances, ())
        if product is ProductType.ISOLATED_MARGIN and self._product() is ProductType.ISOLATED_MARGIN:
            # Pair-scoped evidence is authoritative; an aggregate collateral pool is deliberately absent.
            return AccountObservation(account_id, product, self._any_observed_at(), (), ())
        raise _unavailable("unsupported paper account snapshot")

    def get_connection(self, target: ExecutionTarget) -> TargetConnectionObservation:
        self._require_product_target(target)
        return TargetConnectionObservation(target, True, self._observed_at(target.account_id))

    def get_open_order_count(self, target: ExecutionTarget) -> OpenOrderObservation:
        self._require_product_target(target)
        count = len(self._store.list_open_orders(account_id=target.account_id, product=target.product.value))
        return OpenOrderObservation(target, count, self._observed_at(target.account_id))

    def get_order_rate_window(self, target: ExecutionTarget, window_seconds: int) -> OrderRateObservation:
        self._require_product_target(target)
        if type(window_seconds) is not int or window_seconds <= 0:
            raise ValueError("paper order-rate window must be a positive integer")
        observed_at = self._observed_at(target.account_id)
        return OrderRateObservation(target, 0, observed_at - timedelta(seconds=window_seconds), observed_at)

    def get_loss_drawdown(self, target: ExecutionTarget) -> LossDrawdownObservation:
        self._require_product_target(target)
        observed_at = self._observed_at(target.account_id)
        return LossDrawdownObservation(target, Decimal("0"), Decimal("0"), observed_at.replace(hour=0, minute=0, second=0, microsecond=0), observed_at)

    def get_fee_rate(self, target: ExecutionTarget, symbol: str, quote_identifier: str) -> FeeRateObservation:
        self._require_product_target(target)
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
            raise _unavailable("USDT-perpetual product evidence")
        return evidence

    def submit_order(self, outbound: OutboundSubmission) -> GatewayOperationResult:
        """Accept only a leased outbound authorization and dispatch by canonical product context."""
        if type(outbound) is not OutboundSubmission:
            raise TypeError("PaperGateway accepts only a leased OutboundSubmission")
        if self._leased_submission_verifier is None:
            raise GatewayUnavailableError("PaperGateway submission requires a durable leased authorization verifier")
        self._leased_submission_verifier.validate_leased_outbound_submission(outbound)
        if type(outbound.command.context) is SpotOrderContext:
            return self._submit_spot_order(outbound)
        if type(outbound.command.context) is IsolatedMarginOrderContext:
            return self._submit_margin_order(outbound)
        if type(outbound.command.context) is UsdtPerpetualOrderContext:
            return self._submit_perpetual_order(outbound)
        return self._rejected_result(outbound.client_order_id)

    def _submit_spot_order(self, outbound: OutboundSubmission) -> GatewayOperationResult:
        """Keep the established Spot reservation and matching path unchanged."""
        command = outbound.command
        self._assert_spot_submission(command)
        existing = self._store.fetch_order(outbound.client_order_id)
        if existing is not None:
            return self._result_for_order(existing)
        observation = self._store.load_latest_observation(
            account_id=command.account_id, product=ProductType.SPOT, symbol=command.symbol
        )
        if observation is None:
            return self._rejected_result(command.client_order_id)
        accounting = self._load_spot_snapshot(command.account_id, command.symbol)
        try:
            opened = accounting.open(command, policy=self._require_policy(), observation=observation)
        except ValueError:
            return self._rejected_result(command.client_order_id)

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
        return self._after_accepted_submission(order)

    def _submit_margin_order(self, outbound: OutboundSubmission) -> GatewayOperationResult:
        """Validate exact pair credit context before a durable margin order or simulated fill exists."""
        command = outbound.command
        if command.context.product is not ProductType.ISOLATED_MARGIN:
            return self._rejected_result(command.client_order_id)
        existing = self._store.fetch_order(outbound.client_order_id)
        if existing is not None:
            return self._result_for_order(existing)
        observation = self._store.load_latest_observation(
            account_id=command.account_id,
            product=ProductType.ISOLATED_MARGIN,
            symbol=command.context.isolated_symbol,
        )
        if observation is None:
            return self._rejected_result(command.client_order_id)
        accounting = self._load_margin_snapshot(command.account_id, command.context.isolated_symbol)
        policy = self._require_policy()
        try:
            accounting.validate_open(command, policy=policy, observation=observation)
        except ValueError:
            return self._rejected_result(command.client_order_id)

        def candidates_for(sequence: int) -> tuple[PaperFillCandidate, ...]:
            return match_order(
                command=command,
                observation=observation,
                policy=policy,
                paper_event_sequence=sequence,
            ).candidates

        def settled_accounting(candidates: tuple[PaperFillCandidate, ...]) -> PaperMarginAccounting:
            settled = accounting.settle(command, candidates)
            if settled.margin_health < policy.minimum_margin_health:
                raise ValueError("paper margin fill would breach pair health")
            return settled

        def settled_snapshot(_: int, candidates: tuple[PaperFillCandidate, ...]) -> PaperProductSnapshot:
            return self._margin_snapshot(command.account_id, settled_accounting(candidates))


        try:
            order = self._store.create_order_with_snapshot(
                command,
                self._margin_snapshot(command.account_id, accounting),
                candidate_factory=candidates_for,
                snapshot_factory=settled_snapshot,
            )
        except ValueError:
            return self._rejected_result(command.client_order_id)
        return self._after_accepted_submission(order)

    def _submit_perpetual_order(self, outbound: OutboundSubmission) -> GatewayOperationResult:
        """Open or reduce only the canonical isolated, one-way symbol position."""
        command = outbound.command
        if command.context.product is not ProductType.USDT_PERPETUAL:
            return self._rejected_result(command.client_order_id)
        existing = self._store.fetch_order(outbound.client_order_id)
        if existing is not None:
            return self._result_for_order(existing)
        observation = self._store.load_latest_observation(
            account_id=command.account_id,
            product=ProductType.USDT_PERPETUAL,
            symbol=command.context.symbol or command.symbol,
        )
        if observation is None:
            return self._rejected_result(command.client_order_id)
        accounting = self._load_perpetual_snapshot(command.account_id, command.symbol)
        policy = self._require_policy()
        try:
            accounting.validate_open(command, policy=policy, observation=observation)

            def candidates_for(sequence: int) -> tuple[PaperFillCandidate, ...]:
                return match_order(
                    command=command,
                    observation=observation,
                    policy=policy,
                    paper_event_sequence=sequence,
                ).candidates

            def settled_snapshot(_: int, candidates: tuple[PaperFillCandidate, ...]) -> PaperProductSnapshot:
                return self._perpetual_snapshot(
                    command.account_id, accounting.settle(command, candidates, policy=policy)
                )

            order = self._store.create_order_with_snapshot(
                command,
                self._perpetual_snapshot(command.account_id, accounting),
                candidate_factory=candidates_for,
                snapshot_factory=settled_snapshot,
            )
        except ValueError:
            return self._rejected_result(command.client_order_id)
        return self._after_accepted_submission(order)

    def _after_accepted_submission(self, order: PaperOrder) -> GatewayOperationResult:
        self._submission_invocations += 1
        if self._fault_plan is not None:
            self._fault_plan.raise_if_planned(self._submission_invocations)
        return self._result_for_order(order)

    def cancel_order(self, client_order_id: str) -> GatewayOperationResult:
        """Persist cancellation intent; this method never invents terminal cancellation."""
        order = self._require_order(client_order_id)
        outcome = self._store.request_cancellation(client_order_id, cancellation_id=f"cancel:{client_order_id}")
        if outcome.disposition is CancellationDisposition.REJECTED_TERMINAL:
            return self._result_for_order(order)
        evidence = GatewayEvidence(
            evidence_id=f"paper-cancel-request:{outcome.paper_event_sequence}:{client_order_id}",
            client_order_id=client_order_id,
            state=OrderState.CANCEL_REQUESTED,
            observed_at=self._observed_at(order.account_id, order.symbol),
        )
        return self._result_for_order(self._require_order(client_order_id), evidence=evidence)

    def resolve_cancellation(self, client_order_id: str) -> GatewayOperationResult:
        """Commit terminal cancellation truth before direct observer delivery."""
        order = self._require_order(client_order_id)
        if order.lifecycle_state in {"FILLED", "CANCELLED", "REJECTED"}:
            return self._result_for_order(order)
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
        result = self._result_for_order(self._require_order(client_order_id))
        if outcome.disposition is CancellationDisposition.CANCELLED:
            self._observe_direct(result)
        return result

    def lookup_order_by_client_id(self, client_order_id: str) -> GatewayOperationResult | None:
        order = self._store.fetch_order(client_order_id)
        return None if order is None else self._result_for_order(order)

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
        result = self.lookup_order_by_client_id(command.client_order_id)
        return () if result is None or result.evidence is None else (result.evidence,)

    def advance_market(self, observation: MarketObservation) -> tuple[GatewayOperationResult, ...]:
        """Advance only one explicit typed market fact for its configured Paper product."""
        if type(observation) is not MarketObservation:
            raise TypeError("PaperGateway advance_market requires a MarketObservation")
        if observation.product is ProductType.SPOT:
            return self._advance_spot_market(observation)
        if observation.product is ProductType.ISOLATED_MARGIN:
            return self._advance_margin_market(observation)
        if observation.product is ProductType.USDT_PERPETUAL:
            return self._advance_perpetual_market(observation)
        raise ValueError("PaperGateway requires a supported product observation")

    def _advance_spot_market(self, observation: MarketObservation) -> tuple[GatewayOperationResult, ...]:
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
        results = tuple(
            self._result_for_order(self._require_order(client_order_id))
            for client_order_id in sorted(changed_client_order_ids)
        )
        for operation_result in results:
            self._observe_direct(operation_result)
        return results

    def _advance_margin_market(self, observation: MarketObservation) -> tuple[GatewayOperationResult, ...]:
        if self._product() is not ProductType.ISOLATED_MARGIN:
            raise ValueError("PaperGateway policy does not permit isolated-margin observations")
        accounting = self._load_margin_snapshot(observation.account_id, observation.symbol)
        policy = self._require_policy()
        if observation.version <= accounting.observation_version:
            return ()
        accrued = accounting.accrue_interest(
            observation_version=observation.version, interest_rate=policy.interest_rate
        )
        changed_client_order_ids: set[str] = set()

        def commands() -> tuple[ExecutionCommand, ...]:
            return self._store.list_open_commands(
                account_id=observation.account_id,
                product=ProductType.ISOLATED_MARGIN,
                symbol=observation.symbol,
            )

        def settled(candidates: tuple[PaperFillCandidate, ...]) -> PaperMarginAccounting:
            next_accounting = accrued
            by_command: dict[str, list[PaperFillCandidate]] = {}
            for candidate in candidates:
                by_command.setdefault(candidate.command_id, []).append(candidate)
            for command in commands():
                command_candidates = tuple(by_command.get(command.command_id, ()))
                if command_candidates:
                    next_accounting = next_accounting.settle(command, command_candidates)
            return next_accounting

        def candidates_for(sequence: int) -> tuple[PaperFillCandidate, ...]:
            candidates: list[PaperFillCandidate] = []
            command_ids: set[str] = set()
            for command in commands():
                order = self._require_order(command.client_order_id)
                residual = command.quantity - order.filled_quantity
                if residual <= 0:
                    continue
                matched = match_order(
                    command=replace(command, quantity=residual),
                    observation=observation,
                    policy=policy,
                    paper_event_sequence=sequence,
                ).candidates
                if matched:
                    command_ids.add(command.client_order_id)
                    candidates.extend(matched)
            ordered = sort_fill_candidates(tuple(candidates))
            if settled(ordered).margin_health < policy.minimum_margin_health:
                return ()
            changed_client_order_ids.update(command_ids)
            return ordered

        def settled_snapshot(_: int, candidates: tuple[PaperFillCandidate, ...]) -> PaperProductSnapshot:
            return self._margin_snapshot(observation.account_id, settled(candidates))

        def margin_evidence(_: int, candidates: tuple[PaperFillCandidate, ...]) -> IsolatedMarginProductEvidence:
            return settled(candidates).to_evidence(
                target=self._margin_target(observation.account_id), observed_at=observation.observed_at
            )

        result = self._store.apply_observation(
            observation=observation,
            candidate_factory=candidates_for,
            snapshot_factory=settled_snapshot,
            margin_evidence_factory=margin_evidence,
            allow_terminal_observation=True,
        )
        if result.disposition is not ObservationDisposition.ACCEPTED:
            return ()
        results = tuple(
            self._result_for_order(self._require_order(client_order_id))
            for client_order_id in sorted(changed_client_order_ids)
        )
        for operation_result in results:
            self._observe_direct(operation_result)
        return results

    def _advance_perpetual_market(self, observation: MarketObservation) -> tuple[GatewayOperationResult, ...]:
        """Apply explicit mark/funding facts and atomically force-close a maintenance breach."""
        if self._product() is not ProductType.USDT_PERPETUAL or observation.mark_price is None:
            raise ValueError("PaperGateway policy requires explicit perpetual mark observations")
        accounting = self._load_perpetual_snapshot(observation.account_id, observation.symbol)
        policy = self._require_policy()
        if accounting.liquidated:
            self._store.apply_observation(
                observation=observation,
                snapshot=self._perpetual_snapshot(observation.account_id, accounting),
                allow_terminal_observation=True,
            )
            return ()
        if observation.version <= accounting.observation_version:
            self._store.apply_observation(
                observation=observation,
                snapshot=self._perpetual_snapshot(observation.account_id, accounting),
                allow_terminal_observation=True,
            )
            return ()
        observed = accounting.observe(observation, policy=policy)

        def commands() -> tuple[ExecutionCommand, ...]:
            return self._store.list_open_commands(
                account_id=observation.account_id,
                product=ProductType.USDT_PERPETUAL,
                symbol=observation.symbol,
            )

        def projected(candidates: tuple[PaperFillCandidate, ...]) -> PaperPerpetualAccounting:
            next_accounting = observed
            by_command: dict[str, list[PaperFillCandidate]] = {}
            for candidate in candidates:
                by_command.setdefault(candidate.command_id, []).append(candidate)
            for command in commands():
                command_candidates = tuple(by_command.get(command.command_id, ()))
                if command_candidates:
                    next_accounting = next_accounting.settle(command, command_candidates, policy=policy)
            return next_accounting

        liquidation_candidates = []
        def liquidation(candidates: tuple[PaperFillCandidate, ...]):
            candidate = projected(candidates).liquidation_candidate(observation, policy=policy)
            liquidation_candidates[:] = [candidate]
            return candidate

        def final_accounting(candidates: tuple[PaperFillCandidate, ...]) -> PaperPerpetualAccounting:
            projected_accounting = projected(candidates)
            candidate = projected_accounting.liquidation_candidate(observation, policy=policy)
            return projected_accounting if candidate is None else projected_accounting.liquidate(candidate)

        def candidates_for(sequence: int) -> tuple[PaperFillCandidate, ...]:
            if observed.liquidation_candidate(observation, policy=policy) is not None:
                return ()
            candidates: list[PaperFillCandidate] = []
            for command in commands():
                order = self._require_order(command.client_order_id)
                residual = command.quantity - order.filled_quantity
                if residual <= 0:
                    continue
                matched = match_order(
                    command=replace(command, quantity=residual),
                    observation=observation,
                    policy=policy,
                    paper_event_sequence=sequence,
                ).candidates
                candidates.extend(matched)
            return sort_fill_candidates(tuple(candidates))

        def perpetual_snapshot(_: int, candidates: tuple[PaperFillCandidate, ...]) -> PaperProductSnapshot:
            return self._perpetual_snapshot(observation.account_id, final_accounting(candidates))

        def perpetual_evidence(_: int, candidates: tuple[PaperFillCandidate, ...]) -> UsdtPerpetualProductEvidence:
            return final_accounting(candidates).to_evidence(
                target=self.perpetual_target(observation.account_id),
                observed_at=observation.observed_at,
                mark_price=observation.mark_price,
                policy=policy,
            )

        result = self._store.apply_observation(
            observation=observation,
            candidate_factory=candidates_for,
            snapshot_factory=perpetual_snapshot,
            perpetual_evidence_factory=perpetual_evidence,
            liquidation_factory=lambda _, candidates: liquidation(candidates),
            allow_terminal_observation=True,
        )
        if result.disposition is not ObservationDisposition.ACCEPTED:
            return ()
        candidate = liquidation_candidates[0]
        if candidate is None:
            return ()
        origin = self._store.fetch_order_by_command_id(candidate.origin_command_id)
        if origin is None:
            raise _unavailable("perpetual liquidation origin order")
        operation_result = self._result_for_order(origin)
        self._observe_direct(operation_result)
        return (operation_result,)

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

    def read_operation(self, reference: GatewayOperationReference) -> PaperOperationBatch:
        """Resolve only committed Paper facts for a matching opaque operation reference."""
        if type(reference) is not GatewayOperationReference:
            raise TypeError("PaperGateway operation reads require a GatewayOperationReference")
        order = self._require_order(reference.client_order_id)
        if reference.operation_id != f"paper-order:{order.client_order_id}":
            raise _unavailable("matching committed paper operation")
        evidence = self._evidence_for_order(order)
        snapshot = self._store.load_snapshot(
            account_id=order.account_id,
            product=order.product,
            scope=order.symbol,
        )
        if snapshot is None:
            raise _unavailable("paper operation snapshot")
        return PaperOperationBatch(
            reference=reference,
            evidence=evidence,
            fills=self.list_fills(order.command_id),
            snapshots=(snapshot,),
            paper_fills=self._store.list_fills(order.command_id),
        )

    def _result_for_order(
        self, order: PaperOrder, *, evidence: GatewayEvidence | None = None
    ) -> GatewayOperationResult:
        if order.paper_event_sequence is None:
            raise _unavailable("committed paper operation")
        return GatewayOperationResult(
            evidence=self._evidence_for_order(order) if evidence is None else evidence,
            reference=GatewayOperationReference(
                operation_id=f"paper-order:{order.client_order_id}",
                client_order_id=order.client_order_id,
            ),
        )

    def _rejected_result(self, client_order_id: str) -> GatewayOperationResult:
        return GatewayOperationResult(
            evidence=self._rejected_evidence(client_order_id),
            reference=GatewayOperationReference(
                operation_id=f"paper-rejected:{client_order_id}",
                client_order_id=client_order_id,
            ),
        )

    def _observe_direct(self, result: GatewayOperationResult) -> None:
        if self._operation_observer is not None:
            self._operation_observer.observe_operation(result)

    def _snapshot(self, account_id: str, symbol: str, accounting: PaperSpotAccounting) -> PaperProductSnapshot:
        return PaperProductSnapshot(
            account_id=account_id,
            product=ProductType.SPOT.value,
            scope=symbol,
            schema_version=_SPOT_SNAPSHOT_SCHEMA,
            payload=accounting.to_snapshot_payload(),
        )

    def _margin_snapshot(self, account_id: str, accounting: PaperMarginAccounting) -> PaperProductSnapshot:
        return PaperProductSnapshot(
            account_id=account_id,
            product=ProductType.ISOLATED_MARGIN.value,
            scope=accounting.isolated_symbol,
            schema_version="paper-isolated-margin-snapshot-v1",
            payload=accounting.to_snapshot_payload(),
        )

    def _perpetual_snapshot(self, account_id: str, accounting: PaperPerpetualAccounting) -> PaperProductSnapshot:
        return PaperProductSnapshot(
            account_id=account_id,
            product=ProductType.USDT_PERPETUAL.value,
            scope=accounting.symbol,
            schema_version="paper-usdt-perpetual-snapshot-v1",
            payload=accounting.to_snapshot_payload(),
        )

    def _load_spot_snapshot(self, account_id: str, symbol: str = "BTCUSDT") -> PaperSpotAccounting:
        snapshot = self._store.load_snapshot(account_id=account_id, product=ProductType.SPOT.value, scope=symbol)
        if snapshot is None:
            raise _unavailable("paper Spot account snapshot")
        if snapshot.schema_version != _SPOT_SNAPSHOT_SCHEMA:
            raise ValueError("stored paper Spot snapshot schema is unsupported")
        return PaperSpotAccounting.from_snapshot_payload(snapshot.payload)

    def _load_margin_snapshot(self, account_id: str, isolated_symbol: str) -> PaperMarginAccounting:
        snapshot = self._store.load_snapshot(
            account_id=account_id,
            product=ProductType.ISOLATED_MARGIN.value,
            scope=isolated_symbol,
        )
        if snapshot is None:
            raise _unavailable("paper isolated-margin pair snapshot")
        if snapshot.schema_version != "paper-isolated-margin-snapshot-v1":
            raise ValueError("stored paper margin snapshot schema is unsupported")
        return PaperMarginAccounting.from_snapshot_payload(snapshot.payload)

    def _load_perpetual_snapshot(self, account_id: str, symbol: str) -> PaperPerpetualAccounting:
        snapshot = self._store.load_snapshot(
            account_id=account_id,
            product=ProductType.USDT_PERPETUAL.value,
            scope=symbol,
        )
        if snapshot is None:
            raise _unavailable("paper USDT perpetual symbol snapshot")
        if snapshot.schema_version != "paper-usdt-perpetual-snapshot-v1":
            raise ValueError("stored paper perpetual snapshot schema is unsupported")
        return PaperPerpetualAccounting.from_snapshot_payload(snapshot.payload)

    def load_perpetual_accounting(self, account_id: str, symbol: str) -> PaperPerpetualAccounting:
        """Return the independent, durable symbol state without ledger or submission authority."""
        return self._load_perpetual_snapshot(account_id, symbol)

    def _observed_at(self, account_id: str, symbol: str = "BTCUSDT") -> datetime:
        observation = self._store.load_latest_observation(
            account_id=account_id, product=self._product(), symbol=symbol
        )
        return _PAPER_EPOCH if observation is None else observation.observed_at

    def _any_observed_at(self) -> datetime:
        return _PAPER_EPOCH

    def _observed_at_from_provenance(self, provenance: Mapping[str, object]) -> datetime:
        observation = self._store.load_latest_observation(
            account_id="paper-account", product=self._product(), symbol="BTCUSDT"
        )
        return _PAPER_EPOCH if observation is None else observation.observed_at

    def _require_order(self, client_order_id: str) -> PaperOrder:
        order = self._store.fetch_order(client_order_id)
        if order is None:
            raise _unavailable("paper order")
        return order

    def _require_policy(self) -> PaperEconomicPolicy:
        if self._policy is None:
            raise _unavailable("Paper economic policy")
        return self._policy

    def _product(self) -> ProductType:
        return ProductType.SPOT if self._policy is None else self._policy.product

    @staticmethod
    def _margin_target(account_id: str) -> ExecutionTarget:
        return ExecutionTarget(
            "paper-margin-isolated-primary",
            Mode.PAPER,
            account_id,
            ProductType.ISOLATED_MARGIN,
        )

    @staticmethod
    def perpetual_target(account_id: str) -> ExecutionTarget:
        return ExecutionTarget(
            "paper-usdt-perpetual-primary",
            Mode.PAPER,
            account_id,
            ProductType.USDT_PERPETUAL,
        )

    def _assert_spot_submission(self, command: ExecutionCommand) -> None:
        if command.context.product is not ProductType.SPOT or type(command.context) is not SpotOrderContext:
            raise ValueError("PaperGateway only accepts Paper Spot submissions")
        if self._product() is not ProductType.SPOT:
            raise ValueError("PaperGateway policy is not Spot")

    def _require_product_target(self, target: ExecutionTarget) -> None:
        if (
            type(target) is not ExecutionTarget
            or target.mode is not Mode.PAPER
            or target.product is not self._product()
            or target.target_id
            != {
                ProductType.SPOT: "paper-spot-primary",
                ProductType.ISOLATED_MARGIN: "paper-margin-isolated-primary",
                ProductType.USDT_PERPETUAL: "paper-usdt-perpetual-primary",
            }.get(target.product)
        ):
            raise _unavailable("unsupported paper target")


def _unavailable(fact: str) -> GatewayUnavailableError:
    return GatewayUnavailableError(f"PaperGateway has no committed {fact} fact")
