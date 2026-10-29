"""Glass overlay: theme veils, Windows acrylic call and the safe fallback."""
import ctypes
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtWidgets

import overlay
import theme as T


@pytest.fixture
def vidrio(monkeypatch):
    for nombre in ("VIDRIO", "PANEL_TOP", "PANEL_BODY"):
        monkeypatch.setattr(T, nombre, getattr(T, nombre))
    T.activar_vidrio()


def test_glass_turns_panel_backgrounds_into_veils(vidrio):
    assert T.VIDRIO is True
    assert T.qcolor(T.PANEL_BODY).alpha() < 128


def test_without_glass_backgrounds_are_solid():
    assert (T.VIDRIO, T.qcolor(T.PANEL_BODY).alpha()) == (False, 255)


@pytest.mark.parametrize("texto, rgba", [
    ("rgba(16,19,29,0.26)", (16, 19, 29, 66)),
    ("#7c95ff", (124, 149, 255, 255)),
])
def test_qcolor_reads_css_and_hex(texto, rgba):
    c = T.qcolor(texto)

    assert (c.red(), c.green(), c.blue(), c.alpha()) == rgba


def test_glass_windows_are_translucent(qtbot, vidrio):
    from overlay_ui import TopBar
    bar = TopBar()
    qtbot.addWidget(bar)

    assert bar.testAttribute(QtCore.Qt.WA_TranslucentBackground) is True


def test_solid_windows_keep_uniform_opacity(qtbot):
    from overlay_ui import TopBar
    bar = TopBar()
    qtbot.addWidget(bar)

    assert bar.testAttribute(QtCore.Qt.WA_TranslucentBackground) is False


class FakeUser32:
    def __init__(self, ok=1):
        self.ok, self.politicas = ok, []

    def SetWindowCompositionAttribute(self, hwnd, datos_ptr):
        datos = ctypes.cast(datos_ptr, ctypes.POINTER(overlay._WinCompAttrData)).contents
        pol = ctypes.cast(datos.Data, ctypes.POINTER(overlay._AccentPolicy)).contents
        self.politicas.append((hwnd, datos.Attribute, pol.AccentState, pol.GradientColor))
        return self.ok


@pytest.fixture
def user32(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=fake), raising=False)
    return fake


def test_acrylic_packs_the_tint_as_abgr(user32):
    assert overlay.set_acrylic(42, tinte=(0x11, 0x22, 0x33), alpha=0.5) is True

    assert user32.politicas == [(42, 19, 4, 0x80332211)]


def test_acrylic_can_be_removed(user32):
    overlay.set_acrylic(42, alpha=None)

    assert user32.politicas[0][2:] == (0, 0)


def test_acrylic_reports_a_refusal(user32):
    user32.ok = 0

    assert overlay.set_acrylic(42) is False


def test_glass_is_not_offered_off_windows(qapp):
    assert overlay.vidrio_disponible() is False
