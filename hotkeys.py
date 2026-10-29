"""Atajos globales de Windows con captura exclusiva de Alt.

Por que globales y no atajos normales de Qt: durante una reunion el foco esta en
Zoom / Meet / Teams, no en el overlay. Un atajo de Qt solo dispara con la ventana
enfocada, asi que no serviria de nada.

Atajos actuales (pensados para teclado 60%, sin teclas F):
    Alt+1    mostrar / ocultar overlay
    Alt+2    captura de pantalla (se pueden encadenar varias)
    Alt+3    generar respuesta con las capturas tomadas
    Alt+4    iniciar / detener la reunion
    Alt+5    responder ahora a lo ultimo que dijeron (aunque no pareciera pregunta)
    Alt+6    actualizar la solucion en pantalla con lo que acaban de decir

Se usa Alt (no Shift) porque Alt no interviene al escribir texto; con Shift+tecla
se bloquearia esa tecla en todo el sistema.

Por que un hook de bajo nivel y no solo RegisterHotKey
------------------------------------------------------
RegisterHotKey consume la *combinacion* (Alt+1 no le llega a Excel), pero el Alt
suelto si viaja a la ventana enfocada. Excel/Word abren las KeyTips del ribbon en
cuanto ven ese Alt, asi que el atajo "limpio" ensuciaba igual la app de abajo.

Un hook WH_KEYBOARD_LL se ejecuta antes que cualquier otra aplicacion y antes que
el despacho de hotkeys: si devuelve 1, el evento se descarta y NADIE lo recibe.
Con eso Alt (y el 1..4 que lo acompaña) quedan en exclusiva para esta app
mientras el programa esta en ejecucion.

Excepciones deliberadas: si tras el Alt viene una tecla que no es 1..4 (Tab, F4,
flechas...), se reinyecta el Alt al sistema y se deja pasar la combinacion, para
no romper Alt+Tab, Alt+F4 ni los atajos con Alt del resto de Windows.

RegisterHotKey se mantiene como red de seguridad: si el hook no se puede instalar
(o Windows lo desactiva por timeout), los atajos siguen funcionando, aunque en
ese caso el Alt vuelva a filtrarse.
"""
import ctypes
import logging
import threading
from ctypes import wintypes

from PySide6 import QtCore

log = logging.getLogger("armony.hotkeys")

user32 = ctypes.windll.user32

WM_HOTKEY = 0x0312
MOD_SHIFT = 0x0004
MOD_CONTROL = 0x0002
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000        # evita repeticion al mantener pulsado

VK_1, VK_2, VK_3, VK_4, VK_5 = 0x31, 0x32, 0x33, 0x34, 0x35   # fila superior '1'..'5'
VK_6 = 0x36

# Alt + numero: comodo en teclado 60% (todo en la capa principal, sin Fn) y Alt
# no se usa al escribir, asi que no bloquea ninguna tecla del teclado.
#
# id -> (modificadores, tecla, nombre legible)
BINDINGS = {
    1: (MOD_ALT, VK_1, "Alt+1"),
    2: (MOD_ALT, VK_2, "Alt+2"),
    3: (MOD_ALT, VK_3, "Alt+3"),
    4: (MOD_ALT, VK_4, "Alt+4"),
    5: (MOD_ALT, VK_5, "Alt+5"),
    6: (MOD_ALT, VK_6, "Alt+6"),
}
ACTION_TOGGLE, ACTION_SHOT, ACTION_GENERATE, ACTION_MEETING = 1, 2, 3, 4
ACTION_ANSWER = 5
ACTION_RELAUNCH = 6       # relanzar la solucion en pantalla con lo que dijeron

# --- constantes del hook de bajo nivel -------------------------------------
WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
LLKHF_INJECTED = 0x10

VK_MENU, VK_LMENU, VK_RMENU = 0x12, 0xA4, 0xA5
VK_CONTROL, VK_LCONTROL, VK_RCONTROL = 0x11, 0xA2, 0xA3
_ALT_VKS = (VK_MENU, VK_LMENU, VK_RMENU)
_CTRL_VKS = (VK_CONTROL, VK_LCONTROL, VK_RCONTROL)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MAPVK_VK_TO_VSC = 0

# Firma propia en dwExtraInfo: ademas del flag INJECTED, permite reconocer sin
# ambiguedad las pulsaciones que reinyecta esta app.
_TAG = 0x41524D59   # 'ARMY'

ULONG_PTR = ctypes.c_size_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    # el padding iguala el tamaño de MOUSEINPUT, que es el miembro mas grande
    _fields_ = [("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE,
                                     wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]

WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000


def _send_keys(*events):
    """Reinyecta pulsaciones. events: secuencia de (vk, is_up)."""
    arr = (INPUT * len(events))()
    for i, (vk, is_up) in enumerate(events):
        flags = KEYEVENTF_KEYUP if is_up else 0
        if vk == VK_RMENU:
            flags |= KEYEVENTF_EXTENDEDKEY
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki = KEYBDINPUT(wVk=vk,
                               wScan=user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC),
                               dwFlags=flags, time=0, dwExtraInfo=_TAG)
    user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))


