"""Tests for applog: rotating file handler on the ``armony`` logger and the
uncaught-exception hooks, plus the keyboard hook call site in hotkeys.py.

Every test restores ``sys.excepthook`` / ``threading.excepthook`` and removes
the handlers it attached, so nothing leaks into later tests.
"""
import logging
import logging.handlers
import sys
import threading
from types import SimpleNamespace

import pytest

import applog
import hotkeys


@pytest.fixture(autouse=True)
def restore_logging():
    """Undo setup(): restore both global hooks, drop and close handlers."""
    saved_sys_hook, saved_thread_hook = sys.excepthook, threading.excepthook
    yield
    sys.excepthook, threading.excepthook = saved_sys_hook, saved_thread_hook
    root = logging.getLogger("armony")
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.NOTSET)


def armony_handlers():
    return logging.getLogger("armony").handlers


def last_line_without_timestamp(path):
    """Final log line minus the two-token asctime prefix (date and time)."""
    for handler in armony_handlers():
        handler.flush()
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()[-1].split(" ", 2)[2]


# ------------------------------------------------------------------ setup
def test_setup_creates_log_file_under_logs_dir(tmp_path):
    applog.setup(str(tmp_path))

    assert (tmp_path / "logs" / "armony.log").is_file()


def test_setup_returns_log_file_path(tmp_path):
    assert applog.setup(str(tmp_path)) == str(tmp_path / "logs" / "armony.log")


def test_child_logger_record_reaches_file(tmp_path):
    path = applog.setup(str(tmp_path))

    logging.getLogger("armony.x").info("probe 42")

    assert last_line_without_timestamp(path) == "INFO armony.x [MainThread] probe 42"


def test_setup_does_not_configure_root_logger(tmp_path):
    before = list(logging.getLogger().handlers)

    applog.setup(str(tmp_path))

    assert logging.getLogger().handlers == before


def test_second_setup_keeps_single_handler(tmp_path):
    applog.setup(str(tmp_path))

    applog.setup(str(tmp_path))

    assert len(armony_handlers()) == 1


def test_handler_rotation_settings(tmp_path):
    applog.setup(str(tmp_path))

    handler = armony_handlers()[0]
    assert (type(handler), handler.maxBytes, handler.backupCount) == (
        logging.handlers.RotatingFileHandler, 1_000_000, 3)


def test_logger_level_is_info(tmp_path):
    applog.setup(str(tmp_path))

    assert logging.getLogger("armony").level == logging.INFO


# ------------------------------------------------------------------ hooks
@pytest.fixture
def previous_thread_hook(monkeypatch):
    """Recording stand-in for the hook active before setup()."""
    calls = []
    monkeypatch.setattr(threading, "excepthook", calls.append)
    return calls


def run_failing_thread():
    def boom():
        raise ValueError("thread failed")

    t = threading.Thread(target=boom, name="worker-x")
    t.start()
    t.join()


def test_thread_exception_is_logged(tmp_path, previous_thread_hook, caplog):
    applog.setup(str(tmp_path))

    run_failing_thread()

    record = caplog.records[-1]
    assert (record.name, record.levelname, record.getMessage(), record.exc_info[0]) == (
        "armony", "ERROR", "Uncaught exception in thread worker-x", ValueError)


def test_thread_exception_reaches_previous_hook(tmp_path, previous_thread_hook):
    applog.setup(str(tmp_path))

    run_failing_thread()

    assert [args.exc_type for args in previous_thread_hook] == [ValueError]


@pytest.fixture
def previous_sys_hook(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: calls.append(exc[0]))
    return calls


def raise_and_hook():
    try:
        raise KeyError("main failed")
    except KeyError:
        sys.excepthook(*sys.exc_info())


def test_uncaught_exception_is_logged_critical(tmp_path, previous_sys_hook, caplog):
    applog.setup(str(tmp_path))

    raise_and_hook()

    record = caplog.records[-1]
    assert (record.levelname, record.getMessage(), record.exc_info[0]) == (
        "CRITICAL", "Uncaught exception", KeyError)


def test_uncaught_exception_reaches_previous_hook(tmp_path, previous_sys_hook):
    applog.setup(str(tmp_path))

    raise_and_hook()

    assert previous_sys_hook == [KeyError]


def test_second_setup_does_not_wrap_hook_twice(tmp_path, previous_sys_hook):
    applog.setup(str(tmp_path))
    applog.setup(str(tmp_path))

    raise_and_hook()

    assert previous_sys_hook == [KeyError]


# ------------------------------------- hotkeys.py keyboard hook call site
NEXT_HOOK_RESULT = 7      # value returned by the fake CallNextHookEx


@pytest.fixture
def failing_interceptor(qtbot, monkeypatch):
    monkeypatch.setattr(hotkeys, "user32", SimpleNamespace(
        CallNextHookEx=lambda hook, n_code, wparam, lparam: NEXT_HOOK_RESULT))
    icp = hotkeys.AltInterceptor({})

    def broken(wparam, lparam):
        raise RuntimeError("handler bug")

    monkeypatch.setattr(icp, "_handle", broken)
    return icp


def test_hook_callback_exception_is_logged(failing_interceptor, caplog):
    failing_interceptor._on_key(0, 0x0100, 0)

    record = caplog.records[-1]
    assert (record.name, record.levelname, record.exc_info[0]) == (
        "armony.hotkeys", "ERROR", RuntimeError)


def test_hook_callback_exception_passes_key_through(failing_interceptor):
    assert failing_interceptor._on_key(0, 0x0100, 0) == NEXT_HOOK_RESULT
