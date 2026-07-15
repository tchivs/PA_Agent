"""Integration coverage for SQLite ledger storage policy and schema migrations."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
from pathlib import Path
from threading import Event, Lock

import pytest

from pa_agent.config.paths import EXECUTION_LEDGER_PATH, PROJECT_ROOT
from pa_agent.trading.persistence.migrations import Migration, run_migrations
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerConfigurationError,
    LedgerStorageError,
    bootstrap_sqlite_connection,
    open_sqlite_connection,
)

pytestmark = pytest.mark.integration


def test_execution_ledger_path_is_separate_and_parent_exists_before_open(tmp_path: Path) -> None:
    """The ledger has its own runtime file and initializes its parent on first open."""
    assert EXECUTION_LEDGER_PATH == (
        PROJECT_ROOT / "trade_records" / "execution" / "execution_ledger.sqlite3"
    )
    assert "records" not in EXECUTION_LEDGER_PATH.parts

    database_path = tmp_path / "trade_records" / "execution" / "execution_ledger.sqlite3"
    connection = open_sqlite_connection(database_path)
    connection.close()

    assert database_path.parent.is_dir()
    assert database_path.is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes are not portable")
def test_new_execution_storage_uses_restrictive_posix_modes(tmp_path: Path) -> None:
    """New local ledger storage is inaccessible to other local users."""
    database_path = tmp_path / "trade_records" / "execution" / "execution_ledger.sqlite3"
    connection = open_sqlite_connection(database_path)
    connection.close()

    assert database_path.parent.stat().st_mode & 0o777 == 0o700
    assert database_path.stat().st_mode & 0o777 == 0o600


def test_connection_enforces_durability_pragmas(tmp_path: Path) -> None:
    """Every connection applies the fail-closed SQLite durability policy."""
    connection = open_sqlite_connection(tmp_path / "execution_ledger.sqlite3")
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        connection.close()


def test_storage_initialization_failure_is_typed_and_never_falls_back(tmp_path: Path) -> None:
    """An unusable path refuses normal ledger use with a storage error."""
    blocking_parent = tmp_path / "not-a-directory"
    blocking_parent.write_text("not a directory", encoding="utf-8")

    with pytest.raises(LedgerStorageError):
        open_sqlite_connection(blocking_parent / "execution_ledger.sqlite3")


def test_failed_migration_rolls_back_ddl_and_retries_deterministically(tmp_path: Path) -> None:
    """Migration history is recorded only after the migration DDL succeeds."""
    connection = open_sqlite_connection(tmp_path / "execution_ledger.sqlite3")

    def broken_migration(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE interrupted_schema (id INTEGER PRIMARY KEY)")
        raise LedgerConfigurationError("injected migration failure")

    with pytest.raises(LedgerConfigurationError):
        run_migrations(connection, migrations=(Migration(1, broken_migration),))

    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'interrupted_schema'"
    ).fetchone() is None
    assert connection.execute("SELECT version FROM schema_migrations").fetchall() == []

    def repaired_migration(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE interrupted_schema (id INTEGER PRIMARY KEY)")

    run_migrations(connection, migrations=(Migration(1, repaired_migration),))
    assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]
    connection.close()


def test_bootstrap_uses_one_canonical_path_guard_without_global_serialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Equivalent paths serialize bootstrap while another database can initialize."""
    import pa_agent.trading.persistence.sqlite_connection as sqlite_connection

    database_path = tmp_path / "nested" / "execution_ledger.sqlite3"
    equivalent_path = database_path.parent / "." / database_path.name
    unrelated_path = tmp_path / "other" / "execution_ledger.sqlite3"
    first_path_entered = Event()
    release_first_path = Event()
    equivalent_path_configuring = Event()
    unrelated_path_finished = Event()
    configure_calls = 0
    configure_calls_lock = Lock()
    original_configure = sqlite_connection._configure_connection

    def block_first_path(connection: sqlite3.Connection) -> None:
        nonlocal configure_calls
        connection_path = Path(connection.execute("PRAGMA database_list").fetchone()[2]).resolve()
        if connection_path == database_path.resolve():
            with configure_calls_lock:
                configure_calls += 1
                call_number = configure_calls
            if call_number == 1:
                first_path_entered.set()
                assert release_first_path.wait(timeout=5)
            else:
                equivalent_path_configuring.set()
        original_configure(connection)

    monkeypatch.setattr(sqlite_connection, "_configure_connection", block_first_path)

    def bootstrap(path: Path, finished: Event | None = None) -> None:
        connection = bootstrap_sqlite_connection(path)
        connection.close()
        if finished is not None:
            finished.set()

    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(bootstrap, database_path)
        assert first_path_entered.wait(timeout=5)
        equivalent = executor.submit(bootstrap, equivalent_path.absolute())
        unrelated = executor.submit(bootstrap, unrelated_path, unrelated_path_finished)
        assert unrelated_path_finished.wait(timeout=5)
        assert equivalent_path_configuring.is_set() is False
        release_first_path.set()
        first.result()
        equivalent.result()
        unrelated.result()

    assert configure_calls == 2


def test_bootstrap_migration_failure_rolls_back_and_retries_with_full_policy(tmp_path: Path) -> None:
    """A failed bootstrap migration closes that connection and leaves a clean retry path."""
    database_path = tmp_path / "execution_ledger.sqlite3"

    def broken_migration(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE interrupted_schema (id INTEGER PRIMARY KEY)")
        raise LedgerConfigurationError("injected migration failure")

    with pytest.raises(LedgerConfigurationError, match="injected migration failure"):
        bootstrap_sqlite_connection(
            database_path, migrations=(Migration(1, broken_migration),)
        )

    inspection = open_sqlite_connection(database_path)
    try:
        assert inspection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'interrupted_schema'"
        ).fetchone() is None
        assert inspection.execute("SELECT version FROM schema_migrations").fetchall() == []
    finally:
        inspection.close()

    def repaired_migration(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE interrupted_schema (id INTEGER PRIMARY KEY)")

    connection = bootstrap_sqlite_connection(
        database_path, migrations=(Migration(1, repaired_migration),)
    )
    try:
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA synchronous").fetchone() == (2,)
    finally:
        connection.close()
