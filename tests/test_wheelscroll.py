"""Tests for wheelscroll.py: forwarding the mouse wheel to overlay zones.

No real hook is ever installed: the module-level ``user32`` handle and
``ctypes.windll.kernel32`` are replaced with fakes in every test, and the hook
callback is driven directly with a ctypes-built MSLLHOOKSTRUCT passed by
address.
"""
import ctypes
import threading

import pytest
from PySide6 import QtCore

import wheelscroll

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
WM_QUIT = 0x0012

SWALLOWED = 1             # hook return value that discards the event
PASSED = 0                # FakeUser32.CallNextHookEx default return value

HOOK_HANDLE = 0x5678
HOOK_THREAD_ID = 4343

ANSWER_ZONE = ((100, 200, 300, 400), "respuesta")    # x 100..399, y 200..599


class FakeUser32:
    """Stand-in for ctypes.windll.user32 that records every call."""

    def __init__(self):
        self.hook_handle = HOOK_HANDLE
        self.next_hook_result = PASSED
        self.hook_calls = []
        self.next_hook_calls = []
        self.unhook_calls = []
        self.posted = []
        self._quit = threading.Event()

    def PeekMessageW(self, *_args):
        return 0

    def SetWindowsHookExW(self, id_hook, _proc, hmod, thread_id):
        self.hook_calls.append((id_hook, hmod, thread_id))
        return self.hook_handle

    def GetMessageW(self, *_args):
        # Block like a real message loop until uninstall() posts WM_QUIT.
        self._quit.wait(5.0)
        return 0

    def PostThreadMessageW(self, tid, msg, wparam, lparam):
        self.posted.append((tid, msg, wparam, lparam))
        if msg == WM_QUIT:
            self._quit.set()
        return 1

    def UnhookWindowsHookEx(self, hook):
        self.unhook_calls.append(hook)
        return 1

    def CallNextHookEx(self, hook, n_code, wparam, lparam):
        self.next_hook_calls.append((hook, n_code, wparam, lparam))
        return self.next_hook_result


