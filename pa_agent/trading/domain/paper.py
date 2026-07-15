"""Immutable Decimal-only values for deterministic paper-market matching."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from pa_agent.trading.domain.errors import CanonicalInputError, ProductContextError
from pa_agent.trading.domain.models import ProductType, decimal_from_canonical, decimal_to_canonical

_MAX_BOOK_LEVELS = 1_000


class ObservationDisposition(StrEnum):
    """The pure version/digest classification of an explicit market fact."""

    ACCEPTED = "accepted"
    IDEMPOTENT = "idempotent"
    REJECTED_OUT_OF_ORDER = "rejected_out_of_order"
    REJECTED_CONFLICT = "rejected_conflict"


class PaperObservationError(CanonicalInputError):
    """Raised when an observation cannot be compared within one market scope."""


def _require_identifier(value: str, field_name: str) -> None:
    if type(value) is not str or not value:
        raise CanonicalInputError(f"{field_name} is required")


def _require_positive_integer(value: int, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise CanonicalInputError(f"{field_name} must be a positive integer")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalInputError(f"{field_name} must be timezone-aware")


def _decimal(instance: object, field_name: str) -> None:
    object.__setattr__(instance, field_name, decimal_from_canonical(getattr(instance, field_name)))


def _require_nonnegative(instance: object, field_name: str) -> None:
    if getattr(instance, field_name) < 0:
        raise CanonicalInputError(f"{field_name} must be non-negative")


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_to_canonical(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _canonicalize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_canonicalize(item) for item in value]
    return value


@dataclass(frozen=True)
class DepthLevel:
    """One strictly positive, exact price/quantity level in an explicit market book."""

    price: Decimal | str
    quantity: Decimal | str

    def __post_init__(self) -> None:
        _decimal(self, "price")
        _decimal(self, "quantity")
        if self.price <= 0 or self.quantity <= 0:
            raise CanonicalInputError("depth price and quantity must be positive")


@dataclass(frozen=True)
class MarketObservation:
    """A bounded, immutable market fact that is the only matching-time input."""

    observation_id: str
    account_id: str
    product: ProductType
    symbol: str
    version: int
    observed_at: datetime
    asks: tuple[DepthLevel, ...]
    bids: tuple[DepthLevel, ...]
    mark_price: Decimal | str | None = None
    funding_rate: Decimal | str = Decimal("0")

    def __post_init__(self) -> None:
        for field_name in ("observation_id", "account_id", "symbol"):
            _require_identifier(getattr(self, field_name), field_name)
        if type(self.product) is not ProductType:
            raise CanonicalInputError("product must be a ProductType instance")
        _require_positive_integer(self.version, "version")
        _require_aware(self.observed_at, "observed_at")
        for side_name, reverse in (("asks", False), ("bids", True)):
            levels = getattr(self, side_name)
            if type(levels) is not tuple or not levels or len(levels) > _MAX_BOOK_LEVELS:
                raise CanonicalInputError(f"{side_name} must be a bounded nonempty tuple")
            if any(type(level) is not DepthLevel for level in levels):
                raise CanonicalInputError(f"{side_name} must contain only DepthLevel values")
            prices = tuple(level.price for level in levels)
            expected = tuple(sorted(prices, reverse=reverse))
            if prices != expected:
                raise CanonicalInputError(f"{side_name} must use canonical price order")
        if self.mark_price is not None:
            _decimal(self, "mark_price")
            if self.mark_price <= 0:
                raise CanonicalInputError("mark_price must be positive")
        _decimal(self, "funding_rate")

    @property
    def scope(self) -> tuple[str, ProductType, str]:
        """Return the one account/product/symbol monotonic-version scope."""
        return (self.account_id, self.product, self.symbol)

    @property
    def digest(self) -> str:
        """Hash the complete canonical external fact, including immutable evidence time."""
        payload = json.dumps(
            self.to_canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def to_canonical_dict(self) -> dict[str, Any]:
        """Serialize without lossy Decimal or timezone conversion."""
        return _canonicalize(self)


@dataclass(frozen=True)
class PaperEconomicPolicy:
    """Versioned Decimal fee and slippage inputs scoped to one product."""

    product: ProductType
    policy_version: str
    fee_rate: Decimal | str
    fee_rule_version: str
    slippage_rate: Decimal | str
    slippage_rule_version: str
    interest_rate: Decimal | str = Decimal("0")
    interest_rule_version: str = "interest-v1"
    minimum_margin_health: Decimal | str = Decimal("1.25")
    maximum_leverage: Decimal | str = Decimal("3")
    maintenance_margin_rate: Decimal | str = Decimal("0.05")
    maintenance_rule_version: str = "maintenance-v1"
    funding_rule_version: str = "funding-v1"
    liquidation_price_adjustment: Decimal | str = Decimal("0")
    liquidation_rule_version: str = "liquidation-v1"
    liquidation_fee_rate: Decimal | str = Decimal("0")
    liquidation_fee_rule_version: str = "liquidation-fee-v1"

    def __post_init__(self) -> None:
        if type(self.product) is not ProductType:
            raise CanonicalInputError("product must be a ProductType instance")
        for field_name in (
            "policy_version",
            "fee_rule_version",
            "slippage_rule_version",
            "interest_rule_version",
            "maintenance_rule_version",
            "funding_rule_version",
            "liquidation_rule_version",
            "liquidation_fee_rule_version",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        for field_name in (
            "fee_rate",
            "slippage_rate",
            "interest_rate",
            "maintenance_margin_rate",
            "liquidation_price_adjustment",
            "liquidation_fee_rate",
        ):
            _decimal(self, field_name)
            _require_nonnegative(self, field_name)
        _decimal(self, "maximum_leverage")
        _decimal(self, "minimum_margin_health")
        if self.maximum_leverage <= 0 or self.minimum_margin_health <= 0:
            raise CanonicalInputError("paper policy leverage and margin thresholds must be positive")
        if any(
            rate >= Decimal("1")
            for rate in (
                self.slippage_rate,
                self.maintenance_margin_rate,
                self.liquidation_price_adjustment,
                self.liquidation_fee_rate,
            )
        ):
            raise CanonicalInputError("paper policy rates must remain below one")


@dataclass(frozen=True)
class PaperFillProvenance:
    """All immutable observation and policy inputs needed to reproduce paper economics."""

    observation_id: str
    observation_version: int
    observation_digest: str
    raw_book_price: Decimal | str
    slippage_rate: Decimal | str
    slippage_rule_version: str
    slippage_adjusted_price: Decimal | str
    final_execution_price: Decimal | str
    fee_rate: Decimal | str
    fee_rule_version: str
    fee_basis: Decimal | str
    fee: Decimal | str
    product_policy_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "observation_digest",
            "slippage_rule_version",
            "fee_rule_version",
            "product_policy_version",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive_integer(self.observation_version, "observation_version")
        for field_name in (
            "raw_book_price",
            "slippage_rate",
            "slippage_adjusted_price",
            "final_execution_price",
            "fee_rate",
            "fee_basis",
            "fee",
        ):
            _decimal(self, field_name)
            _require_nonnegative(self, field_name)
        if self.raw_book_price <= 0 or self.slippage_adjusted_price <= 0 or self.final_execution_price <= 0:
            raise CanonicalInputError("execution prices must be positive")
        if self.final_execution_price != self.slippage_adjusted_price:
            raise CanonicalInputError("final execution price must preserve slippage-adjusted price")

    def to_canonical_dict(self) -> dict[str, Any]:
        """Return stable JSON-compatible provenance for future durable projection."""
        return _canonicalize(self)


@dataclass(frozen=True)
class PaperFillCandidate:
    """A pure matcher output with no ledger, account, gateway, or dispatch authority."""

    paper_fill_id: str
    command_id: str
    quantity: Decimal | str
    paper_event_sequence: int
    provenance: PaperFillProvenance

    def __post_init__(self) -> None:
        _require_identifier(self.paper_fill_id, "paper_fill_id")
        _require_identifier(self.command_id, "command_id")
        _decimal(self, "quantity")
        if self.quantity <= 0:
            raise CanonicalInputError("quantity must be positive")
        _require_positive_integer(self.paper_event_sequence, "paper_event_sequence")
        if type(self.provenance) is not PaperFillProvenance:
            raise CanonicalInputError("provenance must be a PaperFillProvenance")

    def to_canonical_dict(self) -> dict[str, Any]:
        """Return all candidate economics in canonical fixed-point form."""
        return _canonicalize(self)


@dataclass(frozen=True)
class PaperLiquidationCandidate:
    """Immutable forced-close fact that is intentionally separate from an order fill quantity."""

    paper_fill_id: str
    account_id: str
    symbol: str
    origin_command_id: str
    quantity: Decimal | str
    provenance: Mapping[str, object]

    def __post_init__(self) -> None:
        for name in ("paper_fill_id", "account_id", "symbol", "origin_command_id"):
            _require_identifier(getattr(self, name), name)
        _decimal(self, "quantity")
        if self.quantity <= 0:
            raise CanonicalInputError("liquidation quantity must be positive")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))
        _canonical_json = json.dumps(dict(self.provenance), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if not _canonical_json:
            raise CanonicalInputError("liquidation provenance is required")


@dataclass(frozen=True)
class PaperMatchResult:
    """The accepted/rejected observation classification and immutable allocation outcome."""

    disposition: ObservationDisposition
    candidates: tuple[PaperFillCandidate, ...]
    filled_quantity: Decimal | str
    remaining_quantity: Decimal | str

    def __post_init__(self) -> None:
        if type(self.disposition) is not ObservationDisposition:
            raise CanonicalInputError("disposition must be an ObservationDisposition")
        if type(self.candidates) is not tuple or any(
            type(candidate) is not PaperFillCandidate for candidate in self.candidates
        ):
            raise CanonicalInputError("candidates must be an immutable candidate tuple")
        for field_name in ("filled_quantity", "remaining_quantity"):
            _decimal(self, field_name)
            _require_nonnegative(self, field_name)


def classify_observation(
    observation: MarketObservation, previous_observation: MarketObservation | None
) -> ObservationDisposition:
    """Classify monotonic market evidence without retaining mutable cursor state."""
    if previous_observation is None:
        return ObservationDisposition.ACCEPTED
    if observation.scope != previous_observation.scope:
        raise PaperObservationError("observation scope differs from prior observation")
    if observation.version > previous_observation.version:
        return ObservationDisposition.ACCEPTED
    if observation.version < previous_observation.version:
        return ObservationDisposition.REJECTED_OUT_OF_ORDER
    if observation.observation_id == previous_observation.observation_id and observation.digest == previous_observation.digest:
        return ObservationDisposition.IDEMPOTENT
    return ObservationDisposition.REJECTED_CONFLICT


def assert_matching_scope(
    *, account_id: str, product: ProductType, symbol: str, observation: MarketObservation, policy: PaperEconomicPolicy
) -> None:
    """Reject cross-account, product, or instrument mixing before any allocation occurs."""
    if (account_id, product, symbol) != observation.scope:
        raise ProductContextError("command must match the observation account/product/symbol scope")
    if policy.product is not product:
        raise ProductContextError("paper policy must match the command product")
