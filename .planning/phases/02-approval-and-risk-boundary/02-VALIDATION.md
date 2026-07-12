---
phase: 02
slug: approval-and-risk-boundary
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-12
---

# Phase 02 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Pytest 9.1.1 and Hypothesis |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.venv/bin/pytest -q tests/unit/execution` |
| **Full suite command** | `.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest -q tests/unit/execution`
- **After every plan wave:** Run `.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution`
- **Before every plan completion:** Run `.venv/bin/ruff check` against that plan's declared Python files.
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 02-01 | 1 | CORE-03 | T-02-01 | Invalid, repaired, ambiguous, or unsupported analysis records are rejected at the snapshot boundary and have no gateway authority. | unit | `.venv/bin/pytest -q tests/unit/execution/test_intent_factory.py` | No W0 | pending |
| 02-02-01 | 02-02 | 1 | SAFE-05 | T-02-05, T-02-14 | Generic settings, audit events, logging, notification payloads, exceptions, and test artifacts retain no synthetic secrets; references/providers declaring withdrawal permission fail closed before an execution-facing consumer. | unit + integration | `.venv/bin/pytest -q tests/unit/execution/test_secret_redaction.py tests/integration/execution/test_secret_nonpersistence.py` | No W0 | pending |
| 02-03-01 | 02-03 | 2 | SAFE-01, SAFE-02 | T-02-02 | `phase2-v1` permits only Paper Spot MARKET/LIMIT and enforces 1000 USDT notional, 3 open orders, 5 accepted orders per rolling 60 seconds, 100 USDT UTC-day realized loss, 10 percent UTC-day drawdown, and bound fee-rate inputs; non-Paper and unsupported products reject before ticket creation. | unit | `.venv/bin/pytest -q tests/unit/execution/test_execution_target_policy.py tests/unit/execution/test_risk_engine.py` | No W0 | pending |
| 02-04-01 | 02-04 | 3 | SAFE-01, SAFE-02 | T-02-02 | Every assessment refreshes target-bound capability, rule, account, quote, clock, connectivity, account counters, and fee-rate evidence; invalid evidence yields no submit attempt. | integration | `.venv/bin/pytest -q tests/integration/execution/test_fresh_evidence_risk.py` | No W0 | pending |
| 02-05-01 | 02-05 | 4 | SIM-03 | T-02-09, T-02-08 | Controlled proposal, conversion/evidence rejection, complete fresh evidence, fee, and risk-audit records survive reopen with source/policy/evidence digests and controlled summaries. | integration | `.venv/bin/pytest -q tests/integration/execution/test_intent_rejections.py tests/integration/execution/test_approval_audit_ledger.py` | No W0 | pending |
| 02-08-01 | 02-08 | 5 | SIM-03, SAFE-04 | T-02-10, T-02-11, T-02-13 | After candidate, complete fresh evidence, and accepted risk are durable, the proposal workflow verifies only their persisted identities, controlled summaries, and hashes to create exactly one pending `phase2-v1` ticket; no collector refresh, risk reassessment, ledger admission, `OutboundSubmission`, or gateway call occurs. | unit + integration | `.venv/bin/pytest -q tests/unit/execution/test_approval_ticket.py tests/integration/execution/test_approval_ticket_issuance.py` | No W0 | pending |
| 02-07-01 | 02-07 | 6 | SIM-03, SAFE-02, SAFE-04 | T-02-03, T-02-10 | Every consumption attempt refreshes all required evidence and reruns risk; expiry, refresh failure, or any source/target/policy/evidence/quote/data-age/risk mismatch transactionally writes the 02-08-owned terminal ticket event and returns non-consumable with no claim, `OutboundSubmission`, or gateway call. Only a current matching ticket is consumed once with command binding and outbound authority. | integration | `.venv/bin/pytest -q tests/integration/execution/test_approval_consumption.py` | No W0 | pending |
| 02-06-01 | 02-06 | 7 | SAFE-03, SIM-03 | T-02-04, T-02-12 | A persisted latch blocks new work across restart, revokes pending tickets, records cancellation work only for capability-cancellable canonical open orders, and requires processed work plus fresh canonical account/open-order/position evidence, no unresolved submission claim/residual exposure, assessment, and explicit recovery. | integration + property | `.venv/bin/pytest -q tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py` | No W0 | pending |

