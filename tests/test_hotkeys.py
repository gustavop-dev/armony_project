"""Tests for hotkeys.py: the WH_KEYBOARD_LL Alt interceptor and RegisterHotKey.

No real hook or hotkey is ever installed. Every test replaces the module-level
``user32`` handle, ``ctypes.windll.kernel32`` and ``hotkeys._send_keys`` with
fakes before anything can reach Windows. Hook callbacks are driven directly
with ctypes-built KBDLLHOOKSTRUCT / MSG structures passed by address.
"""
import ctypes
import threading
from ctypes import wintypes

import pytest
from PySide6 import QtCore

import hotkeys

# The real reinjection helper, captured before any test patches it.
_REAL_SEND_KEYS = hotkeys._send_keys

# Virtual-key codes and messages, written out literally (not read from hotkeys).
VK_TAB = 0x09
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_1 = 0x31
VK_2 = 0x32
VK_3 = 0x33
VK_F4 = 0x73

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

APP_TAG = 0x41524D59      # 'ARMY'
LLKHF_INJECTED = 0x10

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
        self.scan_codes = {}
        self.hook_calls = []
        self.hook_procs = []
        self.next_hook_calls = []
        self.unhook_calls = []
        self.posted = []
        self.register_calls = []
        self.unregister_calls = []
        self.map_calls = []
        self.send_input_calls = []
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

    def MapVirtualKeyW(self, vk, map_type):
        self.map_calls.append((vk, map_type))
        return self.scan_codes.get(vk, 0)

    def SendInput(self, count, inputs, size):
        records = [(inputs[i].type, inputs[i].ki.wVk, inputs[i].ki.wScan,
                    inputs[i].ki.dwFlags, inputs[i].ki.time,
                    inputs[i].ki.dwExtraInfo)
                   for i in range(count)]
        self.send_input_calls.append((count, records, size))
        return count


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


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    """Record every reinjection request instead of calling SendInput."""
    calls = []
    monkeypatch.setattr(hotkeys, "_send_keys", lambda *events: calls.append(events))
    return calls


@pytest.fixture
def fired():
    return []


@pytest.fixture
def interceptor(qtbot, fired):
    icp = hotkeys.AltInterceptor({
        VK_1: lambda: fired.append("one"),
        VK_2: lambda: fired.append("two"),
    })
    yield icp
    icp.uninstall()


def key(icp, vk, wparam, extra=0, flags=0, n_code=0):
    """Feed one keyboard event to the hook callback as Windows would."""
    kb = hotkeys.KBDLLHOOKSTRUCT(vkCode=vk, scanCode=0, flags=flags, time=0,
                                 dwExtraInfo=extra)
    return icp._on_key(n_code, wparam, ctypes.addressof(kb))


def feed(icp, events):
    """Feed (vk, wparam) events in order and return the hook results."""
    return [key(icp, vk, wparam) for vk, wparam in events]


def flush():
    """Deliver the queued bridge signals to their slots."""
    QtCore.QCoreApplication.processEvents()


# -- Alt alone -------------------------------------------------------------

@pytest.mark.parametrize("alt_vk", [VK_MENU, VK_LMENU, VK_RMENU])
def test_alt_keydown_is_swallowed(interceptor, alt_vk):
    result = key(interceptor, alt_vk, WM_SYSKEYDOWN)

    assert result == SWALLOWED


def test_alt_keyup_after_swallowed_alt_is_swallowed(interceptor):
    results = feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_LMENU, WM_KEYUP)])

    assert results == [SWALLOWED, SWALLOWED]


def test_alt_autorepeat_is_swallowed(interceptor):
    results = feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN)] * 3)

    assert results == [SWALLOWED, SWALLOWED, SWALLOWED]


def test_alt_tap_reinjects_nothing(interceptor, sent):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_LMENU, WM_KEYUP)])

    assert sent == []


def test_alt_injected_by_other_tool_is_swallowed(interceptor):
    result = key(interceptor, VK_LMENU, WM_SYSKEYDOWN, flags=LLKHF_INJECTED,
                 extra=0x1111)

    assert result == SWALLOWED


# -- Alt + bound digit -----------------------------------------------------

@pytest.mark.parametrize("digit, expected", [(VK_1, ["one"]), (VK_2, ["two"])])
def test_alt_digit_triggers_bound_action(interceptor, fired, digit, expected):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (digit, WM_SYSKEYDOWN)])
    flush()

    assert fired == expected


