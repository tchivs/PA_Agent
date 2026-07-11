---
phase: 01-execution-foundation
reviewed_range: c6afcc5^..8c8262b
status: issues_found
reviewed_at: 2026-07-11
---

# Phase 01 Code Review

## Scope and method

Reviewed all source and test changes delivered by `01-01-SUMMARY.md` through `01-04-SUMMARY.md`, plus `8c8262b`: 26 changed source/test files (2,720 added lines). The review traced the admission, ambiguity, recovery, evidence-application, lifecycle dispatch, migration, and SQLite transaction paths. No test suite was run, per review-only scope.

## Findings

### P1 — Revoke a claim when submission becomes ambiguous

**Evidence:** `create_or_load_and_claim_submission` persists the sole claim with `status = "admitted"` (`pa_agent/trading/persistence/sqlite_ledger.py:136-140`). When a submit timeout/cancellation/gap moves the command to `SUBMISSION_UNKNOWN`, `mark_submission_ambiguous` updates only `orders` and `reconciliation_jobs` (`:190-202`); it neither revokes the claim nor verifies it before accepting the transition. The original `SubmissionAdmission` consequently remains an admissible `SUBMITTING` authority with its token after an ambiguous gateway outcome.

**Impact and trigger:** A future coordinator can retain the original admission returned before its remote call, time out after possible venue acceptance, call `mark_submission_ambiguous`, then reuse that still-admissible authority for another `submit_order`. This permits a second remote submission for the same logical command exactly when recovery must preserve uncertainty. Revoke/consume the durable claim in the same transaction that records ambiguity, and require the submission boundary to validate that live claim status before every submit.

### P1 — Reject conflicting exchange-order identities

**Evidence:** `apply_reconciliation_evidence` verifies only the client ID and then writes `exchange_order_id = COALESCE(?, exchange_order_id)` (`pa_agent/trading/persistence/sqlite_ledger.py:256-291`). For any later legal observation with a non-null but different exchange ID, the first argument wins and overwrites the already persisted remote identity; no reconciliation incident is recorded.

**Impact and trigger:** Reconcile an uncertain command with acknowledged evidence carrying exchange ID `A`, then reconcile it with a legal open/fill/cancellation observation for the same client ID carrying `B`. The projection silently changes from `A` to `B`, corrupting the durable identity used for auditing and later reconciliation despite the phase contract requiring contradictory evidence to be retained without rewriting the projection. Load the current exchange ID, preserve it when the incoming value is absent/equal, and record an incident (without updating the projection) when both non-null values differ.

### P2 — Include command identity in fill-idempotency comparison

**Evidence:** `record_fill_evidence` reads only quantity, price, fee, asset, and timestamp for an existing `fill_id` (`pa_agent/trading/persistence/sqlite_ledger.py:332-344`). `command_id` is neither selected nor compared, so equal economic fields cause an immediate idempotent success (`:354-355`) even when the incoming fill assigns that fill ID to a different command.

**Impact and trigger:** After recording fill `F` for command `A`, a contradictory observation can assign fill `F` to command `B` with otherwise identical fields. The method returns `True` and records no incident, silently discarding a conflicting allocation between orders. Select and compare the stored `command_id` as part of the canonical evidence identity, and treat a mismatch as `contradictory_fill_evidence`.

## Test adequacy

The existing tests exercise repeated admission, restart recovery, exact duplicate fills, and selected out-of-order evidence, but none covers claim revocation after ambiguity, changing an established exchange-order ID, or reusing a fill ID for another command. Add focused integration coverage for all three failure paths.

## Conclusion

**Status: issues_found.** The SQLite setup, transactions, migration rollback, restart enumeration, lifecycle guard, and no-submit recovery path were reviewed. The three findings above break admission authority or durable reconciliation identity invariants and should be fixed before this phase is accepted.