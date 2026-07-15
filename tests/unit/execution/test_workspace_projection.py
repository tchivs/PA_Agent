"""Contracts for immutable, product-scoped workspace account projections."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from pa_agent.trading.application.workspace_projection import (
    CrossProductSummary,
    FreshnessStatus,
    ProductWorkspaceSection,
    WorkspaceProjectionV1,
)
from pa_agent.trading.domain.models import ProductType


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def _section(
    product: ProductType,
    *,
    freshness: FreshnessStatus = FreshnessStatus.FRESH,
    capability_available: bool = True,
    unavailable_reason: str | None = None,
) -> ProductWorkspaceSection:
    content = (f"{product.value}-balance",) if capability_available else ()
    return ProductWorkspaceSection(
        product=product,
        capability_available=capability_available,
        unavailable_reason=unavailable_reason,
        balances=content,
        positions=() if not capability_available else (f"{product.value}-position",),
        open_orders=() if not capability_available else (f"{product.value}-order",),
        fills=() if not capability_available else (f"{product.value}-fill",),
        source="paper-store",
        last_successful_reconciled_at=NOW,
        freshness=freshness,
        safe_errors=(),
    )


def _projection(*sections: ProductWorkspaceSection) -> WorkspaceProjectionV1:
    return WorkspaceProjectionV1(
        target_digest="paper-spot-primary:digest",
        connection_state="connected",
        reconciliation_state="reconciled",
        configuration_state="applied",
        latch_state="READY",
        sections=sections,
        summary=CrossProductSummary.from_sections(sections),
    )


def test_workspace_projection_and_sections_are_frozen_and_target_product_scoped() -> None:
    """Account facts retain product identity and cannot be retargeted in place."""
    spot = _section(ProductType.SPOT)
    margin = _section(ProductType.ISOLATED_MARGIN)
    perpetual = _section(ProductType.USDT_PERPETUAL)
    projection = _projection(spot, margin, perpetual)

    assert projection.target_digest == "paper-spot-primary:digest"
    assert tuple(section.product for section in projection.sections) == (
        ProductType.SPOT,
        ProductType.ISOLATED_MARGIN,
        ProductType.USDT_PERPETUAL,
    )
    assert projection.section_for(ProductType.SPOT) is spot
    assert projection.section_for(ProductType.ISOLATED_MARGIN) is margin
    assert projection.section_for(ProductType.USDT_PERPETUAL) is perpetual
    assert projection.section_for(ProductType.SPOT).balances == ("spot-balance",)
    assert projection.section_for(ProductType.ISOLATED_MARGIN).balances == (
        "isolated_margin-balance",
    )
    assert projection.section_for(ProductType.USDT_PERPETUAL).balances == (
        "usdt_perpetual-balance",
    )

    with pytest.raises(FrozenInstanceError):
        projection.target_digest = "forged"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        spot.freshness = FreshnessStatus.STALE  # type: ignore[misc]


def test_product_freshness_is_independent_and_stale_content_remains_readable() -> None:
    """A stale or failed product never becomes a synthetic zero-balance section."""
    fresh_spot = _section(ProductType.SPOT, freshness=FreshnessStatus.FRESH)
    stale_margin = _section(ProductType.ISOLATED_MARGIN, freshness=FreshnessStatus.STALE)
    failed_perpetual = _section(
        ProductType.USDT_PERPETUAL,
        freshness=FreshnessStatus.REFRESH_FAILED,
    )
    never_reconciled = _section(
        ProductType.ISOLATED_MARGIN,
        freshness=FreshnessStatus.NEVER_RECONCILED,
    )

    projection = _projection(fresh_spot, stale_margin, failed_perpetual)

    assert projection.section_for(ProductType.SPOT).freshness is FreshnessStatus.FRESH
    assert projection.section_for(ProductType.ISOLATED_MARGIN).freshness is FreshnessStatus.STALE
    assert projection.section_for(ProductType.ISOLATED_MARGIN).balances == (
        "isolated_margin-balance",
    )
    assert projection.section_for(ProductType.USDT_PERPETUAL).freshness is FreshnessStatus.REFRESH_FAILED
    assert never_reconciled.freshness is FreshnessStatus.NEVER_RECONCILED
    assert never_reconciled.last_successful_reconciled_at is None


def test_unavailable_capability_is_explicit_and_never_flattened_to_zero_account_data() -> None:
    """Unavailable products have an explanation rather than a misleading empty account."""
    unavailable = _section(
        ProductType.USDT_PERPETUAL,
        capability_available=False,
        unavailable_reason="当前 Paper capability 不支持 USDT 永续",
    )

    assert unavailable.capability_available is False
    assert unavailable.unavailable_reason == "当前 Paper capability 不支持 USDT 永续"
    assert unavailable.balances == ()
    assert unavailable.positions == ()
    assert unavailable.open_orders == ()
    assert unavailable.fills == ()


def test_cross_product_summary_is_display_only_and_carries_no_approval_authority() -> None:
    """Orientation totals must never become a risk, permit, lease, or submit surface."""
    projection = _projection(
        _section(ProductType.SPOT),
        _section(ProductType.ISOLATED_MARGIN),
        _section(ProductType.USDT_PERPETUAL),
    )

    summary = projection.summary
    assert summary.product_account_counts == {
        "spot": 1,
        "isolated_margin": 1,
        "usdt_perpetual": 1,
    }
    assert summary.item_counts == {
        "balances": 3,
        "positions": 3,
        "open_orders": 3,
        "fills": 3,
    }
    assert summary.last_successful_reconciled_range == (NOW, NOW)
    assert summary.display_notice == "此概览不计算风险，也不决定是否可审批。"
    assert not any(
        forbidden in attribute
        for attribute in vars(CrossProductSummary)
        for forbidden in ("risk", "eligibility", "permit", "lease", "submit", "gateway")
    )
    assert not any(
        forbidden in attribute
        for attribute in vars(WorkspaceProjectionV1)
        for forbidden in ("permit", "lease", "submit", "gateway", "paper_store", "ledger")
    )
