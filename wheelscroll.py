"""Rueda del raton sobre el overlay, sin renunciar al click-through.

El overlay es "de cristal": los clics atraviesan y van al programa de debajo. Eso
se consigue con WS_EX_TRANSPARENT, y el problema es que Windows no distingue por
tipo de mensaje -- la ventana no recibe NADA del raton, ni siquiera la rueda. Con
una respuesta larga te quedabas sin poder subir a leerla, salvo apuntando a la
barra de desplazamiento, que son diez pixeles.

La solucion es la misma idea que con Alt: un hook de bajo nivel ve la rueda antes
que nadie. Si el cursor esta sobre la zona de la respuesta, se hace scroll en el
overlay y el evento se descarta, asi que el Excel de debajo no se mueve. Si esta
en cualquier otro sitio, se deja pasar y todo sigue como siempre.

La zona la publica el hilo de Qt (una tupla de enteros que el hook solo lee), y
el scroll se ejecuta tambien en el hilo de Qt: aqui dentro no se toca la interfaz.
"""
import ctypes
import threading
from ctypes import wintypes

from PySide6 import QtCore

user32 = ctypes.windll.user32

WH_MOUSE_LL = 14
HC_ACTION = 0
WM_MOUSEWHEEL = 0x020A
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000

RUEDA_POR_MUESCA = 120     # WHEEL_DELTA


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE,
                                     wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]


class _Bridge(QtCore.QObject):
    """Lleva la muesca de rueda del hilo del hook al hilo de Qt (en cola)."""
    wheeled = QtCore.Signal(int)

    def __init__(self, destino):
        super().__init__()
        self._destino = destino
        self.wheeled.connect(self._run, QtCore.Qt.QueuedConnection)

    @QtCore.Slot(int)
    def _run(self, muescas):
        self._destino(muescas)


class WheelForwarder:
    """Desvia la rueda al overlay cuando el cursor esta sobre su zona scrollable."""

    def __init__(self, on_scroll):
        """on_scroll(muescas): positivo = hacia arriba. Corre en el hilo de Qt."""
        self._bridge = _Bridge(on_scroll)
        self._proc = HOOKPROC(self._on_mouse)   # referencia viva o crash
        self._hook = None
        self._thread = None
        self._tid = 0
        self._ready = threading.Event()
        self._zona = None        # (x, y, ancho, alto) en coordenadas de pantalla

    # -- zona activa ---------------------------------------------------------
    def set_zone(self, zona):
        """Publica el rectangulo que captura la rueda. None = no capturar nada.

        Se llama desde el hilo de Qt; el hook solo lee la tupla.
        """
        self._zona = tuple(zona) if zona else None

    def _dentro(self, x, y):
        z = self._zona
        if not z:
            return False
        return z[0] <= x < z[0] + z[2] and z[1] <= y < z[1] + z[3]

    # -- ciclo de vida -------------------------------------------------------
    def install(self):
        if self._thread and self._thread.is_alive():
            return bool(self._hook)
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="wheel-hook",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(5.0)
        return bool(self._hook)

    def _run(self):
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        self._ready.set()
        if not self._hook:
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
        finally:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def uninstall(self):
        if self._thread and self._thread.is_alive() and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2.0)
        self._thread = None
        self._hook = None
        self._zona = None

    @property
    def active(self):
        return bool(self._hook)

    # -- hook ----------------------------------------------------------------
    def _on_mouse(self, nCode, wParam, lParam):
        # El hook de raton se llama para CADA movimiento: aqui no puede haber
        # nada lento o Windows lo descarta por LowLevelHooksTimeout.
        try:
            if nCode == HC_ACTION and wParam == WM_MOUSEWHEEL and self._zona:
                ms = MSLLHOOKSTRUCT.from_address(lParam)
                if self._dentro(ms.pt.x, ms.pt.y):
                    delta = ctypes.c_short((ms.mouseData >> 16) & 0xFFFF).value
                    muescas = delta // RUEDA_POR_MUESCA
                    if muescas:
                        self._bridge.wheeled.emit(muescas)
                    return 1        # tragada: lo de debajo no se mueve
        except Exception:
            pass
        return user32.CallNextHookEx(None, nCode, wParam, lParam)
