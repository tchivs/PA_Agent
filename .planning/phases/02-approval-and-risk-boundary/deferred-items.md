# Deferred Items

## 2026-07-12: Existing Ruff violations in plan-scoped legacy files

- `pa_agent/config/settings.py` and `pa_agent/app_context.py` fail the plan's broad Ruff command with 44 existing violations, including non-ASCII comment punctuation, import placement/order, unused imports, and quoted annotations.
- These findings predate the credential-boundary implementation and are unrelated to its behavior. The new security modules and tests pass Ruff independently.
- Deferred to a dedicated formatting/legacy-cleanup task to avoid unrelated churn in this security plan.

## 2026-07-12: Shared-tree migration assertion needs owner reconciliation

- The uncommitted `tests/integration/execution/test_idempotency_recovery.py` asserts the schema migration history ends at version 3. Plan 02-06 correctly adds the ascending version 4 kill-switch migration, so its two bootstrap assertions now fail only because they omit `(4, 1)`.
- The same file contains concurrent uncommitted Phase 1 work. It was intentionally left untouched and unstaged; its owner should update the expected migration sequence when reconciling that work.

## 2026-07-12: Repository-wide Ruff baseline remains outside Plan 02-20

- `.venv/bin/ruff check .` reports 4484 existing violations across unrelated legacy modules and utility scripts, predominantly `RUF001`/`RUF003` non-ASCII punctuation findings.
- Plan 02-20's scoped Ruff command passes for the redactor, formatter, and integration regression. Repository-wide cleanup remains deferred to a dedicated linting task to avoid unrelated changes in this security fix.
