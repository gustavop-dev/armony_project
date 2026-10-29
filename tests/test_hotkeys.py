"""Tests for hotkeys.py: the WH_KEYBOARD_LL Caps Lock layer and RegisterHotKey.

No real hook or hotkey is ever installed. Every test replaces the module-level
``user32`` handle and ``ctypes.windll.kernel32`` with fakes before anything can
reach Windows. Hook callbacks are driven directly
with ctypes-built KBDLLHOOKSTRUCT / MSG structures passed by address.
"""
import ctypes
import threading
from ctypes import wintypes

import pytest
from PySide6 import QtCore

import hotkeys

# Virtual-key codes and messages, written out literally (not read from hotkeys).
VK_TAB = 0x09
VK_SHIFT = 0x10
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LMENU = 0xA4
VK_A = 0x41
VK_D = 0x44
VK_H = 0x48
VK_S = 0x53

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

SWALLOWED = 1             # hook return value that discards the event
PASSED = 0                # FakeUser32.CallNextHookEx default return value

HOOK_HANDLE = 0x1234
HOOK_THREAD_ID = 4242


class FakeUser32:
    """Stand-in for ctypes.windll.user32 that records every call."""

    def __init__(self):
        self.hook_handle = HOOK_HANDLE
        self.next_hook_result = PASSED
        self.failing_hotkey_ids = set()
        self.unregister_error = None
        self.hook_calls = []
        self.hook_procs = []
        self.next_hook_calls = []
        self.unhook_calls = []
        self.posted = []
        self.register_calls = []
        self.unregister_calls = []
        self._quit = threading.Event()

    def PeekMessageW(self, *_args):
        return 0

    def SetWindowsHookExW(self, id_hook, proc, hmod, thread_id):
        self.hook_calls.append((id_hook, hmod, thread_id))
        self.hook_procs.append(proc)
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

    def RegisterHotKey(self, hwnd, hk_id, mods, vk):
        self.register_calls.append((hwnd, hk_id, mods, vk))
        return 0 if hk_id in self.failing_hotkey_ids else 1

    def UnregisterHotKey(self, hwnd, hk_id):
        self.unregister_calls.append((hwnd, hk_id))
        if self.unregister_error is not None:
            raise self.unregister_error
        return 1


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
    monkeypatch.setattr(hotkeys, "user32", fake)
    return fake


@pytest.fixture(autouse=True)
def fake_kernel32(monkeypatch):
    monkeypatch.setattr(ctypes.windll, "kernel32",
                        FakeKernel32(ctypes.windll.kernel32))


@pytest.fixture
def fired():
    return []


@pytest.fixture
def interceptor(qtbot, fired):
    icp = hotkeys.CapsLayer({
        VK_A: lambda: fired.append("answer"),
        VK_S: lambda: fired.append("shot"),
    })
    yield icp
    icp.uninstall()


def key(icp, vk, wparam, n_code=0):
    """Feed one keyboard event to the hook callback as Windows would."""
    kb = hotkeys.KBDLLHOOKSTRUCT(vkCode=vk, scanCode=0, flags=0, time=0,
                                 dwExtraInfo=0)
    return icp._on_key(n_code, wparam, ctypes.addressof(kb))


def feed(icp, events):
    """Feed (vk, wparam) events in order and return the hook results."""
    return [key(icp, vk, wparam) for vk, wparam in events]


def flush():
    """Deliver the queued bridge signals to their slots."""
    QtCore.QCoreApplication.processEvents()


# -- Caps Lock alone -------------------------------------------------------

DOWN, UP = WM_KEYDOWN, WM_KEYUP
CAPS_DOWN, CAPS_UP = (VK_CAPITAL, DOWN), (VK_CAPITAL, UP)


def test_caps_tap_is_swallowed_down_and_up(interceptor):
    assert feed(interceptor, [CAPS_DOWN, CAPS_UP]) == [SWALLOWED, SWALLOWED]


def test_caps_autorepeat_is_swallowed(interceptor):
    assert feed(interceptor, [CAPS_DOWN] * 3) == [SWALLOWED] * 3


def test_caps_tap_fires_nothing(interceptor, fired):
    feed(interceptor, [CAPS_DOWN, CAPS_UP])
    flush()

    assert fired == []


@pytest.mark.parametrize("shift_vk", [VK_SHIFT, VK_LSHIFT, VK_RSHIFT])
def test_shift_caps_passes_so_caps_lock_still_toggles(interceptor, shift_vk):
    results = feed(interceptor, [(shift_vk, DOWN), CAPS_DOWN, CAPS_DOWN,
                                 (shift_vk, UP), CAPS_UP])

    assert results == [PASSED] * 5


