---
phase: 04-local-trading-workspace
plan: 05
subsystem: trading-workspace
tags: [paper, sqlite, projection, immutable-read-model]

requires:
  - phase: 04-01
    provides: workspace projection contracts
  - phase: 04-02
    provides: reopen regression contracts
  - phase: 04-04
    provides: immutable configuration/readiness DTOs
provides:
  - version-checked, product-scoped Paper durable facts reader
  - immutable WorkspaceProjectionV1 with display-only cross-product summary
  - reopen-safe persistent Paper and latch projection
affects: [04-08, trading-account-panel, workspace-worker]

tech-stack:
  added: []
  patterns: [version-checked durable read model, frozen display DTOs, product-scoped freshness]

key-files:
  created: []
  modified:
    - pa_agent/trading/gateways/paper/store.py
    - pa_agent/trading/application/workspace_projection.py
    - tests/integration/execution/test_workspace_projection_reopen.py

key-decisions:
  - "Paper snapshot payloads are parsed at the store boundary into canonical typed facts; GUI-facing values never receive payload mappings or fill provenance JSON."
  - "Cross-product totals are display-only and expose no approval, risk, permit, lease, gateway, ledger, or submit authority."

patterns-established:
  - "Workspace sections preserve independent product capability, reconciliation timestamp, and freshness metadata."
  - "A refresh is an idempotent durable read and cannot allocate submission authority."

requirements-completed: [UI-02]

coverage:
  - id: D1
    description: "Paper durable reader reconstructs committed product facts and reopened workspace state without resubmission."
    requirement: UI-02
    verification:
      - kind: integration
        ref: ".venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_workspace_projection_reopen.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Frozen target/product workspace projection retains independent freshness and a display-only summary."
    requirement: UI-02
    verification:
      - kind: unit
        ref: ".venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_projection.py"
        status: pass
    human_judgment: false

duration: unknown
completed: 2026-07-15
status: complete
---

# Phase 04: Local Trading Workspace Plan 05 Summary

**Version-checked Paper facts now feed frozen, target-bound account sections and a strictly display-only workspace summary.**

## Performance

- **Completed:** 2026-07-15T05:24:44Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- Added a typed PaperStore reader that reconstructs scoped balances, positions, open orders, and display-safe fills strictly from committed snapshot/event sequences.
- Added `WorkspaceProjectionV1`, independent product freshness/reconciliation metadata, and persisted latch display state without storage, gateway, or submission authority in output DTOs.
- Upgraded reopen regression coverage to assert a summary cannot provide approval state and that projection reads create no additional authority or dispatch.

## Task Commits

1. **Task 1: 提供版本化产品 scoped 的 Paper durable read API** — `57547a8` (`feat`)
2. **Task 2: 聚合 immutable workspace projection 并保护 summary 纯度** — `3493d3e` (`feat`)

## Files Created/Modified

- `pa_agent/trading/gateways/paper/store.py` — typed product-scoped durable facts reader with schema validation and persistent reconciliation time.
- `pa_agent/trading/application/workspace_projection.py` — frozen workspace/product/summary/latch projection façade.
- `tests/integration/execution/test_workspace_projection_reopen.py` — reopen assertions for read-only, display-only authority boundaries.

## Verification

- PASS — `.venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_projection.py` — 4 passed.
- PASS — `.venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_workspace_projection_reopen.py` — 3 passed.
- EXPECTED DOWNSTREAM FAILURE — `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_workspace.py` — 3 failed because `pa_agent.gui.trading_account_panel` is intentionally created by Plan 04-08, outside this plan's `files_modified` scope. The non-headless invocation aborts before collection because this worker environment has no Qt display server.

## Decisions Made

- Durable snapshot payloads are parsed and version-checked at the PaperStore boundary, not by the workspace façade or GUI.
- Fill provenance JSON remains store-internal; workspace display facts expose only immutable fill identity, command identity, quantity, and sequence.
- The cross-product summary uses counts and time range only; no summary or root projection approval field exists.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Information disclosure] Removed fill provenance JSON from workspace read facts**
- **Found during:** Task 2
- **Issue:** Reusing `PaperFill` would have carried a raw persisted provenance JSON string across the workspace read boundary.
- **Fix:** Added `PaperWorkspaceFill`, retaining only safe typed display facts.
- **Files modified:** `pa_agent/trading/gateways/paper/store.py`
- **Verification:** Unit and reopen integration suites pass.
- **Committed in:** `3493d3e`

---

**Total deviations:** 1 auto-fixed (1 missing critical safety boundary).
**Impact on plan:** Necessary to preserve the stated GUI authority and payload boundary; no scope expansion.

## Issues Encountered

- The pre-existing account-panel pytest-qt contract remains red until Plan 04-08 supplies `pa_agent.gui.trading_account_panel`; this plan intentionally does not create that downstream UI module.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 04-08 can render all account data from `TradingWorkspaceFacade.read_projection()` without receiving a PaperStore, ledger connection, gateway, permit, lease, or submit capability.
- The UI regression suite will become runnable after its planned account-panel implementation.

---
*Phase: 04-local-trading-workspace*
*Completed: 2026-07-15*
