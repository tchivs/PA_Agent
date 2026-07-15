"""Contracts for non-secret workspace configuration and immutable readiness."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest
from pydantic import ValidationError

from pa_agent.config.settings import (
    TradingSettings,
    WorkspaceRiskLimits,
    WorkspaceTarget,
)
from pa_agent.trading.application.workspace_projection import (
    AppliedWorkspaceConfig,
    ReadinessProjection,
    SectionIssue,
    WorkspaceConfigDraft,
    validate_workspace_config,
)


BASELINE_LIMITS = WorkspaceRiskLimits(
    maximum_order_notional=Decimal("1000"),
    maximum_total_exposure=Decimal("1000"),
    maximum_open_orders=3,
    maximum_utc_day_realized_loss=Decimal("100"),
    maximum_utc_day_drawdown=Decimal("0.10"),
)


def _paper_draft(**overrides: object) -> WorkspaceConfigDraft:
    values: dict[str, object] = {
        "target": WorkspaceTarget.PAPER_SPOT,
        "account_id": "paper-spot-primary",
        "product": "spot",
        "symbol_mapping": {"BTCUSDT": "BTCUSDT"},
        "paper_balances": {"USDT": Decimal("1000")},
        "risk_limits": BASELINE_LIMITS,
        "credential_reference": None,
        "revision": 1,
    }
    values.update(overrides)
    return WorkspaceConfigDraft(**values)


def test_paper_is_the_only_ready_default_and_testnet_live_are_not_saveable() -> None:
    """Visible non-Paper choices cannot become an applied approval target."""
    settings = TradingSettings()

    assert settings.workspace.target is WorkspaceTarget.PAPER_SPOT
    assert settings.workspace.mode == "paper"

    testnet = _paper_draft(target=WorkspaceTarget.BINANCE_TESTNET_SPOT)
    live = _paper_draft(target=WorkspaceTarget.BINANCE_LIVE_SPOT)

    testnet_readiness = validate_workspace_config(
        testnet, baseline_limits=BASELINE_LIMITS, active_target_digest="testnet"
    )
    live_readiness = validate_workspace_config(
        live, baseline_limits=BASELINE_LIMITS, active_target_digest="live"
    )

    assert testnet_readiness.ready is False
    assert any(issue.code == "TARGET_UNAVAILABLE" for issue in testnet_readiness.issues)
    assert live_readiness.ready is False
    assert any(issue.code == "TARGET_DISABLED" for issue in live_readiness.issues)
    assert testnet_readiness.applied_config is None
    assert live_readiness.applied_config is None


def test_draft_stays_distinct_from_applied_until_explicit_validation_succeeds() -> None:
    """Changing target/product/account invalidates readiness without mutating the snapshot."""
    applied = AppliedWorkspaceConfig.from_validated_draft(
        _paper_draft(),
        target_digest="paper-v1",
    )
    changed_draft = _paper_draft(account_id="paper-spot-secondary", revision=2)

    readiness = validate_workspace_config(
        changed_draft,
        baseline_limits=BASELINE_LIMITS,
        active_target_digest="paper-v2",
        applied_config=applied,
    )

    assert readiness.ready is False
    assert readiness.applied_config is applied
    assert readiness.draft_revision == 2
    assert any(issue.section == "account" for issue in readiness.issues)
    with pytest.raises(FrozenInstanceError):
        applied.target_digest = "forged"  # type: ignore[misc]


def test_settings_reject_unknown_and_secret_shaped_values_and_keep_credential_opaque() -> None:
    """Generic settings accept only the opaque credential reference metadata."""
    with pytest.raises(ValidationError):
        TradingSettings.model_validate({"api_key": "secret"})
    with pytest.raises(ValidationError):
        TradingSettings.model_validate({"workspace": {"endpoint_secret": "secret"}})
    with pytest.raises(ValidationError):
        TradingSettings.model_validate({"workspace": {"password": "secret"}})

    opaque = TradingSettings.model_validate(
        {
            "workspace": {
                "credential_reference": {"reference_id": "credential:paper-spot"},
            }
        }
    )
    assert opaque.workspace.credential_reference is not None
    assert opaque.workspace.credential_reference.reference_id == "credential:paper-spot"
    assert "secret" not in opaque.model_dump_json()


def test_only_tightening_limits_accept_equal_or_stricter_and_reject_each_relaxation() -> None:
    """Risk limits are application-validated before they can affect readiness."""
    tightened = WorkspaceRiskLimits(
        maximum_order_notional=Decimal("900"),
        maximum_total_exposure=Decimal("800"),
        maximum_open_orders=2,
        maximum_utc_day_realized_loss=Decimal("90"),
        maximum_utc_day_drawdown=Decimal("0.09"),
    )
    accepted = validate_workspace_config(
        _paper_draft(risk_limits=tightened),
        baseline_limits=BASELINE_LIMITS,
        active_target_digest="paper-v1",
    )

    assert accepted.ready is True
    assert accepted.applied_config is None
    assert accepted.issues == ()

    relaxations = (
        {"maximum_order_notional": Decimal("1001")},
        {"maximum_total_exposure": Decimal("1001")},
        {"maximum_open_orders": 4},
        {"maximum_utc_day_realized_loss": Decimal("101")},
        {"maximum_utc_day_drawdown": Decimal("0.11")},
    )
    for relaxation in relaxations:
        candidate = WorkspaceRiskLimits.model_validate(
            {**BASELINE_LIMITS.model_dump(), **relaxation}
        )
        readiness = validate_workspace_config(
            _paper_draft(risk_limits=candidate),
            baseline_limits=BASELINE_LIMITS,
            active_target_digest="paper-v1",
        )
        assert readiness.ready is False
        assert any(
            issue.section == "risk_limits" and issue.severity == "blocking"
            for issue in readiness.issues
        )


def test_readiness_uses_section_keyed_safe_issues_and_exposes_no_authority() -> None:
    """The central summary reports application facts without risk or submit capability."""
    readiness = ReadinessProjection(
        ready=False,
        draft_revision=1,
        active_target_digest="paper-v1",
        applied_config=None,
        issues=(
            SectionIssue(
                section="reconciliation",
                severity="blocking",
                code="STALE_RECONCILIATION",
                safe_message="账户数据已过期",
                next_action="refresh_account",
            ),
        ),
    )

    assert readiness.issues[0].section == "reconciliation"
    assert readiness.issues[0].severity == "blocking"
    assert not any(
        forbidden in attribute
        for attribute in vars(ReadinessProjection)
        for forbidden in ("submit", "permit", "lease", "gateway", "risk_engine")
    )
    with pytest.raises(FrozenInstanceError):
        readiness.ready = True  # type: ignore[misc]
