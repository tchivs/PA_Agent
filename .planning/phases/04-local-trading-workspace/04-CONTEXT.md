# Phase 4: Local Trading Workspace - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Provide a responsive local PyQt6 trading workspace for the already-validated Paper execution path: configure non-secret trading controls, inspect persisted execution and Paper-account state, review typed approval tickets, and operate the existing kill switch. The UI is a thin projection and command surface over the established trading services; it must not create gateway, approval, risk, lifecycle, or reconciliation authority. No Testnet adapter, Live enablement, new execution product semantics, or network-on-UI-thread behavior belongs in this phase.
</domain>

<decisions>
## Implementation Decisions

### Configuration Workflow
- **D-01:** Organize settings as progressive sections. The operator first chooses mode, target, product, and account; show only configuration applicable to that explicit selection. Paper remains the default; Testnet and disabled Live remain visibly distinct.
- **D-02:** On venue, environment, account, or product changes, retain unsaved edits as a draft but revalidate every affected setting. Approval stays unavailable until the operator explicitly saves and the newly selected configuration passes validation.
- **D-03:** Provide both immediate field-level validation and a fixed, centralized readiness summary. The summary is the single global indication of whether the current applied configuration can enter the approval flow, and must identify blocking errors, warnings, and their owning configuration section.
- **D-04:** A draft becomes applied configuration only through an explicit **Save and validate** action. Persist only validated non-secret settings; visibly distinguish the current applied configuration from unsaved edits.

### Account-State Workspace
- **D-05:** Make balances and positions the primary first-screen content. Connection, reconciliation, readiness, and kill-switch indicators remain present but secondary to the account view.
- **D-06:** Group Spot, isolated-margin, and USDT-perpetual balances, positions, orders, and fills by product. Provide a read-only cross-product summary for orientation only; it must not calculate risk or establish approval eligibility.
- **D-07:** Show each account-data section's last successful reconciliation time, source, and freshness independently. Stale data remains inspectable but is clearly marked, and the UI must not make it appear eligible for approval.
- **D-08:** Keep kill-switch state (READY, LATCHED, or RECOVERING) continuously visible. Trigger and recovery actions open an explicit confirmation flow that displays persisted preconditions and blocking reasons; the UI cannot bypass existing service validation or reconciliation requirements.

### Claude's Discretion
- Exact PyQt widget/module boundaries, table columns, visual density, navigation controls, status wording, worker-object arrangement, and test-helper structure may follow established repository patterns, provided they preserve the decisions and Phase 1–3 authority boundaries above.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and phase scope
- `.planning/PROJECT.md` — bounded local execution architecture; Paper default, disabled Live, Decimal, secret, and UI-thread constraints.
- `.planning/REQUIREMENTS.md` — Phase 4 requirements `UI-01`, `UI-02`, `UI-03`, and `NFR-01`; all relevant safety and approval requirements.
- `.planning/ROADMAP.md` — Phase 4 goal, success criteria, dependencies, and fixed phase boundary.

### Prior verified execution contracts
- `.planning/phases/01-execution-foundation/01-CONTEXT.md` — canonical domain, gateway, ledger, recovery, and UI-isolation decisions.
- `.planning/phases/02-approval-and-risk-boundary/02-CONTEXT.md` — deterministic approval, fresh evidence, ticket, kill-switch, and secret-isolation decisions.
- `.planning/phases/02-approval-and-risk-boundary/02-VERIFICATION.md` — verified permit-only submission, kill-switch, recovery, and secret-safe output boundaries.
- `.planning/phases/03-paper-product-core/03-CONTEXT.md` — deterministic Paper Spot, isolated-margin, perpetual, recovery, and lifecycle decisions.
- `.planning/phases/03-paper-product-core/03-VERIFICATION.md` — verified Paper runtime, Paper truth, and permit → SQLite lease → coordinator → gateway boundary.

### Existing application conventions
- `.planning/codebase/CONVENTIONS.md` — Python/PyQt naming, typing, error handling, module boundaries, and test conventions.
- `.planning/codebase/STRUCTURE.md` — existing `pa_agent/gui/`, `pa_agent/gui/widgets/`, `pa_agent/gui/theme/`, `pa_agent/app_context.py`, `pa_agent/trading/`, and test placement integration points.
- `.planning/codebase/STACK.md` — PyQt6, pytest-qt, Python 3.11, Pydantic, and declared toolchain constraints.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pa_agent/gui/main_window.py` and focused sibling GUI modules — the established top-level workflow/control and feature-panel placement for desktop UI.
- `pa_agent/gui/widgets/` — focused reusable visual primitives; add a reusable trading widget here only when it has an independent presentation responsibility.
- `pa_agent/gui/theme/tokens.py` and `pa_agent/gui/theme/apply.py` — application-wide visual tokens and styling hook.
- `pa_agent/app_context.py` — composition root for explicit application-scoped service wiring.
- `pa_agent/trading/application/`, `pa_agent/trading/ports/`, and `pa_agent/trading/persistence/` — established typed service, gateway, and durable-ledger boundaries that the UI must consume rather than reproduce.
- `tests/e2e/`, `tests/integration/`, and `pytest-qt` — existing locations and tooling for desktop workflow, worker-responsiveness, and integration coverage.

### Established Patterns
- Qt widgets receive background-worker results through signals; trading I/O cannot execute on the GUI thread.
- Trading values and lifecycle truth stay in canonical domain models and SQLite/Paper state; the UI is a projection, never an authority source.
- New GUI panels live in purpose-named modules, while `MainWindow` owns top-level workflow integration.
- Persisted user settings use typed Pydantic validation; generic settings cannot contain exchange secrets.

### Integration Points
- Compose the Phase 4 presentation services through `pa_agent/app_context.py` without joining analysis, alerts, or notifications to submission authority.
- Add top-level trading entry points through `pa_agent/gui/main_window.py`; keep discrete configuration, account, approval, and kill-switch surfaces in focused GUI modules.
- Read typed execution projections and invoke existing application-service commands only after their existing validation/authorization gates.
</code_context>

<specifics>
## Specific Ideas

- The centralized readiness summary should make its meaning explicit: it explains why the configured target can or cannot enter the approval workflow, while individual fields expose local causes.
- Cross-product account aggregation is orientation-only. Product-specific account semantics remain visible and must not be flattened into a synthetic risk calculation.
</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within the fixed Phase 4 scope.
</deferred>

---

*Phase: 04-local-trading-workspace*
*Context gathered: 2026-07-14*