*Status: pending, green, red, flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/execution/test_intent_factory.py` - conversion contract and rejection reason codes.
- [ ] `tests/unit/execution/test_execution_target_policy.py`, `test_risk_engine.py`, `test_approval_ticket.py`, and `test_secret_redaction.py` - pure domain and policy behavior.
- [ ] `tests/integration/execution/test_intent_rejections.py`, `test_approval_audit_ledger.py`, `test_fresh_evidence_risk.py`, `test_approval_consumption.py`, `test_kill_switch.py`, and `test_secret_nonpersistence.py` - SQLite atomicity, restart, and fake-gateway behavior.
- [ ] `tests/integration/execution/test_approval_ticket_issuance.py` - durable auto-issuance of exactly one pending ticket after persisted accepted proposal facts, with no admission or gateway side effect.
- [ ] `tests/property/execution/test_approval_kill_switch_machine.py` - ticket, latch, and restart interleavings.
- [ ] Extend `tests/fixtures/fake_exchange.py` with scripted canonical capability, rule, account, quote, time, and connection observations; assert zero real network access.

---

## Manual-Only Verifications

All phase behaviors have automated verification. Future real credential-store backend selection and external venue validation are explicitly deferred to the respective adapter phases.

---

## Source Coverage Audit

| Source | ID | Feature or constraint | Plan | Status | Notes |
|--------|----|-----------------------|------|--------|-------|
| GOAL | - | Advisory analysis reaches a durable, risk-accepted, operator-approved command without advisory submission authority. | 02-01, 02-04, 02-05, 02-08, 02-07 | COVERED | Conversion, fresh risk, durable audit, pending ticket, then sole authorization are ordered boundaries. |
| REQ | CORE-03 | Deterministic, fail-closed conversion from analysis recommendation. | 02-01, 02-05 | COVERED | Typed conversion and durable rejection audit. |
| REQ | SIM-03 | Durable proposed, approved, rejected, submitted, terminal, and uncertain events with source metadata. | 02-05, 02-08, 02-07, 02-06 | COVERED | Audit, ticket, consumption, and kill-switch events are persistent. |
| REQ | SAFE-01 | Paper default with explicit mode/product state. | 02-01, 02-02, 02-03, 02-04 | COVERED | Only Paper Spot is selectable in Phase 2. |
| REQ | SAFE-02 | Fresh product-aware deterministic risk controls before approval. | 02-03, 02-04, 02-05, 02-07 | COVERED | Policy, evidence, persisted assessment, then consumption-time refresh and re-assessment. |
| REQ | SAFE-03 | Persisted latched kill switch with cautious recovery. | 02-06 | COVERED | Final safety boundary after consumption path exists. |
| REQ | SAFE-04 | Full, single-use, expiring operator approval. | 02-08, 02-07 | COVERED | Pending review ticket then atomic one-time consumption. |
| REQ | SAFE-05 | Reference-only credentials and redacted outputs. | 02-02 | COVERED | No real credential backend or secret persistence. |
| RESEARCH | - | No package installation; SQLite immediate transactions, canonical immutable values, and only `OutboundSubmission` may reach a gateway. | 02-01 through 02-08 | COVERED | Each plan has an installation disposition and preserves the protected submission boundary. |
| RESEARCH | - | `phase2-v1`, 60-second ticket TTL, Paper Spot-only policy, evidence freshness, and capability-aware kill recovery. | 02-03, 02-04, 02-08, 02-06 | COVERED | Resolved policy decisions are explicit in tasks and tests. |
| CONTEXT | D-01 | Complete, executable completed analysis is the only candidate source. | 02-01 | COVERED | Snapshot and candidate contract. |
| CONTEXT | D-02 | Invalid inputs create durable reason-coded rejection with no command or gateway call. | 02-01, 02-05 | COVERED | Conversion and audit persistence are separately tested. |
| CONTEXT | D-03 | Candidate binds stable source ID, completion time, and immutable decision snapshot/version. | 02-01 | COVERED | Frozen canonical hashes. |
| CONTEXT | D-04 | Persisted eligible proposal automatically creates a pending ticket without submission authority. | 02-08 | COVERED | Exact-one auto-issuance and no-submit integration assertions. |
| CONTEXT | D-05 | Every assessment refreshes full target evidence. | 02-04 | COVERED | Complete collector call sequence. |
| CONTEXT | D-06 | Risk acceptance and ticket have fixed short validity; expiry requires re-evaluation. | 02-08, 02-07 | COVERED | 02-08 fixes the 60-second lifecycle; 02-07 refreshes the complete evidence set and reruns risk before consumption. |
| CONTEXT | D-07 | Any evidence failure is persistently rejected. | 02-04, 02-05 | COVERED | Fail-closed collection and controlled audit. |
| CONTEXT | D-08 | Thresholds bind to selected target and product strategy. | 02-03, 02-04 | COVERED | Exact target policy and evidence alignment. |
| CONTEXT | D-09 | Ticket displays complete execution/risk review facts. | 02-08 | COVERED | Review summary test contract. |
| CONTEXT | D-10 | Any binding change invalidates ticket. | 02-08, 02-07 | COVERED | 02-08 owns durable lifecycle invalidation; 02-07 detects runtime binding changes after refreshed evidence/risk and invokes it transactionally. |
| CONTEXT | D-11 | Approval is atomically consumed once with the persisted command. | 02-07 | COVERED | Sole outbound authorization owner. |
| CONTEXT | D-12 | Reject, expire, and kill revocation are distinct durable terminal events. | 02-08, 02-06 | COVERED | Lifecycle and latch-specific audit events. |

---

## Validation Sign-Off

- [x] All tasks have automated verification or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verification
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