def test_caps_after_shift_caps_is_swallowed_again(interceptor):
    feed(interceptor, [(VK_LSHIFT, DOWN), CAPS_DOWN, CAPS_UP, (VK_LSHIFT, UP)])

    assert feed(interceptor, [CAPS_DOWN, CAPS_UP]) == [SWALLOWED, SWALLOWED]


def test_shift_pressed_while_caps_held_keeps_the_layer(interceptor, fired):
    feed(interceptor, [CAPS_DOWN, (VK_LSHIFT, DOWN), CAPS_DOWN, (VK_A, DOWN)])
    flush()

    assert fired == ["answer"]


# -- Caps Lock + bound key -------------------------------------------------

@pytest.mark.parametrize("vk, expected", [(VK_A, ["answer"]), (VK_S, ["shot"])])
def test_caps_key_fires_bound_action(interceptor, fired, vk, expected):
    feed(interceptor, [CAPS_DOWN, (vk, DOWN)])
    flush()

    assert fired == expected


def test_caps_key_is_swallowed_down_and_up(interceptor):
    results = feed(interceptor, [CAPS_DOWN, (VK_A, DOWN), (VK_A, UP), CAPS_UP])

    assert results == [SWALLOWED] * 4


def test_caps_key_held_fires_once(interceptor, fired):
    results = feed(interceptor, [CAPS_DOWN] + [(VK_A, DOWN)] * 3)
    flush()

    assert (fired, results[1:]) == (["answer"], [SWALLOWED] * 3)


def test_caps_key_fires_again_after_release(interceptor, fired):
    press = [CAPS_DOWN, (VK_A, DOWN), (VK_A, UP), CAPS_UP]
    feed(interceptor, press + press)
    flush()

    assert fired == ["answer", "answer"]


def test_two_actions_while_caps_held(interceptor, fired):
    feed(interceptor, [CAPS_DOWN, (VK_A, DOWN), (VK_A, UP),
                       (VK_S, DOWN), (VK_S, UP), CAPS_UP])
    flush()

    assert fired == ["answer", "shot"]


def test_key_released_after_caps_still_swallows_its_keyup(interceptor):
    results = feed(interceptor, [CAPS_DOWN, (VK_A, DOWN), CAPS_UP, (VK_A, UP)])

    assert results[-1] == SWALLOWED


def test_bound_key_without_caps_types_normally(interceptor, fired):
    results = feed(interceptor, [(VK_A, DOWN), (VK_A, UP)])
    flush()

    assert (results, fired) == ([PASSED, PASSED], [])


def test_key_held_before_caps_does_not_fire_on_repeat(interceptor, fired):
    results = feed(interceptor, [(VK_A, DOWN), CAPS_DOWN, (VK_A, DOWN),
                                 (VK_A, UP), CAPS_UP])
    flush()

    assert (fired, results[2:4]) == ([], [PASSED, PASSED])


def test_key_held_before_caps_fires_after_a_new_press(interceptor, fired):
    feed(interceptor, [(VK_A, DOWN), CAPS_DOWN, (VK_A, UP), (VK_A, DOWN)])
    flush()

    assert fired == ["answer"]


@pytest.mark.parametrize("wparam", [WM_SYSKEYDOWN, WM_KEYDOWN])
def test_caps_key_fires_with_either_keydown_message(interceptor, fired, wparam):
    feed(interceptor, [CAPS_DOWN, (VK_A, wparam)])
    flush()

    assert fired == ["answer"]


# -- Caps Lock + any other key ---------------------------------------------

def test_caps_other_key_passes(interceptor, fired):
    results = feed(interceptor, [CAPS_DOWN, (VK_H, DOWN), (VK_H, UP), CAPS_UP])
    flush()

    assert (results, fired) == ([SWALLOWED, PASSED, PASSED, SWALLOWED], [])


@pytest.mark.parametrize("vk", [VK_TAB, VK_LMENU, VK_D])
def test_keys_without_caps_pass(interceptor, vk):
    assert feed(interceptor, [(vk, DOWN), (vk, UP)]) == [PASSED, PASSED]


# -- _on_key plumbing ------------------------------------------------------

