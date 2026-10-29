"""Atajos globales de Windows: Bloq Mayus como tecla propia de Armony.

Por que globales y no atajos normales de Qt: durante una reunion el foco esta en
Zoom / Meet / Teams, no en el overlay. Un atajo de Qt solo dispara con la ventana
enfocada, asi que no serviria de nada.

Atajos (Bloq Mayus mantenido + tecla, todo junto a la mano izquierda en reposo):
    Bloq Mayus+A    responder ahora a lo ultimo que dijeron (el mas usado)
    Bloq Mayus+S    captura de pantalla (se pueden encadenar varias)
    Bloq Mayus+D    generar respuesta con las capturas tomadas
    Bloq Mayus+F    actualizar la solucion en pantalla con lo que acaban de decir
    Bloq Mayus+Q    mostrar / ocultar overlay
    Bloq Mayus+Esc  iniciar / detener la reunion (a proposito, dificil sin querer)

Por que Bloq Mayus y no Alt + numero: los numeros quedan lejos de la mano y
Alt + letra choca con las apps de reunion (en Zoom, Alt+A silencia, Alt+S
comparte pantalla y Alt+Q termina la reunion). Bloq Mayus no lo usa ninguna, y
como modificador propio no hace falta tragar ni reinyectar teclas del sistema.

Solo durante la reunion: fuera de ella (en la Home) Bloq Mayus y Alt+1..6 son
de las demas apps, como si Armony no estuviera (ver GlobalHotkeys.set_activo).
En la reunion, Bloq Mayus deja de bloquear mayusculas: el hook se traga la
tecla, asi que nadie la ve. Shift+Bloq Mayus pasa intacto y lo activa de
verdad, como siempre.

Por que un hook de bajo nivel: RegisterHotKey solo admite Alt / Ctrl / Shift /
Win como modificadores, no Bloq Mayus. Un hook WH_KEYBOARD_LL se ejecuta antes
que cualquier otra aplicacion: si devuelve 1, el evento se descarta y NADIE lo
recibe.

Respaldo: Alt+1..6 (los atajos de antes) siguen registrados con RegisterHotKey.
Sirven si el hook no se puede instalar o si Bloq Mayus esta remapeada a otra
tecla; en ese caso el Alt suelto si llega a la app de abajo.
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
VK_A, VK_S, VK_D, VK_F, VK_Q = 0x41, 0x53, 0x44, 0x46, 0x51
VK_ESCAPE = 0x1B
VK_CAPITAL = 0x14            # Bloq Mayus

ACTION_TOGGLE, ACTION_SHOT, ACTION_GENERATE, ACTION_MEETING = 1, 2, 3, 4
ACTION_ANSWER = 5
ACTION_RELAUNCH = 6       # relanzar la solucion en pantalla con lo que dijeron

# Capa de Bloq Mayus (via principal): accion -> (tecla, nombre legible)
CAPS_BINDINGS = {
    ACTION_ANSWER: (VK_A, "Caps+A"),
    ACTION_SHOT: (VK_S, "Caps+S"),
    ACTION_GENERATE: (VK_D, "Caps+D"),
    ACTION_RELAUNCH: (VK_F, "Caps+F"),
    ACTION_TOGGLE: (VK_Q, "Caps+Q"),
    ACTION_MEETING: (VK_ESCAPE, "Caps+Esc"),
}

# Respaldo con RegisterHotKey (los atajos de antes, misma accion por numero):
# id -> (modificadores, tecla, nombre legible)
BINDINGS = {
    1: (MOD_ALT, VK_1, "Alt+1"),
    2: (MOD_ALT, VK_2, "Alt+2"),
    3: (MOD_ALT, VK_3, "Alt+3"),
    4: (MOD_ALT, VK_4, "Alt+4"),
    5: (MOD_ALT, VK_5, "Alt+5"),
    6: (MOD_ALT, VK_6, "Alt+6"),
}

# --- constantes del hook de bajo nivel -------------------------------------
WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105

VK_SHIFT, VK_LSHIFT, VK_RSHIFT = 0x10, 0xA0, 0xA1
_SHIFT_VKS = (VK_SHIFT, VK_LSHIFT, VK_RSHIFT)

ULONG_PTR = ctypes.c_size_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


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
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]

WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000


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


class CapsLayer:
    """Bloq Mayus como modificador propio, mediante un hook WH_KEYBOARD_LL.

    Mientras esta instalado:
      - Bloq Mayus (down, repeticiones y up) se descarta: nadie la ve, asi que
        no cambia mayusculas.
      - Bloq Mayus + tecla con accion dispara la accion una vez (sin
        autorepeticion) y se descarta tambien la tecla, down y up, para que no
        se escriba en la app de abajo.
      - Bloq Mayus + cualquier otra tecla: la tecla pasa tal cual.
      - Shift + Bloq Mayus pasa intacto: es la forma de activar mayusculas.
    """

    def __init__(self, actions):
        """actions: dict {vk: callback} (p. ej. {VK_A: answer_now})."""
        self._actions = dict(actions)
        self._hook = None
        self._proc = HOOKPROC(self._on_key)   # referencia viva: si se recolecta, crash
        self._enabled = True
        self._caps_down = False       # Bloq Mayus pulsada y tragada
        self._caps_paso = False       # Shift+Bloq Mayus: esta pulsacion es del sistema
        self._shift_down = False
        self._eaten = set()           # teclas cuyo keydown tragamos: tragar su keyup
        self._fuera = set()           # teclas con accion pulsadas antes de Bloq Mayus
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
        saltaria el hook -- Bloq Mayus cambiaria las mayusculas justo en ese
        momento, y Windows puede llegar a desinstalarlo.
        """
        if self._thread and self._thread.is_alive():
            return bool(self._hook)
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="caps-hook",
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
            log.warning("SetWindowsHookExW(WH_KEYBOARD_LL) failed; Caps Lock shortcuts "
                        "unavailable, Alt+1..6 still work")
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
        self._reset()

    def _dispatch(self, vk):
        cb = self._actions.get(vk)
        if cb is not None:
            cb()

    def set_enabled(self, on):
        """Permite desactivar la captura sin desinstalar el hook."""
        self._enabled = bool(on)
        if not on:
            self._reset()

    @property
    def active(self):
        return bool(self._hook) and self._enabled

    def _reset(self):
        self._caps_down = False
        self._caps_paso = False
        self._shift_down = False
        self._eaten.clear()
        self._fuera.clear()

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

        if vk in _SHIFT_VKS:
            self._shift_down = down
            return False

        if vk == VK_CAPITAL:
            if down:
                if self._caps_paso:
                    return False            # repeticion de un Shift+Bloq Mayus
                if self._shift_down and not self._caps_down:
                    self._caps_paso = True  # Shift+Bloq Mayus: mayusculas de verdad
                    return False
                self._caps_down = True
                return True
            # keyup
            if self._caps_paso:
                self._caps_paso = False
                return False
            self._caps_down = False
            return True

        # El keyup de una tecla tragada se traga siempre, aunque Bloq Mayus ya
        # se haya soltado (Caps, A, soltar Caps, soltar A).
        if not down:
            self._fuera.discard(vk)
            if vk in self._eaten:
                self._eaten.discard(vk)
                return True
            return False

        if vk not in self._actions:
            return False
        if not self._caps_down or vk in self._fuera:
            # Tecla normal (o mantenida desde antes de Bloq Mayus, cuyas
            # repeticiones no deben disparar nada).
            self._fuera.add(vk)
            return False
        if vk not in self._eaten:           # sin autorepeticion al mantener
            self._eaten.add(vk)
            # emitir es barato; la accion se ejecuta luego en el hilo Qt
            self._bridge.triggered.emit(vk)
        return True