class _Bridge(QtCore.QObject):
    """Pasa la accion del hilo del hook al hilo de Qt.

    El slot tiene que ser un metodo de este QObject (creado en el hilo de Qt):
    conectar a una funcion suelta daria una conexion directa y la accion se
    ejecutaria en el hilo del hook, tocando la GUI desde fuera de su hilo.
    """
    triggered = QtCore.Signal(int)

    def __init__(self, dispatch):
        super().__init__()
        self._dispatch = dispatch
        self.triggered.connect(self._run, QtCore.Qt.QueuedConnection)

    @QtCore.Slot(int)
    def _run(self, vk):
        self._dispatch(vk)


class AltInterceptor:
    """Captura Alt en exclusiva para esta app mediante un hook WH_KEYBOARD_LL.

    Mientras esta instalado:
      - Alt (down y up) se descarta: ninguna otra aplicacion lo ve, asi que Excel
        no abre las KeyTips ni Windows activa la barra de menu.
      - Alt + 1..4 dispara la accion y se descarta tambien el numero, para que no
        se escriba en la app de abajo.
      - Alt + cualquier otra tecla se devuelve al sistema (se reinyecta el Alt que
        habiamos tragado) para no romper Alt+Tab, Alt+F4, etc.
      - Con Ctrl pulsado el Alt pasa intacto: eso cubre Ctrl+Alt+tecla y, sobre
        todo, AltGr (que el driver manda como Ctrl izquierdo + Alt derecho). Sin
        esta excepcion no se podrian escribir | @ # ~ en teclado español.
    """

    def __init__(self, actions):
        """actions: dict {vk: callback} (p. ej. {VK_1: toggle_overlay})."""
        self._actions = dict(actions)
        self._hook = None
        self._proc = HOOKPROC(self._on_key)   # referencia viva: si se recolecta, crash
        self._enabled = True
        self._alt_down = False        # Alt fisico pulsado (lo hayamos tragado o no)
        self._alt_vk = VK_LMENU       # cual de los dos Alt esta pulsado
        self._ctrl_down = False       # para distinguir AltGr / Ctrl+Alt
        self._passthrough = False     # ya devolvimos este Alt al sistema
        self._eaten = set()           # teclas cuyo keydown tragamos: tragar su keyup
        self._thread = None
        self._tid = 0
        self._ready = threading.Event()
        # creado en el hilo de Qt: lo que se emita desde el hook llega en cola
        self._bridge = _Bridge(self._dispatch)

    # -- ciclo de vida ------------------------------------------------------
    def install(self):
        """Instala el hook en un hilo propio. Devuelve True si quedo activo.

        El hook vive en su propio hilo con su bucle de mensajes, no en el de Qt:
        si el hilo de la GUI se queda ocupado (p. ej. codificando la captura de
        pantalla en PNG) tardaria mas que LowLevelHooksTimeout y Windows se
        saltaria el hook -- el Alt se filtraria a Excel justo en ese momento, y
        Windows puede llegar a desinstalarlo.
        """
        if self._thread and self._thread.is_alive():
            return bool(self._hook)
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="alt-hook",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(5.0)
        return bool(self._hook)

    def _run(self):
        msg = wintypes.MSG()
        # fuerza la creacion de la cola de mensajes antes de anunciar el tid,
        # si no un PostThreadMessage inmediato se perderia
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        self._ready.set()
        if not self._hook:
            log.warning("SetWindowsHookExW(WH_KEYBOARD_LL) failed; Alt shortcuts "
                        "fall back to RegisterHotKey")
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass          # solo se espera al WM_QUIT de uninstall()
        finally:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def uninstall(self):
        if self._thread and self._thread.is_alive() and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2.0)
        self._thread = None
        self._hook = None
        # si habiamos devuelto un Alt al sistema y aun no llego su keyup, soltarlo
        if self._passthrough:
            _send_keys((self._alt_vk, True))
        self._reset()

    def _dispatch(self, vk):
        cb = self._actions.get(vk)
        if cb is not None:
            cb()

    def set_enabled(self, on):
        """Permite desactivar la captura sin desinstalar el hook."""
        self._enabled = bool(on)
        if not on:
            if self._passthrough:
                _send_keys((self._alt_vk, True))
            self._reset()

    @property
    def active(self):
        return bool(self._hook) and self._enabled

    def _reset(self):
        self._alt_down = False
        self._ctrl_down = False
        self._passthrough = False
        self._eaten.clear()

    # -- hook ---------------------------------------------------------------
    def _on_key(self, nCode, wParam, lParam):
        # Windows descarta el hook si tarda demasiado (LowLevelHooksTimeout), asi
        # que aqui no se hace nada lento: los callbacks se encolan en el bucle Qt.
        try:
            if nCode == HC_ACTION and self._enabled:
                swallow = self._handle(wParam, lParam)
                if swallow:
                    return 1
        except Exception:
            # ante cualquier fallo, dejar pasar la tecla
            log.exception("Keyboard hook callback failed; key passed through")
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _handle(self, wParam, lParam):
        kb = KBDLLHOOKSTRUCT.from_address(lParam)
        vk = int(kb.vkCode)
        down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
        propio = kb.dwExtraInfo == _TAG

        if propio:
            # Solo se ignora lo que reinyecta esta app (de ahi la firma): asi no
            # hay bucle, pero si siguen valiendo las pulsaciones inyectadas por
            # otros -- teclado en pantalla, remapeadores, teclados macro.
            return False

        if vk in _CTRL_VKS:
            self._ctrl_down = down

        if vk in _ALT_VKS:
            if down:
                self._alt_vk = vk
                self._alt_down = True
                if self._ctrl_down:
                    # AltGr o Ctrl+Alt+tecla: no es nuestro, no se toca.
                    self._passthrough = True
                    return False
                # si ya devolvimos el Alt al sistema, dejar pasar las repeticiones
                return not self._passthrough
            # keyup de Alt
            self._alt_down = False
            if self._passthrough:
                self._passthrough = False
                return False    # cierra el Alt que reinyectamos
            return True         # Alt tragado de principio a fin: nadie lo vio

        # Before the passthrough branch: a bound digit whose key-down was
        # swallowed must lose its key-up too, even if the combo was handed back
        # to the system in between (Alt, 1, Tab, release 1). Otherwise it stays
        # in _eaten and the next Alt+digit is swallowed without firing.
        if not down and vk in self._eaten:
            self._eaten.discard(vk)
            return True         # el keyup del numero tampoco sale de aqui

        if self._passthrough:
            return False        # combinacion cedida al sistema

        if self._alt_down and down:
            if vk in _CTRL_VKS:
                # Ctrl pulsado despues del Alt: aun no se sabe si sera Ctrl+Alt+X.
                # Se deja pasar y se decide con la tecla final, que reinyectara el
                # Alt si hace falta.
                return False
            if vk in self._actions:
                if vk not in self._eaten:      # sin autorepeticion al mantener
                    self._eaten.add(vk)
                    # emitir es barato; la accion se ejecuta luego en el hilo Qt
                    self._bridge.triggered.emit(vk)
                return True
            # No es atajo nuestro (Alt+Tab, Alt+F4...): devolver el Alt al sistema.
            # Se reinyectan Alt y la tecla juntos, y se traga el evento original,
            # para que lleguen en ese orden; dejarlo pasar lo colaria antes del Alt.
            self._passthrough = True
            _send_keys((self._alt_vk, False), (vk, False))
            return True

        return False


