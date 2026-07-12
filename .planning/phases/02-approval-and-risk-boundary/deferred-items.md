# Deferred Items

## 2026-07-12: Existing Ruff violations in plan-scoped legacy files

- `pa_agent/config/settings.py` and `pa_agent/app_context.py` fail the plan's broad Ruff command with 44 existing violations, including non-ASCII comment punctuation, import placement/order, unused imports, and quoted annotations.
- These findings predate the credential-boundary implementation and are unrelated to its behavior. The new security modules and tests pass Ruff independently.
- Deferred to a dedicated formatting/legacy-cleanup task to avoid unrelated churn in this security plan.
