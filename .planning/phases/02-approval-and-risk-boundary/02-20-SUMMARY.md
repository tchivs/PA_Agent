---
phase: 02-approval-and-risk-boundary
plan: 20
subsystem: security
tags: [safe-05, logging, redaction, formatter, file-handler]

requires:
  - phase: 02-15
    provides: centralized SecretRedactor and registered-secret output boundaries
provides:
  - Safe LogRecord copies that redact message arguments before standard logging interpolation
  - Controlled exception rendering that cannot reuse raw cached exception text
  - Real FileHandler regressions for normalized exception inputs
affects: [phase-02-verification, logging, secret-redaction]

tech-stack:
  added: []
  patterns: [copy-before-formatting, controlled-exception-rendering, recursive-output-redaction]

key-files:
  created: []
  modified:
    - pa_agent/trading/security/redaction.py
    - pa_agent/util/logging.py
    - tests/integration/execution/test_secret_nonpersistence.py

key-decisions:
  - "MaskingFormatter copies and sanitizes each LogRecord before Formatter interpolation so handlers cannot mutate or leak through the shared record."
  - "Exception output retains the original exception class name and traceback structure but replaces the value with a fixed reason code and REDACTION_TOKEN."

patterns-established:
  - "Any output formatter handling untrusted logging records must sanitize a record copy before calling standard formatting."
  - "Cached formatter fields such as exc_text must be explicitly cleared on secure record copies."

requirements-completed: [SAFE-05]

coverage:
  - id: D1
    description: "A real logger and FileHandler path redacts unregistered nested authorization and signature values before interpolation."
    requirement: SAFE-05
    verification:
      - kind: integration
        ref: tests/integration/execution/test_secret_nonpersistence.py#test_masking_formatter_redacts_shared_records_before_file_output
        status: pass
    human_judgment: false
  - id: D2
    description: "Pre-filled raw exception text and bare exception secrets cannot reach protected file output for true, exception-instance, or explicit-tuple exc_info inputs."
    requirement: SAFE-05
    verification:
      - kind: integration
        ref: tests/integration/execution/test_secret_nonpersistence.py#test_masking_formatter_redacts_shared_records_before_file_output
        status: pass
    human_judgment: false

duration: 3 min
completed: 2026-07-12
status: complete
---

# Phase 02 Plan 20: Pre-Interpolation Logging Redaction Summary

**Safe LogRecord copies now remove nested unknown secrets and cached exception text before the standard formatter can serialize a protected file log.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-07-12T17:50:54Z
- **Completed:** 2026-07-12T17:54:08Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added a parameterized production-shaped regression that formats one shared record with an ordinary formatter before sending it through an independent logger and real `FileHandler` protected by `MaskingFormatter`.
- Recursively redact copied `msg` and `args` before interpolation, including nested mapping and list values carrying unregistered authorization or signature fields.
- Replace every exception representation handed to the standard formatter with a controlled type, `logging_exception_redacted`, and `REDACTION_TOKEN`; copied records clear inherited `exc_text` and never expose the original exception value.

## Task Commits

1. **Task 1: Specify the multi-handler file regression for cached exception text** - `e6cbd37` (test)
2. **Task 2: Sanitize logging records before interpolation and exception rendering** - `b649f3d` (feat)

## Files Created/Modified

- `pa_agent/trading/security/redaction.py` - Recognizes sensitive header, repr, and key-value string shapes through the centralized redactor.
- `pa_agent/util/logging.py` - Creates an isolated sanitized record and controlled exception tuple before standard formatter execution.
- `tests/integration/execution/test_secret_nonpersistence.py` - Verifies actual on-disk handler output for `True`, exception-instance, and tuple `exc_info` inputs.

## Decisions Made

- Preserve ordinary safe message fields and exception class names, while redacting all exception values with a stable controlled reason code.
- Retain only standard traceback structure associated with the safe exception object; raw exception values, arguments, and cached `exc_text` do not cross the formatter boundary.

## Verification

- PASS: `.venv/bin/pytest -q tests/integration/execution/test_secret_nonpersistence.py` (15 tests).
- PASS: `.venv/bin/ruff check pa_agent/trading/security/redaction.py pa_agent/util/logging.py tests/integration/execution/test_secret_nonpersistence.py`.
- PASS: `.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution` (240 tests).
- BASELINE ONLY: `.venv/bin/ruff check .` reports 4484 unrelated repository-wide legacy violations; the scoped Plan 02-20 Ruff gate is clean. Recorded in `deferred-items.md` without unrelated source changes.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None. The modified production modules have no placeholder output paths; existing empty values in unrelated integration fixtures are intentional test inputs and are not used by this logging regression.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SAFE-05 has real disk-output proof that unknown structured secrets, keyless exception secrets, and prior-handler cached exception text cannot enter protected logs.
- The repository-wide Ruff baseline requires a separate cleanup task but does not block this plan's scoped security gate.

---
*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*

## Self-Check: PASSED

- Verified `pa_agent/trading/security/redaction.py`, `pa_agent/util/logging.py`, and `tests/integration/execution/test_secret_nonpersistence.py` exist.
- Verified task commits `e6cbd37` and `b649f3d` exist in git history.
