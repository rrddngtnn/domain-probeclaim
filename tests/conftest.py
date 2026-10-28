"""tests — semuanya offline. Tidak ada satu pun tes yang menyentuh jaringan.

Server tiruan dijalankan in-process lewat TestClient, jadi suite bisa
dijalankan di CI tanpa kredensial dan tanpa risiko.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


@pytest.fixture()
def mock_app():
    from ramet import mock_server
    mock_server.reset()
    from fastapi.testclient import TestClient
    return mock_server.app, TestClient(mock_server.app)


@pytest.fixture()
def client(mock_app):
    """TestClient yang MEMPERTAHANKAN cookie. Tanpa ini semua request
    setelah signup akan 401 karena sesi berbasis cookie."""
    from fastapi.testclient import TestClient
    from ramet import mock_server
    mock_server.reset()
    return TestClient(mock_server.app)


@pytest.fixture()
def db(tmp_path):
    from ramet.core.store import open_db
    return open_db(str(tmp_path / "t.db"))
