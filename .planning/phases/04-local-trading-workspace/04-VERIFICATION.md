---
phase: 04-local-trading-workspace
verified: 2026-07-15T07:09:41Z
status: human_needed
score: 4/4 must-haves verified
behavior_unverified: 1
overrides_applied: 0
gaps: []
behavior_unverified_items:
  - truth: "The local PyQt workspace visibly defaults to Paper and reflows cleanly at desktop breakpoints."
    test: "Launch the real AppContext-backed workspace; resize it at ≥1280px, 1024–1279px, and <1024px/<700px; verify Paper default, disabled Testnet/Live presentation, progressive fields, and the reachable 保存并验证 action."
    expected: "Chinese labels remain unclipped; the status band and save action remain reachable; numeric columns retain precision; only a successfully validated applied configuration can progress toward a ticket."
    why_human: "The deterministic pytest-qt checks cannot evaluate actual desktop layout, visual reflow, or clipping."
---

# Phase 4: Local Trading Workspace Verification Report

**Phase Goal:** An operator can configure non-secret trading controls, inspect execution state, approve eligible commands, and operate the kill switch without blocking the desktop application.
**Verified:** 2026-07-15T07:09:41Z
**Status:** human_needed
**Re-verification:** Yes — post-gap closure

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The workspace visibly defaults to Paper and requires separate mode, venue/environment, account, product, symbol mapping, paper-balance, margin/leverage, and risk configuration before a ticket is available. | ✓ VERIFIED (automated); human visual reflow pending | `TradingConfigPanel` keeps the Paper-first draft/applied/readiness boundary and the panel gates ticket creation on a rendered `applied` projection with a READY latch. The focused configuration and workspace tests passed. Desktop breakpoint composition remains the documented human-only check. |
| 2 | The workspace displays connection/reconciliation state, capabilities, balances, positions, open orders, recent fills, gateway errors, and persisted kill-switch state from execution projections. | ✓ VERIFIED | `_compose_workspace_facade()` derives the target digest and account from the active applied workspace configuration; `TradingWorkspaceFacade.read_projection()` returns that identity; `TradingWorkspacePanel._render_projection()` accepts and renders only the matching identity. `test_real_app_context_composed_projection_uses_panel_request_identity` exercised the composed AppContext path and observed `paper-spot-primary:paper-account:spot` in both facade and panel. |
| 3 | An eligible persisted analysis record can be reviewed in a typed ticket, explicitly approved or rejected, and traced to source metadata; advisory paths have no submit control. | ✓ VERIFIED | `TradingWorkspacePanel` dispatches only `WorkspaceTicketCreation(source_id)` and `WorkspaceTicketAction(ticket_id)`, opens `TradingApprovalDialog` from the durable ticket projection, and binds explicit dialog confirmation to the worker generation/digest. The application facade derives target/policy/context and `approve_ticket_from_durable_ticket()` rereads/rebuilds from the ticket’s persisted source. The integrated eligible-record → CREATE_TICKET → dialog → explicit confirmation → durable reread regression passed; dialog rejection requires separate explicit confirmation and updates only from a returned durable ticket projection. |
| 4 | Delayed/failing connection, validation, submission, cancellation, and reconciliation work keeps Qt responsive; stale callbacks cannot affect a switched or closed workspace. | ✓ VERIFIED | `WorkspaceWorker` is a `QThread` using immutable generation/digest DTOs. The panel invalidates/cancels detachable reads and accepts callbacks only for its live exact generation/digest. Worker fixture terminal signals are followed by `isFinished()` waits; the combined run terminates normally. |