class GlobalHotkeys(QtCore.QAbstractNativeEventFilter):
    """Atajos globales: capa de Bloq Mayus como via principal, Alt+1..6 de respaldo."""

    def __init__(self, callbacks):
        """callbacks: dict {ACTION_*: funcion}."""
        super().__init__()
        self._callbacks = callbacks
        self._registered = []
        self._failed = []
        self._caps = CapsLayer({
            vk: callbacks[accion]
            for accion, (vk, _n) in CAPS_BINDINGS.items()
            if accion in callbacks
        })

    @property
    def caps_layer(self):
        """True si los atajos con Bloq Mayus estan activos."""
        return self._caps.active

    @property
    def hook_instalado(self):
        """True si Windows dejo instalar el hook (sin el, solo hay Alt+1..6)."""
        return bool(self._caps._hook)

    def register(self):
        """Instala hook + atajos de respaldo, ya activos. Devuelve (registrados,
        fallidos) de los de respaldo (Alt+1..6)."""
        self._caps.install()
        self._registrar_respaldo()
        return [BINDINGS[i][2] for i in self._registered], self._failed

    def instalar(self):
        """Instala el hook sin activar nada: hasta set_activo(True) deja pasar
        todas las teclas y no hay Alt+1..6 registrados."""
        self._caps.set_enabled(False)
        self._caps.install()

    def set_activo(self, on):
        """Atajos solo durante la reunion. Activa (o apaga) la capa de Bloq
        Mayus y registra (o libera) los Alt+1..6 de respaldo. Devuelve los de
        respaldo que no se pudieron registrar (otra app los tiene)."""
        self._caps.set_enabled(on)
        if on:
            self._registrar_respaldo()
            return list(self._failed)
        self._liberar_respaldo()
        return []

    def _registrar_respaldo(self):
        self._failed = []
        for hk_id, (mods, vk, nombre) in BINDINGS.items():
            if hk_id in self._registered:
                continue
            # hWnd=None: el mensaje va a la cola del hilo, que Qt ya procesa.
            if user32.RegisterHotKey(None, hk_id, mods | MOD_NOREPEAT, vk):
                self._registered.append(hk_id)
            else:
                # Otra aplicacion ya tiene esa combinacion registrada.
                self._failed.append(nombre)

    def _liberar_respaldo(self):
        for hk_id in self._registered:
            try:
                user32.UnregisterHotKey(None, hk_id)
            except Exception:
                log.debug("UnregisterHotKey(%d) failed", hk_id, exc_info=True)
        self._registered = []

    def unregister(self):
        self._caps.uninstall()
        self._liberar_respaldo()

    def set_caps_layer(self, on):
        """Activa/desactiva la capa de Bloq Mayus en caliente."""
        self._caps.set_enabled(on)

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
