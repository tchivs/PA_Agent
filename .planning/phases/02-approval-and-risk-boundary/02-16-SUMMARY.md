---
phase: 02-approval-and-risk-boundary
plan: 16
subsystem: trading-approval-consumption
tags: [python, sqlite, approval, evidence-freshness, risk, pytest, ruff]

requires:
  - phase: 02-14
    provides: Side-priced MARKET economics and Paper Spot balance gates at ticket issuance and consumption.
provides:
  - A pure TicketBinding authorization-equivalence API that permits only fresh timestamp changes inside the fixed phase2-v1 window.
  - Atomic append-only evidence and accepted-risk refresh audit facts before one ticket consumption and outbound authorization.
affects: [approval-tickets, approval-consumption, execution-audit, phase-02-verification]

tech-stack:
  added: []
  patterns:
    - Compare timestamp-free evidence semantics and complete accepted economics while independently validating every new observation timestamp.
    - Append current evidence and reassessment audit facts in the same BEGIN IMMEDIATE decision as conditional ticket consumption.

key-files:
  created: []
  modified:
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_approval_consumption.py

key-decisions:
  - "Only raw evidence observation timestamps and their storage digests may differ; the fixed phase2-v1 freshness window is independently validated before comparison."
  - "Candidate/source/target/policy/evidence semantics/quote/fee/economic values/accepted risk result remain exact TicketBinding requirements under D-10."
  - "Successful refreshed consumption records distinct evidence and assessment identities before conditional ticket consumption creates outbound authority."

patterns-established:
  - "Ticket refreshes must be authorization-equivalent, not merely fresh: any semantic evidence or risk mutation terminates the ticket."
  - "Refresh audit writes are part of the durable consume transaction, not a post-consumption best-effort action."

requirements-completed: [SAFE-02, SAFE-04, SIM-03]

coverage:
  - id: D1
    description: "A complete T0-to-T0+1 fresh evidence bundle with unchanged authorization semantics consumes one ticket exactly once and creates distinct persisted refresh audit facts."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_t0_to_t0_plus_one_equivalent_fresh_evidence_consumes_once"
        status: pass
    human_judgment: false
  - id: D2
    description: "Each D-10-protected candidate, source, target, policy, evidence, fee, economic, risk, and freshness mutation remains authorization-inequivalent."
    requirement: SAFE-02
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_authorization_equivalence_rejects_every_d10_binding_mutation"
        status: pass
      - kind: other
        ref: ".venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution"
        status: pass
    human_judgment: false
  - id: D3
    description: "A refreshed accepted assessment and evidence are append-only audit facts within the same immediate SQLite consume decision."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_t0_to_t0_plus_one_equivalent_fresh_evidence_consumes_once"
        status: pass
    human_judgment: false

metrics:
  duration: 5 min
  completed: 2026-07-12
status: complete
---

# Phase 02 Plan 16: Timestamp-Only Approval Refresh Summary

**Approval consumption now accepts only complete, fixed-window fresh evidence whose authorization semantics, economics, policy, target, candidate, and accepted risk result remain identical, while persisting the refresh as new audit facts.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-12T16:58:44Z
- **Completed:** 2026-07-12T17:04:40Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- Added RED real-SQLite coverage for a T0-to-T0+1 equivalently refreshed ticket, one-time outbound authority, distinct evidence/assessment audit rows, and D-10 mutation families.
- Added `TicketBinding.is_authorization_equivalent_to()` with explicit timestamp-free evidence semantics plus independent complete-window freshness validation.
- Made successful refresh evidence and accepted reassessment append-only facts inside the immediate transaction before conditional ticket consumption and outbound authorization.

## Task Commits

1. **Task 1: Specify explicit authorization-equivalence regressions** - `6fccba0` (`test`)
2. **Task 2: Implement the pure authorization-equivalence API and atomic refresh audit** - `c8abe74` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/approval.py` - Defines timestamp-free evidence semantics, complete observation freshness validation, and the named pure equivalence API.
- `pa_agent/trading/persistence/sqlite_ledger.py` - Uses semantic equivalence and records refresh evidence and risk facts before one conditional consume decision.
- `tests/integration/execution/test_approval_consumption.py` - Covers the T0/T0+1 success path, D-10 mutation matrix, and persisted refresh audit identities.

## Decisions Made

- The only ignored binding values are raw observation timestamps and timestamp-derived storage digests; data-age freshness remains independently enforced by the fixed policy window.
- The authorization-evidence digest excludes timestamps but preserves every other canonical evidence fact, so quote, capability, rule, account, fee, open-order, rate, and loss/drawdown changes remain invalidating.
- Existing presentation-only test helpers retain a minimal compatibility default, while all production issuance and consumption bindings provide the complete observation set.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_approval_consumption.py
# 29 passed

.venv/bin/ruff check pa_agent/trading/domain/approval.py pa_agent/trading/application/approval.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_approval_consumption.py
# All checks passed!

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test correctness] Preserve UTC-day boundary during T0+1 evidence refresh**
- **Found during:** Task 2 GREEN verification.
- **Issue:** The test fake advanced its UTC-day start timestamp by one second, which correctly triggered the pre-existing UTC-day validity guard instead of exercising authorization equivalence.
- **Fix:** Normalized the synthetic UTC-day start to midnight while advancing only the intended observation timestamps.
- **Files modified:** `tests/integration/execution/test_approval_consumption.py`
- **Verification:** Focused consumption suite, Ruff, and full offline execution corpus passed.
- **Committed in:** `c8abe74`

**2. [Rule 1 - Compatibility] Kept presentation-only TicketBinding builders usable**
- **Found during:** Task 2 full offline execution verification.
- **Issue:** Existing unit tests construct standalone review bindings without evidence bundles, so the new complete-observation parameters broke unrelated presentation assertions.
- **Fix:** Added a minimal default only to the public builder; production issuance and consumption continue to provide and verify complete observation timestamps.
- **Files modified:** `pa_agent/trading/domain/approval.py`
- **Verification:** Full offline execution corpus passed.
- **Committed in:** `c8abe74`

---

**Total deviations:** 2 auto-fixed (2 Rule 1 correctness/compatibility fixes).
**Impact on plan:** Both corrections preserve the strict authorization boundary. No candidate, target, policy, economic, risk, or outbound authority was broadened.

## Issues Encountered

None.

## Known Stubs

None.

## Threat Flags

None. The plan changes an existing local SQLite authorization boundary and introduces no new network endpoint, auth path, file-access pattern, or schema trust boundary.

## Next Phase Readiness

The approval boundary now distinguishes fresh observation time from authorization fact changes without weakening D-10. Subsequent dispatch-permit work can depend on one-time, fully audited ticket consumption.

## Self-Check: PASSED

- Verified `pa_agent/trading/domain/approval.py`, `pa_agent/trading/persistence/sqlite_ledger.py`, and `tests/integration/execution/test_approval_consumption.py` exist.
- Verified task commits `6fccba0` and `c8abe74` exist in git history.
- Scanned plan-modified files for placeholder and incomplete-value markers; none found.

---
*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*
