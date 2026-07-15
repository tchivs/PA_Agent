"""Immutable application contracts for the non-secret trading workspace."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Callable, Literal, Mapping

from pa_agent.config.settings import (
    WorkspaceCredentialReference,
    WorkspaceRiskLimits,
    WorkspaceTarget,
)
from pa_agent.trading.domain.approval import KillSwitchStatus
from pa_agent.trading.domain.models import ProductType
from pa_agent.trading.gateways.paper.store import PaperWorkspaceProductFacts

IssueSeverity = Literal["blocking", "warning"]
WorkspaceProduct = Literal["spot", "isolated_margin", "usdt_perpetual"]


@dataclass(frozen=True, slots=True)
class WorkspaceConfigDraft:
    """An operator's unsaved, typed workspace edit with no execution authority."""

    target: WorkspaceTarget
    account_id: str
    product: WorkspaceProduct
    symbol_mapping: dict[str, str]
    paper_balances: dict[str, Decimal]
    risk_limits: WorkspaceRiskLimits
    credential_reference: WorkspaceCredentialReference | None
    revision: int

    def __post_init__(self) -> None:
        if not self.account_id or self.revision < 1:
            raise ValueError("workspace drafts require an account and positive revision")
        if self.product not in {"spot", "isolated_margin", "usdt_perpetual"}:
            raise ValueError("workspace drafts require a supported product")
        if any(not symbol or not mapped for symbol, mapped in self.symbol_mapping.items()):
            raise ValueError("symbol mappings require non-empty symbols")
        if any(value < 0 for value in self.paper_balances.values()):
            raise ValueError("Paper balances must not be negative")


@dataclass(frozen=True, slots=True)
class AppliedWorkspaceConfig:
    """A validated Paper snapshot; creating it never persists or grants approval authority."""

    target: WorkspaceTarget
    account_id: str
    product: WorkspaceProduct
    symbol_mapping: dict[str, str]
    paper_balances: dict[str, Decimal]
    risk_limits: WorkspaceRiskLimits
    credential_reference: WorkspaceCredentialReference | None
    draft_revision: int
    target_digest: str

    @classmethod
    def from_validated_draft(
        cls, draft: WorkspaceConfigDraft, *, target_digest: str
    ) -> AppliedWorkspaceConfig:
        if type(draft) is not WorkspaceConfigDraft or not target_digest:
            raise ValueError("applied workspace configuration requires a validated typed draft")
        if draft.target is not WorkspaceTarget.PAPER_SPOT:
            raise ValueError("only the Paper target can become an applied configuration")
        return cls(
            target=draft.target,
            account_id=draft.account_id,
            product=draft.product,
            symbol_mapping=dict(draft.symbol_mapping),
            paper_balances=dict(draft.paper_balances),
            risk_limits=draft.risk_limits,
            credential_reference=draft.credential_reference,
            draft_revision=draft.revision,
            target_digest=target_digest,
        )


@dataclass(frozen=True, slots=True)
class SectionIssue:
    """A controlled readiness result associated with one configuration section."""

    section: str
    severity: IssueSeverity
    code: str
    safe_message: str
    next_action: str

    def __post_init__(self) -> None:
        if (
            not self.section
            or self.severity not in {"blocking", "warning"}
            or not self.code
            or not self.safe_message
            or not self.next_action
        ):
            raise ValueError("workspace issues require complete safe section metadata")


@dataclass(frozen=True, slots=True)
class ReadinessProjection:
    """The single global configuration-readiness result with no risk or submit capability."""

    ready: bool
    draft_revision: int
    active_target_digest: str
    applied_config: AppliedWorkspaceConfig | None
    issues: tuple[SectionIssue, ...]

    def __post_init__(self) -> None:
        if self.draft_revision < 1 or not self.active_target_digest:
            raise ValueError("readiness requires a draft revision and active target digest")
        if any(type(issue) is not SectionIssue for issue in self.issues):
            raise TypeError("readiness issues must be typed section issues")
        if self.ready and any(issue.severity == "blocking" for issue in self.issues):
            raise ValueError("blocking issues cannot be ready")


def _risk_relaxation_fields(
    candidate: WorkspaceRiskLimits, baseline: WorkspaceRiskLimits
) -> tuple[str, ...]:
    fields = (
        "maximum_order_notional",
        "maximum_total_exposure",
        "maximum_open_orders",
        "maximum_utc_day_realized_loss",
        "maximum_utc_day_drawdown",
    )
    return tuple(name for name in fields if getattr(candidate, name) > getattr(baseline, name))


def _draft_matches_applied(
    draft: WorkspaceConfigDraft, applied: AppliedWorkspaceConfig
) -> bool:
    return (
        draft.target == applied.target
        and draft.account_id == applied.account_id
        and draft.product == applied.product
        and draft.symbol_mapping == applied.symbol_mapping
        and draft.paper_balances == applied.paper_balances
        and draft.risk_limits == applied.risk_limits
        and draft.credential_reference == applied.credential_reference
    )


