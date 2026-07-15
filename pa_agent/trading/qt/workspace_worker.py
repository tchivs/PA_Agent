"""QThread-owned, target-bound protocol for workspace application operations."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from PyQt6.QtCore import QThread, pyqtSignal

from pa_agent.trading.security.redaction import SecretRedactor, output_redactor
from pa_agent.util.threading import CancelToken


class WorkspaceOperation(StrEnum):
    """Closed set of application operations a workspace worker may dispatch."""

    READ_PROJECTION = "read_projection"
    REFRESH_PROJECTION = "refresh_projection"
    VALIDATE_CONFIGURATION = "validate_configuration"
    SAVE_CONFIGURATION = "save_configuration"
    CREATE_TICKET = "create_ticket"
    REJECT_TICKET = "reject_ticket"
    APPROVE_TICKET = "approve_ticket"
    PROCESS_CANCELLATION = "process_cancellation"
    TRIGGER_KILL_SWITCH = "trigger_kill_switch"
    BEGIN_KILL_SWITCH_RECOVERY = "begin_kill_switch_recovery"
    COMPLETE_KILL_SWITCH_RECOVERY = "complete_kill_switch_recovery"

    @property
    def is_cancellable_read(self) -> bool:
        """Only idempotent read/validation work may be silently cancelled."""
        return self in {
            WorkspaceOperation.READ_PROJECTION,
            WorkspaceOperation.REFRESH_PROJECTION,
            WorkspaceOperation.VALIDATE_CONFIGURATION,
        }


@dataclass(frozen=True, slots=True)
class EmptyWorkspacePayload:
    """Explicit empty payload for worker operations without typed arguments."""

@dataclass(frozen=True, slots=True)
class WorkspaceArguments:
    """Immutable named arguments for one preselected closed façade operation."""

    values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

@dataclass(frozen=True, slots=True)
class WorkspaceTicketCreation:
    """Operator-selected persisted analysis identity; application owns all execution inputs."""

    source_id: str

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("ticket creation requires a persisted analysis source identifier")


@dataclass(frozen=True, slots=True)
class WorkspaceTicketAction:
    """Immutable ticket action identity without candidate, target, policy, or authority."""

    ticket_id: str
    reason: str = "operator_declined_from_workspace"

    def __post_init__(self) -> None:
        if not self.ticket_id:
            raise ValueError("ticket actions require a durable ticket identifier")
        if not self.reason:
            raise ValueError("ticket actions require a safe operator reason")


@dataclass(frozen=True, slots=True)
class WorkspaceConfigPayload:
    """Typed configuration draft plus explicitly retained applied snapshot if any."""

    draft: object
    applied_config: object | None = None
    prerequisite_issues: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceRequest:
    """Immutable target-bound dispatch context that never carries UI or service authority."""

    operation: WorkspaceOperation
    generation: int
    active_target_digest: str
    payload: object = field(default_factory=EmptyWorkspacePayload)
    cancel_token: CancelToken = field(default_factory=CancelToken, compare=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.operation) is not WorkspaceOperation:
            raise TypeError("workspace requests require a known operation")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("workspace request generations must be non-negative integers")
        if type(self.active_target_digest) is not str or not self.active_target_digest:
            raise ValueError("workspace requests require an active target digest")
        if type(self.cancel_token) is not CancelToken:
            raise TypeError("workspace requests require a CancelToken")


class WorkspaceResultStatus(StrEnum):
    """Safe worker terminal outcomes that do not describe durable authority."""

    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class WorkspaceResult:
    """Immutable queued success or cancellable-read result for one request identity."""

    operation: WorkspaceOperation
    generation: int
    active_target_digest: str
    status: WorkspaceResultStatus
    value: object | None


@dataclass(frozen=True, slots=True)
class WorkspaceError:
    """Controlled, redacted worker failure suitable for an operator-facing slot."""

    operation: WorkspaceOperation
    generation: int
    active_target_digest: str
    code: str
    safe_message: str
    next_action: str


@runtime_checkable
class WorkspaceOperationFacade(Protocol):
    """The sole non-Qt authority a workspace worker may retain."""

    def execute(self, request: WorkspaceRequest) -> object:
        """Perform exactly one closed, target-bound application operation."""



class WorkspaceFacade:
    """Single application-composed operation surface retained by QThread workers only."""

    def __init__(
        self,
        *,
        handlers: Mapping[WorkspaceOperation, Callable[[WorkspaceRequest], object]],
        runtime_close: Callable[[], None] | None = None,
        target_digest_provider: Callable[[], str] | None = None,
    ) -> None:
        if not handlers:
            raise ValueError("workspace facade requires closed operation handlers")
        if any(type(operation) is not WorkspaceOperation for operation in handlers):
            raise TypeError("workspace facade handlers require known operations")
        self._handlers = MappingProxyType(dict(handlers))
        self._runtime_close = runtime_close
        self._target_digest_provider = target_digest_provider
        self._lock = Lock()
        self._execution_lock = Lock()
        self._active_operations = 0
        self._closed = False
        self._runtime_closed = False

    @property
    def active_target_digest(self) -> str | None:
        """Return the application-composed identity without exposing runtime services."""
        if self._target_digest_provider is None:
            return None
        return self._target_digest_provider()

    def execute(self, request: WorkspaceRequest) -> object:
        """Invoke exactly one configured application operation without a QWidget reference."""
        with self._lock:
            if self._closed:
                raise RuntimeError("workspace facade is closed")
            handler = self._handlers.get(request.operation)
            if handler is None:
                raise ValueError(f"workspace operation is unavailable: {request.operation.value}")
            self._active_operations += 1
        try:
            with self._execution_lock:
                return handler(request)
        finally:
            with self._lock:
                self._active_operations -= 1
                should_close_runtime = self._closed and self._active_operations == 0
            if should_close_runtime:
                self._close_runtime()

    def close(self) -> bool:
        """Reject future work and defer owned runtime closure until active workers finish."""
        with self._lock:
            self._closed = True
            should_close_runtime = self._active_operations == 0
        if should_close_runtime:
            self._close_runtime()
        return True

    def _close_runtime(self) -> None:
        with self._lock:
            if self._runtime_closed:
                return
            self._runtime_closed = True
        if self._runtime_close is not None:
            self._runtime_close()

class WorkspaceWorker(QThread):
    """Run one workspace-facade operation off the GUI thread and emit safe immutable DTOs."""

    completed = pyqtSignal(object)  # WorkspaceResult
    failed = pyqtSignal(object)  # WorkspaceError
    cancelled = pyqtSignal(object)  # WorkspaceResult

    def __init__(
        self,
        *,
        facade: WorkspaceOperationFacade,
        request: WorkspaceRequest,
        redactor: SecretRedactor | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(facade, WorkspaceOperationFacade):
            raise TypeError("workspace workers require an operation facade")
        if type(request) is not WorkspaceRequest:
            raise TypeError("workspace workers require an immutable WorkspaceRequest")
        self._facade = facade
        self._request = request
        self._redactor = redactor or output_redactor()

    def run(self) -> None:
        """Keep Qt work limited to queued immutable signal delivery."""
        if self._request.cancel_token.is_set() and self._request.operation.is_cancellable_read:
            self.cancelled.emit(self._cancelled_result())
            return
        try:
            value = self._facade.execute(self._request)
        except Exception as exc:  # noqa: BLE001 - this is the redacted UI boundary
            self.failed.emit(self._safe_error(exc))
            return
        if self._request.cancel_token.is_set() and self._request.operation.is_cancellable_read:
            self.cancelled.emit(self._cancelled_result())
            return
        self.completed.emit(
            WorkspaceResult(
                operation=self._request.operation,
                generation=self._request.generation,
                active_target_digest=self._request.active_target_digest,
                status=WorkspaceResultStatus.SUCCEEDED,
                value=value,
            )
        )

    def _cancelled_result(self) -> WorkspaceResult:
        return WorkspaceResult(
            operation=self._request.operation,
            generation=self._request.generation,
            active_target_digest=self._request.active_target_digest,
            status=WorkspaceResultStatus.CANCELLED,
            value=None,
        )

    def _safe_error(self, exc: Exception) -> WorkspaceError:
        safe_message = self._redactor.redact(str(exc))
        if not isinstance(safe_message, str):
            safe_message = "操作未完成，请检查状态后重试。"
        return WorkspaceError(
            operation=self._request.operation,
            generation=self._request.generation,
            active_target_digest=self._request.active_target_digest,
            code="WORKSPACE_OPERATION_FAILED",
            safe_message=safe_message,
            next_action="refresh_workspace_state",
        )