class FakeKernel32:
    """Fixed thread id; anything else is delegated to the real kernel32."""

    def __init__(self, real):
        self._real = real

    def GetCurrentThreadId(self):
        return HOOK_THREAD_ID

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture(autouse=True)
def fake_user32(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(wheelscroll, "user32", fake)
    return fake


@pytest.fixture(autouse=True)
def fake_kernel32(monkeypatch):
    monkeypatch.setattr(ctypes.windll, "kernel32",
                        FakeKernel32(ctypes.windll.kernel32))


@pytest.fixture
def scrolls():
    return []


@pytest.fixture
def forwarder(qtbot, scrolls):
    fw = wheelscroll.WheelForwarder(lambda name, notches: scrolls.append((name, notches)))
    yield fw
    fw.uninstall()


def mouse(fw, x, y, wparam=WM_MOUSEWHEEL, delta=120, n_code=0):
    """Feed one low-level mouse event to the hook callback as Windows would."""
    ms = wheelscroll.MSLLHOOKSTRUCT(mouseData=(delta & 0xFFFF) << 16)
    ms.pt.x = x
    ms.pt.y = y
    return fw._on_mouse(n_code, wparam, ctypes.addressof(ms))


def flush():
    """Deliver the queued bridge signals to their slots."""
    QtCore.QCoreApplication.processEvents()


# -- zones -----------------------------------------------------------------

@pytest.mark.parametrize("x, y, expected", [
    (100, 200, "respuesta"),     # top-left corner is inside
    (399, 599, "respuesta"),     # last pixel is inside
    (250, 400, "respuesta"),
    (400, 400, None),            # right edge is exclusive
    (250, 600, None),            # bottom edge is exclusive
    (99, 400, None),
    (250, 199, None),
])
def test_zone_hit_test(forwarder, x, y, expected):
    forwarder.set_zones([ANSWER_ZONE])

    assert forwarder._zona_en(x, y) == expected


def test_zone_first_match_wins_on_overlap(forwarder):
    forwarder.set_zones([((0, 0, 50, 50), "first"), ((0, 0, 100, 100), "second")])

    assert forwarder._zona_en(10, 10) == "first"


def test_zone_second_zone_is_found(forwarder):
    forwarder.set_zones([((0, 0, 50, 50), "first"), ((200, 0, 50, 50), "second")])

    assert forwarder._zona_en(210, 10) == "second"


def test_zone_none_before_set_zones(forwarder):
    assert forwarder._zona_en(0, 0) is None


def test_set_zones_stores_rects_as_tuples(forwarder):
    forwarder.set_zones([([1, 2, 3, 4], "lista")])

    assert forwarder._zonas == (((1, 2, 3, 4), "lista"),)


@pytest.mark.parametrize("zones", [None, [], [((), "vacia")], [(None, "nula")]])
def test_set_zones_empty_input_captures_nothing(forwarder, zones):
    forwarder.set_zones(zones)

    assert forwarder._zonas == ()


def test_set_zones_replaces_previous_zones(forwarder):
    forwarder.set_zones([ANSWER_ZONE])

    forwarder.set_zones([((0, 0, 10, 10), "otra")])

    assert forwarder._zona_en(250, 400) is None


# -- wheel inside a zone ---------------------------------------------------

@pytest.mark.parametrize("delta, expected", [
    (120, [("respuesta", 1)]),
    (240, [("respuesta", 2)]),
    (-120, [("respuesta", -1)]),
    (-360, [("respuesta", -3)]),
])
def test_wheel_in_zone_forwards_notches(forwarder, scrolls, delta, expected):
    forwarder.set_zones([ANSWER_ZONE])

    mouse(forwarder, 250, 400, delta=delta)
    flush()

    assert scrolls == expected


def test_wheel_in_second_zone_forwards_its_name(forwarder, scrolls):
    forwarder.set_zones([ANSWER_ZONE, ((0, 0, 50, 50), "transcripcion")])

    mouse(forwarder, 10, 10, delta=120)
    flush()

    assert scrolls == [("transcripcion", 1)]


@pytest.mark.parametrize("delta", [120, -120, 60])
def test_wheel_in_zone_is_swallowed(forwarder, delta):
    forwarder.set_zones([ANSWER_ZONE])

    result = mouse(forwarder, 250, 400, delta=delta)

    assert result == SWALLOWED


def test_wheel_in_zone_skips_next_hook(forwarder, fake_user32):
    forwarder.set_zones([ANSWER_ZONE])

    mouse(forwarder, 250, 400, delta=120)

    assert fake_user32.next_hook_calls == []


def test_wheel_in_zone_scrolls_only_through_qt_queue(forwarder, scrolls):
    forwarder.set_zones([ANSWER_ZONE])

    mouse(forwarder, 250, 400, delta=120)

    assert scrolls == []


def test_wheel_partial_notch_up_does_not_scroll(forwarder, scrolls):
    forwarder.set_zones([ANSWER_ZONE])

    mouse(forwarder, 250, 400, delta=60)
    flush()

    assert scrolls == []


@pytest.mark.parametrize("delta, expected", [
    (-60, []),
    (-180, [("respuesta", -1)]),
])
def test_wheel_partial_notch_down_mirrors_up(forwarder, scrolls, delta, expected):
    forwarder.set_zones([ANSWER_ZONE])

    mouse(forwarder, 250, 400, delta=delta)
    flush()

    assert scrolls == expected


def _wheel_stream(fw, deltas):
    for delta in deltas:
        mouse(fw, 250, 400, delta=delta)
    flush()


@pytest.mark.parametrize("deltas, expected", [
    ([60, 60], [("respuesta", 1)]),
    ([-60, -60], [("respuesta", -1)]),
    ([30] * 8, [("respuesta", 1), ("respuesta", 1)]),
    ([-30] * 8, [("respuesta", -1), ("respuesta", -1)]),
    ([-15] * 7, []),
])
def test_partial_wheel_deltas_accumulate(forwarder, scrolls, deltas, expected):
    forwarder.set_zones([ANSWER_ZONE])

    _wheel_stream(forwarder, deltas)

    assert scrolls == expected


def test_direction_change_drops_partial_remainder(forwarder, scrolls):
    forwarder.set_zones([ANSWER_ZONE])

    _wheel_stream(forwarder, [-100, 60, 60])

    assert scrolls == [("respuesta", 1)]


# -- events that must pass -------------------------------------------------

def test_wheel_outside_zone_passes(forwarder):
    forwarder.set_zones([ANSWER_ZONE])

    result = mouse(forwarder, 50, 50, delta=120)

    assert result == PASSED


def test_wheel_outside_zone_does_not_scroll(forwarder, scrolls):
    forwarder.set_zones([ANSWER_ZONE])

    mouse(forwarder, 50, 50, delta=120)
    flush()

    assert scrolls == []


def test_wheel_without_zones_passes(forwarder):
    result = mouse(forwarder, 250, 400, delta=120)

    assert result == PASSED


@pytest.mark.parametrize("wparam", [WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_MOUSEHWHEEL])
def test_non_wheel_message_in_zone_passes(forwarder, scrolls, wparam):
    forwarder.set_zones([ANSWER_ZONE])

    result = mouse(forwarder, 250, 400, wparam=wparam, delta=120)
    flush()

    assert (result, scrolls) == (PASSED, [])


@pytest.mark.parametrize("n_code", [-1, 3])
def test_non_action_code_in_zone_passes(forwarder, n_code):
    forwarder.set_zones([ANSWER_ZONE])

    result = mouse(forwarder, 250, 400, delta=120, n_code=n_code)

    assert result == PASSED


def test_pass_calls_next_hook_with_same_arguments(forwarder, fake_user32):
    ms = wheelscroll.MSLLHOOKSTRUCT(mouseData=120 << 16)
    address = ctypes.addressof(ms)

    forwarder._on_mouse(0, WM_MOUSEWHEEL, address)

    assert fake_user32.next_hook_calls == [(None, 0, WM_MOUSEWHEEL, address)]


def test_pass_returns_next_hook_result(forwarder, fake_user32):
    fake_user32.next_hook_result = 77

    result = mouse(forwarder, 0, 0, wparam=WM_MOUSEMOVE)

    assert result == 77


def test_malformed_zone_lets_wheel_pass(forwarder):
    forwarder.set_zones([((100, 200, 300), "rota")])

    result = mouse(forwarder, 150, 250, delta=120)

    assert result == PASSED


# -- install / uninstall lifecycle -----------------------------------------

def test_lifecycle_install_returns_true(forwarder):
    assert forwarder.install() is True


def test_lifecycle_install_sets_mouse_ll_hook(forwarder, fake_user32):
    forwarder.install()

    assert fake_user32.hook_calls == [(14, None, 0)]


def test_lifecycle_install_twice_hooks_once(forwarder, fake_user32):
    forwarder.install()

    second = forwarder.install()

    assert (second, len(fake_user32.hook_calls)) == (True, 1)


def test_lifecycle_install_failure_returns_false(forwarder, fake_user32):
    fake_user32.hook_handle = None

    assert forwarder.install() is False


def test_lifecycle_uninstall_posts_quit_to_hook_thread(forwarder, fake_user32):
    forwarder.install()

    forwarder.uninstall()

    assert fake_user32.posted == [(HOOK_THREAD_ID, WM_QUIT, 0, 0)]


def test_lifecycle_uninstall_unhooks_handle(forwarder, fake_user32):
    forwarder.install()

    forwarder.uninstall()

    assert fake_user32.unhook_calls == [HOOK_HANDLE]


def test_lifecycle_uninstall_clears_zones(forwarder):
    forwarder.set_zones([ANSWER_ZONE])

    forwarder.uninstall()

    assert forwarder._zona_en(250, 400) is None


def test_lifecycle_uninstall_without_install_posts_nothing(forwarder, fake_user32):
    forwarder.uninstall()

    assert fake_user32.posted == []


def test_lifecycle_active_false_before_install(forwarder):
    assert forwarder.active is False


def test_lifecycle_active_true_after_install(forwarder):
    forwarder.install()

    assert forwarder.active is True


def test_lifecycle_active_false_after_uninstall(forwarder):
    forwarder.install()

    forwarder.uninstall()

    assert forwarder.active is False


def test_lifecycle_active_false_when_hook_fails(forwarder, fake_user32):
    fake_user32.hook_handle = None

    forwarder.install()

    assert forwarder.active is False
