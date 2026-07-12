---
phase: 02-approval-and-risk-boundary
plan: 05
subsystem: trading-audit-ledger
tags: [python, sqlite, audit, proposal, risk, decimal, sha256, pytest]

requires:
  - phase: 02-01
    provides: Frozen candidate intents with stable source provenance and digests.
  - phase: 02-03
    provides: Target-bound risk policies, fee estimates, evidence bundles, and assessments.
  - phase: 02-04
    provides: Complete fresh evidence collection with controlled failure reasons.
provides:
  - Durable, queryable pre-ticket proposal, evidence, fee, and risk-audit facts.
  - Controlled conversion and risk rejection facts with stable reason codes and redacted summaries.
  - SQLite migration 2 with append-only audit tables, foreign keys, and audit query indexes.
affects: [approval-tickets, atomic-consumption, kill-switch, execution-audit]

tech-stack:
  added: []
  patterns:
    - Persist only canonical domain values, allowlisted summaries, and SHA-256 bindings at the proposal-to-ledger boundary.
    - Keep proposal conversion, evidence collection, and risk persistence separate from ticket issuance and outbound submission.

key-files:
  created:
    - pa_agent/trading/application/proposal.py
    - tests/integration/execution/test_intent_rejections.py
    - tests/integration/execution/test_approval_audit_ledger.py
  modified:
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py

key-decisions:
  - "ProposalService is the sole pre-ticket coordinator: it records conversion outcomes, collects fresh evidence once, and persists the resulting risk assessment without submission authority."
  - "SQLite audit rows retain stable source IDs and candidate/policy/evidence hashes, but summaries use an explicit allowlist and never persist gateway exception data or credentials."

requirements-completed: [SIM-03, SAFE-04]

coverage:
  - id: D1
    description: "Conversion and fresh-evidence failures survive SQLite reopen as independently queryable, reason-coded, redacted audit facts with no gateway submission."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_intent_rejections.py#test_conversion_and_evidence_rejections_survive_reopen_as_redacted_audit_facts
        status: pass
    human_judgment: false
  - id: D2
    description: "Accepted candidates, complete evidence, exact fee facts, and risk assessments persist before any ticket or outbound claim and retain foreign-key bindings after reopen."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: tests/integration/execution/test_approval_audit_ledger.py#test_accepted_candidate_evidence_fee_and_assessment_are_queryable_after_reopen
        status: pass
    human_judgment: false

metrics:
  duration: 12 min
  completed: 2026-07-12
status: complete
---

# Phase 02 Plan 05: Durable Proposal Audit Storage Summary

**SQLite now retains redacted, digest-bound conversion, evidence, fee, and risk facts before any approval ticket or outbound submission can exist.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-12T10:56:04Z
- **Completed:** 2026-07-12T11:08:41Z
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

- Added RED integration coverage for durable conversion/evidence/risk rejections and accepted pre-ticket audit facts after SQLite reopen.
- Added `ProposalService`, a ledger-owning coordinator that records candidates, complete fresh evidence, fixed-point fee results, and risk assessments without ticket or gateway authority.
- Added migration 2 with append-only proposal audit tables, foreign keys, indexes, canonical JSON, SHA-256 bindings, and controlled audit queries.

## Task Commits

1. **Task 1: Specify durable proposal, rejection, evidence, and assessment audit behavior** - `d879b3a` (`test`)
2. **Task 2: Implement proposal audit migration and ledger-port contract** - `af0df88` (`feat`)

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_intent_rejections.py tests/integration/execution/test_approval_audit_ledger.py
# 2 passed

.venv/bin/ruff check pa_agent/trading/ports/ledger.py pa_agent/trading/application/proposal.py pa_agent/trading/persistence/migrations.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_intent_rejections.py tests/integration/execution/test_approval_audit_ledger.py
# All checks passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# 138 passed
```

The proposal coordinator was statically checked to confirm it contains no admission, outbound-submission, or gateway-submit call.

## Decisions Made

- `ProposalService` performs the sole pre-ticket persistence sequence. It converts or records a controlled conversion rejection, collects fresh evidence once, and persists the associated risk result.
- Audit storage retains canonical hashes and selected safe metadata only. Raw gateway exception messages and secrets do not cross into SQLite records.
- The new persistence surface deliberately exposes no ticket consumption, command admission, `OutboundSubmission`, or gateway call; Plans 02-08 and 02-07 own those boundaries.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Canonicalized nested candidate provenance before hashing**
- **Found during:** Task 2
- **Issue:** Candidate provenance hashing attempted to serialize an aware `datetime` embedded in a mapping without canonicalization.
- **Fix:** Canonicalized the complete provenance material before deterministic JSON and SHA-256 hashing.
- **Files modified:** `pa_agent/trading/persistence/sqlite_ledger.py`
- **Verification:** Both focused SQLite audit tests pass after reopen.
- **Committed in:** `af0df88`

**2. [Rule 1 - Bug] Updated shared migration-history assertions for audit migration 2**
- **Found during:** Plan-level execution regression
- **Issue:** Existing concurrent bootstrap tests expected only migration 1, so adding the planned audit migration made their exact history assertion fail.
- **Fix:** Updated the shared-worktree assertions to require migrations 1 and 2 exactly once.
- **Files modified:** `tests/integration/execution/test_idempotency_recovery.py`
- **Verification:** Full execution suite passes (138 tests).
- **Commit:** Preserved in the pre-existing shared-tree test work; not force-staged into this plan's atomic implementation commit.

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs).
**Impact on plan:** Both corrections preserve deterministic audit and migration behavior without expanding execution authority.

## Issues Encountered

The shared main tree contained concurrent persistence and recovery work before this plan began. The implementation preserved that work while integrating the audit migration; unrelated application, connection, and recovery changes remain unstaged.

## Known Stubs

None.

## User Setup Required

None - no external service configuration, credentials, or network access is required.

## Next Phase Readiness

Plan 02-08 can issue a pending approval ticket only from durable candidate, evidence, and risk records. Plan 02-07 can then consume a valid ticket atomically without recreating these facts.

## Self-Check: PASSED

- Verified both audit integration test files and `pa_agent/trading/application/proposal.py` exist.
- Verified task commits `d879b3a` and `af0df88` exist in git history.
