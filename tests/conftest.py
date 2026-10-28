"""Test configuration and offline fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


@pytest.fixture()
def mock_app():
    from accfarm import mock_server
    mock_server.reset()
    from fastapi.testclient import TestClient
    return mock_server.app, TestClient(mock_server.app)


@pytest.fixture()
def client(mock_app):
    from fastapi.testclient import TestClient
    from accfarm import mock_server
    mock_server.reset()
    return TestClient(mock_server.app)


@pytest.fixture()
def db(tmp_path):
    from accfarm.core.store import open_db
    return open_db(str(tmp_path / "t.db"))
