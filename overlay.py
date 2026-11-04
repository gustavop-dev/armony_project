"""Hace la ventana invisible para la captura de pantalla / grabacion.

Usa SetWindowDisplayAffinity con WDA_EXCLUDEFROMCAPTURE (Windows 10 2004+ / Windows 11).
La ventana la sigues viendo tu; en cualquier compartir pantalla o grabacion sale como
un hueco negro (o simplemente no aparece). Es API nativa de Windows.
"""
import ctypes

WDA_NONE = 0x00
WDA_EXCLUDEFROMCAPTURE = 0x11  # requiere Windows 10 version 2004 (build 19041) o superior


GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020   # la ventana deja pasar los clics a lo que hay debajo
WS_EX_LAYERED = 0x00080000       # necesario para opacidad; siempre presente


def set_click_through(hwnd, enabled: bool) -> bool:
    """Activa/desactiva que los clics atraviesen la ventana.

    Con enabled=True, hacer clic sobre la app 'toca' el programa que hay debajo,
    como si el overlay fuera de cristal. Se alterna por zona: encendido en las
    partes decorativas, apagado sobre los controles (punticos, engranaje) para
    que esos si respondan.
    """
    try:
        u32 = ctypes.windll.user32
        u32.GetWindowLongW.restype = ctypes.c_long
        u32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        ex = u32.GetWindowLongW(int(hwnd), GWL_EXSTYLE)
        # Solo tocamos el bit de click-through. NO reasignamos WS_EX_LAYERED (lo
        # gestiona Qt para la opacidad); reasignarlo reseteaba la transparencia.
        nuevo = (ex | WS_EX_TRANSPARENT) if enabled else (ex & ~WS_EX_TRANSPARENT)
        if nuevo != ex:
            u32.SetWindowLongW(int(hwnd), GWL_EXSTYLE, nuevo)
        return True
    except Exception:
        return False


def set_no_activate(hwnd, activo=True) -> bool:
    """Impide (activo=False lo vuelve a permitir) que la ventana tome el foco
    al pulsarla.

    Comportamiento estandar de cualquier overlay (Discord, Steam, OBS): pulsar un
    boton del overlay no debe sacar el foco de la aplicacion en la que estas
    trabajando, porque perderias el cursor y el contexto de lo que estabas haciendo.
    """
    try:
        u32 = ctypes.windll.user32
        u32.GetWindowLongW.restype = ctypes.c_long
        actual = u32.GetWindowLongW(int(hwnd), GWL_EXSTYLE)
        nuevo = (actual | WS_EX_NOACTIVATE) if activo else (actual & ~WS_EX_NOACTIVATE)
        return bool(u32.SetWindowLongW(int(hwnd), GWL_EXSTYLE, nuevo))
    except Exception:
        return False


def set_capture_protection(hwnd, enabled: bool) -> bool:
    """Activa/desactiva la exclusion de captura para el HWND dado.

    Devuelve True si Windows acepto la llamada.
    """
    try:
        affinity = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(hwnd), affinity))
    except Exception:
        return False


# --------------------------------------------------------------- vidrio
# Acrilico de Windows (desenfoque + tinte) detras de una ventana translucida.
# Va por SetWindowCompositionAttribute (sin documentar, estable desde Windows 10
# 1803): las "system backdrops" de Windows 11 (Mica/Acrylic) se vuelven solidas
# con la ventana inactiva, y el overlay no se activa nunca a proposito.
_WCA_ACCENT_POLICY = 19
_ACCENT_ACRYLIC = 4
_ACCENT_DISABLED = 0


