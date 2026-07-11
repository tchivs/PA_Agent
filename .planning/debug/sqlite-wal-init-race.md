---
status: diagnosed
trigger: "Diagnose UAT test 6 in Phase 01: Atomic one-claim admission that survives restart, serializes concurrent repeats, and preserves contradictory fill evidence. Investigate pa_agent/trading/persistence/sqlite_connection.py, SQLiteExecutionLedger construction, and tests/integration/execution/test_idempotency_recovery.py::test_concurrent_admissions_produce_exactly_one_admissible_claim. Non-goal: implement fixes."
created: 2026-07-11T10:26:00Z
updated: 2026-07-11T10:29:16Z
---

## Current Focus

hypothesis: Confirmed: concurrent `SQLiteExecutionLedger.__init__` calls race while changing the persistent journal mode and beginning schema bootstrap; the UAT failure occurs at WAL configuration before any admission transaction.
test: ran the sole focused UAT reproducer in the repository virtual environment; inspected fixture, connection policy, constructor, and migration sequencing; compared busy-handler and journal-mode semantics to SQLite primary documentation.
expecting: concurrent setup must be serialized independently of ordinary admission transactions; without that, a competing WAL mode change can return `SQLITE_BUSY` immediately despite a per-connection timeout.
next_action: return root-cause report and minimal fail-closed bootstrap design; do not edit production or test code.

expected: Concurrent repository initialization and repeated admission yield exactly one admissible claim without an SQLite lock error; contradictory fill evidence remains durable.
actual: `PRAGMA journal_mode = WAL` raises a locked-database error despite a configured busy timeout during `test_concurrent_admissions_produce_exactly_one_admissible_claim`.
errors: database is locked while executing PRAGMA journal_mode = WAL
reproduction: Run `tests/integration/execution/test_idempotency_recovery.py::test_concurrent_admissions_produce_exactly_one_admissible_claim`.
started: Failed Phase 01 UAT test 6 at base 45c96e697478afe802385b1123aee234135064cf.

## Eliminated

- hypothesis: The pytest fixture starts a competing connection or transaction.
  evidence: `tests/integration/execution/conftest.py::execution_database_path` only returns a fresh `tmp_path`-derived `Path`; it performs no SQLite operation.
  timestamp: 2026-07-11T10:29:16Z
- hypothesis: The durable admission `BEGIN IMMEDIATE` transaction is the observed failure point.
  evidence: The reproducer traceback enters `SQLiteExecutionLedger.__init__` and fails at `_configure_connection` line 80, before `run_migrations` completes and before `create_or_load_and_claim_submission` can call `transaction`.
  timestamp: 2026-07-11T10:29:16Z

## Evidence

- timestamp: 2026-07-11T10:26:00Z
  checked: debug-session initialization and knowledge base
  found: Created an isolated-worktree investigation record; no `.planning/debug/knowledge-base.md` exists, so no known-pattern candidate applies.
  implication: Investigation begins without prior-diagnosis bias.
- timestamp: 2026-07-11T10:26:00Z
  checked: `pa_agent/trading/persistence/sqlite_connection.py::_configure_connection` and the target concurrent test
  found: Each `SQLiteExecutionLedger` constructed in four executor threads opens its own connection and runs `busy_timeout`, `foreign_keys`, then `journal_mode=WAL` before admission. The test does not preconstruct a ledger or start a transaction.
  implication: Initialization-time PRAGMA contention is a primary candidate.
- timestamp: 2026-07-11T10:29:16Z
  checked: focused reproducer: `.venv/bin/python -m pytest -q tests/integration/execution/test_idempotency_recovery.py::test_concurrent_admissions_produce_exactly_one_admissible_claim`
  found: Failed in 0.61 seconds. A worker raised `sqlite3.OperationalError: database is locked` at `connection.execute("PRAGMA journal_mode = WAL")` in `_configure_connection`; it was wrapped as `LedgerConfigurationError` while constructing `SQLiteExecutionLedger`.
  implication: Failure is real and precedes the claim-admission transaction.
- timestamp: 2026-07-11T10:29:16Z
  checked: fixture and construction path
  found: The fixture only supplies a path. `SQLiteExecutionLedger.__init__` calls `open_sqlite_connection`, then `run_migrations`; all four workers use the same fresh file concurrently.
  implication: This is an application initialization race, not a fixture race.
- timestamp: 2026-07-11T10:29:16Z
  checked: SQLite primary documentation and migration runner
  found: SQLite documents WAL as a persistent database journal mode, `journal_mode` as a mode-changing pragma, and `busy_timeout` as a per-connection busy handler that may be bypassed to avoid deadlock. `run_migrations` separately opens immediate transactions and computes applied versions outside one encompassing bootstrap critical section.
  implication: A busy timeout is not an initialization mutex; even after the immediate WAL failure is removed, concurrently selected pending migrations are a latent bootstrap race.

## Resolution

root_cause: Unsynchronized concurrent ledger bootstrap lets multiple fresh connections execute the persistent, lock-requiring `PRAGMA journal_mode = WAL` and schema migration sequence against one file. SQLite may return `SQLITE_BUSY` without invoking the busy handler when waiting could deadlock, so the configured 5-second timeout does not guarantee this transition will wait. The observed failure occurs before admission; the fixture does not participate.
fix: Introduce one keyed bootstrap critical section per canonical ledger path that encloses policy setup and `run_migrations`; retain fail-closed errors and do not weaken durability. If concurrent processes are supported, make that guard an OS-visible advisory initialization lock, not only a thread lock. Subsequent per-connection setup should verify the persistent journal mode and set it only while holding the bootstrap guard.
verification: Reproduced the target UAT failure once; static trace confirms fixture and admission transaction are not in the failed call path. A post-fix regression must deliberately synchronize concurrent constructors at bootstrap and assert all initialize and exactly one admission is admissible.
files_changed: [".planning/debug/sqlite-wal-init-race.md"]
