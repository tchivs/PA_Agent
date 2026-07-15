---
phase: 04-local-trading-workspace
kind: gap-closure-summary
completed: 2026-07-15
---

# Phase 04 Gap Closure Summary

## Commit

- `0098e1e fix(04): close workspace facade and Qt lifecycle gaps`

## Files

- `pa_agent/app_context.py` — composes target/account/product identity from the active applied configuration and derives typed ticket inputs only at the application boundary.
- `pa_agent/gui/trading_approval_dialog.py` — binds explicit confirmation callbacks to the current worker generation and target digest.
- `pa_agent/gui/trading_config_panel.py` — emits the same canonical target/account/product digest used by the application facade.
- `pa_agent/gui/trading_panel.py` — renders the composed facade projection, selects persisted record IDs, creates/reviews/approves tickets through typed worker payloads, and queues all Qt callbacks/reaping safely.
- `pa_agent/trading/application/workspace_commands.py` — projects durable ticket review data and reconstructs approval candidates from the ticket's persisted source.
- `pa_agent/trading/application/workspace_projection.py` — reads projection account, digest, and configuration state through an active configuration identity.
- `pa_agent/trading/persistence/sqlite_connection.py` — permits the application-serialized workspace worker access required by the composed runtime.
- `pa_agent/trading/qt/workspace_worker.py` — exposes the active target identity and serializes shared runtime operations.
- `tests/e2e/execution/test_trading_workspace_workers.py` — adds AppContext projection and eligible-record/ticket lifecycle regressions and finalizes direct QThread fixtures before teardown.

## Deviations

- The composed runtime owns SQLite connections before worker dispatch. To preserve the worker-only UI boundary without rebuilding the runtime for every request, workspace facade execution is serialized and its SQLite connections permit that serialized cross-worker access.
- Direct `WorkspaceWorker` fixture tests now wait for `isFinished()` after observing their terminal signal. This fixes the actual Qt teardown ownership fault rather than splitting the combined test process.

## Self-check

- The AppContext-composed facade exposes `paper-spot-primary:paper-account:spot`; the panel uses that same identity for its request and renders the matching projection.
- The workspace sends only `WorkspaceTicketCreation(source_id)` and `WorkspaceTicketAction(ticket_id)`; candidate, target, policy, and durable reread remain application-owned.
- Explicit dialog confirmation reaches a durable reread state, while dialog callbacks remain generation/digest/live-UI guarded.
- The combined nine-file Phase 04 focused command completed normally: `58 passed`.