class _AccentPolicy(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _WinCompAttrData(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


def set_acrylic(hwnd, tinte=(14, 17, 26), alpha=0.5) -> bool:
    """Desenfoca lo que hay detras de la ventana y lo tine (alpha 0..1). Con
    alpha None lo quita. Devuelve True si Windows acepto la llamada."""
    try:
        if alpha is None:
            politica = _AccentPolicy(_ACCENT_DISABLED, 0, 0, 0)
        else:
            r, g, b = tinte
            a = max(0, min(255, round(alpha * 255)))
            # GradientColor va en AABBGGRR
            politica = _AccentPolicy(_ACCENT_ACRYLIC, 2, (a << 24) | (b << 16) | (g << 8) | r, 0)
        datos = _WinCompAttrData(_WCA_ACCENT_POLICY,
                                 ctypes.cast(ctypes.pointer(politica), ctypes.c_void_p),
                                 ctypes.sizeof(politica))
        return bool(ctypes.windll.user32.SetWindowCompositionAttribute(
            int(hwnd), ctypes.byref(datos)))
    except Exception:
        return False


def vidrio_disponible() -> bool:
    """True si una ventana translucida (por pixel) se puede excluir de la
    captura y llevar acrilico en este Windows.

    En versiones anteriores Windows rechazaba ocultar ventanas 'layered' al
    compartir pantalla; por eso se prueba con una ventana de verdad antes de
    crear el overlay. Si falla, el overlay sigue con fondo solido.
    """
    from PySide6 import QtCore, QtWidgets
    if QtWidgets.QApplication.instance() is None or not hasattr(ctypes, "windll"):
        return False
    if QtWidgets.QApplication.platformName() != "windows":
        return False
    prueba = QtWidgets.QWidget()
    prueba.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool)
    prueba.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
    prueba.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
    prueba.resize(8, 8)
    prueba.show()
    try:
        hwnd = int(prueba.winId())
        ok = set_capture_protection(hwnd, True) and set_acrylic(hwnd, alpha=0.5)
    finally:
        prueba.close()
        prueba.deleteLater()
    return ok


# --------------------------------------------------------------- foco
# La caja de preguntas es la unica ventana del overlay que se escribe: tiene
# que poder quitarle el teclado a la app en la que estas (Zoom, el editor...) y
# devolverselo al cerrarse. Windows no deja que una app en segundo plano se
# ponga delante por su cuenta (SetForegroundWindow falla en silencio); unirse
# un momento a la cola de entrada de la ventana activa (AttachThreadInput) es
# la forma de que lo acepte, sin inyectar teclas.

def _user32():
    u32 = ctypes.windll.user32
    u32.GetForegroundWindow.restype = ctypes.c_void_p
    u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    u32.GetWindowThreadProcessId.restype = ctypes.c_uint32
    u32.AttachThreadInput.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int]
    u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    u32.BringWindowToTop.argtypes = [ctypes.c_void_p]
    u32.IsWindow.argtypes = [ctypes.c_void_p]
    return u32


def ventana_activa():
    """HWND de la ventana que tiene el foco ahora (0 si no se sabe)."""
    try:
        return int(_user32().GetForegroundWindow() or 0)
    except Exception:
        return 0


def traer_al_frente(hwnd) -> int:
    """Pone la ventana delante y con el teclado. Devuelve el HWND que lo tenia
    (para devolverselo luego), o 0."""
    try:
        u32 = _user32()
        antes = int(u32.GetForegroundWindow() or 0)
        if antes == int(hwnd):
            return 0
        yo = ctypes.windll.kernel32.GetCurrentThreadId()
        suyo = u32.GetWindowThreadProcessId(antes, None) if antes else 0
        unido = bool(suyo and suyo != yo and u32.AttachThreadInput(yo, suyo, 1))
        try:
            u32.BringWindowToTop(int(hwnd))
            u32.SetForegroundWindow(int(hwnd))
        finally:
            if unido:
                u32.AttachThreadInput(yo, suyo, 0)
        return antes
    except Exception:
        return 0


def devolver_foco(hwnd) -> bool:
    """Devuelve el teclado a la ventana que lo tenia antes de abrir la caja."""
    try:
        u32 = _user32()
        if not hwnd or not u32.IsWindow(int(hwnd)):
            return False
        return bool(u32.SetForegroundWindow(int(hwnd)))
    except Exception:
        return False
