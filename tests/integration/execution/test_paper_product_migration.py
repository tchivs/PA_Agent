"""Forward-compatible durable product-context migration tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pa_agent.trading.domain.models import SpotOrderContext
from pa_agent.trading.persistence.migrations import MIGRATIONS
from pa_agent.trading.persistence.sqlite_connection import bootstrap_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import (
    SQLiteExecutionLedger,
    _command_from_canonical_json,
)


def test_forward_migration_preserves_legacy_spot_row_and_adds_context_contract_columns(
    execution_database_path: Path,
) -> None:
    """A Phase 2 Spot command stays intact while new context columns are appended."""
    connection = bootstrap_sqlite_connection(execution_database_path, migrations=MIGRATIONS[:8])
    legacy_command = {
        "account_id": "paper-account",
        "client_order_id": "legacy-client",
        "command_id": "legacy-command",
        "context": {"product": "spot"},
        "logical_command_key": "legacy-key",
        "mode": "paper",
        "order_type": "limit",
        "price": "42000.00",
        "quantity": "0.1",
        "side": "buy",
        "symbol": "BTCUSDT",
    }
    try:
        connection.execute(
            """
            INSERT INTO order_commands(
                command_id, logical_command_key, client_order_id, command_json,
                mode, product, account_id, symbol, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-command",
                "legacy-key",
                "legacy-client",
                json.dumps(legacy_command, sort_keys=True, separators=(",", ":")),
                "paper",
                "spot",
                "paper-account",
                "BTCUSDT",
                "2026-07-13T00:00:00+00:00",
            ),
        )
    finally:
        connection.close()

    ledger = SQLiteExecutionLedger(execution_database_path)
    try:
        row = ledger._require_connection().execute(  # noqa: SLF001 - integration migration assertion
            "SELECT command_json, product_context_json, product_context_digest "
            "FROM order_commands WHERE command_id = ?",
            ("legacy-command",),
        ).fetchone()
    finally:
        ledger.close()

    rebuilt = _command_from_canonical_json(row[0])
    assert rebuilt.context == SpotOrderContext()
    assert rebuilt.symbol == "BTCUSDT"
    assert row == (json.dumps(legacy_command, sort_keys=True, separators=(",", ":")), None, None)


def test_migration_is_idempotent_for_existing_spot_rows(execution_database_path: Path) -> None:
    """Reopening after the append-only migration does not rewrite legacy command meaning."""
    first = SQLiteExecutionLedger(execution_database_path)
    first.close()
    second = SQLiteExecutionLedger(execution_database_path)
    try:
        versions = second._require_connection().execute(  # noqa: SLF001 - schema assertion
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        second.close()

    assert versions[-1] == (10,)
