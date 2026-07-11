---
phase: 01-execution-foundation
plan: 05
subsystem: trading-validation
tags: [python, decimal, validation, gateway, pytest, hypothesis]

requires:
  - phase: 01-01
    provides: Immutable canonical Decimal commands and instrument rules.
  - phase: 01-02
    provides: Canonical TradingGateway contract with typed gateway failures.
  - phase: 01-04
    provides: Constructor-injected application-service and deterministic gateway fake patterns.
provides:
  - Internal pure Decimal validation for immutable limit commands against canonical instrument rules.
  - A fresh-rule public validation boundary that never accepts caller-supplied metadata.
  - Deterministic offline proof of one lookup per validation attempt and no submission side effect.
affects: [approval-risk-boundary, paper-product-core, gateways]

tech-stack:
  added: []
  patterns:
    - Public validation fetches exactly one current RuleObservation immediately before internal validation.
    - Internal Decimal calculation remains underscored and side-effect free.
    - Scripted metadata fakes consume one typed response per request and reject submission.

key-files:
  created:
    - pa_agent/trading/application/validation.py
    - tests/unit/execution/test_order_validation.py
    - tests/property/execution/test_rule_validation_properties.py
    - tests/integration/execution/test_refresh_before_validation.py
  modified:
    - pa_agent/trading/domain/errors.py
    - tests/fixtures/fake_exchange.py

key-decisions:
  - "OrderValidationService.validate(command) owns the sole public typed-command boundary and does not accept rules or observations from callers."
  - "Market commands fail closed because canonical rules alone cannot establish their notional without a separately sourced price."
  - "Unavailable metadata propagates its typed gateway error without caching, retrying, or invoking the internal helper."

patterns-established:
  - "Refresh-before-validation: make one immediate gateway metadata lookup and pass only its rules to an internal pure helper."
  - "Validation safety fakes: record each metadata symbol, consume scripted results, and raise on any submit attempt."

requirements-completed: [NFR-02]

coverage:
  - id: D1
    description: "Pure internal Decimal validation accepts only exact limit tick and step multiples that satisfy quantity and notional minima."
    requirement: NFR-02
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_order_validation.py"
        status: pass
      - kind: other
        ref: "tests/property/execution/test_rule_validation_properties.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "OrderValidationService refreshes one current rule observation per attempt, fails closed, and never submits an order."
    requirement: NFR-02
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_refresh_before_validation.py"
        status: pass
    human_judgment: false

duration: 4 min
completed: 2026-07-11
status: complete
---

# Phase 01 Plan 05: Fresh Metadata Validation Summary

**Fresh gateway rule retrieval now gates every public Decimal order validation attempt without any order-submission path.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-11T09:15:05Z
- **Completed:** 2026-07-11T09:19:08Z
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

- Added `InstrumentRuleValidationError` and an internal pure Decimal helper that checks symbol scope, exact positive price tick, quantity step, minimum quantity, and minimum notional without modifying commands.
- Added `OrderValidationService.validate(command)` as the sole public typed-command validation entry point; it obtains exactly one current `RuleObservation` before delegating to the helper and retains no cache or fallback state.
- Added deterministic unit, Hypothesis property, and offline integration coverage for rule boundaries, fresh lookup ordering, unavailable and mismatched metadata, and zero submission calls.

## Task Commits

Each task followed the TDD cycle and was committed atomically:

1. **Task 1: Define internal pure Decimal instrument-rule calculation and deterministic boundary tests** - `cef4ac5` (test), `fd73a6d` (feat)
2. **Task 2: Enforce fresh metadata retrieval before every validation attempt** - `1534f83` (test), `9e86cbd` (feat)

**Plan metadata:** committed with this summary.

## Files Created/Modified

- `pa_agent/trading/domain/errors.py` - Adds the typed deterministic instrument-rule rejection.
- `pa_agent/trading/application/validation.py` - Provides the private Decimal helper and fresh-metadata validation service.
- `tests/fixtures/fake_exchange.py` - Adds a scripted metadata-only fake that records lookups and rejects submission.
- `tests/unit/execution/test_order_validation.py` - Covers deterministic internal validation boundaries.
- `tests/property/execution/test_rule_validation_properties.py` - Generates exact and fractional Decimal increment cases.
- `tests/integration/execution/test_refresh_before_validation.py` - Proves public signature, per-attempt ordering, no fallback, and zero submit calls.

## Decisions Made

- Kept all deterministic rule checks in an underscored helper so callers cannot supply or reuse `InstrumentRules` or `RuleObservation` through a public typed-command API.
- Rejected market commands at this boundary because their missing canonical price cannot prove the venue notional minimum without introducing an out-of-scope quote source.
- Propagated `GatewayUnavailableError` unchanged and did not add cache, TTL, retry, persistence, admission, recovery, approval, or submission behavior.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected stale sequential plan position**
- **Found during:** GSD tracking update after Task 2
- **Issue:** `STATE.md` still reported Plan 1 after four completed summaries, so one normal plan advance left the phase at Plan 2 instead of ready for verification.
- **Fix:** Used the required `state.advance-plan` handler until its last-plan guard set Phase 01 to `ready_for_verification`.
- **Files modified:** `.planning/STATE.md`
- **Verification:** `roadmap.update-plan-progress 01` reported five plans and five summaries with complete status.
- **Committed in:** Plan metadata commit

---

**Total deviations:** 1 auto-fixed (1 blocking tracking issue).
**Impact on plan:** No product code or scope changed; the correction restores accurate sequential GSD tracking.

## Issues Encountered

- The shell's default `PATH` did not expose `python`; the prescribed focused commands were run against the existing local `.venv` by prepending `.venv/bin` to `PATH`. No dependency, configuration, or tracked project file changed.

## Verification

Passed the prescribed focused commands using the existing project virtual environment:

```bash
python -m pytest tests/unit/execution/test_order_validation.py tests/property/execution/test_rule_validation_properties.py -q
# 9 passed

python -m pytest tests/integration/execution/test_refresh_before_validation.py -q
# 4 passed

python -m pytest tests/unit/execution/test_order_validation.py tests/property/execution/test_rule_validation_properties.py tests/integration/execution/test_refresh_before_validation.py -q
# 13 passed
```

The final suite proves one fresh command-symbol lookup before internal validation on every attempt, consumption of two separate observations across two attempts, unavailable metadata without helper fallback, cross-symbol rejection, exact Decimal rule enforcement, and zero submission calls.

## User Setup Required

None - no external service configuration or credentials are required.

## Next Phase Readiness

NFR-02 now has an enforced metadata-refresh boundary that later approval and risk services can compose without introducing a metadata cache or submission capability.

## Self-Check: PASSED

- Verified the summary, validation module, and all three focused test artifacts exist.
- Verified TDD task commits `cef4ac5`, `fd73a6d`, `1534f83`, and `9e86cbd` exist in git history.

---
*Phase: 01-execution-foundation*
*Completed: 2026-07-11*