class GlobalHotkeys(QtCore.QAbstractNativeEventFilter):
    """Atajos globales: hook de Alt como via principal, RegisterHotKey de respaldo."""

    def __init__(self, callbacks):
        """callbacks: dict {ACTION_*: funcion}."""
        super().__init__()
        self._callbacks = callbacks
        self._registered = []
        self._failed = []
        self._alt = AltInterceptor({
            vk: callbacks[hk_id]
            for hk_id, (_mods, vk, _n) in BINDINGS.items()
            if hk_id in callbacks
        })

    @property
    def exclusive_alt(self):
        """True si Alt queda reservado para esta app (nadie mas lo recibe)."""
        return self._alt.active

    def register(self):
        """Instala hook + atajos. Devuelve (registrados, fallidos)."""
        self._alt.install()
        for hk_id, (mods, vk, nombre) in BINDINGS.items():
            # hWnd=None: el mensaje va a la cola del hilo, que Qt ya procesa.
            # Con el hook activo esto no llega a dispararse (el hook consume la
            # tecla antes), pero cubre el caso de que el hook no este disponible.
            if user32.RegisterHotKey(None, hk_id, mods | MOD_NOREPEAT, vk):
                self._registered.append(hk_id)
            else:
                # Otra aplicacion ya tiene esa combinacion registrada.
                self._failed.append(nombre)
        return [BINDINGS[i][2] for i in self._registered], self._failed

    def unregister(self):
        self._alt.uninstall()
        for hk_id in self._registered:
            try:
                user32.UnregisterHotKey(None, hk_id)
            except Exception:
                log.debug("UnregisterHotKey(%d) failed", hk_id, exc_info=True)
        self._registered = []

    def set_alt_capture(self, on):
        """Activa/desactiva la captura exclusiva de Alt en caliente."""
        self._alt.set_enabled(on)

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
