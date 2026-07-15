"""Application context wiring shared resources without global singletons."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppContext:
    """Carries shared resources to GUI widgets and orchestrators."""

    settings: Any = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("pa_agent"))
    event_bus: Any = None

    # Data layer
    data_source: Any = None       # DataSource implementation

    # AI / orchestration layer
    client: Any = None            # DeepSeekClient
    assembler: Any = None         # PromptAssembler
    router: Any = None            # route_strategy_files callable
    validator: Any = None         # JsonValidator
    pending_writer: Any = None    # PendingWriter
    exp_reader: Any = None        # ExperienceReader
    ledger: Any = None            # SessionTokenLedger

    # Trading security boundary: reference metadata only, never resolved credentials.
    trading_credential_reference: Any = None

    # Trading workspace UI receives this façade only; runtime remains composition-private.
    workspace_facade: Any = None
    _trading_runtime: Any = field(default=None, repr=False)
    _is_closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        """Close the workspace owner without making the GUI thread wait on worker I/O."""
        if self._is_closed:
            return
        self._is_closed = True
        facade_close = getattr(self.workspace_facade, "close", None)
        runtime_owned_by_facade = facade_close() if callable(facade_close) else False
        if runtime_owned_by_facade is True:
            return
        runtime_close = getattr(self._trading_runtime, "close", None)
        if callable(runtime_close):
            runtime_close()

    @classmethod
    def bootstrap(cls) -> "AppContext":
        """Wire all real components and return a fully initialised AppContext."""
        from pa_agent.config.paths import (
            SETTINGS_JSON_PATH,
            RECORDS_PENDING_DIR,
            EXPERIENCE_DIR,
            PROMPT_DIR,
        )
        from pa_agent.config.settings import load_settings
        from pa_agent.util.logging import configure_logging, update_api_key
        from pa_agent.util.event_bus import EventBus
        from pa_agent.util.mask_secret import mask_secret
        from pa_agent.data.factory import create_data_source, normalize_data_source_kind
        from pa_agent.ai.client_factory import create_ai_client
        from pa_agent.ai.prompt_assembler import PromptAssembler
        from pa_agent.ai.router import route_strategy_files
        from pa_agent.ai.json_validator import JsonValidator
        from pa_agent.ai.session_ledger import SessionTokenLedger
        from pa_agent.records.pending_writer import PendingWriter
        from pa_agent.records.experience_reader import ExperienceReader

        # ── Settings ──────────────────────────────────────────────────────────
        settings = load_settings(SETTINGS_JSON_PATH)
        from pa_agent.ai.qclaw_connector import sync_qclaw_agent_provider_on_load
        from pa_agent.ai.workbuddy_connector import sync_workbuddy_provider_on_load
        from pa_agent.ai.cursor_connector import sync_cursor_provider_on_load

        sync_qclaw_agent_provider_on_load(settings, save_path=SETTINGS_JSON_PATH)
        sync_workbuddy_provider_on_load(settings, save_path=SETTINGS_JSON_PATH)
        sync_cursor_provider_on_load(settings, save_path=SETTINGS_JSON_PATH)

        # ── Logging (with API key masking) ────────────────────────────────────
        configure_logging(api_key=settings.provider.api_key)

        app_logger = logging.getLogger("pa_agent")

        # ── Event bus ─────────────────────────────────────────────────────────
        event_bus = EventBus()

        # ── Data layer ────────────────────────────────────────────────────────
        from pa_agent.data.kline_adjust import apply_kline_adjust_from_settings

        apply_kline_adjust_from_settings(settings)
        ds_kind = normalize_data_source_kind(
            getattr(settings.general, "last_data_source", "mt5")
        )
        data_source = create_data_source(ds_kind)

        # Subscribe to the last-used symbol/timeframe from settings
        try:
            data_source.connect()
            if ds_kind == "tradingview":
                from pa_agent.data.tradingview import TradingViewSource

                if isinstance(data_source, TradingViewSource):
                    # Use saved exchange setting, default to auto (empty).
                    saved_exchange = getattr(settings.general, 'last_tradingview_exchange', '') or ''
                    data_source.set_exchange(saved_exchange)
            data_source.subscribe(
                settings.general.last_symbol,
                settings.general.last_timeframe,
            )
            app_logger.info(
                "Data source %s subscribed to %s %s",
                ds_kind,
                settings.general.last_symbol,
                settings.general.last_timeframe,
            )
        except Exception as exc:  # noqa: BLE001
            app_logger.warning("Initial data source subscription failed: %s", exc)

        # ── AI client ─────────────────────────────────────────────────────────
        from pa_agent.ai.client_factory import create_ai_client

        client = create_ai_client(settings.provider, logger_=app_logger)

        # ── Prompt assembler ──────────────────────────────────────────────────
        exp_reader = ExperienceReader(experience_dir=EXPERIENCE_DIR, logger=app_logger)
        assembler = PromptAssembler(
            prompt_dir=PROMPT_DIR,
            experience_reader=exp_reader,
            prompt_settings=settings.prompt,
        )

        workspace_facade, trading_runtime = _compose_workspace_facade(
            settings=settings,
            settings_path=SETTINGS_JSON_PATH,
            pending_dir=RECORDS_PENDING_DIR,
        )

        # ── Validator & router ────────────────────────────────────────────────
        validator = JsonValidator(settings)
        router = route_strategy_files

        # ── Pending writer ────────────────────────────────────────────────────
        pending_writer = PendingWriter(
            pending_dir=RECORDS_PENDING_DIR,
            event_bus=event_bus,
            api_key=settings.provider.api_key,
        )

        # ── Session ledger ────────────────────────────────────────────────────
        ledger = SessionTokenLedger(
            context_window=settings.provider.context_window,
            warn_pct=settings.general.context_warning_threshold_pct,
        )

        return cls(
            settings=settings,
            logger=app_logger,
            event_bus=event_bus,
            data_source=data_source,
            client=client,
            assembler=assembler,
            router=router,
            validator=validator,
            pending_writer=pending_writer,
            exp_reader=exp_reader,
            ledger=ledger,
            workspace_facade=workspace_facade,
            _trading_runtime=trading_runtime,
            trading_credential_reference=settings.trading.credential_reference,
        )


def _compose_workspace_facade(*, settings: Any, settings_path: Any, pending_dir: Any) -> tuple[Any, Any]:
    """Compose the single runtime behind a worker-only façade at the application root."""
    from dataclasses import replace
    from datetime import UTC, datetime

    from pa_agent.config.paths import EXECUTION_LEDGER_PATH
    from pa_agent.config.settings import WorkspaceRiskLimits, WorkspaceSettings, save_settings
    from pa_agent.trading.application.approval import ApprovalService
    from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
    from pa_agent.trading.application.intent_factory import IntentFactory
    from pa_agent.trading.application.kill_switch import KillSwitchService
    from pa_agent.trading.application.paper_runtime import PaperTradingRuntime
    from pa_agent.trading.application.proposal import ProposalService
    from pa_agent.trading.application.risk_engine import RiskEngine
    from pa_agent.trading.application.workspace_commands import TradingWorkspaceCommands
    from pa_agent.trading.application.workspace_projection import (
        AppliedWorkspaceConfig,
        TradingWorkspaceFacade,
        WorkspaceConfigDraft,
        WorkspaceConfigurationFacade,
        WorkspaceProjectionIdentity,
    )
    from pa_agent.trading.domain.approval import ExecutionTarget
    from pa_agent.trading.domain.models import Mode, ProductType, SpotOrderContext
    from pa_agent.trading.domain.risk import select_paper_product_policy
    from pa_agent.trading.gateways.paper.store import PaperStore
    from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
    from pa_agent.trading.ports.analysis_records import AnalysisRecordSnapshotReader
    from pa_agent.trading.qt.workspace_worker import (
        WorkspaceArguments,
        WorkspaceConfigPayload,
        WorkspaceFacade,
        WorkspaceOperation,
        WorkspaceRequest,
        WorkspaceTicketAction,
        WorkspaceTicketCreation,
    )
    from pa_agent.trading.security.redaction import output_redactor

    utc_now = lambda: datetime.now(UTC)
    runtime = PaperTradingRuntime(
        ledger=SQLiteExecutionLedger(EXECUTION_LEDGER_PATH),
        store=PaperStore(EXECUTION_LEDGER_PATH.with_name("paper_workspace.sqlite3")),
        initial_balances=settings.trading.workspace.paper_balances,
    )
    baseline_limits = WorkspaceRiskLimits(
        maximum_order_notional="1000",
        maximum_total_exposure="1000",
        maximum_open_orders=3,
        maximum_utc_day_realized_loss="100",
        maximum_utc_day_drawdown="0.10",
    )
    configuration = WorkspaceConfigurationFacade(baseline_limits=baseline_limits)
    reader = AnalysisRecordSnapshotReader(pending_dir=pending_dir, utc_now=utc_now)
    evidence_collector = FreshEvidenceCollector(gateway=runtime.gateway, utc_now=utc_now)
    risk_engine = RiskEngine()
    approval_service = ApprovalService(
        ledger=runtime.ledger,
        utc_now=utc_now,
        evidence_collector=evidence_collector,
        risk_engine=risk_engine,
    )
    commands = TradingWorkspaceCommands(
        analysis_reader=reader,
        proposal_service=ProposalService(
            ledger=runtime.ledger,
            intent_factory=IntentFactory(utc_now=utc_now),
            evidence_collector=evidence_collector,
            risk_engine=risk_engine,
            approval_service=approval_service,
            redactor=output_redactor(),
        ),
        approval_service=approval_service,
        submission_coordinator=runtime.submission,
        kill_switch_service=KillSwitchService(
            ledger=runtime.ledger,
            gateway=runtime.gateway,
            utc_now=utc_now,
        ),
    )
    active_applied_config: AppliedWorkspaceConfig | None = None

    def workspace_target_digest(*, account_id: str, product: str) -> str:
        target_id = {
            "spot": "paper-spot-primary",
            "isolated_margin": "paper-margin-isolated-primary",
            "usdt_perpetual": "paper-usdt-perpetual-primary",
        }[product]
        return f"{target_id}:{account_id}:{product}"

    workspace = settings.trading.workspace
    if workspace.risk_limits is not None and workspace.symbol_mapping and workspace.paper_balances:
        persisted_draft = WorkspaceConfigDraft(
            target=workspace.target,
            account_id=workspace.account_id,
            product=workspace.product,
            symbol_mapping=dict(workspace.symbol_mapping),
            paper_balances=dict(workspace.paper_balances),
            risk_limits=workspace.risk_limits,
            credential_reference=workspace.credential_reference,
            revision=1,
        )
        active_applied_config = AppliedWorkspaceConfig.from_validated_draft(
            persisted_draft,
            target_digest=workspace_target_digest(
                account_id=workspace.account_id,
                product=workspace.product,
            ),
        )

    def projection_identity() -> WorkspaceProjectionIdentity:
        current = settings.trading.workspace
        return WorkspaceProjectionIdentity(
            account_id=current.account_id,
            target_digest=workspace_target_digest(
                account_id=current.account_id,
                product=current.product,
            ),
            configuration_state="applied" if active_applied_config is not None else "not-configured",
        )

    projection = TradingWorkspaceFacade(runtime=runtime, identity=projection_identity)

    def config_payload(request: WorkspaceRequest) -> WorkspaceConfigPayload:
        if type(request.payload) is not WorkspaceConfigPayload:
            raise TypeError("workspace configuration requires WorkspaceConfigPayload")
        if type(request.payload.draft) is not WorkspaceConfigDraft:
            raise TypeError("workspace configuration requires a typed draft")
        return request.payload

    def validate_configuration(request: WorkspaceRequest) -> object:
        payload = config_payload(request)
        return configuration.validate(
            payload.draft,
            active_target_digest=request.active_target_digest,
            applied_config=payload.applied_config,
            prerequisite_issues=payload.prerequisite_issues,
        )

    def save_configuration(request: WorkspaceRequest) -> object:
        nonlocal active_applied_config
        payload = config_payload(request)
        readiness = validate_configuration(request)
        if not readiness.ready:
            return readiness
        applied = AppliedWorkspaceConfig.from_validated_draft(
            payload.draft,
            target_digest=request.active_target_digest,
        )
        settings.trading.workspace = WorkspaceSettings(
            target=payload.draft.target,
            account_id=payload.draft.account_id,
            product=payload.draft.product,
            symbol_mapping=payload.draft.symbol_mapping,
            paper_balances=payload.draft.paper_balances,
            risk_limits=payload.draft.risk_limits,
            credential_reference=payload.draft.credential_reference,
        )
        save_settings(settings, settings_path)
        active_applied_config = applied
        return replace(readiness, applied_config=applied)

    def command_handler(method_name: str):
        def invoke(request: WorkspaceRequest) -> object:
            if type(request.payload) is not WorkspaceArguments:
                raise TypeError("workspace commands require immutable WorkspaceArguments")
            return getattr(commands, method_name)(**request.payload.values)

        return invoke

    def ticket_inputs(request: WorkspaceRequest) -> tuple[ExecutionTarget, object, SpotOrderContext]:
        applied = active_applied_config
        if applied is None or request.active_target_digest != applied.target_digest:
            raise RuntimeError("workspace approval requires the current applied configuration")
        product = ProductType(applied.product)
        if product is not ProductType.SPOT:
            raise RuntimeError("workspace approval requires a configured supported product context")
        target_id = {
            ProductType.SPOT: "paper-spot-primary",
            ProductType.ISOLATED_MARGIN: "paper-margin-isolated-primary",
            ProductType.USDT_PERPETUAL: "paper-usdt-perpetual-primary",
        }[product]
        target = ExecutionTarget(target_id, Mode.PAPER, applied.account_id, product)
        context = SpotOrderContext()
        return target, select_paper_product_policy(target, context), context

    def create_ticket(request: WorkspaceRequest) -> object:
        if type(request.payload) is not WorkspaceTicketCreation:
            raise TypeError("ticket creation requires a typed persisted analysis selection")
        target, policy, context = ticket_inputs(request)
        return commands.create_ticket(
            source_id=request.payload.source_id,
            target=target,
            policy=policy,
            context=context,
        )

    def reject_ticket(request: WorkspaceRequest) -> object:
        if type(request.payload) is not WorkspaceTicketAction:
            raise TypeError("ticket rejection requires a typed durable ticket action")
        return commands.reject_ticket(request.payload.ticket_id, request.payload.reason)

    def approve_ticket(request: WorkspaceRequest) -> object:
        if type(request.payload) is not WorkspaceTicketAction:
            raise TypeError("ticket approval requires a typed durable ticket action")
        target, policy, context = ticket_inputs(request)
        return commands.approve_ticket_from_durable_ticket(
            ticket_id=request.payload.ticket_id,
            target=target,
            policy=policy,
            context=context,
        )

    handlers = {
        WorkspaceOperation.READ_PROJECTION: lambda request: projection.read_projection(),
        WorkspaceOperation.REFRESH_PROJECTION: lambda request: projection.refresh_projection(),
        WorkspaceOperation.VALIDATE_CONFIGURATION: validate_configuration,
        WorkspaceOperation.SAVE_CONFIGURATION: save_configuration,
        WorkspaceOperation.CREATE_TICKET: create_ticket,
        WorkspaceOperation.REJECT_TICKET: reject_ticket,
        WorkspaceOperation.APPROVE_TICKET: approve_ticket,
        WorkspaceOperation.PROCESS_CANCELLATION: command_handler("process_cancellation_work"),
        WorkspaceOperation.TRIGGER_KILL_SWITCH: command_handler("trigger_kill_switch"),
        WorkspaceOperation.BEGIN_KILL_SWITCH_RECOVERY: command_handler("begin_kill_switch_recovery"),
        WorkspaceOperation.COMPLETE_KILL_SWITCH_RECOVERY: command_handler(
            "complete_kill_switch_recovery"
        ),
    }
    return WorkspaceFacade(
        handlers=handlers,
        runtime_close=runtime.close,
        target_digest_provider=lambda: projection.active_target_digest,
    ), runtime