def test_alt_digit_keydown_is_swallowed(interceptor):
    results = feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN)])

    assert results == [SWALLOWED, SWALLOWED]


def test_alt_digit_action_runs_only_through_qt_queue(interceptor, fired):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN)])

    assert fired == []


def test_alt_digit_autorepeat_triggers_action_once(interceptor, fired):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN)] + [(VK_1, WM_SYSKEYDOWN)] * 3)
    flush()

    assert fired == ["one"]


def test_alt_digit_autorepeat_is_swallowed(interceptor):
    results = feed(interceptor,
                   [(VK_LMENU, WM_SYSKEYDOWN)] + [(VK_1, WM_SYSKEYDOWN)] * 3)

    assert results == [SWALLOWED, SWALLOWED, SWALLOWED, SWALLOWED]


def test_alt_digit_keyup_is_swallowed(interceptor):
    results = feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN),
                                 (VK_1, WM_SYSKEYUP)])

    assert results == [SWALLOWED, SWALLOWED, SWALLOWED]


def test_digit_keyup_after_alt_release_is_swallowed(interceptor):
    results = feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN),
                                 (VK_LMENU, WM_KEYUP), (VK_1, WM_KEYUP)])

    assert results == [SWALLOWED, SWALLOWED, SWALLOWED, SWALLOWED]


def test_alt_digit_reinjects_nothing(interceptor, sent):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN),
                       (VK_1, WM_SYSKEYUP), (VK_LMENU, WM_KEYUP)])

    assert sent == []


def test_second_alt_digit_press_triggers_again(interceptor, fired):
    press = [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN),
             (VK_1, WM_SYSKEYUP), (VK_LMENU, WM_KEYUP)]
    feed(interceptor, press + press)
    flush()

    assert fired == ["one", "one"]


def test_digit_without_alt_passes(interceptor, fired):
    results = feed(interceptor, [(VK_1, WM_KEYDOWN), (VK_1, WM_KEYUP)])
    flush()

    assert (results, fired) == ([PASSED, PASSED], [])


def test_alt_digit_triggers_after_hold_interrupted_by_other_key(interceptor, fired):
    interrupted = [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN),
                   (VK_TAB, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYUP),
                   (VK_TAB, WM_SYSKEYUP), (VK_LMENU, WM_KEYUP)]
    feed(interceptor, interrupted + [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN)])
    flush()

    assert fired == ["one", "one"]


def test_digit_keyup_after_interrupted_combo_is_swallowed(interceptor):
    results = feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN),
                                 (VK_TAB, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYUP)])

    assert results == [SWALLOWED, SWALLOWED, SWALLOWED, SWALLOWED]


def test_interrupted_combo_leaves_nothing_eaten(interceptor):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN),
                       (VK_TAB, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYUP),
                       (VK_TAB, WM_SYSKEYUP), (VK_LMENU, WM_KEYUP)])

    assert interceptor._eaten == set()


# -- Alt + any other key ---------------------------------------------------

@pytest.mark.parametrize("alt_vk, other_vk, expected", [
    (VK_LMENU, VK_TAB, [((VK_LMENU, False), (VK_TAB, False))]),
    (VK_RMENU, VK_F4, [((VK_RMENU, False), (VK_F4, False))]),
    (VK_LMENU, VK_3, [((VK_LMENU, False), (VK_3, False))]),
])
def test_alt_other_key_reinjects_alt_then_key(interceptor, sent, alt_vk, other_vk,
                                              expected):
    feed(interceptor, [(alt_vk, WM_SYSKEYDOWN), (other_vk, WM_SYSKEYDOWN)])

    assert sent == expected


def test_alt_other_key_original_event_is_swallowed(interceptor):
    results = feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_TAB, WM_SYSKEYDOWN)])

    assert results == [SWALLOWED, SWALLOWED]


def test_combo_keys_after_reinjection_pass(interceptor):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_TAB, WM_SYSKEYDOWN)])

    results = feed(interceptor, [(VK_TAB, WM_SYSKEYUP), (VK_TAB, WM_SYSKEYDOWN)])

    assert results == [PASSED, PASSED]


def test_combo_bound_digit_after_reinjection_passes(interceptor, fired):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_TAB, WM_SYSKEYDOWN)])

    result = key(interceptor, VK_1, WM_SYSKEYDOWN)
    flush()

    assert (result, fired) == (PASSED, [])


def test_alt_autorepeat_after_reinjection_passes(interceptor):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_TAB, WM_SYSKEYDOWN)])

    result = key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    assert result == PASSED


