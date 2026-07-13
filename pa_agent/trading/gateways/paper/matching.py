"""Pure deterministic Decimal depth allocation for explicit paper market observations."""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256

from pa_agent.trading.domain.errors import CanonicalInputError, ProductContextError
from pa_agent.trading.domain.models import ExecutionCommand, Mode, OrderType, Side
from pa_agent.trading.domain.paper import (
    DepthLevel,
    MarketObservation,
    ObservationDisposition,
    PaperEconomicPolicy,
    PaperFillCandidate,
    PaperFillProvenance,
    PaperMatchResult,
    assert_matching_scope,
    classify_observation,
)


def _require_event_sequence(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise CanonicalInputError("paper_event_sequence must be a positive integer")


def _matching_product(command: ExecutionCommand) -> object:
    """Keep product extraction local so matching never knows account semantics."""
    return command.context.product


def _crosses(command: ExecutionCommand, level: DepthLevel) -> bool:
    """Determine whether a level may trade without broadening order semantics."""
    if command.order_type is OrderType.MARKET:
        return True
    if command.price is None:
        raise CanonicalInputError("limit commands require an exact limit price")
    if command.side is Side.BUY:
        return level.price <= command.price
    return level.price >= command.price


def _ordered_levels(command: ExecutionCommand, observation: MarketObservation) -> tuple[DepthLevel, ...]:
    """Return explicit price-time deterministic traversal independent of input container order."""
    if command.side is Side.BUY:
        return tuple(
            sorted(
                observation.asks,
                key=lambda level: (level.price, observation.version),
            )
        )
    return tuple(
        sorted(
            observation.bids,
            key=lambda level: (-level.price, observation.version),
        )
    )


def _execution_price(*, raw_book_price: Decimal, side: Side, slippage_rate: Decimal) -> Decimal:
    """Apply the frozen directional slippage rate exactly once to raw book price."""
    if side is Side.BUY:
        return raw_book_price * (Decimal("1") + slippage_rate)
    return raw_book_price * (Decimal("1") - slippage_rate)


def _candidate_id(
    *, command_id: str, observation: MarketObservation, paper_event_sequence: int, ordinal: int
) -> str:
    """Derive a repeatable candidate identity from immutable matching inputs only."""
    material = "|".join(
        (
            command_id,
            observation.observation_id,
            str(observation.version),
            observation.digest,
            str(paper_event_sequence),
            str(ordinal),
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _candidate(
    *,
    command: ExecutionCommand,
    observation: MarketObservation,
    policy: PaperEconomicPolicy,
    paper_event_sequence: int,
    level: DepthLevel,
    quantity: Decimal,
    ordinal: int,
) -> PaperFillCandidate:
    """Freeze all economic inputs before returning a candidate to later accounting code."""
    final_execution_price = _execution_price(
        raw_book_price=level.price,
        side=command.side,
        slippage_rate=policy.slippage_rate,
    )
    fee_basis = quantity * final_execution_price
    provenance = PaperFillProvenance(
        observation_id=observation.observation_id,
        observation_version=observation.version,
        observation_digest=observation.digest,
        raw_book_price=level.price,
        slippage_rate=policy.slippage_rate,
        slippage_rule_version=policy.slippage_rule_version,
        slippage_adjusted_price=final_execution_price,
        final_execution_price=final_execution_price,
        fee_rate=policy.fee_rate,
        fee_rule_version=policy.fee_rule_version,
        fee_basis=fee_basis,
        fee=fee_basis * policy.fee_rate,
        product_policy_version=policy.policy_version,
    )
    return PaperFillCandidate(
        paper_fill_id=_candidate_id(
            command_id=command.command_id,
            observation=observation,
            paper_event_sequence=paper_event_sequence,
            ordinal=ordinal,
        ),
        command_id=command.command_id,
        quantity=quantity,
        paper_event_sequence=paper_event_sequence,
        provenance=provenance,
    )


def sort_fill_candidates(
    candidates: tuple[PaperFillCandidate, ...],
) -> tuple[PaperFillCandidate, ...]:
    """Order same-price fill work by observation version then persisted paper sequence."""
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.provenance.raw_book_price,
                candidate.provenance.observation_version,
                candidate.paper_event_sequence,
                candidate.paper_fill_id,
            ),
        )
    )


def match_order(
    *,
    command: ExecutionCommand,
    observation: MarketObservation,
    policy: PaperEconomicPolicy,
    paper_event_sequence: int,
    previous_observation: MarketObservation | None = None,
) -> PaperMatchResult:
    """Allocate one order against one explicit observation without side effects or time reads."""
    if type(command) is not ExecutionCommand:
        raise CanonicalInputError("command must be an ExecutionCommand")
    if command.mode is not Mode.PAPER:
        raise ProductContextError("paper matcher accepts only paper commands")
    if type(observation) is not MarketObservation or type(policy) is not PaperEconomicPolicy:
        raise CanonicalInputError("observation and policy must use canonical paper values")
    _require_event_sequence(paper_event_sequence)
    product = _matching_product(command)
    if type(product) is not type(observation.product):
        raise ProductContextError("command context must provide a canonical product")
    assert_matching_scope(
        account_id=command.account_id,
        product=product,
        symbol=command.symbol,
        observation=observation,
        policy=policy,
    )
    disposition = classify_observation(observation, previous_observation)
    if disposition is not ObservationDisposition.ACCEPTED:
        return PaperMatchResult(
            disposition=disposition,
            candidates=(),
            filled_quantity=Decimal("0"),
            remaining_quantity=command.quantity,
        )

    remaining_quantity = command.quantity
    candidates: list[PaperFillCandidate] = []
    for level in _ordered_levels(command, observation):
        if remaining_quantity == 0 or not _crosses(command, level):
            break
        quantity = min(remaining_quantity, level.quantity)
        candidates.append(
            _candidate(
                command=command,
                observation=observation,
                policy=policy,
                paper_event_sequence=paper_event_sequence,
                level=level,
                quantity=quantity,
                ordinal=len(candidates),
            )
        )
        remaining_quantity -= quantity

    return PaperMatchResult(
        disposition=disposition,
        candidates=tuple(candidates),
        filled_quantity=command.quantity - remaining_quantity,
        remaining_quantity=remaining_quantity,
    )
