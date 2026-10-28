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


def set_no_activate(hwnd) -> bool:
    """Impide que la ventana tome el foco al pulsarla.

    Comportamiento estandar de cualquier overlay (Discord, Steam, OBS): pulsar un
    boton del overlay no debe sacar el foco de la aplicacion en la que estas
    trabajando, porque perderias el cursor y el contexto de lo que estabas haciendo.
    """
    try:
        u32 = ctypes.windll.user32
        u32.GetWindowLongW.restype = ctypes.c_long
        actual = u32.GetWindowLongW(int(hwnd), GWL_EXSTYLE)
        return bool(u32.SetWindowLongW(int(hwnd), GWL_EXSTYLE,
                                       actual | WS_EX_NOACTIVATE))
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