def test_alt_keyup_after_reinjection_passes(interceptor):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_TAB, WM_SYSKEYDOWN)])

    result = key(interceptor, VK_LMENU, WM_KEYUP)

    assert result == PASSED


def test_alt_capture_resumes_after_reinjected_combo(interceptor):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_TAB, WM_SYSKEYDOWN),
                       (VK_TAB, WM_SYSKEYUP), (VK_LMENU, WM_KEYUP)])

    result = key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    assert result == SWALLOWED


# -- Ctrl + Alt / AltGr ----------------------------------------------------

@pytest.mark.parametrize("ctrl_vk", [VK_CONTROL, VK_LCONTROL, VK_RCONTROL])
def test_ctrl_held_alt_keydown_passes(interceptor, ctrl_vk):
    results = feed(interceptor, [(ctrl_vk, WM_KEYDOWN), (VK_RMENU, WM_SYSKEYDOWN)])

    assert results == [PASSED, PASSED]


def test_ctrl_held_alt_digit_passes(interceptor, fired):
    feed(interceptor, [(VK_LCONTROL, WM_KEYDOWN), (VK_RMENU, WM_SYSKEYDOWN)])

    result = key(interceptor, VK_2, WM_SYSKEYDOWN)
    flush()

    assert (result, fired) == (PASSED, [])


def test_ctrl_held_alt_combo_reinjects_nothing(interceptor, sent):
    feed(interceptor, [(VK_LCONTROL, WM_KEYDOWN), (VK_RMENU, WM_SYSKEYDOWN),
                       (VK_2, WM_SYSKEYDOWN), (VK_2, WM_SYSKEYUP),
                       (VK_RMENU, WM_KEYUP), (VK_LCONTROL, WM_KEYUP)])

    assert sent == []


def test_ctrl_held_alt_keyup_passes(interceptor):
    feed(interceptor, [(VK_LCONTROL, WM_KEYDOWN), (VK_RMENU, WM_SYSKEYDOWN)])

    result = key(interceptor, VK_RMENU, WM_KEYUP)

    assert result == PASSED


def test_alt_capture_resumes_after_ctrl_release(interceptor):
    feed(interceptor, [(VK_LCONTROL, WM_KEYDOWN), (VK_RMENU, WM_SYSKEYDOWN),
                       (VK_RMENU, WM_KEYUP), (VK_LCONTROL, WM_KEYUP)])

    result = key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    assert result == SWALLOWED


def test_ctrl_pressed_after_alt_passes(interceptor):
    results = feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN),
                                 (VK_LCONTROL, WM_SYSKEYDOWN)])

    assert results == [SWALLOWED, PASSED]


def test_ctrl_pressed_after_alt_reinjects_nothing(interceptor, sent):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_LCONTROL, WM_SYSKEYDOWN)])

    assert sent == []


# -- the app's own injected events -----------------------------------------

def test_own_tagged_alt_passes(interceptor):
    result = key(interceptor, VK_LMENU, WM_SYSKEYDOWN, extra=APP_TAG,
                 flags=LLKHF_INJECTED)

    assert result == PASSED


def test_own_tagged_alt_does_not_arm_digit_capture(interceptor, fired):
    key(interceptor, VK_LMENU, WM_SYSKEYDOWN, extra=APP_TAG, flags=LLKHF_INJECTED)

    result = key(interceptor, VK_1, WM_SYSKEYDOWN)
    flush()

    assert (result, fired) == (PASSED, [])


def test_own_tagged_digit_after_alt_passes(interceptor, fired):
    key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    result = key(interceptor, VK_1, WM_SYSKEYDOWN, extra=APP_TAG,
                 flags=LLKHF_INJECTED)
    flush()

    assert (result, fired) == (PASSED, [])


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
    key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    assert fake_user32.next_hook_calls == []


@pytest.mark.parametrize("n_code", [-1, 3])
def test_hook_non_action_code_passes_alt(interceptor, n_code):
    result = key(interceptor, VK_LMENU, WM_SYSKEYDOWN, n_code=n_code)

    assert result == PASSED


class FailingOnceSendKeys:
    """Reinjection stub whose first call fails, like a rejected SendInput."""

    def __init__(self):
        self.calls = []

    def __call__(self, *events):
        self.calls.append(events)
        if len(self.calls) == 1:
            raise OSError("SendInput failed")