def test_hook_pass_calls_next_hook_with_same_arguments(interceptor, fake_user32):
    kb = hotkeys.KBDLLHOOKSTRUCT(vkCode=VK_TAB)
    address = ctypes.addressof(kb)

    interceptor._on_key(0, WM_KEYDOWN, address)

    assert fake_user32.next_hook_calls == [(None, 0, WM_KEYDOWN, address)]


def test_hook_pass_returns_next_hook_result(interceptor, fake_user32):
    fake_user32.next_hook_result = 99

    result = key(interceptor, VK_TAB, WM_KEYDOWN)

    assert result == 99


def test_hook_swallow_skips_next_hook(interceptor, fake_user32):
    key(interceptor, VK_CAPITAL, WM_KEYDOWN)

    assert fake_user32.next_hook_calls == []


@pytest.mark.parametrize("n_code", [-1, 3])
def test_hook_non_action_code_passes_caps(interceptor, n_code):
    result = key(interceptor, VK_CAPITAL, WM_KEYDOWN, n_code=n_code)

    assert result == PASSED


# -- enable / disable ------------------------------------------------------

def test_disabled_layer_passes_caps(interceptor):
    interceptor.set_enabled(False)

    assert feed(interceptor, [CAPS_DOWN, CAPS_UP]) == [PASSED, PASSED]


def test_disabled_layer_fires_nothing(interceptor, fired):
    interceptor.set_enabled(False)
    feed(interceptor, [CAPS_DOWN, (VK_A, DOWN)])
    flush()

    assert fired == []


def test_disabling_mid_combo_forgets_the_held_caps(interceptor, fired):
    feed(interceptor, [CAPS_DOWN])
    interceptor.set_enabled(False)
    interceptor.set_enabled(True)

    result = key(interceptor, VK_A, DOWN)
    flush()

    assert (result, fired) == (PASSED, [])


def test_reenabled_layer_fires_again(interceptor, fired):
    interceptor.set_enabled(False)
    interceptor.set_enabled(True)
    feed(interceptor, [CAPS_DOWN, (VK_S, DOWN)])
    flush()

    assert fired == ["shot"]


# -- install / uninstall lifecycle -----------------------------------------

def test_lifecycle_install_returns_true(interceptor):
    assert interceptor.install() is True


def test_lifecycle_install_sets_keyboard_ll_hook(interceptor, fake_user32):
    interceptor.install()

    assert fake_user32.hook_calls == [(13, None, 0)]


def test_lifecycle_install_twice_hooks_once(interceptor, fake_user32):
    interceptor.install()

    second = interceptor.install()

    assert (second, len(fake_user32.hook_calls)) == (True, 1)


def test_lifecycle_install_failure_returns_false(interceptor, fake_user32):
    fake_user32.hook_handle = None

    assert interceptor.install() is False


def test_lifecycle_failed_install_never_unhooks(interceptor, fake_user32):
    fake_user32.hook_handle = None
    interceptor.install()

    assert fake_user32.unhook_calls == []


def test_lifecycle_uninstall_posts_quit_to_hook_thread(interceptor, fake_user32):
    interceptor.install()

    interceptor.uninstall()

    assert fake_user32.posted == [(HOOK_THREAD_ID, WM_QUIT, 0, 0)]


def test_lifecycle_uninstall_unhooks_handle(interceptor, fake_user32):
    interceptor.install()

    interceptor.uninstall()

    assert fake_user32.unhook_calls == [HOOK_HANDLE]


def test_lifecycle_uninstall_without_install_posts_nothing(interceptor, fake_user32):
    interceptor.uninstall()

    assert fake_user32.posted == []


def test_lifecycle_active_false_before_install(interceptor):
    assert interceptor.active is False


def test_lifecycle_active_true_after_install(interceptor):
    interceptor.install()

    assert interceptor.active is True


def test_lifecycle_active_false_while_disabled(interceptor):
    interceptor.install()

    interceptor.set_enabled(False)

    assert interceptor.active is False


def test_lifecycle_active_false_after_uninstall(interceptor):
    interceptor.install()

    interceptor.uninstall()

    assert interceptor.active is False


def test_lifecycle_active_false_when_hook_fails(interceptor, fake_user32):
    fake_user32.hook_handle = None

    interceptor.install()

    assert interceptor.active is False


# -- _dispatch -------------------------------------------------------------

def test_dispatch_runs_bound_callback(interceptor, fired):
    interceptor._dispatch(VK_S)

    assert fired == ["shot"]


def test_dispatch_ignores_unknown_vk(interceptor, fired):
    interceptor._dispatch(VK_TAB)

    assert fired == []


