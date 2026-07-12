---
phase: 02-approval-and-risk-boundary
plan: 15
subsystem: security
tags: [safe-05, secret-redaction, sqlite, logging, notifications, records]

requires:
  - phase: 02-02
    provides: credential-reference contract and recursive SecretRedactor
  - phase: 02-13
    provides: current SQLite approval and risk audit boundary
provides:
  - One registered-secret output boundary for all actual trading-adjacent producers
  - Controlled credential failure reasons and redacted SQLite audit serialization
  - End-to-end production-path scans of SQLite, logging, notifications, JSON, and CSV
affects: [phase-02-verification, notifications, records, audit]

tech-stack:
  added: []
  patterns: [process-wide registered SecretRedactor, redacted canonical audit serialization, controlled credential reason codes]

key-files:
  created: []
  modified:
    - pa_agent/trading/security/redaction.py
    - pa_agent/trading/security/credentials.py
    - pa_agent/trading/application/proposal.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - pa_agent/util/logging.py
    - pa_agent/records/pending_writer.py
    - pa_agent/records/trade_logger.py
    - pa_agent/notify/feishu_notifier.py
    - pa_agent/notify/pushplus_notifier.py
    - tests/unit/execution/test_secret_redaction.py
    - tests/integration/execution/test_secret_nonpersistence.py

key-decisions:
  - "Resolved credential values register with one process-wide SecretRedactor before validation can emit a public failure."
  - "Credential failures use stable controlled reason codes; proposal/audit storage only writes redacted canonical values."
  - "Notification transport remains advisory-only and receives sanitized decision content without gateway or submission imports."

requirements-completed: [SAFE-05, SIM-03]

coverage:
  - id: D1
    description: "Credential delivery and unavailable-store failures expose controlled reasons without resolved or caller-provided secret material."
    requirement: SAFE-05
    verification:
      - kind: unit
        ref: tests/unit/execution/test_secret_redaction.py#test_credential_failure_exposes_only_a_controlled_reason_code
        status: pass
      - kind: unit
        ref: tests/unit/execution/test_secret_redaction.py#test_unavailable_credential_store_exposes_only_a_controlled_reason_code
        status: pass
    human_judgment: false
  - id: D2
    description: "ProposalService and SQLite persist redacted canonical audit facts without synthetic credential material."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_secret_nonpersistence.py#test_proposal_service_and_sqlite_audit_do_not_persist_injected_secret_material
        status: pass
    human_judgment: false
  - id: D3
    description: "Logging, record files, and both notification payloads exclude registered synthetic secrets."
    requirement: SAFE-05
    verification:
      - kind: integration
        ref: tests/integration/execution/test_secret_nonpersistence.py
        status: pass
    human_judgment: false

duration: 20 min
completed: 2026-07-12
status: complete
---

# Phase 02 Plan 15: Production Output Secret Redaction Summary

**Unified registered-secret redaction now protects credential failures, durable audit facts, root logs, generated records, and advisory notification payloads.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-07-12T19:36:00Z
- **Completed:** 2026-07-12T19:56:00Z
- **Tasks:** 3
- **Files modified:** 11

## Accomplishments

- Registered credential material before public validation can fail, replacing observable failure text with stable reason codes.
- Redacted proposal and SQLite audit serialization while preserving canonical append-only audit and existing transaction checks.
- Routed every actual output producer in the plan inventory through the same output boundary and proved it with offline real-artifact scans.

## Production Output Scan

| Actual producer | Sanitized production path | End-to-end scan result |
| --- | --- | --- |
| `deliver_trading_credentials()` | Registers every resolved value before validation; emits `credential_permission_rejected` only. | PASS: API key, secret, and passphrase absent from the public failure. |
| `UnavailableCredentialStore.resolve()` | Emits `credential_provider_unavailable` without rendering the reference. | PASS: provider/reference-shaped synthetic values absent. |
| `ProposalService` -> `SQLiteExecutionLedger` | Shared redactor protects canonical candidate, evidence, assessment, source, and allowlisted audit JSON. | PASS: SQLite bytes and `proposal_audit_facts.summary_json` contain none of the injected values. |
| `MaskingFormatter` | Formats first, then applies the shared redactor to message and exception text. | PASS: captured formatted root-log representation contains no injected values. |
| `PendingWriter` | Sanitizes full/partial JSON and follow-up serialization before disk output. | PASS: generated pending JSON contains no injected values. |
| `save_trade_record()` | Sanitizes decision inputs before CSV construction and redacts diagnostic exceptions. | PASS: generated CSV contains no injected values. |
| `feishu_notifier.send_order_signal()` | Sanitizes decision-derived card content and transport result/error diagnostics. | PASS: captured Feishu request payload contains no injected values. |
| `pushplus_notifier.send_order_signal()` | Sanitizes decision-derived HTML before `send_pushplus_raw()` and redacts response/error diagnostics. | PASS: captured PushPlus request payload contains no injected values. |

No producer imports a gateway, ledger admission, approval, command, claim, or submission capability. Both notification routes remain advisory-only.

## Task Commits

1. **Task 1: Specify complete production-output secret non-retention regressions** - `3ae2aa4` (test)
2. **Task 2: Enforce centralized redaction at credential and SQLite audit boundaries** - `530d1dc` (feat)
3. **Task 3: Wire logging, notifications, and generated record writers to the same output boundary** - `3a5aa2d` (feat)

## Verification

- PASS: `.venv/bin/pytest -q tests/unit/execution/test_secret_redaction.py tests/integration/execution/test_secret_nonpersistence.py` (20 tests).
- PASS: `.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution` (205 tests).
- BLOCKED BY BASELINE: the exact plan Ruff command was run and returned 129 pre-existing violations in the legacy notification/record/logging modules, dominated by existing `RUF001/2/3`, `UP`, `E741`, and stale `noqa` issues. The newly introduced security and test changes were checked during implementation; no package or framework change was needed.

## Decisions Made

- Use one process-wide redactor so credential resolution can register values before they reach every downstream output sink.
- Keep notification transport credentials functional but prevent analysis-derived secret material from entering business content, diagnostics, or captured payloads.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Protected unavailable credential-store failures**
- **Found during:** Task 3 producer inventory review.
- **Issue:** `UnavailableCredentialStore.resolve()` embedded the caller-provided provider value in its exception message.
- **Fix:** Replaced the rendered reference with `credential_provider_unavailable` and added a direct producer regression.
- **Files modified:** `pa_agent/trading/security/credentials.py`, `tests/unit/execution/test_secret_redaction.py`
- **Verification:** Controlled-reason regression and full focused security suite pass.
- **Committed in:** `3a5aa2d`

**Total deviations:** 1 auto-fixed (1 Rule 2 missing critical output boundary).
**Impact on plan:** The fix closes the second credential-failure producer specified in the plan without expanding authority or persistence scope.

## Issues Encountered

- The required Ruff command was executed but cannot pass without unrelated cleanup of 129 pre-existing violations in legacy modules. This plan does not alter their language, broad style, or historical lint configuration; the security tests and complete offline execution corpus pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SAFE-05 now has production-path evidence across every output producer enumerated by Plan 02-15.
- The remaining Phase 02 gap-closure plans can rely on redacted output boundaries without gaining execution authority.

---
*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*

## Self-Check: PASSED

- Verified all modified producer modules and both test files exist.
- Verified task commits `3ae2aa4`, `530d1dc`, and `3a5aa2d` exist in git history.