def test_hook_passes_key_when_handler_raises(interceptor, monkeypatch):
    monkeypatch.setattr(hotkeys, "_send_keys", FailingOnceSendKeys())
    key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    result = key(interceptor, VK_TAB, WM_SYSKEYDOWN)

    assert result == PASSED


# -- enable / disable ------------------------------------------------------

def test_disabled_interceptor_passes_alt(interceptor):
    interceptor.set_enabled(False)

    result = key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    assert result == PASSED


def test_disabled_interceptor_ignores_alt_digit(interceptor, fired):
    interceptor.set_enabled(False)

    results = feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_1, WM_SYSKEYDOWN)])
    flush()

    assert (results, fired) == ([PASSED, PASSED], [])


def test_reenabled_interceptor_swallows_alt(interceptor):
    interceptor.set_enabled(False)
    interceptor.set_enabled(True)

    result = key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    assert result == SWALLOWED


def test_disable_releases_reinjected_alt(interceptor, sent):
    feed(interceptor, [(VK_RMENU, WM_SYSKEYDOWN), (VK_TAB, WM_SYSKEYDOWN)])

    interceptor.set_enabled(False)

    assert sent[-1] == ((VK_RMENU, True),)


def test_disable_without_reinjected_alt_sends_nothing(interceptor, sent):
    key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    interceptor.set_enabled(False)

    assert sent == []


def test_disable_forgets_held_alt(interceptor, fired):
    key(interceptor, VK_LMENU, WM_SYSKEYDOWN)
    interceptor.set_enabled(False)
    interceptor.set_enabled(True)

    result = key(interceptor, VK_1, WM_KEYDOWN)
    flush()

    assert (result, fired) == (PASSED, [])


def test_uninstall_releases_reinjected_alt(interceptor, sent):
    feed(interceptor, [(VK_LMENU, WM_SYSKEYDOWN), (VK_TAB, WM_SYSKEYDOWN)])

    interceptor.uninstall()

    assert sent[-1] == ((VK_LMENU, True),)


def test_uninstall_without_reinjected_alt_sends_nothing(interceptor, sent):
    key(interceptor, VK_LMENU, WM_SYSKEYDOWN)

    interceptor.uninstall()

    assert sent == []


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
    interceptor._dispatch(VK_2)

    assert fired == ["two"]


def test_dispatch_ignores_unknown_vk(interceptor, fired):
    interceptor._dispatch(VK_TAB)

    assert fired == []


# -- _send_keys ------------------------------------------------------------

@pytest.fixture
def send_keys(fake_user32):
    fake_user32.scan_codes = {VK_LMENU: 0x38, VK_RMENU: 0x38, VK_TAB: 0x0F}
    return _REAL_SEND_KEYS


def test_send_keys_builds_tagged_keyboard_inputs(send_keys, fake_user32):
    send_keys((VK_LMENU, False), (VK_TAB, False))

    assert fake_user32.send_input_calls[0][1] == [
        (1, VK_LMENU, 0x38, 0, 0, APP_TAG),
        (1, VK_TAB, 0x0F, 0, 0, APP_TAG),
    ]


def test_send_keys_passes_event_count(send_keys, fake_user32):
    send_keys((VK_LMENU, False), (VK_TAB, False), (VK_TAB, True))

    assert fake_user32.send_input_calls[0][0] == 3


def test_send_keys_passes_input_struct_size(send_keys, fake_user32):
    send_keys((VK_TAB, True))

    assert fake_user32.send_input_calls[0][2] == 40


def test_send_keys_maps_vk_to_scan_code(send_keys, fake_user32):
    send_keys((VK_LMENU, False), (VK_TAB, True))

    assert fake_user32.map_calls == [(VK_LMENU, 0), (VK_TAB, 0)]


@pytest.mark.parametrize("vk, is_up, flags", [
    (VK_TAB, False, 0x0),
    (VK_TAB, True, 0x2),
    (VK_LMENU, True, 0x2),
    (VK_RMENU, False, 0x1),
    (VK_RMENU, True, 0x3),
])
def test_send_keys_sets_key_flags(send_keys, fake_user32, vk, is_up, flags):
    send_keys((vk, is_up))

    assert fake_user32.send_input_calls[0][1][0][3] == flags


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
    })
    yield gh
    gh.unregister()


def native(gh, message, wparam, event_type=b"windows_generic_MSG"):
    """Call nativeEventFilter with a real MSG struct passed by address."""
    msg = wintypes.MSG(hWnd=None, message=message, wParam=wparam, lParam=0)
    return gh.nativeEventFilter(event_type, ctypes.addressof(msg))


