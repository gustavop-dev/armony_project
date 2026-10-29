"""Shared pytest fixtures.

Every test runs with user data redirected to a temp dir, outbound network
blocked and the process-wide metrics singleton reset, so no test can read the
real config.json, call a paid API or leak samples into another test.
"""
import os
import socket

# Qt widgets render without a display (set before any Qt import).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

import config  # noqa: E402
import agents  # noqa: E402
import contexts  # noqa: E402
import sesiones  # noqa: E402
from metrics import metricas  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point config.json, contexts/, agents/, sesiones/ and data_dir() at a per-test temp dir."""
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(contexts, "CONTEXTS_DIR", str(tmp_path / "contexts"))
    monkeypatch.setattr(agents, "AGENTS_DIR", str(tmp_path / "agents"))
    monkeypatch.setattr(sesiones, "SESIONES_DIR", str(tmp_path / "sesiones"))
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
