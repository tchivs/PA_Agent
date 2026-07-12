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
| 02-05-01 | 02-05 | 4 | SIM-03 | T-02-09 | Controlled proposal, conversion/evidence rejection, and risk-audit records survive reopen with source/policy/evidence digests and controlled summaries. | integration | `.venv/bin/pytest -q tests/integration/execution/test_intent_rejections.py tests/integration/execution/test_approval_audit_ledger.py` | No W0 | pending |
| 02-05-02 | 02-05 | 4 | SAFE-04 | T-02-10, T-02-11, T-02-13 | Complete `phase2-v1` tickets disclose all review facts, expire at 60 seconds, and become non-current on changed or fee-unverifiable evidence. | unit | `.venv/bin/pytest -q tests/unit/execution/test_approval_ticket.py` | No W0 | pending |
| 02-07-01 | 02-07 | 5 | SIM-03, SAFE-04 | T-02-03, T-02-10 | A current ticket is consumed once with command binding and outbound authority in one transaction; duplicate, failed, expired, changed, and reopened attempts have no gateway call. | integration | `.venv/bin/pytest -q tests/integration/execution/test_approval_consumption.py` | No W0 | pending |
| 02-06-01 | 02-06 | 6 | SAFE-03, SIM-03 | T-02-04, T-02-12 | A persisted latch blocks new work across restart, revokes pending tickets, records cancellation work only for capability-cancellable canonical open orders, and requires processed work plus fresh canonical account/open-order/position evidence, no unresolved submission claim/residual exposure, assessment, and explicit recovery. | integration + property | `.venv/bin/pytest -q tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py` | No W0 | pending |

*Status: pending, green, red, flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/execution/test_intent_factory.py` - conversion contract and rejection reason codes.
- [ ] `tests/unit/execution/test_execution_target_policy.py`, `test_risk_engine.py`, `test_approval_ticket.py`, and `test_secret_redaction.py` - pure domain and policy behavior.
- [ ] `tests/integration/execution/test_intent_rejections.py`, `test_approval_audit_ledger.py`, `test_fresh_evidence_risk.py`, `test_approval_consumption.py`, `test_kill_switch.py`, and `test_secret_nonpersistence.py` - SQLite atomicity, restart, and fake-gateway behavior.
- [ ] `tests/property/execution/test_approval_kill_switch_machine.py` - ticket, latch, and restart interleavings.
- [ ] Extend `tests/fixtures/fake_exchange.py` with scripted canonical capability, rule, account, quote, time, and connection observations; assert zero real network access.

---

## Manual-Only Verifications

All phase behaviors have automated verification. Future real credential-store backend selection and external venue validation are explicitly deferred to the respective adapter phases.

---

## Validation Sign-Off

- [x] All tasks have automated verification or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verification
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
