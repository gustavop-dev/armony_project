"""Tokens de diseno del overlay (Interview Overlay.dc.html).

Todos los colores, radios y tamanos salen de aqui: si el diseno cambia, se cambia
en un solo sitio. Los valores son literales del diseno original.
"""
import os
import re

from PySide6 import QtGui

_HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(_HERE, "assets", "fonts")

# ---------------------------------------------------------------- color
# Vidrio oscuro con un unico acento pervinca: el acento marca lo que importa
# (la respuesta, el boton principal, el agente) y todo lo demas es neutro frio.
ACCENT          = "#7c95ff"   # acento principal (pervinca, aclarado para fondo oscuro)
ACCENT_LIGHT    = "#a9b9ff"
ACCENT_HI       = "#c3ceff"
ACCENT_DEEP     = "#5b7cfa"
ACCENT_LABEL    = "#93a8ff"   # etiquetas de seccion (Answer, Context...)
ANSWER_TEXT     = "#ffffff"   # cuerpo de la respuesta de la IA (blanco, maximo contraste)
ACCENT_BTN_TOP  = "#8ea6ff"   # degradado del boton principal
ACCENT_BTN_BOT  = "#5b7cfa"
ACCENT_BTN_INK  = "#ffffff"

TEXT_BRIGHT   = "#f2f4fa"
TEXT          = "#e3e7f2"
TEXT_BODY     = "#edf0f7"
TEXT_MUTED    = "#c9cfde"
TEXT_DIM      = "#9aa3b8"
TEXT_FAINT    = "#7d869c"

REC_DOT       = "#ff5f57"
REC_BORDER    = "rgba(217,74,61,0.5)"
REC_BG        = "rgba(217,74,61,0.18)"
REC_TEXT      = "#f6d9d4"

INTERVIEWER_DOT = "#8e9bb8"

# Fondos de los paneles.
#
# Con vidrio (activar_vidrio, si Windows deja ocultar al compartir pantalla una
# ventana translucida) el fondo es un velo sobre el acrilico de Windows, que
# desenfoca lo de detras; el texto queda opaco. Sin vidrio, fondo solido y una
# translucidez uniforme por opacidad de ventana (WINDOW_OPACITY), que tambien
# atenua el texto pero es compatible con la invisibilidad en cualquier Windows.
PANEL_SOLID   = "#151824"     # menus y lo que no puede ser translucido
PANEL_TOP     = "#151824"
PANEL_BODY    = "#121520"
PANEL_BORDER  = "rgba(255,255,255,0.12)"
PANEL_BORDER2 = "rgba(124,149,255,0.45)"

# Opacidad por defecto de las ventanas del overlay (se puede ajustar en config).
# Baja = mas transparente (se ve mas lo de detras). Con vidrio regula el tinte
# del acrilico, no la ventana: el texto no se atenua.
WINDOW_OPACITY = 0.65

VIDRIO = False                # lo enciende activar_vidrio() al arrancar


def activar_vidrio():
    """Paneles de vidrio: velos translucidos en vez de fondos solidos. Se llama
    antes de crear las ventanas del overlay (leen estos valores al construirse)."""
    global VIDRIO, PANEL_TOP, PANEL_BODY
    VIDRIO = True
    PANEL_TOP = "rgba(18,21,32,0.30)"
    PANEL_BODY = "rgba(16,19,29,0.26)"


def qcolor(color):
    """QColor desde '#rrggbb' o 'rgba(r,g,b,a)' (QColor no lee el formato CSS)."""
    m = re.match(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)", color)
    if m:
        r, g, b_, a = m.groups()
        return QtGui.QColor(int(r), int(g), int(b_), round(float(a) * 255))
    return QtGui.QColor(color)


DIVIDER       = "rgba(220,228,255,0.16)"
DIVIDER_SOFT  = "rgba(220,228,255,0.10)"
DIVIDER_FAINT = "rgba(220,228,255,0.08)"

BTN_BG        = "rgba(220,228,255,0.06)"
BTN_BG_HOVER  = "rgba(220,228,255,0.14)"
BTN_BORDER    = "rgba(220,228,255,0.12)"

KBD_BG        = "rgba(255,255,255,0.08)"
KBD_BG_LIGHT  = "rgba(255,255,255,0.05)"
KBD_TEXT      = "#d5dbea"

INPUT_BG      = "rgba(0,0,0,0.25)"

# ---------------------------------------------------------------- medidas
R_TOPBAR   = 16
R_PANEL    = 18
R_BTN      = 11
R_BRAND    = 8
R_KBD      = 5
R_COLLAPSE = 12

PANEL_WIDTH   = 1080     # ancho del panel inferior
# Columnas laterales: el hablado solo, a la derecha; con pantallazos, el hablado
# pasa a la izquierda y la pantalla (codigo, mas ancha) ocupa la derecha.
COLUMN_WIDTH   = 460     # panel de la conversacion hablada
SCREEN_WIDTH   = 640     # panel de la pantalla (codigo)
SIDE_MARGIN    = 16      # separacion de los bordes laterales
COLUMN_GAP     = 12      # entre la barra superior y las columnas
PANEL_MARGIN   = 80      # margen minimo a los lados
TOP_OFFSET     = 20      # separacion desde el borde superior
BOTTOM_OFFSET  = 26      # separacion desde el borde inferior

# ---------------------------------------------------------------- tipografia
# El diseno usa Instrument Sans y JetBrains Mono. No vienen con Windows: si las
# dejas en assets/fonts/ se cargan; si no, se usa la alternativa mas parecida.
SANS_STACK = "'Instrument Sans', 'Segoe UI Variable Display', 'Segoe UI', sans-serif"
MONO_STACK = "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace"

_loaded = {"sans": False, "mono": False}


def load_fonts():
    """Carga las tipografias del diseno si estan disponibles en assets/fonts/."""
    if not os.path.isdir(FONT_DIR):
        return _loaded
    for fn in os.listdir(FONT_DIR):
        if not fn.lower().endswith((".ttf", ".otf")):
            continue
        fid = QtGui.QFontDatabase.addApplicationFont(os.path.join(FONT_DIR, fn))
        if fid == -1:
            continue
        for fam in QtGui.QFontDatabase.applicationFontFamilies(fid):
            low = fam.lower()
            if "instrument" in low:
                _loaded["sans"] = True
            elif "jetbrains" in low:
                _loaded["mono"] = True
    return _loaded


def fonts_missing():
    """Devuelve las familias del diseno que no se pudieron cargar."""
    faltan = []
    if not _loaded["sans"]:
        faltan.append("Instrument Sans")
    if not _loaded["mono"]:
        faltan.append("JetBrains Mono")
    return faltan


def kbd_qss(light=False):
    """Estilo de las teclas (Ctrl, B, H, Enter) mostradas en los botones."""
    bg = KBD_BG_LIGHT if light else KBD_BG
    fg = ACCENT_BTN_INK if light else KBD_TEXT
    borde = "none" if light else f"1px solid {BTN_BORDER}"
    return (f"font-family: {MONO_STACK}; font-size: 11px; padding: 2px 5px;"
            f" border-radius: {R_KBD}px; background: {bg};"
            f" border: {borde}; color: {fg};")