# -- GlobalHotkeys ---------------------------------------------------------

@pytest.fixture
def actions():
    return []


@pytest.fixture
def global_hotkeys(qtbot, actions):
    gh = hotkeys.GlobalHotkeys({
        1: lambda: actions.append("toggle"),
        2: lambda: actions.append("shot"),
        3: lambda: actions.append("generate"),
        4: lambda: actions.append("meeting"),
        5: lambda: actions.append("answer"),
    })
    yield gh
    gh.unregister()


def native(gh, message, wparam, event_type=b"windows_generic_MSG"):
    """Call nativeEventFilter with a real MSG struct passed by address."""
    msg = wintypes.MSG(hWnd=None, message=message, wParam=wparam, lParam=0)
    return gh.nativeEventFilter(event_type, ctypes.addressof(msg))


def test_global_register_returns_all_names(global_hotkeys):
    result = global_hotkeys.register()

    assert result == (["Alt+1", "Alt+2", "Alt+3", "Alt+4", "Alt+5", "Alt+6"], [])


def test_global_register_reports_failed_names(global_hotkeys, fake_user32):
    fake_user32.failing_hotkey_ids = {2, 5}

    result = global_hotkeys.register()

    assert result == (["Alt+1", "Alt+3", "Alt+4", "Alt+6"], ["Alt+2", "Alt+5"])


def test_global_register_uses_alt_norepeat_digits(global_hotkeys, fake_user32):
    global_hotkeys.register()

    assert fake_user32.register_calls == [
        (None, 1, 0x4001, 0x31),
        (None, 2, 0x4001, 0x32),
        (None, 3, 0x4001, 0x33),
        (None, 4, 0x4001, 0x34),
        (None, 5, 0x4001, 0x35),
        (None, 6, 0x4001, 0x36),
    ]


def test_global_register_installs_keyboard_hook(global_hotkeys, fake_user32):
    global_hotkeys.register()

    assert fake_user32.hook_calls == [(13, None, 0)]


def test_global_caps_layer_false_before_register(global_hotkeys):
    assert global_hotkeys.caps_layer is False


def test_global_caps_layer_true_after_register(global_hotkeys):
    global_hotkeys.register()

    assert global_hotkeys.caps_layer is True


def test_global_caps_layer_false_when_hook_fails(global_hotkeys, fake_user32):
    fake_user32.hook_handle = None

    global_hotkeys.register()

    assert global_hotkeys.caps_layer is False


def test_global_set_caps_layer_off_disables_layer(global_hotkeys):
    global_hotkeys.register()

    global_hotkeys.set_caps_layer(False)

    assert global_hotkeys.caps_layer is False


def test_global_set_caps_layer_on_restores_layer(global_hotkeys):
    global_hotkeys.register()
    global_hotkeys.set_caps_layer(False)

    global_hotkeys.set_caps_layer(True)

    assert global_hotkeys.caps_layer is True


@pytest.mark.parametrize("vk, expected", [
    (VK_A, ["answer"]),
    (VK_S, ["shot"]),
    (VK_D, ["generate"]),
    (VK_ESCAPE, ["meeting"]),
])
def test_global_hook_caps_key_runs_mapped_action(global_hotkeys, fake_user32,
                                                 actions, vk, expected):
    global_hotkeys.register()
    proc = fake_user32.hook_procs[0]
    caps = hotkeys.KBDLLHOOKSTRUCT(vkCode=VK_CAPITAL)
    tecla = hotkeys.KBDLLHOOKSTRUCT(vkCode=vk)

    proc(0, WM_KEYDOWN, ctypes.addressof(caps))
    proc(0, WM_KEYDOWN, ctypes.addressof(tecla))
    flush()

    assert actions == expected


def test_global_hook_ignores_keys_of_actions_without_callback(global_hotkeys,
                                                              fake_user32):
    global_hotkeys.register()
    proc = fake_user32.hook_procs[0]
    caps = hotkeys.KBDLLHOOKSTRUCT(vkCode=VK_CAPITAL)
    tecla = hotkeys.KBDLLHOOKSTRUCT(vkCode=0x46)       # F: relaunch, not wired

    proc(0, WM_KEYDOWN, ctypes.addressof(caps))
    result = proc(0, WM_KEYDOWN, ctypes.addressof(tecla))

    assert result == PASSED


def test_caps_bindings_cover_every_action_once():
    teclas = [vk for vk, _n in hotkeys.CAPS_BINDINGS.values()]

    assert (sorted(hotkeys.CAPS_BINDINGS), len(set(teclas))) == (
        sorted(hotkeys.BINDINGS), len(teclas))