def test_global_register_returns_all_names(global_hotkeys):
    result = global_hotkeys.register()

    assert result == (["Alt+1", "Alt+2", "Alt+3", "Alt+4", "Alt+5"], [])


def test_global_register_reports_failed_names(global_hotkeys, fake_user32):
    fake_user32.failing_hotkey_ids = {2, 5}

    result = global_hotkeys.register()

    assert result == (["Alt+1", "Alt+3", "Alt+4"], ["Alt+2", "Alt+5"])


def test_global_register_uses_alt_norepeat_digits(global_hotkeys, fake_user32):
    global_hotkeys.register()

    assert fake_user32.register_calls == [
        (None, 1, 0x4001, 0x31),
        (None, 2, 0x4001, 0x32),
        (None, 3, 0x4001, 0x33),
        (None, 4, 0x4001, 0x34),
        (None, 5, 0x4001, 0x35),
    ]


def test_global_register_installs_keyboard_hook(global_hotkeys, fake_user32):
    global_hotkeys.register()

    assert fake_user32.hook_calls == [(13, None, 0)]


def test_global_exclusive_alt_false_before_register(global_hotkeys):
    assert global_hotkeys.exclusive_alt is False


def test_global_exclusive_alt_true_after_register(global_hotkeys):
    global_hotkeys.register()

    assert global_hotkeys.exclusive_alt is True


def test_global_exclusive_alt_false_when_hook_fails(global_hotkeys, fake_user32):
    fake_user32.hook_handle = None

    global_hotkeys.register()

    assert global_hotkeys.exclusive_alt is False


def test_global_set_alt_capture_off_releases_alt(global_hotkeys):
    global_hotkeys.register()

    global_hotkeys.set_alt_capture(False)

    assert global_hotkeys.exclusive_alt is False


def test_global_set_alt_capture_on_restores_alt(global_hotkeys):
    global_hotkeys.register()
    global_hotkeys.set_alt_capture(False)

    global_hotkeys.set_alt_capture(True)

    assert global_hotkeys.exclusive_alt is True


def test_global_hook_alt_digit_runs_mapped_callback(global_hotkeys, fake_user32,
                                                    actions):
    global_hotkeys.register()
    proc = fake_user32.hook_procs[0]
    alt = hotkeys.KBDLLHOOKSTRUCT(vkCode=VK_LMENU)
    digit = hotkeys.KBDLLHOOKSTRUCT(vkCode=VK_3)

    proc(0, WM_SYSKEYDOWN, ctypes.addressof(alt))
    proc(0, WM_SYSKEYDOWN, ctypes.addressof(digit))
    flush()

    assert actions == ["generate"]


def test_global_hook_reinjects_digit_without_callback(global_hotkeys, fake_user32,
                                                      sent):
    global_hotkeys.register()
    proc = fake_user32.hook_procs[0]
    alt = hotkeys.KBDLLHOOKSTRUCT(vkCode=VK_LMENU)
    digit = hotkeys.KBDLLHOOKSTRUCT(vkCode=0x34)

    proc(0, WM_SYSKEYDOWN, ctypes.addressof(alt))
    proc(0, WM_SYSKEYDOWN, ctypes.addressof(digit))

    assert sent == [((VK_LMENU, False), (0x34, False))]


def test_global_unregister_releases_registered_ids(global_hotkeys, fake_user32):
    fake_user32.failing_hotkey_ids = {2, 5}
    global_hotkeys.register()

    global_hotkeys.unregister()

    assert fake_user32.unregister_calls == [(None, 1), (None, 3), (None, 4)]


def test_global_unregister_removes_keyboard_hook(global_hotkeys, fake_user32):
    global_hotkeys.register()

    global_hotkeys.unregister()

    assert fake_user32.unhook_calls == [HOOK_HANDLE]


def test_global_unregister_drops_exclusive_alt(global_hotkeys):
    global_hotkeys.register()

    global_hotkeys.unregister()

    assert global_hotkeys.exclusive_alt is False


def test_global_unregister_tolerates_unregister_errors(global_hotkeys, fake_user32):
    fake_user32.unregister_error = OSError("invalid hotkey id")
    global_hotkeys.register()

    global_hotkeys.unregister()

    assert len(fake_user32.unregister_calls) == 5


def test_global_second_unregister_releases_nothing(global_hotkeys, fake_user32):
    global_hotkeys.register()
    global_hotkeys.unregister()

    global_hotkeys.unregister()

    assert len(fake_user32.unregister_calls) == 5


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
