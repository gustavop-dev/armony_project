"""Tests for overlay.py Win32 wrappers.

ctypes.windll.user32 is replaced with a fake that stores one extended-style
value per HWND, so no real window is touched.
"""
from types import SimpleNamespace

import pytest

import overlay


class FakeUser32:
    def __init__(self, exstyle=0, affinity_ok=1, set_ok=1):
        self.exstyle = exstyle
        self.affinity_ok = affinity_ok
        self.set_ok = set_ok
        self.set_calls = []
        self.affinity_calls = []
        self.GetWindowLongW = _Fn(lambda hwnd, idx: self.exstyle)
        self.SetWindowLongW = _Fn(self._set)
        self.SetWindowDisplayAffinity = self._affinity

    def _set(self, hwnd, idx, value):
        self.set_calls.append((hwnd, idx, value))
        self.exstyle = value
        return self.set_ok

    def _affinity(self, hwnd, value):
        self.affinity_calls.append((hwnd, value))
        return self.affinity_ok


class _Fn:
    """Callable that tolerates ctypes-style restype/argtypes assignment."""

    def __init__(self, fn):
        self._fn = fn

    def __call__(self, *args):
        return self._fn(*args)


@pytest.fixture
def user32(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(overlay.ctypes, "windll", SimpleNamespace(user32=fake))
    return fake


def test_click_through_on_sets_transparent_bit(user32):
    user32.exstyle = overlay.WS_EX_LAYERED

    overlay.set_click_through(42, True)

    assert user32.exstyle == overlay.WS_EX_LAYERED | overlay.WS_EX_TRANSPARENT


def test_click_through_off_clears_only_transparent_bit(user32):
    user32.exstyle = overlay.WS_EX_LAYERED | overlay.WS_EX_TRANSPARENT

    overlay.set_click_through(42, False)

    assert user32.exstyle == overlay.WS_EX_LAYERED


def test_click_through_skips_write_when_unchanged(user32):
    user32.exstyle = overlay.WS_EX_TRANSPARENT

    overlay.set_click_through(42, True)

    assert user32.set_calls == []


def test_click_through_reports_failure(monkeypatch):
    monkeypatch.setattr(overlay.ctypes, "windll", SimpleNamespace())

    assert overlay.set_click_through(42, True) is False


def test_no_activate_adds_style_bit(user32):
    user32.exstyle = overlay.WS_EX_LAYERED

    overlay.set_no_activate(7)

    assert user32.set_calls == [(7, overlay.GWL_EXSTYLE,
                                 overlay.WS_EX_LAYERED | overlay.WS_EX_NOACTIVATE)]


def test_no_activate_returns_api_result(user32):
    user32.set_ok = 0

    assert overlay.set_no_activate(7) is False


def test_no_activate_reports_failure(monkeypatch):
    monkeypatch.setattr(overlay.ctypes, "windll", SimpleNamespace())

    assert overlay.set_no_activate(7) is False


@pytest.mark.parametrize("enabled, affinity", [
    (True, 0x11), (False, 0x00)])
def test_capture_protection_sets_affinity(user32, enabled, affinity):
    overlay.set_capture_protection(9, enabled)

    assert user32.affinity_calls == [(9, affinity)]


def test_capture_protection_returns_api_result(user32):
    user32.affinity_ok = 0

    assert overlay.set_capture_protection(9, True) is False


def test_capture_protection_reports_failure(monkeypatch):
    monkeypatch.setattr(overlay.ctypes, "windll", SimpleNamespace())

    assert overlay.set_capture_protection(9, True) is False