def validate_workspace_config(
    draft: WorkspaceConfigDraft,
    *,
    baseline_limits: WorkspaceRiskLimits,
    active_target_digest: str,
    applied_config: AppliedWorkspaceConfig | None = None,
    prerequisite_issues: tuple[SectionIssue, ...] = (),
) -> ReadinessProjection:
    """Validate a draft without persisting it or replacing the applied snapshot."""
    if type(draft) is not WorkspaceConfigDraft or type(baseline_limits) is not WorkspaceRiskLimits:
        raise TypeError("workspace validation requires typed draft and baseline limits")
    if not active_target_digest:
        raise ValueError("workspace validation requires an active target digest")
    if applied_config is not None and type(applied_config) is not AppliedWorkspaceConfig:
        raise TypeError("applied configuration must be a typed snapshot")
    if any(type(issue) is not SectionIssue for issue in prerequisite_issues):
        raise TypeError("prerequisites must be typed section issues")

    issues: list[SectionIssue] = list(prerequisite_issues)
    if draft.target is WorkspaceTarget.BINANCE_TESTNET_SPOT:
        issues.append(
            SectionIssue(
                section="target",
                severity="blocking",
                code="TARGET_UNAVAILABLE",
                safe_message="Testnet 当前不可用，不能进入审批流程。",
                next_action="select_paper_target",
            )
        )
    elif draft.target is WorkspaceTarget.BINANCE_LIVE_SPOT:
        issues.append(
            SectionIssue(
                section="target",
                severity="blocking",
                code="TARGET_DISABLED",
                safe_message="Live 已禁用，不能进入审批流程。",
                next_action="select_paper_target",
            )
        )

    for field_name in _risk_relaxation_fields(draft.risk_limits, baseline_limits):
        issues.append(
            SectionIssue(
                section="risk_limits",
                severity="blocking",
                code=f"RISK_LIMIT_RELAXED_{field_name.upper()}",
                safe_message="本地风险限额不能放宽服务基线。",
                next_action="tighten_risk_limit",
            )
        )

    if applied_config is not None:
        if applied_config.target_digest != active_target_digest:
            issues.append(
                SectionIssue(
                    section="target",
                    severity="blocking",
                    code="TARGET_DIGEST_STALE",
                    safe_message="目标已变化，当前已应用配置需要重新验证。",
                    next_action="save_and_validate",
                )
            )
        if not _draft_matches_applied(draft, applied_config):
            changed_section = (
                "account"
                if draft.account_id != applied_config.account_id
                else "product"
                if draft.product != applied_config.product
                else "target"
            )
            issues.append(
                SectionIssue(
                    section=changed_section,
                    severity="blocking",
                    code="UNSAVED_DRAFT",
                    safe_message="草稿未保存，尚未应用，当前配置不可进入审批流程。",
                    next_action="save_and_validate",
                )
            )

    return ReadinessProjection(
        ready=not any(issue.severity == "blocking" for issue in issues),
        draft_revision=draft.revision,
        active_target_digest=active_target_digest,
        applied_config=applied_config,
        issues=tuple(issues),
    )


class WorkspaceConfigurationFacade:
    """Application-owned validation façade with no persistence or approval operation."""

    def __init__(self, *, baseline_limits: WorkspaceRiskLimits) -> None:
        self._baseline_limits = baseline_limits

    def validate(
        self,
        draft: WorkspaceConfigDraft,
        *,
        active_target_digest: str,
        applied_config: AppliedWorkspaceConfig | None = None,
        prerequisite_issues: tuple[SectionIssue, ...] = (),
    ) -> ReadinessProjection:
        return validate_workspace_config(
            draft,
            baseline_limits=self._baseline_limits,
            active_target_digest=active_target_digest,
            applied_config=applied_config,
            prerequisite_issues=prerequisite_issues,
        )


class FreshnessStatus(StrEnum):
    """Independent display state for already persisted product facts."""

    FRESH = "fresh"
    STALE = "stale"
    REFRESHING = "refreshing"
    REFRESH_FAILED = "refresh-failed"
    NEVER_RECONCILED = "never-reconciled"

    @property
    def is_viewable(self) -> bool:
        """Every product section remains visible, including unavailable products."""
        return True


@dataclass(frozen=True, slots=True)
class SafeWorkspaceError:
    """Controlled operator-facing failure without gateway or payload details."""

    code: str
    message: str
    next_action: str

    def __post_init__(self) -> None:
        if not all((self.code, self.message, self.next_action)):
            raise ValueError("safe workspace errors require complete operator guidance")


