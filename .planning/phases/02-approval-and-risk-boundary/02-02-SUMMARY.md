---
phase: 02-approval-and-risk-boundary
plan: 02
subsystem: security
tags: [credentials, secret-redaction, pydantic, settings, safe-05]

requires:
  - phase: 02-01
    provides: immutable, advisory-only execution boundary
provides:
  - Reference-only credential lookup port with fixed trading-only capabilities
  - Recursive redaction for registered values and sensitive output shapes
  - Paper Spot-only non-secret trading settings
affects: [phase-02-risk, future-adapters, audit, notifications]

tech-stack:
  added: []
  patterns: [reference-only credential contract, centralized recursive redaction, non-secret nested settings]

key-files:
  created:
    - pa_agent/trading/ports/credential_store.py
    - pa_agent/trading/security/credentials.py
    - pa_agent/trading/security/redaction.py
    - tests/unit/execution/test_secret_redaction.py
    - tests/integration/execution/test_secret_nonpersistence.py
  modified:
    - pa_agent/config/settings.py
    - pa_agent/app_context.py

key-decisions:
  - "Credential references are immutable opaque metadata; resolved material crosses only the validated execution-facing handoff."
  - "Trading settings permit only Paper Spot and phase2-v1 while rejecting secret-like, Testnet, Live, and withdrawal-capable declarations."
  - "Recursive redaction replaces registered values and sensitive-key/query/exception content before output serialization."

patterns-established:
  - "Credential providers must prove trade-only permissions before any execution consumer receives their result."
  - "Trading-facing outputs use SecretRedactor instead of the analysis record writer's single-value sanitizer."

requirements-completed: [SAFE-05]

coverage:
  - id: D1
    description: "Credential references and provider results are trade-only, and withdrawal declarations fail before execution consumers receive credentials."
    requirement: SAFE-05
    verification:
      - kind: unit
        ref: tests/unit/execution/test_secret_redaction.py#test_withdrawal_capable_provider_result_is_rejected_before_execution_consumer
        status: pass
    human_judgment: false
  - id: D2
    description: "Registered secrets and sensitive nested output data are redacted before persisted payload serialization."
    requirement: SAFE-05
    verification:
      - kind: integration
        ref: tests/integration/execution/test_secret_nonpersistence.py#test_persisted_audit_payload_uses_recursive_redaction_before_serialization
        status: pass
    human_judgment: false
  - id: D3
    description: "Trading settings serialize only Paper Spot metadata and credential references."
    requirement: SAFE-05
    verification:
      - kind: integration
        ref: tests/integration/execution/test_secret_nonpersistence.py#test_settings_round_trip_persists_only_non_secret_trading_reference
        status: pass
    human_judgment: false

duration: 5 min
completed: 2026-07-12
status: complete
---

# Phase 02 Plan 02: Credential Reference And Secret Redaction Summary

**Reference-only trading credentials, fail-closed withdrawal rejection, recursive output redaction, and Paper Spot-only non-secret settings.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-12T10:26:52Z
- **Completed:** 2026-07-12T10:31:51Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Added a runtime-checkable credential-store port and frozen credential contracts that reject any withdrawal-capable reference or provider result before an execution-facing consumer can receive it.
- Added `SecretRedactor` for nested mappings, sequences, headers, query-like strings, signatures, exception payloads, sensitive field names, and registered secret values.
- Added strict, non-secret `TradingSettings` that persist only Paper Spot `phase2-v1` metadata and an optional credential reference.

## Task Commits

Each task was committed atomically:

1. **Task 1: Define credential-reference and recursive-redaction security tests** - `815d8d8` (test)
2. **Task 2: Implement credential references, redaction, and non-secret composition** - `baaabe2` (feat)

**Plan metadata:** committed with this summary and state update.

## Files Created/Modified

- `pa_agent/trading/ports/credential_store.py` - Runtime-checkable opaque-reference lookup protocol.
- `pa_agent/trading/security/credentials.py` - Frozen reference/result contracts, fail-closed permission checks, and unavailable/environment providers.
- `pa_agent/trading/security/redaction.py` - Central recursive secret redactor.
- `pa_agent/config/settings.py` - Strict Paper Spot-only trading settings and JSON-mode serialization.
- `pa_agent/app_context.py` - Exposes validated credential-reference metadata without injecting a provider or gateway.
- `tests/unit/execution/test_secret_redaction.py` - Unit tests for capability rejection and nested redaction.
- `tests/integration/execution/test_secret_nonpersistence.py` - Settings round-trip and safe-payload persistence tests.

## Decisions Made

- Credential material is never part of `Settings`; only the opaque `CredentialReference` serializes.
- Withdrawal is a non-grantable capability. Any request or provider declaration containing it is rejected before execution consumption.
- `save_settings()` uses Pydantic JSON mode so frozen permission sets serialize safely without widening persisted fields.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Serialized frozen credential permissions as JSON-safe values**
- **Found during:** Task 2 (non-secret settings implementation)
- **Issue:** The existing `Settings.model_dump()` left `CredentialReference.requested_permissions` as a `frozenset`, causing `json.dumps()` to fail during settings persistence.
- **Fix:** Switched settings serialization to `model_dump(mode="json")`.
- **Files modified:** `pa_agent/config/settings.py`
- **Verification:** Settings save/reload security test passes.
- **Committed in:** `baaabe2` (Task 2 commit)

---

**2. [Rule 1 - Bug] Repaired malformed execution state after CLI argument mismatch**
- **Found during:** Plan metadata update
- **Issue:** The installed `state.add-decision` handler interpreted a summary-file argument as literal decision text and inserted the whole summary into `STATE.md`.
- **Fix:** Restored the compact state structure, retained the completed plan/metric updates, and added the two actual decisions as concise entries.
- **Files modified:** `.planning/STATE.md`
- **Verification:** State remains under 150 lines and records Plan 3 of 8 with the Phase 02 Plan 02 metric.
- **Committed in:** plan metadata commit

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs).
**Impact on plan:** Both corrections preserve required persistence and execution metadata without changing the security boundary's scope.

## Issues Encountered

- The plan's broad Ruff command reports 44 pre-existing violations in `pa_agent/config/settings.py` and `pa_agent/app_context.py`, including existing non-ASCII-comment, import-placement, unused-import, and annotation rules. New security modules and new tests pass Ruff, and the complete execution test suite passes. The baseline lint findings are recorded in `deferred-items.md` without unrelated cleanup.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SAFE-05 now has tested non-persistence, redaction, and trade-only capability boundaries.
- Phase 02-03 can bind Paper Spot `phase2-v1` target policy to the new non-secret settings model.

---
*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*

## Self-Check: PASSED

- Verified the summary and all created security/test files exist.
- Verified task commits `815d8d8` and `baaabe2` exist in git history.
