"""Tokens de diseno del overlay (Interview Overlay.dc.html).

Todos los colores, radios y tamanos salen de aqui: si el diseno cambia, se cambia
en un solo sitio. Los valores son literales del diseno original.
"""
import os
from PySide6 import QtGui

_HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(_HERE, "assets", "fonts")

# ---------------------------------------------------------------- color
GOLD          = "#f2c94c"   # acento principal
GOLD_LIGHT    = "#f7dd7f"
GOLD_HI       = "#ffe38a"
GOLD_DEEP     = "#d8a92f"
GOLD_LABEL    = "#e7b93a"   # etiquetas de seccion (Answer, Context...)
ANSWER_TEXT   = "#ffffff"   # cuerpo de la respuesta de la IA (blanco, maximo contraste)
GOLD_BTN_TOP  = "#f7d768"   # degradado del boton Generate
GOLD_BTN_BOT  = "#f2c94c"
GOLD_BTN_INK  = "#2a2410"

TEXT_BRIGHT   = "#f3ead4"
TEXT          = "#ece3cd"
TEXT_BODY     = "#f0e8d6"
TEXT_MUTED    = "#d9cfb8"
TEXT_DIM      = "#a89f8a"
TEXT_FAINT    = "#8f8674"

REC_DOT       = "#ff5f57"
REC_BORDER    = "rgba(217,74,61,0.5)"
REC_BG        = "rgba(217,74,61,0.18)"
REC_TEXT      = "#f6d9d4"

INTERVIEWER_DOT = "#b98d4a"

# Fondos SOLIDOS de los paneles.
#
# El diseno pedia paneles al 40% de opacidad (fondo por-pixel). En Windows eso
# convierte la ventana en "layered" y Windows RECHAZA ocultarla al compartir
# pantalla (SetWindowDisplayAffinity falla con err=8). Como la privacidad al
# compartir es el requisito principal, usamos fondo solido + una translucidez
# uniforme suave via opacidad de ventana (WINDOW_OPACITY), que si es compatible.
PANEL_TOP     = "#1b1811"
PANEL_BODY    = "#17140f"
PANEL_BORDER  = "rgba(242,201,76,0.35)"
PANEL_BORDER2 = "rgba(242,201,76,0.4)"

# Opacidad por defecto de las ventanas del overlay (se puede ajustar en config).
# Baja = mas transparente (se ve mas lo de detras); es compatible con la
# invisibilidad al compartir pantalla y con el click-through.
WINDOW_OPACITY = 0.65

DIVIDER       = "rgba(243,234,212,0.18)"
DIVIDER_SOFT  = "rgba(243,234,212,0.12)"
DIVIDER_FAINT = "rgba(243,234,212,0.10)"

BTN_BG        = "rgba(243,234,212,0.06)"
BTN_BG_HOVER  = "rgba(243,234,212,0.14)"
BTN_BORDER    = "rgba(243,234,212,0.14)"

KBD_BG        = "rgba(0,0,0,0.35)"
KBD_BG_LIGHT  = "rgba(0,0,0,0.18)"
KBD_TEXT      = "#d9d0ba"

INPUT_BG      = "rgba(0,0,0,0.25)"

# ---------------------------------------------------------------- medidas
R_TOPBAR   = 16
R_PANEL    = 18
R_BTN      = 11
R_BRAND    = 8
R_KBD      = 5
R_COLLAPSE = 12

PANEL_WIDTH   = 1080     # ancho del panel inferior
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
    fg = GOLD_BTN_INK if light else KBD_TEXT
    borde = "none" if light else f"1px solid {BTN_BORDER}"
    return (f"font-family: {MONO_STACK}; font-size: 11px; padding: 2px 5px;"
            f" border-radius: {R_KBD}px; background: {bg};"
            f" border: {borde}; color: {fg};")