@dataclass(frozen=True, slots=True)
class ProductCapability:
    """Read-only availability state for exactly one configured Paper product."""

    available: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.available and not self.reason:
            raise ValueError("unavailable product capabilities require a safe reason")
        if self.available and self.reason is not None:
            raise ValueError("available product capabilities cannot carry an unavailable reason")


@dataclass(frozen=True, slots=True)
class ReconciliationMetadata:
    """Persisted source and last successful reconciliation metadata for one product."""

    source: str
    last_successful_at: datetime | None

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("reconciliation metadata requires a source")
        if self.last_successful_at is not None and self.last_successful_at.tzinfo is None:
            raise ValueError("reconciliation time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ProductWorkspaceSection:
    """Immutable facts for one product, never a risk or approval decision."""

    product: ProductType
    capability_available: bool
    unavailable_reason: str | None
    balances: tuple[object, ...]
    positions: tuple[object, ...]
    open_orders: tuple[object, ...]
    fills: tuple[object, ...]
    source: str
    last_successful_reconciled_at: datetime | None
    freshness: FreshnessStatus
    safe_errors: tuple[SafeWorkspaceError, ...]

    def __post_init__(self) -> None:
        if type(self.product) is not ProductType or not self.source:
            raise ValueError("workspace sections require a product and source")
        if self.last_successful_reconciled_at is not None and self.last_successful_reconciled_at.tzinfo is None:
            raise ValueError("workspace section reconciliation time must be timezone-aware")
        if not self.capability_available and not self.unavailable_reason:
            raise ValueError("unavailable workspace products require a safe reason")
        if self.capability_available and self.unavailable_reason is not None:
            raise ValueError("available workspace products cannot carry an unavailable reason")
        if type(self.freshness) is not FreshnessStatus:
            raise TypeError("workspace freshness must be a known status")
        if any(type(error) is not SafeWorkspaceError for error in self.safe_errors):
            raise TypeError("workspace sections require controlled errors")
        if self.freshness is FreshnessStatus.NEVER_RECONCILED:
            object.__setattr__(self, "last_successful_reconciled_at", None)

    @property
    def capability(self) -> ProductCapability:
        return ProductCapability(self.capability_available, self.unavailable_reason)

    @property
    def reconciliation(self) -> ReconciliationMetadata:
        return ReconciliationMetadata(self.source, self.last_successful_reconciled_at)

    @property
    def orders(self) -> tuple[object, ...]:
        """Read-only open-order table compatibility name."""
        return self.open_orders


@dataclass(frozen=True, slots=True)
class CrossProductSummary:
    """Display-only totals and time range; it cannot decide risk or eligibility."""

    product_account_counts: Mapping[str, int]
    item_counts: Mapping[str, int]
    last_successful_reconciled_range: tuple[datetime, datetime] | None
    display_notice: str = "此概览不计算风险，也不决定是否可审批。"

    def __post_init__(self) -> None:
        object.__setattr__(self, "product_account_counts", MappingProxyType(dict(self.product_account_counts)))
        object.__setattr__(self, "item_counts", MappingProxyType(dict(self.item_counts)))
        if not self.display_notice:
            raise ValueError("cross-product summaries require their display-only notice")

    @classmethod
    def from_sections(cls, sections: tuple[ProductWorkspaceSection, ...]) -> CrossProductSummary:
        product_counts = {section.product.value: int(section.capability_available) for section in sections}
        item_counts = {
            "balances": sum(len(section.balances) for section in sections),
            "positions": sum(len(section.positions) for section in sections),
            "open_orders": sum(len(section.open_orders) for section in sections),
            "fills": sum(len(section.fills) for section in sections),
        }
        reconciled = tuple(
            section.last_successful_reconciled_at
            for section in sections
            if section.last_successful_reconciled_at is not None
        )
        time_range = None if not reconciled else (min(reconciled), max(reconciled))
        return cls(product_counts, item_counts, time_range)


@dataclass(frozen=True, slots=True)
class SafeCancellationRequest:
    """Non-terminal durable cancellation evidence suitable for display."""

    work_id: str
    status: str
    is_terminal: bool = False


class WorkspaceLatchState(StrEnum):
    """Safe display labels for the durable kill-switch state."""

    READY = "READY"
    LATCHED = "LATCHED"
    RECOVERING = "RECOVERING"


@dataclass(frozen=True, slots=True)
class KillSwitchProjection:
    """Persisted latch display state without a ledger connection or recovery authority."""

    state: WorkspaceLatchState
    recovery_allowed: bool
    cancellation_requests: tuple[SafeCancellationRequest, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceProjectionV1:
    """Frozen, target-bound read facade for operator workspace account displays."""

    target_digest: str
    connection_state: str
    reconciliation_state: str
    configuration_state: str
    latch_state: str
    sections: tuple[ProductWorkspaceSection, ...]
    summary: CrossProductSummary
    kill_switch: KillSwitchProjection | None = None

    def __post_init__(self) -> None:
        if not self.target_digest or not self.sections:
            raise ValueError("workspace projections require target-bound product sections")
        if len({section.product for section in self.sections}) != len(self.sections):
            raise ValueError("workspace projections cannot mix duplicate product sections")

    @property
    def cross_product_summary(self) -> CrossProductSummary:
        return self.summary

    def section_for(self, product: ProductType | str) -> ProductWorkspaceSection:
        expected = product.value if type(product) is ProductType else product
        for section in self.sections:
            if section.product.value == expected:
                return section
        raise KeyError(f"workspace projection has no {expected} section")


@dataclass(frozen=True, slots=True)
class WorkspaceProjectionIdentity:
    """Applied configuration identity used for every workspace read and request."""

    account_id: str
    target_digest: str
    configuration_state: str

    def __post_init__(self) -> None:
        if not self.account_id or not self.target_digest or not self.configuration_state:
            raise ValueError("workspace projection identity requires active configuration facts")


class TradingWorkspaceFacade:
    """Application-owned workspace reader with no public storage or submission surface."""

    def __init__(
        self,
        *,
        runtime: object,
        target_digest: str | None = None,
        identity: Callable[[], WorkspaceProjectionIdentity] | None = None,
    ) -> None:
        self._runtime = runtime
        self._identity = identity or (
            lambda: WorkspaceProjectionIdentity(
                account_id="paper-account",
                target_digest=target_digest or "paper-spot-primary:paper-account:spot",
                configuration_state="not-configured",
            )
        )

    @property
    def active_target_digest(self) -> str:
        """Expose the current applied target identity to the presentation session."""
        return self._identity().target_digest

    def read_projection(self) -> WorkspaceProjectionV1:
        """Read immutable persisted Paper and latch facts without a gateway operation."""
        store = getattr(self._runtime, "_store", None)
        ledger = getattr(self._runtime, "ledger", None)
        if store is None or ledger is None:
            raise TypeError("workspace facade requires the owned Paper runtime")
        identity = self._identity()
        sections = tuple(
            _section_from_facts(
                store.read_workspace_product_facts(account_id=identity.account_id, product=product)
            )
            for product in ProductType
        )
        durable_latch = ledger.get_kill_switch_state()
        cancellation_requests = tuple(
            SafeCancellationRequest(work.work_id, work.status)
            for work in ledger.list_cancellation_work()
        )
        kill_switch = KillSwitchProjection(
            state=WorkspaceLatchState(durable_latch.status.value.upper()),
            recovery_allowed=durable_latch.status is KillSwitchStatus.READY,
            cancellation_requests=cancellation_requests,
        )
        return WorkspaceProjectionV1(
            target_digest=identity.target_digest,
            connection_state="connected",
            reconciliation_state="reconciled",
            configuration_state=identity.configuration_state,
            latch_state=durable_latch.status.value.upper(),
            sections=sections,
            summary=CrossProductSummary.from_sections(sections),
            kill_switch=kill_switch,
        )

    def refresh_projection(self) -> WorkspaceProjectionV1:
        """Alias an idempotent durable read; refresh never writes or submits."""
        return self.read_projection()

    def trigger_kill_switch(self, *, actor_label: str) -> KillSwitchProjection:
        """Retain the existing safety-latch request seam without returning command authority."""
        from pa_agent.trading.application.kill_switch import KillSwitchService

        ledger = getattr(self._runtime, "ledger", None)
        gateway = getattr(self._runtime, "gateway", None)
        if ledger is None or gateway is None:
            raise TypeError("workspace facade requires the owned Paper runtime")
        state = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=lambda: datetime.now(UTC)).latch(
            "operator_request", actor_label, "workspace", "operator requested durable latch"
        )
        return KillSwitchProjection(
            state=WorkspaceLatchState(state.status.value.upper()),
            recovery_allowed=False,
            cancellation_requests=tuple(
                SafeCancellationRequest(work.work_id, work.status)
                for work in ledger.list_cancellation_work()
            ),
        )


def _section_from_facts(facts: PaperWorkspaceProductFacts) -> ProductWorkspaceSection:
    """Construct one display section from only version-checked durable product facts."""
    available = facts.source_sequence is not None
    return ProductWorkspaceSection(
        product=facts.product,
        capability_available=available,
        unavailable_reason=(None if available else f"当前 Paper target 未配置 {facts.product.value} 账户"),
        balances=facts.balances,
        positions=facts.positions,
        open_orders=facts.open_orders,
        fills=facts.fills,
        source=facts.source,
        last_successful_reconciled_at=facts.last_successful_reconciled_at,
        freshness=(FreshnessStatus.FRESH if available else FreshnessStatus.NEVER_RECONCILED),
        safe_errors=(),
    )
