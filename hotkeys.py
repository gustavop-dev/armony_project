"""Atajos globales de Windows (RegisterHotKey).

Por que globales y no atajos normales de Qt: durante una reunion el foco esta en
Zoom / Meet / Teams, no en el overlay. Un atajo de Qt solo dispara con la ventana
enfocada, asi que no serviria de nada.

Atajos actuales (pensados para teclado 60%, sin teclas F):
    Alt+1    mostrar / ocultar overlay
    Alt+2    captura de pantalla (se pueden encadenar varias)
    Alt+3    generar respuesta con las capturas tomadas
    Alt+4    iniciar / detener la reunion

Se usa Alt (no Shift) porque Alt no interviene al escribir texto; con Shift+tecla
se bloquearia esa tecla en todo el sistema. Windows entrega la combinacion
registrada a esta aplicacion y no a la que tiene el foco.
"""
import ctypes
from ctypes import wintypes

from PySide6 import QtCore

WM_HOTKEY = 0x0312
MOD_SHIFT = 0x0004
MOD_CONTROL = 0x0002
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000        # evita repeticion al mantener pulsado

VK_1, VK_2, VK_3, VK_4 = 0x31, 0x32, 0x33, 0x34   # teclas '1'..'4' de la fila superior

# Alt + numero: comodo en teclado 60% (todo en la capa principal, sin Fn) y Alt
# no se usa al escribir, asi que no bloquea ninguna tecla del teclado.
#
# id -> (modificadores, tecla, nombre legible)
BINDINGS = {
    1: (MOD_ALT, VK_1, "Alt+1"),
    2: (MOD_ALT, VK_2, "Alt+2"),
    3: (MOD_ALT, VK_3, "Alt+3"),
    4: (MOD_ALT, VK_4, "Alt+4"),
}
ACTION_TOGGLE, ACTION_SHOT, ACTION_GENERATE, ACTION_MEETING = 1, 2, 3, 4


class GlobalHotkeys(QtCore.QAbstractNativeEventFilter):
    """Registra los atajos en Windows y los traduce a callbacks."""

    def __init__(self, callbacks):
        """callbacks: dict {ACTION_*: funcion}."""
        super().__init__()
        self._callbacks = callbacks
        self._registered = []
        self._failed = []

    def register(self):
        """Intenta registrar todos los atajos. Devuelve (ok, fallidos)."""
        user32 = ctypes.windll.user32
        for hk_id, (mods, vk, nombre) in BINDINGS.items():
            # hWnd=None: el mensaje va a la cola del hilo, que Qt ya procesa.
            if user32.RegisterHotKey(None, hk_id, mods | MOD_NOREPEAT, vk):
                self._registered.append(hk_id)
            else:
                # Otra aplicacion ya tiene esa combinacion registrada.
                self._failed.append(nombre)
        return [BINDINGS[i][2] for i in self._registered], self._failed

    def unregister(self):
        user32 = ctypes.windll.user32
        for hk_id in self._registered:
            try:
                user32.UnregisterHotKey(None, hk_id)
            except Exception:
                pass
        self._registered = []

    def nativeEventFilter(self, eventType, message):
        if eventType != b"windows_generic_MSG":
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == WM_HOTKEY:
            cb = self._callbacks.get(int(msg.wParam))
            if cb is not None:
                cb()
                return True, 0
        return False, 0
