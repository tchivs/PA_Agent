---
phase: 01-execution-foundation
plan: 06
subsystem: trading-contracts
tags: [python, decimal, dataclasses, execution, ledger, gateway, pytest, hypothesis]

requires:
  - phase: 01-05
    provides: Fresh canonical Decimal validation through the gateway rule-observation boundary.
provides:
  - Runtime-strict canonical execution commands, evidence, instrument rules, and typed account observations.
  - Ledger-owned durable identity and irreversible outbound-submission contract for future adapters.
  - A canonical gateway submit signature that cannot accept a free-floating command or revocable claim.
affects: [sqlite-ledger, execution-coordinator, recovery, paper-gateway, venue-adapters]

tech-stack:
  added: []
  patterns:
    - Exact enum and discriminated product-context runtime checks at public canonical ingress.
    - Ledger admission followed by atomic non-revocable outbound authorization before a future gateway call.
    - Explicit immutable ProductType-scoped account observations containing only Balance and Position tuples.

key-files:
  created: []
  modified:
    - pa_agent/trading/domain/models.py
    - pa_agent/trading/domain/errors.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/ports/gateway.py
    - pa_agent/trading/ports/__init__.py
    - tests/fixtures/execution_factories.py
    - tests/unit/execution/test_models.py
    - tests/property/execution/test_decimal_invariants.py
    - tests/unit/execution/test_gateway_contract.py

key-decisions:
  - "Public execution models reject raw enums and context lookalikes rather than normalizing untrusted runtime values."
  - "The ledger, not callers, owns durable client-ID allocation and transforms one admission into irreversible outbound authority."
  - "Future gateways accept only OutboundSubmission, while account persistence accepts only typed canonical observations."

patterns-established:
  - "Strict ingress: use CanonicalInputError for malformed public runtime shapes before Decimal or downstream validation."
  - "Protected outbound chain: admission -> begin_outbound_submission -> gateway submit; recovery remains lookup-only."

requirements-completed: [CORE-01, CORE-02, SIM-02, NFR-02]

coverage:
  - id: D1
    description: "Strict canonical execution ingress rejects raw/wrong enums, invalid product contexts, malformed evidence, negative rule minima, and untyped account observations."
    requirement: CORE-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_models.py"
        status: pass
      - kind: other
        ref: "tests/property/execution/test_decimal_invariants.py"
        status: pass
      - kind: unit
        ref: "tests/unit/execution/test_order_validation.py"
        status: pass
      - kind: other
        ref: "tests/property/execution/test_rule_validation_properties.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Ledger-generated identity, irreversible outbound authorization, typed observation persistence, and protected gateway submit contracts."
    requirement: CORE-02
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_gateway_contract.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Canonical typed observations and no-submission boundary remain available for durable SQLite implementation in the dependent repair plan."
    requirement: SIM-02
    verification:
      - kind: other
        ref: ".venv/bin/python -m pytest tests/unit/execution/test_models.py tests/property/execution/test_decimal_invariants.py tests/unit/execution/test_gateway_contract.py tests/unit/execution/test_order_validation.py tests/property/execution/test_rule_validation_properties.py -q"
        status: pass
    human_judgment: false

metrics:
  duration: 5 min
  completed: 2026-07-11
status: complete
---

# Phase 01 Plan 06: Strict Canonical and Durable Outbound Contracts Summary

**Runtime-strict canonical execution ingress with ledger-owned durable identities and irreversible gateway submission authority, all verified offline.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-11T10:51:44Z
- **Completed:** 2026-07-11T10:56:31Z
- **Tasks:** 2/2
- **Files modified:** 9

## Accomplishments

- Made `ExecutionCommand`, `GatewayEvidence`, `InstrumentRules`, and `AccountObservation` fail closed for malformed runtime types while preserving exact `Decimal` construction and zero-as-no-minimum semantics.
- Replaced the revocable claim-check contract with ledger-generated client identity documentation, `OutboundSubmission`, atomic `begin_outbound_submission`, and typed account-observation persistence contracts.
- Changed `TradingGateway.submit_order` to require only the irreversible ledger-created authorization; no concrete gateway, adapter, network transport, credential handling, UI path, or real submission was introduced.

## Task Commits

1. **Task 1: Make all public canonical execution ingress runtime-strict**
   - `d15ba9b97b630e313474d790724ecaee8dcaec09` — `test(01-06): add failing strict ingress tests`
   - `a398c4a924bfa8a22fc9c4a6ada47bcece5b294a` — `feat(01-06): enforce strict canonical execution ingress`
2. **Task 2: Publish generated-identity and non-revocable outbound contracts**
   - `ec1b7b6dd0bba3bdee15c1ebe750bd0559df49ce` — `test(01-06): add failing durable outbound contract tests`
   - `c7d2715f0ed7ad1fdb74ada3bdacf5603665a4c1` — `feat(01-06): publish protected outbound contracts`

## Files Created/Modified

- `pa_agent/trading/domain/errors.py` — Defines `CanonicalInputError` for invalid public runtime shapes.
- `pa_agent/trading/domain/models.py` — Enforces exact enum/context types, typed evidence, non-negative minima, and immutable canonical account observations.
- `pa_agent/trading/ports/ledger.py` — Publishes durable admission, protected outbound authorization, and typed-observation port contracts.
- `pa_agent/trading/ports/gateway.py` — Requires `OutboundSubmission` for future gateway submission.
- `pa_agent/trading/ports/__init__.py` — Exports the ledger and protected outbound contract types.
- `tests/fixtures/execution_factories.py` — Supplies deterministic typed account observations.
- `tests/unit/execution/test_models.py` — Covers fail-closed runtime ingress behavior.
- `tests/property/execution/test_decimal_invariants.py` — Generates negative rule-minimum rejection cases without weakening Decimal behavior.
- `tests/unit/execution/test_gateway_contract.py` — Verifies generated-ID, protected-submit, and typed-observation port signatures.

## Decisions Made

- Preserved `ExecutionCommand.client_order_id` only as a non-authoritative caller candidate pending the concrete ledger cutover in Plan 07.
- Kept the gateway abstract and synchronous; recovery retains only persisted identity/evidence lookup responsibility.
- Kept account observations ProductType-scoped and tuple-backed to exclude arbitrary payload maps, raw venue fields, lists, and unsupported nested values.

## Verification

Passed the plan-prescribed offline focused suite:

```bash
.venv/bin/python -m pytest tests/unit/execution/test_models.py tests/property/execution/test_decimal_invariants.py tests/unit/execution/test_gateway_contract.py tests/unit/execution/test_order_validation.py tests/property/execution/test_rule_validation_properties.py -q
# 36 passed
```

Targeted source scan found no `requests`, `httpx`, `urllib`, `socket`, `websocket`, credential/API-key, PyQt, or GUI imports in the changed domain and port files. The only gateway class remains abstract `TradingGateway`; no adapter, network, credential, UI, or real submission implementation was added.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration or credentials are required.

## Next Phase Readiness

Plan 07 can implement the durable SQLite behavior against strict canonical ingress and the single protected outbound contract without adding a second identity or stale claim-check path.

## Self-Check: PASSED

- Verified all changed domain and port artifacts plus this summary exist.
- Verified task commits `d15ba9b`, `a398c4a`, `ec1b7b6`, and `c7d2715` exist in git history.
