"""Property-level regression for removal of legacy dispatch admission."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from pa_agent.trading.persistence.sqlite_connection import open_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger


@given(st.integers(min_value=0, max_value=10))
def test_legacy_admission_never_creates_rows_after_reopen(_: int) -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "execution.sqlite3"
        ledger = SQLiteExecutionLedger(path)
        try:
            assert not hasattr(ledger, "create_or_load_and_claim_submission")
            assert not hasattr(ledger, "begin_outbound_submission")
        finally:
            ledger.close()
        connection = open_sqlite_connection(path)
        try:
            assert connection.execute("SELECT COUNT(*) FROM order_commands").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM submission_claims").fetchone()[0] == 0
        finally:
            connection.close()
