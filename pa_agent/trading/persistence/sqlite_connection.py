"""Fail-closed SQLite connection policy for the execution ledger."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path


class LedgerConfigurationError(RuntimeError):
    """Raised when required SQLite durability configuration cannot be enforced."""


class LedgerStorageError(RuntimeError):
    """Raised when the local execution ledger cannot be safely accessed."""


_BUSY_TIMEOUT_MS = 5_000
_POSIX_DIRECTORY_MODE = 0o700
_POSIX_DATABASE_MODE = 0o600


def open_sqlite_connection(database_path: Path) -> sqlite3.Connection:
    """Open a ledger connection only after enforcing the required local policy.

    The connection is thread-confined and uses explicit transactions. Storage or
    pragma failures are typed and never cause a weaker configuration fallback.
    """
    path = Path(database_path)
    _prepare_storage(path)
    database_is_new = not path.exists()
    try:
        connection = sqlite3.connect(
            path,
            check_same_thread=True,
            isolation_level=None,
            timeout=_BUSY_TIMEOUT_MS / 1_000,
        )
    except (OSError, sqlite3.Error) as exc:
        raise LedgerStorageError(f"unable to open execution ledger at {path}") from exc

    try:
        if database_is_new:
            _apply_posix_mode(path, _POSIX_DATABASE_MODE, "database")
        _configure_connection(connection)
    except (OSError, sqlite3.Error, LedgerConfigurationError, LedgerStorageError) as exc:
        connection.close()
        if isinstance(exc, (LedgerConfigurationError, LedgerStorageError)):
            raise
        raise LedgerConfigurationError("unable to enforce execution ledger SQLite policy") from exc
    return connection


def _prepare_storage(database_path: Path) -> None:
    """Create the private ledger directory before SQLite opens the database file."""
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        _apply_posix_mode(database_path.parent, _POSIX_DIRECTORY_MODE, "directory")
    except OSError as exc:
        raise LedgerStorageError(
            f"unable to prepare execution ledger directory {database_path.parent}"
        ) from exc


def _apply_posix_mode(path: Path, mode: int, kind: str) -> None:
    """Apply and verify restrictive modes where the operating system supports them."""
    if os.name != "posix":
        return
    os.chmod(path, mode)
    if path.stat().st_mode & 0o777 != mode:
        raise LedgerStorageError(f"execution ledger {kind} does not have mode {mode:o}")


def _configure_connection(connection: sqlite3.Connection) -> None:
    """Apply and verify every required SQLite pragma on a fresh connection."""
    try:
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")

        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
    except sqlite3.Error as exc:
        raise LedgerConfigurationError("execution ledger SQLite pragma configuration failed") from exc

    if foreign_keys != (1,):
        raise LedgerConfigurationError("SQLite foreign-key enforcement is unavailable")
    if journal_mode is None or str(journal_mode[0]).lower() != "wal":
        raise LedgerConfigurationError("SQLite WAL journal mode is unavailable")
    if synchronous is None or str(synchronous[0]).lower() not in {"2", "full"}:
        raise LedgerConfigurationError("SQLite FULL synchronous durability is unavailable")
    if busy_timeout != (_BUSY_TIMEOUT_MS,):
        raise LedgerConfigurationError("SQLite busy timeout policy is unavailable")


@contextmanager
def transaction(connection: sqlite3.Connection) -> Generator[sqlite3.Connection, None, None]:
    """Run a short immediate transaction, rolling back every failed operation."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.execute("COMMIT")
    except sqlite3.Error as exc:
        _rollback_quietly(connection)
        raise LedgerStorageError("execution ledger transaction failed") from exc
    except Exception:
        _rollback_quietly(connection)
        raise


def _rollback_quietly(connection: sqlite3.Connection) -> None:
    """Best-effort rollback without concealing the original operation failure."""
    with suppress(sqlite3.Error):
        connection.execute("ROLLBACK")