**Score:** 4/4 must-haves verified. One manual desktop visual/reflow check remains because it is not deterministically testable in pytest-qt.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `pa_agent/config/settings.py` | Strict non-secret Paper-only workspace configuration | ✓ VERIFIED | Typed frozen settings and risk limits are covered by `test_workspace_settings.py`. |
| `pa_agent/trading/application/workspace_projection.py` | Frozen persisted execution workspace projection | ✓ VERIFIED | `WorkspaceProjectionIdentity` supplies the active configuration account/digest; reads project that exact target-bound identity. |
| `pa_agent/trading/application/workspace_commands.py` | Permit-only approval and persisted kill-switch facade | ✓ VERIFIED | Ticket creation reads strict persisted analysis; approval rereads the durable ticket/source and derives candidate, target, and policy outside the UI. |
| `pa_agent/trading/qt/workspace_worker.py` | QThread generation-scoped request/result protocol | ✓ VERIFIED | Closed operation enum and immutable typed creation/action DTOs keep UI requests free of execution authority. |
| `pa_agent/app_context.py` | Single runtime/facade composition and facade-first close ownership | ✓ VERIFIED | Applied-config target identity is composed once; `CREATE_TICKET`, `APPROVE_TICKET`, and `REJECT_TICKET` accept only typed UI identifiers and retain authority in the application boundary. |
| `pa_agent/gui/trading_config_panel.py` | Draft/applied/readiness configuration presentation | ✓ VERIFIED | Paper-first, worker-only configuration UI is covered by focused UI tests; visual reflow is pending human inspection. |
| `pa_agent/gui/trading_account_panel.py` | Read-only product account presentation | ✓ VERIFIED | It receives and renders matching immutable projection sections from the composed facade path. |
| `pa_agent/gui/trading_approval_dialog.py` | Typed ticket review and explicit confirmation | ✓ VERIFIED | The dialog is read-only, has explicit approve/reject confirmations, ignores stale results, and adopts only a returned durable ticket projection. |
| `pa_agent/gui/trading_kill_switch_dialog.py` | Persisted latch and recovery-condition presentation | ✓ VERIFIED | Persisted latch/recovery projections are rendered by focused tests. |
| `pa_agent/gui/trading_panel.py` | Top-level composition, callback guards, and worker lifecycle | ✓ VERIFIED | Matching target projection rendering, eligible-record ticket creation/review, typed ticket actions, durable result routing, and safe worker reaping are wired. |
| `pa_agent/gui/main_window.py` | One workspace entry and close forwarding | ✓ VERIFIED | One workspace action lazily reuses the panel and forwards safe close ownership. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `app_context.py` | `workspace_projection.py` | Active applied configuration → `WorkspaceProjectionIdentity` | ✓ WIRED | Account/product derive `paper-spot-primary:paper-account:spot`; the same digest is the facade’s active identity. |
| `trading_panel.py` | projection facade | Target-bound worker request → projection render | ✓ WIRED | The composed regression refreshes through AppContext and proves facade, request, and rendered panel target digests agree. |
| `trading_panel.py` | approval dialog/command facade | Eligible source → typed ticket creation → durable review → explicit action | ✓ WIRED | The panel sends only source/ticket identifiers. The dialog has no candidate, target, policy, permit, lease, ledger, gateway, or submission authority. |
| `workspace_commands.py` | durable ticket/source | Approval and rejection terminal state | ✓ WIRED | Approval rereads ticket and strict persisted source before reconstructing a candidate; rejection persists through the approval service; both return durable ticket state for display. |
| `workspace_worker.py` | Qt panel/dialog callbacks | Generation/digest/liveness guards | ✓ WIRED | Commands bind confirmation to the dispatched request; stale/closed callbacks are discarded. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| All Phase 04 unit, integration, and Qt worker/UI contracts, including post-closure projection and ticket lifecycle regressions | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_settings.py tests/unit/execution/test_workspace_projection.py tests/integration/execution/test_completed_analysis_snapshot_reader.py tests/integration/execution/test_workspace_projection_reopen.py tests/integration/execution/test_workspace_ticket_commands.py tests/e2e/execution/test_trading_configuration.py tests/e2e/execution/test_trading_workspace.py tests/e2e/execution/test_trading_workspace_workers.py tests/e2e/execution/test_trading_approval.py` | `..........................................................               [100%]`<br>`pytest: 58 passed in 1.84s` | ✓ PASS — clean exit |
| Target-bound AppContext projection rendering | Included above: `test_real_app_context_composed_projection_uses_panel_request_identity` | The rendered panel digest equals the facade’s active `paper-spot-primary:paper-account:spot` digest. | ✓ PASS |
| Eligible record → ticket → explicit approval → durable reread with typed UI payloads | Included above: `test_eligible_record_ticket_review_confirmation_and_durable_reread_use_typed_worker_inputs` | Creation sends `WorkspaceTicketCreation`; confirmation sends `WorkspaceTicketAction`; durable ticket transitions to `CONSUMED`. | ✓ PASS |
| Explicit approval/rejection and durable-only dialog state | Included above: `test_only_explicit_final_confirmation_enqueues_approval_command` and `test_reject_requires_explicit_confirmation_and_only_durable_ticket_projection_changes_ui` | Dismiss/Esc are no-ops; both actions require confirmation; a bare status result cannot mutate the dialog. | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| UI-01 | 04-01, 04-02, 04-04, 04-08, 04-10 | Non-secret configuration UI and centralized readiness | ✓ SATISFIED (automated) | Focused settings/configuration/workspace tests pass. The only remaining human check is visual desktop reflow and clipping. |
| UI-02 | 04-01, 04-02, 04-03, 04-05, 04-08, 04-10 | Account workspace backed by execution projections | ✓ SATISFIED | Real AppContext composed-facade refresh renders a projection only when its applied target identity matches the panel request identity. |
| UI-03 | 04-01, 04-02, 04-03, 04-06, 04-09, 04-10 | Eligible-record approval ticket, explicit approval/rejection, no advisory submit route | ✓ SATISFIED | Typed source/ticket-only UI protocol, explicit confirmation, durable state projection, and application-owned approval inputs are exercised by combined focused tests. |
| NFR-01 | 04-03, 04-07, 04-09, 04-10 | Exchange I/O must not block the Qt UI thread | ✓ SATISFIED | Generation-scoped QThread worker checks and the clean nine-file combined run pass. |

No orphaned Phase 04 requirements were found: every requirement mapped to Phase 04 is declared by one or more Phase 04 plans.

### Anti-Patterns Found

No Phase 04 blockers found in the post-closure code paths inspected. The prior hardcoded projection identity, orphaned approval control, incompatible ticket payload seam, and combined Qt lifecycle abort are closed and covered by the focused combined test run.

### Human Verification Required

#### 1. Desktop configuration and reflow

**Test:** Launch the application through the real `AppContext`, open `交易工作区`, and resize at ≥1280px, 1024–1279px, and <1024px/<700px.

**Expected:** Paper is visibly default; Testnet is visibly unavailable and Live disabled; progressive Chinese controls, status band, and `保存并验证` remain reachable; numeric columns preserve precision; no label is clipped.

**Why human:** Widget-level tests cannot establish real desktop composition, threshold reflow, or visual clipping.

## Verification Complete

**Status:** passed_with_manual_visual_check_pending
**Score:** 4/4 must-haves verified; 1 manual desktop visual/reflow check pending.
**Report:** `.planning/phases/04-local-trading-workspace/04-VERIFICATION.md`

_Verified: 2026-07-15T07:09:41Z_
_Verifier: Claude (gsd-verifier)_
