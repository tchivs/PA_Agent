---
phase: 4
slug: local-trading-workspace
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-14
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-qt 4.5.0 |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_workspace.py` |
| **Full suite command** | `.venv/bin/python -m pytest -q -o addopts='' tests/unit/execution tests/integration/execution tests/e2e/execution` |
| **Estimated runtime** | ~90 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest -q -o addopts='' <touched-test-files>`.
- **After every plan wave:** Run `.venv/bin/python -m pytest -q -o addopts='' tests/unit/execution tests/integration/execution tests/e2e/execution`.
- **Before `/gsd:verify-work`:** The full focused Phase 4 suite must be green.
- **Max feedback latency:** 90 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-W0-01 | TBD | 0 | UI-01 | T-04-01 | Draft/applied non-secret settings, only-tightening policy contract, Paper-default validation DTOs | unit | `.venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_settings.py` | ❌ W0 | ⬜ pending |
| 04-W0-02 | TBD | 0 | UI-02 | T-04-04 | Immutable product projection has no risk or submit authority | unit | `.venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_projection.py` | ❌ W0 | ⬜ pending |
| 04-W0-03 | TBD | 0 | UI-03 | T-04-02 | Persisted record adapter strictly rejects stale, repaired, digest-mismatched, or Decimal-incomplete records | integration | `.venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_completed_analysis_snapshot_reader.py` | ❌ W0 | ⬜ pending |
| 04-W0-04 | TBD | 0 | UI-02 | T-04-04 | Reopened Paper and ledger state projects balances, orders, fills, reconciliation, and kill-switch truth | integration | `.venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_workspace_projection_reopen.py` | ❌ W0 | ⬜ pending |
| 04-W0-05 | TBD | 0 | UI-03 | T-04-02 | Workspace ticket commands remain permit → lease → coordinator only; alert/notification paths have no submit call | integration | `.venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_workspace_ticket_commands.py` | ❌ W0 | ⬜ pending |
| 04-W0-06 | TBD | 0 | UI-01 | T-04-01 | Configuration UI exposes Paper default, disabled targets, draft/applied distinction, and centralized readiness | pytest-qt e2e | `.venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_configuration.py` | ❌ W0 | ⬜ pending |
| 04-W0-07 | TBD | 0 | UI-02 | T-04-04 | Product sections render independent freshness and persisted kill-switch state from projections | pytest-qt e2e | `.venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_workspace.py` | ❌ W0 | ⬜ pending |
| 04-W0-08 | TBD | 0 | NFR-01 | T-04-01 / T-04-05 | Delayed workers do not block Qt; switched/closed workspaces ignore stale callbacks | pytest-qt e2e | `.venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_workspace_workers.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/execution/test_workspace_settings.py` — non-secret schema, only-tightening policy, draft/applied validation DTOs.
- [ ] `tests/unit/execution/test_workspace_projection.py` — immutable product-scoped projections and freshness mapping.
- [ ] `tests/integration/execution/test_completed_analysis_snapshot_reader.py` — strict persisted record adapter acceptance/rejection.
- [ ] `tests/integration/execution/test_workspace_projection_reopen.py` — reopened Paper/ledger projection truth.
- [ ] `tests/integration/execution/test_workspace_ticket_commands.py` — permit/lease/coordinator-only ticket commands.
- [ ] `tests/e2e/execution/test_trading_configuration.py` — Paper default, disabled modes, draft/applied, readiness.
- [ ] `tests/e2e/execution/test_trading_workspace.py` — product sections, freshness, persisted kill-switch state.
- [ ] `tests/e2e/execution/test_trading_workspace_workers.py` — delayed workers, event-loop heartbeat, switch/close stale callback rejection, no GUI-thread I/O.

Existing pytest, pytest-qt, and execution test infrastructure cover all framework prerequisites; no package-install Wave 0 task is needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Desktop width reflow at ≥1280px, 1024–1279px, and <1024px / <700px | UI-01, UI-02 | Qt layout composition and Chinese visual clipping require human visual review beyond deterministic widget tests. | Resize the workspace through the three thresholds; confirm state band and “保存并验证” remain reachable, numeric columns do not lose precision, and no Chinese control label is clipped. |

---

## Validation Sign-Off

- [x] All planned requirement behaviors have automated verification targets or Wave 0 dependencies.
- [x] Sampling continuity: every planned execution task must run a focused automated command.
- [x] Wave 0 covers all currently missing test references.
- [x] No watch-mode flags are used.
- [x] Feedback latency target is < 90 seconds.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** approved 2026-07-14