def test_global_unregister_releases_registered_ids(global_hotkeys, fake_user32):
    fake_user32.failing_hotkey_ids = {2, 5}
    global_hotkeys.register()

    global_hotkeys.unregister()

    assert fake_user32.unregister_calls == [(None, 1), (None, 3), (None, 4), (None, 6)]


def test_global_unregister_removes_keyboard_hook(global_hotkeys, fake_user32):
    global_hotkeys.register()

    global_hotkeys.unregister()

    assert fake_user32.unhook_calls == [HOOK_HANDLE]


def test_global_unregister_drops_caps_layer(global_hotkeys):
    global_hotkeys.register()

    global_hotkeys.unregister()

    assert global_hotkeys.caps_layer is False


def test_global_unregister_tolerates_unregister_errors(global_hotkeys, fake_user32):
    fake_user32.unregister_error = OSError("invalid hotkey id")
    global_hotkeys.register()

    global_hotkeys.unregister()

    assert len(fake_user32.unregister_calls) == 6


def test_global_second_unregister_releases_nothing(global_hotkeys, fake_user32):
    global_hotkeys.register()
    global_hotkeys.unregister()

    global_hotkeys.unregister()

    assert len(fake_user32.unregister_calls) == 6


@pytest.mark.parametrize("hk_id, expected", [
    (1, ["toggle"]),
    (2, ["shot"]),
    (3, ["generate"]),
])
def test_global_native_hotkey_runs_callback(global_hotkeys, actions, hk_id,
                                            expected):
    native(global_hotkeys, WM_HOTKEY, hk_id)

    assert actions == expected


def test_global_native_hotkey_is_consumed(global_hotkeys):
    result = native(global_hotkeys, WM_HOTKEY, 2)

    assert result == (True, 0)


def test_global_native_unknown_hotkey_id_is_ignored(global_hotkeys, actions):
    result = native(global_hotkeys, WM_HOTKEY, 9)

    assert (result, actions) == ((False, 0), [])


def test_global_native_other_message_is_ignored(global_hotkeys, actions):
    result = native(global_hotkeys, WM_KEYDOWN, 1)

    assert (result, actions) == ((False, 0), [])


def test_global_native_other_event_type_is_ignored(global_hotkeys, actions):
    result = native(global_hotkeys, WM_HOTKEY, 1, event_type=b"xcb_generic_event_t")

    assert (result, actions) == ((False, 0), [])


def test_global_native_unreadable_message_is_ignored(global_hotkeys):
    result = global_hotkeys.nativeEventFilter(b"windows_generic_MSG", None)

    assert result == (False, 0)


# -- active only during a meeting ------------------------------------------

def test_installed_shortcuts_start_switched_off(global_hotkeys, fake_user32):
    global_hotkeys.instalar()

    assert global_hotkeys.hook_instalado is True
    assert global_hotkeys.caps_layer is False
    assert fake_user32.register_calls == []


def test_switched_off_layer_lets_caps_lock_through(global_hotkeys, fake_user32):
    global_hotkeys.instalar()
    proc = fake_user32.hook_procs[0]
    caps = hotkeys.KBDLLHOOKSTRUCT(vkCode=VK_CAPITAL)

    assert proc(0, WM_KEYDOWN, ctypes.addressof(caps)) == PASSED


def test_meeting_switches_shortcuts_on(global_hotkeys, fake_user32):
    global_hotkeys.instalar()

    ocupados = global_hotkeys.set_activo(True)

    assert (global_hotkeys.caps_layer, ocupados) == (True, [])
    assert len(fake_user32.register_calls) == 6


def test_end_of_meeting_releases_everything(global_hotkeys, fake_user32):
    global_hotkeys.instalar()
    global_hotkeys.set_activo(True)

    global_hotkeys.set_activo(False)

    assert global_hotkeys.caps_layer is False
    assert len(fake_user32.unregister_calls) == 6


def test_switching_on_twice_registers_once(global_hotkeys, fake_user32):
    global_hotkeys.instalar()
    global_hotkeys.set_activo(True)

    global_hotkeys.set_activo(True)

    assert len(fake_user32.register_calls) == 6


def test_busy_fallbacks_are_reported(global_hotkeys, fake_user32):
    fake_user32.failing_hotkey_ids = {2}
    global_hotkeys.instalar()

    assert global_hotkeys.set_activo(True) == ["Alt+2"]
