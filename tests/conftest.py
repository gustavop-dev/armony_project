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
import precarga  # noqa: E402
import repos  # noqa: E402
import sesiones  # noqa: E402
from metrics import metricas  # noqa: E402

PRECALENTAR_REAL = precarga.precalentar


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point config.json, contexts/, agents/, sesiones/ and data_dir() at a per-test temp dir."""
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(contexts, "CONTEXTS_DIR", str(tmp_path / "contexts"))
    monkeypatch.setattr(agents, "AGENTS_DIR", str(tmp_path / "agents"))
    monkeypatch.setattr(sesiones, "SESIONES_DIR", str(tmp_path / "sesiones"))
    monkeypatch.setattr(repos, "REPOS_DIR", str(tmp_path / "repos"))
    return tmp_path


@pytest.fixture(autouse=True)
def no_late_saves(isolated_data_dir):
    """A Home left with a pending autosave (600 ms timer) must not save after
    the test: by then config/agents paths point at the real project again,
    and the save would overwrite the developer's config.json and agents.
    Runs before isolated_data_dir is undone (it depends on it)."""
    yield
    cancelar_autoguardados()


def cancelar_autoguardados():
    """Stop every live Home's pending autosave."""
    import sys
    home_window = sys.modules.get("home_window")
    if home_window is None:
        return
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        if isinstance(w, home_window.HomeWindow):
            w._guardado.stop()
            w._dirty = False


@pytest.fixture(autouse=True)
def no_prewarm(monkeypatch):
    """The Home prewarms agents in a background thread: off unless a test asks
    for precarga.precalentar (see precalentar_real)."""
    calls = []
    monkeypatch.setattr(precarga, "precalentar",
                        lambda cfg, agente, **kw: calls.append(agente["id"]) or False)
    precarga.olvidar()
    return calls


@pytest.fixture
def precalentar_real(monkeypatch):
    monkeypatch.setattr(precarga, "precalentar", PRECALENTAR_REAL)
    return PRECALENTAR_REAL


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
