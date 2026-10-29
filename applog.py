"""Rotating file log for the ``armony`` logger hierarchy.

``setup(data_dir)`` attaches one ``RotatingFileHandler`` writing
``<data_dir>/logs/armony.log`` to the ``armony`` logger (the root logger is not
touched) and wraps ``sys.excepthook`` / ``threading.excepthook`` so uncaught
exceptions are written to that file before the previous hook runs.

Modules log through child loggers (``logging.getLogger("armony.<module>")``),
which inherit the handler. Privacy rule for every call site: log exception
types, library error messages, HTTP status codes, counts, durations and file
paths only; never API keys, config values, prompts, transcript text, model
output, screenshots or context bodies.
"""
import logging
import logging.handlers
import os
import sys
import threading

LOGGER_NAME = "armony"
LOG_DIR = "logs"
LOG_FILE = "armony.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3
FORMAT = "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s"

log = logging.getLogger(LOGGER_NAME)

# Hooks that were active before setup() wrapped them; the wrappers delegate here.
_previous_sys_hook = None
_previous_thread_hook = None


def _is_own_handler(handler):
    return getattr(handler, "_armony_file", False)


def setup(data_dir):
    """Attach the rotating file handler and install the exception hooks.

    Idempotent: a repeated call with the same directory changes nothing; a call
    with another directory replaces the handler. Returns the log file path.
    Raises OSError if the log directory cannot be created.
    """
    path = os.path.join(data_dir, LOG_DIR, LOG_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for handler in list(log.handlers):
        if not _is_own_handler(handler):
            continue
        if handler.baseFilename == os.path.abspath(path):
            _install_hooks()
            return path
        log.removeHandler(handler)
        handler.close()
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter(FORMAT))
    handler._armony_file = True
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    _install_hooks()
    return path


def _install_hooks():
    global _previous_sys_hook, _previous_thread_hook
    if sys.excepthook is not _sys_excepthook:
        _previous_sys_hook = sys.excepthook
        sys.excepthook = _sys_excepthook
    if threading.excepthook is not _thread_excepthook:
        _previous_thread_hook = threading.excepthook
        threading.excepthook = _thread_excepthook


def _sys_excepthook(exc_type, exc_value, exc_traceback):
    """Log an uncaught main-thread exception at CRITICAL, then delegate."""
    if not issubclass(exc_type, KeyboardInterrupt):
        log.critical("Uncaught exception",
                     exc_info=(exc_type, exc_value, exc_traceback))
    previous = _previous_sys_hook or sys.__excepthook__
    previous(exc_type, exc_value, exc_traceback)


def _thread_excepthook(args):
    """Log an uncaught worker-thread exception at ERROR, then delegate."""
    if args.exc_type is not SystemExit:
        name = args.thread.name if args.thread is not None else "unknown"
        log.error("Uncaught exception in thread %s", name,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    previous = _previous_thread_hook or threading.__excepthook__
    previous(args)
