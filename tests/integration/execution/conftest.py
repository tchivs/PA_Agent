"""Integration-local fixtures for the durable execution ledger."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def execution_database_path(tmp_path: Path) -> Path:
    """Provide an isolated local SQLite path for real ledger integration tests."""
    return tmp_path / "trade_records" / "execution" / "execution_ledger.sqlite3"
