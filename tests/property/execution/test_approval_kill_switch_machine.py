"""Property-level checks for the permit-only authorization boundary."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger


@given(st.text(min_size=1, max_size=32))
def test_arbitrary_legacy_method_names_cannot_create_authority(name: str) -> None:
    with TemporaryDirectory() as directory:
        ledger = SQLiteExecutionLedger(Path(directory) / "execution.sqlite3")
        try:
            assert not hasattr(ledger, "create_or_load_and_claim_submission")
            assert not hasattr(ledger, "begin_outbound_submission")
            assert not hasattr(ledger, name) or name not in {
                "create_or_load_and_claim_submission",
                "begin_outbound_submission",
            }
        finally:
            ledger.close()
