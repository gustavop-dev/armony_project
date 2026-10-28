"""Shared pytest fixtures.

Every test runs with user data redirected to a temp dir, outbound network
blocked and the process-wide metrics singleton reset, so no test can read the
real config.json, call a paid API or leak samples into another test.
"""
import socket

import pytest

import config
import contexts
from metrics import metricas


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point config.json, contexts/ and data_dir() at a per-test temp dir."""
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(contexts, "CONTEXTS_DIR", str(tmp_path / "contexts"))
    return tmp_path


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail fast on any outbound socket connection."""
    def blocked(*_args, **_kwargs):
        raise RuntimeError("network access is blocked in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture(autouse=True)
def fresh_metrics():
    """Start every test with an empty metrics singleton."""
    metricas.iniciar()
