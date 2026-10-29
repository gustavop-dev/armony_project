"""Interfaz del overlay, segun 'Interview Overlay.dc.html'.

Dos ventanas flotantes, sin marco, translucidas al 40% y siempre encima:
  - TopBar          barra de atajos centrada arriba
  - TranscriptPanel ventana de transcripcion + respuesta sugerida, abajo
Mas dos elementos auxiliares: CollapsedButton (cuando el overlay esta oculto)
y FlashOverlay (destello al capturar pantalla).
"""
import html
import math

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid

import avatares
import icons
from feedanchor import ANCLADO, FeedAnchor
import richtext
import theme as T
from metrics import PINTADO, metricas

# Cada cuanto se repinta la respuesta mientras llega. Bastante mas rapido que
# leer, pero mil veces menos trabajo que reconstruir el panel en cada trozo.
INTERVALO_REPINTADO = 90    # ms
# A partir de aqui la latencia se ensena en la cabecera (por debajo no hay nada
# que mirar): transcripcion y carrera completa pregunta -> primera palabra.
LATENCIA_LENTA_MS = 1500
RESPUESTA_LENTA_MS = 3000
AVISO_MS = 4000              # lo que dura un aviso de paso en la pastilla

# Cuantos mensajes se mantienen vivos en el hilo.
#
# Redimensionar el panel cuesta en proporcion a lo que haya dentro, y sin tope
# eso crecia toda la reunion: medido, 19 ms por paso de arrastre con 2 turnos,
# 114 con 12 y 178 con 20. Por eso se trababa mas cuanto mas avanzada iba.
#
# Con tope el coste deja de crecer, y en 10 se queda en unos 40 ms por paso aun
# con 40 turnos hablados. Subirlo se paga enseguida (14 ya son ~50) y bajarlo a
# 8 apenas gana, asi que 10 es el punto donde deja de doler.
#
# Lo que sale no se pierde: la conversacion entera queda en el acta de la sesion.
# Y el caso de uso tampoco pide subir mucho -- el scroll se usa para leer una
# respuesta larga, no para repasar la reunion de hace media hora.
MAX_FILAS_HILO = 10

# Barra de desplazamiento a juego con el overlay. La de Windows (canal gris y
# pulgar negro) se veia pegada encima de la interfaz, no como parte de ella.
_BARRA_QSS = f"""
    QScrollArea {{ background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 4px 2px 22px 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(124,149,255,0.28);
        border-radius: 5px; min-height: 34px;
    }}
    QScrollBar::handle:vertical:hover {{ background: rgba(124,149,255,0.5); }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    /* La horizontal solo aparece cuando una linea de codigo no cabe. Se deja
       hueco a la derecha por el agarre de redimension, igual que la vertical. */
    QScrollBar:horizontal {{
        background: transparent; height: 10px; margin: 0 22px 3px 16px;
    }}
    QScrollBar::handle:horizontal {{
        background: rgba(124,149,255,0.28);
        border-radius: 5px; min-width: 34px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: rgba(124,149,255,0.5); }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
"""


# --------------------------------------------------------------- utilidades

def _frameless(win):
    """Ventana sin marco, siempre encima y fuera de la barra de tareas.

    Con vidrio (T.VIDRIO) la ventana es translucida por pixel: los fondos son
    velos y el acrilico de Windows (overlay.set_acrylic, desde app.py) desenfoca
    lo de detras, con el texto opaco. Solo se enciende si overlay.vidrio_disponible()
    comprobo que Windows aun puede ocultarla al compartir pantalla.

    Sin vidrio NO se usa WA_TranslucentBackground: en Windows antiguos convierte
    la ventana en 'layered' y Windows rechaza ocultarla al compartir. Entonces:
    fondo solido + opacidad de ventana uniforme + esquinas por mascara.
    """
    win.setWindowFlags(
        QtCore.Qt.FramelessWindowHint
        | QtCore.Qt.WindowStaysOnTopHint
        | QtCore.Qt.Tool
    )
    if T.VIDRIO:
        win.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
    else:
        win.setWindowOpacity(T.WINDOW_OPACITY)


def _round_mask(win, radius):
    """Aplica esquinas redondeadas via mascara (necesario sin fondo translucido)."""
    if win.width() <= 0 or win.height() <= 0:
        return
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(0, 0, win.width(), win.height()),
                        radius, radius)
    win.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))


class ClickFrame(QtWidgets.QFrame):
    """Boton con contenido compuesto (texto + teclas).

    QPushButton calcula su tamano a partir de su texto e ignora el layout interno,
    asi que los botones del diseno saldrian encogidos. QFrame si respeta el layout.
    """
    clicked = QtCore.Signal()

    def __init__(self, drags_window=False):
        """drags_window: a press that moves beyond the drag distance moves the
        top-level window instead of clicking (used by CollapsedButton, whose
        whole surface is this frame)."""
        super().__init__()
        self._drags_window = drags_window
        self._press = None          # (global press point, window top-left)
        self._dragged = False
        # A proposito NO se cambia el cursor. La ventana es invisible al compartir
        # pantalla, pero el cursor NO lo es: si se volviera una manita al pasar
        # sobre un boton, quien te ve compartiendo pantalla veria el puntero
        # transformandose encima de la nada. El overlay se delataria solo.

    def mousePressEvent(self, e):
        if self._drags_window and e.button() == QtCore.Qt.LeftButton:
            self._press = (e.globalPosition().toPoint(),
                           self.window().frameGeometry().topLeft())
            self._dragged = False
        e.accept()          # no propagar: evita arrastrar la ventana al pulsar

    def mouseMoveEvent(self, e):
        if self._press is not None and e.buttons() & QtCore.Qt.LeftButton:
            delta = e.globalPosition().toPoint() - self._press[0]
            if (self._dragged or delta.manhattanLength()
                    >= QtWidgets.QApplication.startDragDistance()):
                self._dragged = True
                self.window().move(self._press[1] + delta)
        e.accept()

    def mouseReleaseEvent(self, e):
        dragged, self._press, self._dragged = self._dragged, None, False
        if (not dragged and e.button() == QtCore.Qt.LeftButton
                and self.rect().contains(e.position().toPoint())):
            self.clicked.emit()
        e.accept()


def _kbd(texto, light=False):
    lab = QtWidgets.QLabel(texto)
    lab.setStyleSheet(T.kbd_qss(light))
    lab.setAlignment(QtCore.Qt.AlignCenter)
    return lab


def _keys(*teclas, light=False):
    """Grupo de teclas, p. ej. Ctrl + B."""
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    for t in teclas:
        lay.addWidget(_kbd(t, light))
    return w


def _tracked(label, px, weight, color, spacing=1.0, upper=False):
    """Etiqueta con letter-spacing (QSS no lo soporta: hay que usar QFont)."""
    lab = QtWidgets.QLabel(label.upper() if upper else label)
    f = lab.font()
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, spacing)
    lab.setFont(f)
    lab.setStyleSheet(f"color: {color}; background: transparent;")
    return lab


class _TituloElastico(QtWidgets.QLabel):
    """Titulo que cede ancho recortandose con "…" en vez de ensanchar su fila.

    En la columna hablada la cabecera lleva titulo, estado, agarre y agente; con
    letra grande o un nombre de agente largo, un titulo rigido la desbordaba.
    """

    def __init__(self, texto, fuente, color):
        super().__init__(texto)
        self._completo = texto
        self.setFont(fuente)
        self.setStyleSheet(f"color: {color}; background: transparent;")
        self.setMinimumWidth(40)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

    def sizeHint(self):
        fm = self.fontMetrics()
        return QtCore.QSize(fm.horizontalAdvance(self._completo) + 2,
                            super().sizeHint().height())

    def minimumSizeHint(self):
        return QtCore.QSize(self.minimumWidth(), super().minimumSizeHint().height())

    def resizeEvent(self, e):
        self.setText(self.fontMetrics().elidedText(
            self._completo, QtCore.Qt.ElideRight, self.width()))
        super().resizeEvent(e)


class _Draggable:
    """Permite arrastrar una ventana sin marco desde cualquier zona vacia."""

    def _init_drag(self):
        self.__off = None

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.__off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self.__off is not None and e.buttons() & QtCore.Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self.__off)
            e.accept()

    def mouseReleaseEvent(self, e):
        self.__off = None


# --------------------------------------------------------------- barras de audio

class DragBar(QtWidgets.QWidget):
    """Cabecera que arrastra la ventana de nivel superior, como una barra de titulo.

    Mover desde aqui reposiciona todo el panel manteniendo pulsado, igual que
    cualquier ventana de Windows.
    """

    def __init__(self):
        super().__init__()
        # Sin cambio de cursor: la senal de que se puede arrastrar son los
        # punticos (GripDots), no el puntero.
        self._off = None

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._off = (e.globalPosition().toPoint()
                         - self.window().frameGeometry().topLeft())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._off is not None and e.buttons() & QtCore.Qt.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._off)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._off = None


class GripDots(QtWidgets.QWidget):
    """Rejilla de punticos que indica que la cabecera se puede arrastrar.

    Es la senal visual (en vez de cambiar el cursor): dos filas de puntos
    centradas, como el 'agarre' de las apps que se pueden reposicionar.
    """

    def __init__(self, cols=6, rows=2, gap=5, r=1.4):
        super().__init__()
        self._cols, self._rows, self._gap, self._r = cols, rows, gap, r
        self.setFixedSize(cols * gap, rows * gap)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)  # el arrastre lo hace la cabecera

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        col = QtGui.QColor(T.TEXT_FAINT)
        p.setBrush(col)
        p.setPen(QtCore.Qt.NoPen)
        for iy in range(self._rows):
            for ix in range(self._cols):
                cx = ix * self._gap + self._gap / 2
                cy = iy * self._gap + self._gap / 2
                p.drawEllipse(QtCore.QPointF(cx, cy), self._r, self._r)
        p.end()


class ResizeGrip(QtWidgets.QWidget):
    """Agarre en la esquina inferior derecha para redimensionar el panel.

    Estilo de punticos diagonales, como la barra de arriba. No cambia el cursor
    (el usuario lo pidio asi). Redimensiona la ventana de nivel superior.
    """

    MIN_W, MIN_H = 520, 200

    def __init__(self):
        super().__init__()
        self.setFixedSize(18, 18)
        self._start = None

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QColor(T.TEXT_FAINT))
        p.setPen(QtCore.Qt.NoPen)
        # triangulo de puntos en diagonal (\)
        pts = [(12, 4), (4, 12), (12, 12)]
        for cx, cy in pts:
            p.drawEllipse(QtCore.QPointF(cx, cy), 1.4, 1.4)
        p.drawEllipse(QtCore.QPointF(8, 8), 1.4, 1.4)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._start = (e.globalPosition().toPoint(), self.window().size())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._start is not None and e.buttons() & QtCore.Qt.LeftButton:
            ini, size0 = self._start
            d = e.globalPosition().toPoint() - ini
            w = max(self.MIN_W, size0.width() + d.x())
            h = max(self.MIN_H, size0.height() + d.y())
            self.window().resize(w, h)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._start = None


class StatusBadge(QtWidgets.QWidget):
    """Pastilla de estado con puntito de color (idle / cargando / escuchando...)."""

    # texto -> (color del punto/borde, si el fondo va tenido)
    COLORS = {
        "idle":        ("#7d869c", False),
        "loading":     ("#93a8ff", True),
        "listening":   ("#3ddc84", True),   # verde bonito
        "transcribing": ("#7c95ff", True),
        "drafting":    ("#7c95ff", True),
        "analyzing":   ("#7c95ff", True),
        "error":       ("#e0554b", True),
        "info":        ("#7d869c", False),
    }

    def __init__(self):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(9, 3, 11, 3)
        lay.setSpacing(6)
        self._dot = QtWidgets.QLabel(); self._dot.setFixedSize(7, 7)
        lay.addWidget(self._dot)
        self._lbl = QtWidgets.QLabel("Idle")
        lf = self._lbl.font(); lf.setPixelSize(12); self._lbl.setFont(lf)
        lay.addWidget(self._lbl)
        self.set("Idle", "idle")

    def set(self, texto, kind):
        color, tinted = self.COLORS.get(kind, self.COLORS["info"])
        self._dot.setStyleSheet(f"background: {color}; border-radius: 3px;")
        self._lbl.setStyleSheet(f"color: {color if tinted else '#9aa3b8'}; background: transparent;")
        rgb = QtGui.QColor(color)
        bg = (f"rgba({rgb.red()},{rgb.green()},{rgb.blue()},0.14)" if tinted
              else "rgba(220,228,255,0.05)")
        bd = (f"rgba({rgb.red()},{rgb.green()},{rgb.blue()},0.45)" if tinted
              else "rgba(220,228,255,0.10)")
        self.setStyleSheet(
            f"StatusBadge {{ background: {bg}; border: 1px solid {bd}; border-radius: 11px; }}")
        self._lbl.setText(texto)


class _AutoScroll:
    """Decide donde se queda un area con scroll (la decision vive en
    feedanchor.FeedAnchor): pegada al final, donde la dejaste, o anclada a la
    respuesta que estas leyendo.

    Dos detalles que parecen tonterias y no lo son:

    1. El alto definitivo del contenido no se sabe al pintar, sino cuando Qt
       recalcula el layout, que es cuando se emite rangeChanged. Bajar antes deja
       el texto arriba.
    2. Repintar destruye y recrea los widgets; al vaciarlos el rango cae a cero y
       con el la posicion. Sin guardarla, subir a releer no serviria de nada.
    """

    MARGEN = 8      # pixeles de tolerancia para considerarse "al final"
    # Si la pregunta que precede a la respuesta ocupa menos que esto (fraccion
    # del alto visible), se ancla la pregunta: se lee que te preguntaron y
    # debajo que contestar, como en un chat.
    PREGUNTA_VISIBLE = 0.4

    def __init__(self, scroll, on_nuevo_abajo=None):
        self.scroll = scroll
        self.ancla = FeedAnchor(margen_final=self.MARGEN)
        self._on_nuevo_abajo = on_nuevo_abajo or (lambda hay: None)
        self._anclados = None            # (respuesta, pregunta o None)
        self._ajustando = False
        sb = scroll.verticalScrollBar()
        sb.rangeChanged.connect(lambda *_: self.restaurar())
        # Tambien cuenta lo que mueva Qt por su cuenta: el gesto del panel
        # tactil o arrastrar la barra. Si no, se seguiria el final igualmente y
        # el texto nuevo te devolveria abajo justo cuando subiste a releer.
        sb.valueChanged.connect(self._movido_a_mano)

    # -- anclado ---------------------------------------------------------------
    def anclar(self, respuesta, pregunta=None):
        """Desde ya, lo que se lee es esta respuesta: no se mueve de arriba."""
        self._anclados = (respuesta, pregunta)
        self.ancla.anclar()
        self._avisar()

    def ir_al_final(self):
        self._anclados = None
        self.ancla.ir_al_final()
        self.restaurar()
        self._avisar()

    def contenido_nuevo(self):
        self.ancla.contenido_nuevo()
        self._avisar()

    def _avisar(self):
        self._on_nuevo_abajo(self.ancla.nuevo_abajo)

    def _y_ancla(self):
        """y (en el contenido) de lo que se ancla, o None si ya no existe."""
        if not self._anclados:
            return None
        respuesta, pregunta = self._anclados
        cont = self.scroll.widget()
        if not isValid(respuesta) or cont is None:
            return None
        y = respuesta.mapTo(cont, QtCore.QPoint(0, 0)).y()
        if pregunta is not None and isValid(pregunta):
            yp = pregunta.mapTo(cont, QtCore.QPoint(0, 0)).y()
            if 0 <= y - yp <= self.scroll.viewport().height() * self.PREGUNTA_VISIBLE:
                y = yp
        return y

    # -- seguimiento -----------------------------------------------------------
    def _movido_a_mano(self, valor):
        if self._ajustando:
            return
        anclado_antes = self._anclados is not None
        self.ancla.movido_a_mano(valor, self.scroll.verticalScrollBar().maximum())
        self._anclados = None
        if anclado_antes:
            self.restaurar()             # quita el hueco reservado debajo
        self._avisar()

    def anotar(self):
        """Antes de repintar: recuerda donde estabas y si venias siguiendo."""
        sb = self.scroll.verticalScrollBar()
        self.ancla.anotar(sb.value(), sb.maximum())

    def restaurar(self):
        sb = self.scroll.verticalScrollBar()
        self._ajustando = True       # lo que movamos aqui no es "a mano"
        try:
            if self._anclados is not None:
                self.ancla.ubicar(self._y_ancla())
                if self.ancla.modo != ANCLADO:
                    self._anclados = None
            cont = self.scroll.widget()
            if cont is not None:
                alto = self.ancla.alto_minimo(self.scroll.viewport().height())
                if cont.minimumHeight() != alto:
                    cont.setMinimumHeight(alto)    # vuelve por rangeChanged
            sb.setValue(self.ancla.valor(sb.maximum()))
        finally:
            self._ajustando = False

    def rueda(self, muescas):
        """muescas positivas = hacia arriba.

        El salto se mide contra el alto visible, no con el singleStep de Qt:
        ese son ~20 px, y en un panel grande con conversacion larga mover 60 px
        por muesca se siente como que la rueda no hace nada.
        """
        sb = self.scroll.verticalScrollBar()
        salto = max(80, int(self.scroll.viewport().height() * 0.28))
        self._ajustando = True
        try:
            sb.setValue(sb.value() - muescas * salto)
        finally:
            self._ajustando = False
        # La rueda es mover a mano: suelta el anclado y decide por posicion.
        self._movido_a_mano(sb.value())

    def zona(self):
        """Rectangulo en pantalla, para el desviador de rueda."""
        if not self.scroll.isVisible():
            return None
        tl = self.scroll.mapToGlobal(QtCore.QPoint(0, 0))
        return (tl.x(), tl.y(), self.scroll.width(), self.scroll.height())


# Color de la pestaña de cada lenguaje, el que se le asocia de siempre. Sirve
# para reconocer de un vistazo que trae el bloque sin leer la etiqueta.
_COLOR_LENGUAJE = {
    "python": "#7ee0c6", "py": "#7ee0c6",
    "javascript": "#7c95ff", "js": "#7c95ff",
    "typescript": "#89ddf0", "ts": "#89ddf0", "tsx": "#89ddf0",
    "java": "#f2a06a", "kotlin": "#c58af9",
    "sql": "#b3e08a", "bash": "#b3e08a", "sh": "#b3e08a", "shell": "#b3e08a",
    "html": "#ffa96b", "css": "#89ddf0",
    "json": "#ffd479", "yaml": "#ffd479", "yml": "#ffd479",
    "go": "#89ddf0", "rust": "#ffa96b", "c": "#9ad2e0", "cpp": "#9ad2e0",
    "csharp": "#c58af9", "cs": "#c58af9", "php": "#c58af9", "ruby": "#f08fb0",
}


class CodeBlock(QtWidgets.QFrame):
    """Bloque de codigo: cabecera con el lenguaje, boton de copiar y el cuerpo.

    El cuerpo va en texto plano y monoespaciado a proposito: asi los saltos de
    linea y la indentacion salen tal cual los escribio el modelo, que es lo unico
    que hace legible el codigo.
    """

    def __init__(self, lenguaje, codigo):
        super().__init__()
        self._codigo = codigo
        color_leng = _COLOR_LENGUAJE.get((lenguaje or "").lower(), T.ACCENT_LABEL)
        # Fondo bastante mas opaco que el resto del panel: el codigo tiene que
        # leerse como un editor, no como texto flotando sobre la reunion. Y un
        # filo del color del lenguaje, que es lo que lo marca como bloque de
        # codigo desde el otro lado de la pantalla.
        self.setStyleSheet(f"""
            CodeBlock {{
                background: rgba(6,7,10,0.92);
                border: 1px solid rgba(124,149,255,0.18);
                border-left: 2px solid {color_leng};
                border-radius: 8px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        cab = QtWidgets.QWidget()
        # Barra de titulo, un punto mas clara que el cuerpo: separa el bloque del
        # resto de la respuesta sin necesidad de otra linea.
        cab.setStyleSheet("background: rgba(255,255,255,0.035); "
                          "border-top-left-radius: 8px; "
                          "border-top-right-radius: 8px;")
        cl = QtWidgets.QHBoxLayout(cab)
        cl.setContentsMargins(10, 5, 6, 5)
        cl.setSpacing(7)

        # Punto de color del lenguaje, como la pestaña de un editor.
        punto = QtWidgets.QLabel()
        punto.setFixedSize(7, 7)
        punto.setStyleSheet(f"background: {color_leng}; border-radius: 3px;")
        cl.addWidget(punto)

        etq = QtWidgets.QLabel((lenguaje or "code").upper())
        ef = etq.font(); ef.setPixelSize(10); ef.setWeight(QtGui.QFont.DemiBold)
        ef.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 0.8)
        etq.setFont(ef)
        etq.setStyleSheet(f"color: {color_leng}; background: transparent;")
        cl.addWidget(etq)
        cl.addStretch()

        self.btn_copy = ClickFrame()
        self.btn_copy.setStyleSheet(f"""
            QFrame {{ border: 1px solid {T.BTN_BORDER}; border-radius: 6px;
                      background: {T.BTN_BG}; }}
            QFrame:hover {{ background: {T.BTN_BG_HOVER}; }}
            QLabel {{ border: none; background: transparent; }}
        """)
        bl = QtWidgets.QHBoxLayout(self.btn_copy)
        bl.setContentsMargins(8, 3, 8, 3)
        self.lbl_copy = QtWidgets.QLabel("Copy")
        cf = self.lbl_copy.font(); cf.setPixelSize(10); self.lbl_copy.setFont(cf)
        self.lbl_copy.setStyleSheet(f"color: {T.TEXT_DIM}; background: transparent;")
        bl.addWidget(self.lbl_copy)
        self.btn_copy.clicked.connect(self._copiar)
        cl.addWidget(self.btn_copy)
        lay.addWidget(cab)

        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {T.DIVIDER_FAINT}; border: none;")
        lay.addWidget(sep)

        coloreado = richtext.resaltar(codigo, lenguaje, numerar=True)
        cuerpo = QtWidgets.QLabel()
        if coloreado:
            # &nbsp; y <br> conservan sangria y saltos, que es lo unico que hace
            # legible el codigo, y ademas cada token va con su color.
            cuerpo.setTextFormat(QtCore.Qt.RichText)
            cuerpo.setText(f'<div style="font-family:{T.MONO_STACK}; '
                           f'font-size:12.5px; line-height:145%;">{coloreado}</div>')
        else:
            cuerpo.setTextFormat(QtCore.Qt.PlainText)   # respeta saltos y espacios
            cuerpo.setText(codigo)
            cuerpo.setStyleSheet(f"font-family: {T.MONO_STACK}; font-size: 12.5px; "
                                 f"color: {T.TEXT_BRIGHT};")
        cuerpo.setWordWrap(True)
        cuerpo.setStyleSheet(cuerpo.styleSheet() +
                             "background: transparent; padding: 9px 11px;")
        # Nada de texto seleccionable: Qt pondria el cursor de texto encima, y el
        # cursor si se ve al compartir pantalla aunque la ventana no. Ademas la
        # seleccion no funcionaria (esta zona deja pasar los clics): para eso esta
        # el boton de copiar.
        lay.addWidget(cuerpo)

    def _copiar(self):
        QtWidgets.QApplication.clipboard().setText(self._codigo)
        self.lbl_copy.setText("Copied")
        # Context-object overload: Qt drops the call if the label is destroyed
        # first (answer re-render, row pruning, limpiar_hilo).
        QtCore.QTimer.singleShot(1400, self.lbl_copy, lambda: self.lbl_copy.setText("Copy"))


class ShotThumb(QtWidgets.QFrame):
    """Miniatura de una captura enviada, al estilo de un mensaje propio."""

    def __init__(self, pixmap, ancho=190):
        super().__init__()
        self.setStyleSheet(f"""
            ShotThumb {{ background: {T.KBD_BG_LIGHT};
                         border: 1px solid {T.PANEL_BORDER};
                         border-radius: 8px; }}
            QLabel {{ border: none; background: transparent; }}
        """)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 4)
        lay.setSpacing(3)
        img = QtWidgets.QLabel()
        img.setPixmap(pixmap.scaledToWidth(ancho, QtCore.Qt.SmoothTransformation))
        lay.addWidget(img)
        pie = QtWidgets.QLabel("screenshot sent")
        pf = pie.font(); pf.setPixelSize(9); pie.setFont(pf)
        pie.setStyleSheet(f"color: {T.TEXT_FAINT}; background: transparent;")
        pie.setAlignment(QtCore.Qt.AlignRight)
        lay.addWidget(pie)


class PanelCard(QtWidgets.QFrame):
    """Fondo y borde del panel, pintados a mano.

    El borde late mientras escucha, once veces por segundo. Hacerlo con
    setStyleSheet obliga a Qt a repasar el estilo de TODOS los hijos, y el hilo
    de conversacion son cientos de widgets: medido, 377 ms por fotograma con
    quince turnos, o sea que ni terminaba antes del siguiente. La app se atascaba
    mas cuanto mas larga era la reunion.

    Pintarlo aqui es un repintado de este widget y nada mas.
    """

    def __init__(self):
        super().__init__()
        self._color = QtGui.QColor(210, 220, 223, 36)
        self._grosor = 1

    def set_borde(self, color, grosor):
        if color == self._color and grosor == self._grosor:
            return
        self._color, self._grosor = color, grosor
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        m = self._grosor / 2
        r = QtCore.QRectF(self.rect()).adjusted(m, m, -m, -m)
        p.setBrush(T.qcolor(T.PANEL_BODY))
        p.setPen(QtGui.QPen(self._color, self._grosor))
        p.drawRoundedRect(r, T.R_PANEL, T.R_PANEL)
        p.end()


class Burbuja(QtWidgets.QFrame):
    """Un mensaje del hilo: lo que dijeron ellos, o lo que se te sugiere decir.

    Las de ellos van a la izquierda y en gris; las tuyas a la derecha y en
    dorado, como en cualquier chat. Asi de un vistazo sabes quien dijo que sin
    tener que leer, que es lo unico que puedes permitirte en mitad de una
    reunion.
    """

    def __init__(self, quien, ancho_maximo=700):
        super().__init__()
        self.quien = quien                       # 'ellos' | 'tu'
        self._raw = ""
        self._label = None                       # etiqueta reutilizada del texto
        self.copy_buttons = []
        mio = quien == "tu"
        self.setStyleSheet(f"""
            Burbuja {{
                background: {'rgba(124,149,255,0.07)' if mio else 'rgba(220,228,255,0.04)'};
                border: 1px solid {'rgba(124,149,255,0.28)' if mio else T.DIVIDER_FAINT};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        self.setMaximumWidth(ancho_maximo)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(13, 9, 13, 10)
        lay.setSpacing(5)

        cab = QtWidgets.QHBoxLayout()
        cab.setSpacing(6)
        self._cab = cab
        self._actualizada = None
        if mio:
            cab.addStretch()
            cab.addWidget(icons.label("sparkles", T.ACCENT, 12))
            cab.addWidget(_tracked("You", 10, QtGui.QFont.Bold, T.ACCENT, 0.6, upper=True))
        else:
            cab.addWidget(_tracked("Participant", 10, QtGui.QFont.DemiBold,
                                   T.TEXT_FAINT, 0.6, upper=True))
            cab.addStretch()
        lay.addLayout(cab)

        self.cuerpo = QtWidgets.QVBoxLayout()
        self.cuerpo.setContentsMargins(0, 0, 0, 0)
        self.cuerpo.setSpacing(7)
        lay.addLayout(self.cuerpo)

    def marcar_actualizada(self):
        """La sugerencia se reescribio con lo que anadieron: que se note."""
        if self._actualizada is None:
            self._actualizada = _tracked("Updated", 10, QtGui.QFont.DemiBold,
                                         T.TEXT_FAINT, 0.6, upper=True)
            self._cab.insertWidget(1, self._actualizada)   # tras el hueco

    @property
    def actualizada(self):
        return self._actualizada is not None

    # -- contenido ----------------------------------------------------------
    def _vaciar(self):
        self.copy_buttons = []
        self._label = None
        while self.cuerpo.count():
            it = self.cuerpo.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

    def set_texto(self, texto, caret=False):
        """Texto llano (lo que dicen ellos), con caret mientras siguen hablando.

        La etiqueta se reutiliza en vez de rehacerla: el caret parpadea once
        veces por segundo y crear y destruir widgets a ese ritmo se nota.
        """
        self._raw = texto
        cursor = f'<span style="color:{T.ACCENT};">&#9611;</span>' if caret else ""
        html_ = (f'<div style="line-height:150%; color:{T.TEXT_BODY}; '
                 f'font-size:15px;">{html.escape(texto)}{cursor}</div>')
        if self._label is None:
            self._vaciar()
            self._label = QtWidgets.QLabel()
            self._label.setWordWrap(True)
            self._label.setTextFormat(QtCore.Qt.RichText)
            self.cuerpo.addWidget(self._label)
        self._label.setText(html_)

    def set_markdown(self, raw, parrafo, vinetas):
        """Respuesta del modelo: secciones, codigo, listas."""
        self._raw = raw
        self._vaciar()
        for etiqueta, bloques in richtext.parse_answer(raw):
            self.cuerpo.addWidget(_tracked(etiqueta, 10, QtGui.QFont.Bold,
                                           T.ACCENT_LABEL, 0.9, upper=True))
            for bloque in bloques:
                if bloque[0] == richtext.CODE:
                    cb = CodeBlock(bloque[1], bloque[2])
                    self.copy_buttons.append(cb.btn_copy)
                    self.cuerpo.addWidget(cb)
                elif bloque[0] == richtext.BULLETS:
                    self.cuerpo.addWidget(vinetas(bloque[1]))
                else:
                    self.cuerpo.addWidget(parrafo(bloque[1]))


class NewBelowChip(QtWidgets.QPushButton):
    """'nuevo ↓': hay conversacion por debajo de la respuesta que estas leyendo.

    Mientras lees, lo nuevo NO te mueve el texto: entra abajo y solo se avisa
    aqui. Pulsarlo baja al final y vuelve a seguir la conversacion.
    """

    def __init__(self):
        super().__init__("nuevo ↓")
        f = self.font(); f.setPixelSize(11); self.setFont(f)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum,
                           QtWidgets.QSizePolicy.Fixed)
        self.setStyleSheet(
            "QPushButton {"
            f"  color: {T.ACCENT_LABEL};"
            "   background: rgba(124,149,255,0.10);"
            "   border: 1px solid rgba(124,149,255,0.35);"
            "   border-radius: 9px;"
            "   padding: 3px 10px;"
            "}"
            "QPushButton:hover { background: rgba(124,149,255,0.18); }")
        self.setVisible(False)


class AgentChip(QtWidgets.QPushButton):
    """'Coach ▾': el agente en uso. Al pulsarlo, un menu para cambiarlo, tambien
    en plena reunion (la siguiente respuesta ya sale con el nuevo)."""
    chosen = QtCore.Signal(str)
    _ANCHO_MAX = 130        # del nombre; mas largo se recorta con "…"
    _RELLENO = 22           # padding y borde del estilo
    _FLECHA = " ▾"

    def __init__(self):
        super().__init__("")
        f = self.font(); f.setPixelSize(11); self.setFont(f)
        self.setToolTip("Agent answering — click to switch")
        # Ancho justo para su nombre (topado): un nombre largo se recorta en vez
        # de empujar la columna hablada fuera de su sitio.
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.nombre = ""
        # Es el titulo del panel: texto claro, sin caja; al pasar, se ve pulsable.
        f.setPixelSize(13); f.setWeight(QtGui.QFont.DemiBold); self.setFont(f)
        self.setStyleSheet(
            "QPushButton {"
            f"  color: {T.TEXT_BRIGHT};"
            "   background: transparent;"
            "   border: none;"
            "   border-radius: 8px;"
            "   padding: 2px 6px;"
            "   text-align: left;"
            "}"
            "QPushButton:hover { background: rgba(124,149,255,0.16); }")
        self.menu = QtWidgets.QMenu(self)
        self.menu.setStyleSheet(
            f"QMenu {{ background: {T.PANEL_SOLID}; border: 1px solid {T.PANEL_BORDER}; "
            f"border-radius: 8px; padding: 4px; color: {T.TEXT}; font-size: 12px; }}"
            "QMenu::item { padding: 5px 18px 5px 22px; border-radius: 5px; }"
            "QMenu::item:selected { background: rgba(124,149,255,0.18); }")
        # El menu es otra ventana: quien lo crea debe excluirlo de la captura
        # de pantalla igual que el overlay (si no, se veria al compartir).
        self.antes_de_mostrar = None
        self._agentes = []
        self._caras = {}
        self._expresion = avatares.ABIERTOS
        self.activo = ""
        self.clicked.connect(self._abrir)
        self.setVisible(False)

    _CARA = 18                # lado del personaje junto al nombre

    def set_agents(self, agentes, activo):
        """agentes: [(id, nombre)] o [(id, nombre, (personaje, color))];
        activo: id del que se usa."""
        self._agentes = [(a[0], a[1]) for a in agentes]
        self._caras = {a[0]: a[2] for a in agentes if len(a) > 2}
        self.activo = activo
        self.nombre = next((n for a, n in self._agentes if a == activo), "")
        self._pintar_cara()
        # Aun sin colocar no se sabe el ancho: se rotula con el maximo y el
        # resizeEvent lo ajusta al que le toque.
        self._rotular(self.sizeHint().width())
        self.updateGeometry()
        self.setVisible(bool(self._agentes))

    def _rotular(self, ancho=None):
        fm = self.fontMetrics()
        ancho = self.width() if ancho is None else ancho
        libre = min(self._ANCHO_MAX, ancho - self._RELLENO - self._hueco_cara()
                    - fm.horizontalAdvance(self._FLECHA))
        # Si cabe, entero: elidedText recorta por redondeo con el ancho justo.
        nombre = (self.nombre if fm.horizontalAdvance(self.nombre) <= libre
                  else fm.elidedText(self.nombre, QtCore.Qt.ElideRight, max(0, libre)))
        self.setText(nombre + self._FLECHA)

    def sizeHint(self):
        fm = self.fontMetrics()
        ancho = (min(self._ANCHO_MAX, fm.horizontalAdvance(self.nombre))
                 + fm.horizontalAdvance(self._FLECHA) + self._RELLENO + self._hueco_cara())
        return QtCore.QSize(ancho, super().sizeHint().height())

    def _hueco_cara(self):
        return self._CARA + 6 if not self.icon().isNull() else 0

    def _pintar_cara(self):
        cara = getattr(self, "_caras", {}).get(self.activo)
        if cara is None:
            self.setIcon(QtGui.QIcon())
            return
        self.setIcon(QtGui.QIcon(avatares.pixmap(*cara, self._CARA, self._expresion)))
        self.setIconSize(QtCore.QSize(self._CARA, self._CARA))

    def set_pensando(self, on):
        """Mientras redacta la respuesta, el personaje mira hacia arriba."""
        expresion = avatares.PENSANDO if on else avatares.ABIERTOS
        if expresion != self._expresion:
            self._expresion = expresion
            self._pintar_cara()

    def minimumSizeHint(self):
        # Cede el titulo del panel, no el agente: es lo que se pulsa. Su ancho
        # ya va topado (_ANCHO_MAX), asi que nunca se come la cabecera.
        return self.sizeHint()

    def resizeEvent(self, e):
        self._rotular()
        super().resizeEvent(e)

    def _abrir(self):
        self.menu.clear()
        for aid, nombre in self._agentes:
            accion = self.menu.addAction(nombre)
            if aid in self._caras:
                accion.setIcon(QtGui.QIcon(avatares.pixmap(*self._caras[aid], 18)))
            accion.setCheckable(True)
            accion.setChecked(aid == self.activo)
            accion.triggered.connect(lambda _c=False, a=aid: self.chosen.emit(a))
        if self.antes_de_mostrar is not None:
            self.antes_de_mostrar(self.menu)
        self.menu.popup(self.mapToGlobal(QtCore.QPoint(0, self.height() + 4)))


class SuggestionChip(QtWidgets.QPushButton):
    """'↻ Update with: «…» — Caps+F': relanzar la solucion en pantalla con lo
    que acaban de decir. Lo decide el tester; nunca pasa solo."""

    # Lo que no es la cita: icono, rotulo, atajo y el relleno del estilo.
    _MARCO = "↻ Update with: «» — Caps+F"
    _RELLENO = 26

    def __init__(self):
        super().__init__("")
        f = self.font(); f.setPixelSize(11); self.setFont(f)
        # El texto se recorta al ancho que haya ("…"), nunca al reves: con la
        # cita entera de ancho minimo, el panel crecia hasta salirse de la
        # pantalla. La cita completa queda en el tooltip.
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                           QtWidgets.QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setStyleSheet(
            "QPushButton {"
            f"  color: {T.ACCENT_LABEL};"
            "   background: rgba(124,149,255,0.12);"
            "   border: 1px solid rgba(124,149,255,0.45);"
            "   border-radius: 9px;"
            "   padding: 3px 10px;"
            "   text-align: left;"
            "}"
            "QPushButton:hover { background: rgba(124,149,255,0.20); }")
        self.texto = ""
        self.setVisible(False)

    def mostrar(self, texto):
        self.texto = texto or ""
        if not self.texto:
            self.setVisible(False)
            return
        self.setToolTip(self.texto)
        self._rotular()
        self.setVisible(True)

    def _rotular(self):
        fm = self.fontMetrics()
        libre = max(0, self.width() - fm.horizontalAdvance(self._MARCO) - self._RELLENO)
        cita = fm.elidedText(self.texto, QtCore.Qt.ElideRight, libre)
        self.setText(f"↻ Update with: «{cita}» — Caps+F")

    def sizeHint(self):
        # Pide el ancho de la cita entera; el layout le da lo que haya.
        fm = self.fontMetrics()
        return QtCore.QSize(fm.horizontalAdvance(self._MARCO + self.texto) + self._RELLENO,
                            super().sizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.texto:
            self._rotular()


class SkipPill(QtWidgets.QLabel):
    """Aviso de que NO va a haber respuesta.

    Sin esto, un silencio es ambiguo: no sabes si la IA esta tardando o si ha
    decidido que ahi no habia ninguna pregunta. Va debajo de la transcripcion,
    discreta, y desaparece en cuanto vuelven a hablar.
    """

    def __init__(self):
        super().__init__("")
        f = self.font(); f.setPixelSize(11); self.setFont(f)
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum,
                           QtWidgets.QSizePolicy.Fixed)
        self.setStyleSheet(
            "QLabel {"
            f"  color: {T.TEXT_FAINT};"
            "   background: rgba(220,228,255,0.05);"
            "   border: 1px solid rgba(220,228,255,0.10);"
            "   border-radius: 9px;"
            "   padding: 3px 9px;"
            "}")
        self.setVisible(False)

    def show_text(self, texto):
        self.setText(texto)
        self.setVisible(True)

    def hide_pill(self):
        self.setVisible(False)


class AudioBars(QtWidgets.QWidget):
    """Las tres barras del encabezado. Reflejan el nivel real del audio."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(17, 14)
        self._level = 0
        self._listening = False
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)

    def set_level(self, v):
        self._level = max(0, min(100, int(v)))

    def set_listening(self, on):
        self._listening = bool(on)
        self.update()

    def _tick(self):
        if self._listening:
            self._phase += 0.35
            self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        color = QtGui.QColor(T.ACCENT)
        if not self._listening:
            color.setAlphaF(0.5)
        p.setBrush(color)
        p.setPen(QtCore.Qt.NoPen)
        h_max = self.height()
        for i in range(3):
            if self._listening:
                # amplitud base animada + empuje del nivel real de audio
                osc = 0.5 + 0.5 * math.sin(self._phase - i * 0.9)
                amp = 0.35 + 0.65 * osc * (0.35 + 0.65 * self._level / 100.0)
            else:
                amp = 0.36
            h = max(3, int(h_max * amp))
            p.drawRoundedRect(QtCore.QRectF(i * 5, h_max - h, 3, h), 1.5, 1.5)
        p.end()


# --------------------------------------------------------------- barra superior

# _Draggable goes first in the bases: its mouse handlers must override QWidget's.
class TopBar(_Draggable, QtWidgets.QWidget):
    startStopClicked = QtCore.Signal()
    screenshotClicked = QtCore.Signal()
    generateClicked = QtCore.Signal()
    answerNowClicked = QtCore.Signal()
    toggleClicked = QtCore.Signal()

    def __init__(self):
        super().__init__()
        _frameless(self)
        self._init_drag()
        self._in_meeting = False
        self._build()

    def resizeEvent(self, e):
        _round_mask(self, T.R_TOPBAR)
        super().resizeEvent(e)

    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Con selector: sin el, cada hijo hereda el fondo y, con vidrio, los
        # velos translucidos se apilan en recuadros mas oscuros.
        self.setStyleSheet("TopBar { background: transparent; }")
        self.card = QtWidgets.QFrame()
        self.card.setObjectName("card")
        self.card.setStyleSheet(f"""
            QFrame#card {{
                background: {T.PANEL_TOP};
                border: 1px solid {T.PANEL_BORDER};
                border-radius: {T.R_TOPBAR}px;
            }}
        """)
        outer.addWidget(self.card)

        lay = QtWidgets.QHBoxLayout(self.card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        # Asa de arrastre: solo los punticos (la marca no aportaba nada en plena
        # reunion y quitaba sitio en pantallas pequenas). Esta en
        # interactive_widgets para que no deje pasar el clic.
        marca = QtWidgets.QWidget()
        self.drag_zone = marca
        ml = QtWidgets.QHBoxLayout(marca)
        ml.setContentsMargins(8, 6, 6, 6)
        ml.addWidget(GripDots(cols=2, rows=3))
        lay.addWidget(marca)

        sep = QtWidgets.QFrame()
        sep.setFixedSize(1, 24)
        sep.setStyleSheet(f"background: {T.DIVIDER}; border: none;")
        lay.addWidget(sep)

        # --- iniciar / detener reunion (solo icono play/stop, sin bolita) ---
        self.btn_meeting = ClickFrame()
        bl = QtWidgets.QHBoxLayout(self.btn_meeting)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(8)
        self.ico_meeting = icons.label("play", "#b4c3ff", 15)
        bl.addWidget(self.ico_meeting)
        self.lbl_meeting = QtWidgets.QLabel("Start meeting")
        f = self.lbl_meeting.font(); f.setPixelSize(13); f.setWeight(QtGui.QFont.DemiBold)
        self.lbl_meeting.setFont(f)
        bl.addWidget(self.lbl_meeting)
        self.lbl_timer = QtWidgets.QLabel("")
        self.lbl_timer.setStyleSheet(
            f"font-family: {T.MONO_STACK}; font-size: 12px; color: {T.TEXT}; background: transparent;")
        bl.addWidget(self.lbl_timer)
        bl.addWidget(_keys("Caps", "Esc"))
        self.btn_meeting.clicked.connect(self.startStopClicked)
        lay.addWidget(self.btn_meeting)
        self._paint_meeting()

        # Orden de izquierda a derecha: meeting, generate, answer now,
        # screenshot, show/hide. Se agrupan los dos que hacen responder a la IA
        # (generate y answer now), que es como se usan.

        # --- generar (se ilumina cuando hay capturas listas) ---
        self.btn_gen = ClickFrame()
        gl = QtWidgets.QHBoxLayout(self.btn_gen)
        gl.setContentsMargins(12, 8, 12, 8)
        gl.setSpacing(7)
        self.ico_gen = icons.label("sparkles", T.TEXT, 16)
        gl.addWidget(self.ico_gen)
        self.lbl_gen = QtWidgets.QLabel("Generate")
        # Mismo peso que el resto de la barra: antes iba en negrita para
        # sostener el fondo amarillo, que ya no esta.
        gf = self.lbl_gen.font(); gf.setPixelSize(13); gf.setWeight(QtGui.QFont.Medium)
        self.lbl_gen.setFont(gf)
        gl.addWidget(self.lbl_gen)
        self.keys_gen = _keys("Caps", "D")
        gl.addWidget(self.keys_gen)
        self.btn_gen.clicked.connect(self.generateClicked)
        lay.addWidget(self.btn_gen)
        self.set_generate_enabled(False)

        # --- responder ahora (red de seguridad si no se detecto la pregunta) ---
        self.btn_answer = self._pill("Answer now", ("Caps", "A"), icono="chat")
        self.btn_answer.setToolTip(
            "Responde a lo último que dijeron, aunque no pareciera una pregunta")
        self.btn_answer.clicked.connect(self.answerNowClicked)
        lay.addWidget(self.btn_answer)

        # --- captura de pantalla ---
        self.btn_shot = self._pill("Screenshot", ("Caps", "S"), icono="camera")
        self.btn_shot.clicked.connect(self.screenshotClicked)
        lay.addWidget(self.btn_shot)

        # --- mostrar / ocultar ---
        self.btn_toggle = self._pill("Show / Hide", ("Caps", "Q"), icono="eye")
        self.btn_toggle.clicked.connect(self.toggleClicked)
        lay.addWidget(self.btn_toggle)
        # Los ajustes viven en la Home, que vuelve al terminar la reunion.

    def interactive_widgets(self):
        """Zonas que SI responden al mouse (el resto deja pasar el clic)."""
        return [self.drag_zone]

    def set_generate_enabled(self, on):
        """Encendido = hay capturas listas. Se maneja por Bloq Mayus+D; aqui solo se ve."""
        on = bool(on)
        if on:
            # Encendido = el mismo tono que Screenshot o Answer now. Antes se
            # ponia de un amarillo macizo que gritaba en una barra que es toda
            # oscura: llamaba mas la atencion el boton que la propia respuesta.
            # Que este disponible ya se ve en que el texto deja de estar apagado.
            self.btn_gen.setStyleSheet(f"""
                QFrame {{ border: 1px solid {T.BTN_BORDER}; border-radius: {T.R_BTN}px;
                          background: {T.BTN_BG}; }}
                QFrame:hover {{ background: {T.BTN_BG_HOVER}; }}
                QLabel {{ border: none; background: transparent; }}
            """)
            self.lbl_gen.setStyleSheet(f"color: {T.TEXT}; background: transparent;")
            self.ico_gen.setPixmap(icons.pixmap("sparkles", T.TEXT, 16))
        else:
            self.btn_gen.setStyleSheet(f"""
                QFrame {{ border: 1px solid {T.BTN_BORDER}; border-radius: {T.R_BTN}px;
                          background: {T.BTN_BG}; }}
                QLabel {{ border: none; background: transparent; }}
            """)
            self.lbl_gen.setStyleSheet(f"color: {T.TEXT_FAINT}; background: transparent;")
            self.ico_gen.setPixmap(icons.pixmap("sparkles", T.TEXT_FAINT, 16))
        self.keys_gen.setEnabled(on)

    def _pill(self, texto, teclas, icono=None, ancho=None):
        b = ClickFrame()
        b.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {T.BTN_BORDER};
                background: {T.BTN_BG};
                border-radius: {T.R_BTN}px;
            }}
            QFrame:hover {{ background: {T.BTN_BG_HOVER}; }}
            QLabel {{ border: none; background: transparent; }}
        """)
        lay = QtWidgets.QHBoxLayout(b)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(7)
        if icono:
            lay.addWidget(icons.label(icono, T.TEXT, 16))
        if texto:
            lab = QtWidgets.QLabel(texto)
            f = lab.font(); f.setPixelSize(13); f.setWeight(QtGui.QFont.Medium)
            lab.setFont(f)
            lab.setStyleSheet(f"color: {T.TEXT}; background: transparent;")
            lay.addWidget(lab)
        if teclas:
            lay.addWidget(_keys(*teclas))
        if ancho:
            b.setFixedWidth(ancho)
            lay.setContentsMargins(0, 8, 0, 8)
            lay.setAlignment(QtCore.Qt.AlignCenter)
        return b

    def _paint_meeting(self):
        if self._in_meeting:
            borde, fondo, texto = T.REC_BORDER, T.REC_BG, T.REC_TEXT
        else:
            borde, fondo, texto = "rgba(124,149,255,0.5)", "rgba(124,149,255,0.16)", "#b4c3ff"
        self.btn_meeting.setStyleSheet(f"""
            QFrame {{ border: 1px solid {borde}; background: {fondo};
                      border-radius: {T.R_BTN}px; }}
            QLabel {{ border: none; background: transparent; }}
        """)
        self.lbl_meeting.setStyleSheet(f"color: {texto}; background: transparent;")
        # El icono cambia de reproducir (parado) a stop (en reunion).
        self.ico_meeting.setPixmap(icons.pixmap(
            "stop" if self._in_meeting else "play", texto, 15))

    def set_meeting(self, activo):
        self._in_meeting = bool(activo)
        self.lbl_meeting.setText("Stop meeting" if activo else "Start meeting")
        if not activo:
            self.lbl_timer.setText("")
        self._paint_meeting()

    def set_timer(self, texto):
        self.lbl_timer.setText(texto)


# --------------------------------------------------------------- panel principal

class TranscriptPanel(_Draggable, QtWidgets.QWidget):
    """Un panel del overlay. Dos modos:

    - "voz": la conversacion hablada (lo que dice el entrevistador y la
      sugerencia). Lo que dices tu no se pinta: va solo como contexto.
    - "pantalla": capturas y soluciones de codigo. Solo existe cuando se usan
      pantallazos; trae la sugerencia de relanzar la solucion y un cierre.
    """
    relaunchClicked = QtCore.Signal()
    closeClicked = QtCore.Signal()
    agentChosen = QtCore.Signal(str)

    def __init__(self, modo="voz"):
        super().__init__()
        self.modo = modo
        _frameless(self)
        self._init_drag()
        self._raw = ""
        self._state = "idle"
        self._caret_on = True
        self._anim_phase = 0
        self._burbujas = []         # todas las del hilo, para los botones copiar
        self._burbuja_viva = None   # la intervencion que se esta transcribiendo
        self._burbuja_resp = None   # la sugerencia que se esta generando
        self._ultima_resp = None    # la ultima sugerencia, por si se reescribe
        self._repintado_pendiente = False
        # Owned single-shot timer (not QTimer.singleShot) so a pending repaint
        # can be cancelled when the answer is closed or the thread is cleared.
        self._timer_repintado = QtCore.QTimer(self)
        self._timer_repintado.setSingleShot(True)
        self._timer_repintado.setInterval(INTERVALO_REPINTADO)
        self._timer_repintado.timeout.connect(self._repintar)
        self._auto = {}             # se llena en _body, al crear el hilo
        # Los avisos de paso (aviso()) se van solos.
        self._aviso_fugaz = QtCore.QTimer(self)
        self._aviso_fugaz.setSingleShot(True)
        self._aviso_fugaz.setInterval(AVISO_MS)
        self._aviso_fugaz.timeout.connect(self.hide_skip)
        self._build()
        # Animacion: pulso del borde (listening) + caret parpadeante.
        self._anim = QtCore.QTimer(self)
        self._anim.timeout.connect(self._animate)
        self._anim.start(90)
        self._apply_border()

    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # El fondo lo pinta PanelCard; la ventana, transparente y sin herencia
        # (con vidrio, un fondo heredado se apilaria en cada hijo).
        self.setStyleSheet("TranscriptPanel { background: transparent; }")
        # Se pinta sola (ver PanelCard): el borde late y con hoja de estilo eso
        # repasaba el estilo de todo el hilo en cada fotograma.
        self.card = PanelCard()
        self.card.setObjectName("panel")
        outer.addWidget(self.card)

        root = QtWidgets.QVBoxLayout(self.card)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._header())
        root.addWidget(self._body(), 1)

        # Agarre de redimension en la esquina inferior derecha (encima de todo).
        self.resize_grip = ResizeGrip()
        self.resize_grip.setParent(self.card)
        self.resize_grip.raise_()

    def resizeEvent(self, e):
        _round_mask(self, T.R_PANEL)
        # reposicionar el agarre a la esquina inferior derecha
        if hasattr(self, "resize_grip"):
            g = self.resize_grip
            g.move(self.card.width() - g.width() - 7,
                   self.card.height() - g.height() - 7)
            g.raise_()
        if e.oldSize().width() != e.size().width():
            self._congelar_ancho()
        super().resizeEvent(e)

    # -- redimension fluida --------------------------------------------------
    #
    # Cambiar el ancho es lo caro: como el texto se ajusta al ancho, Qt tiene que
    # recalcular de cero el alto de cada mensaje, y arrastrar la esquina genera
    # decenas de anchos por segundo. Con la reunion avanzada eso pasaba de 80 ms
    # por paso y el arrastre iba a tirones.
    #
    # Asi que durante el arrastre el hilo se queda con el ancho que ya tenia: se
    # recorta o sobra un poco de fondo, y nadie recalcula nada. Al parar el raton
    # 140 ms se suelta y se reajusta una sola vez, que es cuando de verdad se
    # mira. El unico coste es ese margen breve, y a cambio arrastrar es fluido.
    def _congelar_ancho(self):
        cont = getattr(self, "_cont", None)
        if cont is None:
            return
        if not self._descongelar.isActive():        # aun no estaba congelado
            cont.setFixedWidth(cont.width())
            self.scroll.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarAlwaysOff)      # no asomar por el sobrante
        self._descongelar.start(140)

    def _descongelar_ancho(self):
        cont = getattr(self, "_cont", None)
        if cont is None:
            return
        cont.setMinimumWidth(0)
        cont.setMaximumWidth(16777215)
        cont.resize(self.scroll.viewport().width(), cont.height())
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

    def interactive_widgets(self):
        """Zonas que responden al mouse: cabecera (mover), scroll, agarre y copiar.

        Se consulta cada 30 ms desde app.py, asi que los botones de copiar que se
        crean en cada render entran solos.

        Cuando hay conversacion de sobra, el hilo entero entra en la lista. Es la
        unica forma de que funcione el gesto de dos dedos del panel tactil: ese
        no viaja como rueda de raton, Windows se lo entrega directamente a la
        ventana que hay bajo el cursor, y una ventana de cristal no cuenta -- se
        lo pasa a la de abajo. Mientras no haya nada que desplazar se deja pasar
        el clic como siempre, que es lo normal en una reunion.
        """
        zonas = ([self._drag_header, self.scroll.verticalScrollBar(),
                  self.resize_grip] + self._copy_buttons)
        if self.nuevo_chip.isVisible():
            zonas.append(self.nuevo_chip)
        for extra in (self.relanzar_chip, self.btn_close, self.agent_chip):
            if extra.isVisible():
                zonas.append(extra)
        # La horizontal solo esta cuando el codigo no cabe de ancho; si no se
        # puede arrastrar, el trozo que sobresale seguiria sin poder leerse.
        if self.scroll.horizontalScrollBar().isVisible():
            zonas.append(self.scroll.horizontalScrollBar())
        if self.scroll.verticalScrollBar().maximum() > 0:
            zonas.append(self.scroll.viewport())
        return zonas

    # ---------------- encabezado
    def _header(self):
        """Solo lo que sirve en plena reunion:

        - hablado: actividad del audio, el agente que responde (pulsable para
          cambiarlo) y el estado real (Listening, Drafting...).
        - pantalla: cuantas capturas lleva, el estado y el cierre.
        La latencia solo aparece cuando va lenta: si va bien, no hay nada que
        mirar. Los avisos que no son un estado van a la pastilla de abajo.
        """
        w = DragBar()          # arrastrar desde aqui mueve todo el panel
        self._drag_header = w
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(10)

        self.bars = AudioBars()
        lay.addWidget(self.bars)

        # Hablado: el titulo es el agente. Pantalla: "Screen · N shots".
        self.agent_chip = AgentChip()
        self.agent_chip.chosen.connect(self.agentChosen.emit)
        lay.addWidget(self.agent_chip)
        base = _tracked("Screen", 13, QtGui.QFont.DemiBold, T.TEXT_BRIGHT, 0)
        self.titulo = _TituloElastico("Screen", base.font(), T.TEXT_BRIGHT)
        base.deleteLater()
        lay.addWidget(self.titulo)

        lay.addStretch()
        self.badge = StatusBadge()
        lay.addWidget(self.badge)
        # Latencias: solo cuando van lentas (ver set_latency / set_e2e).
        self.lat = QtWidgets.QLabel("")
        lf = self.lat.font(); lf.setPixelSize(11); self.lat.setFont(lf)
        self.lat.setToolTip("Transcripción lenta: de la última palabra al texto")
        self.lat.setVisible(False)
        lay.addWidget(self.lat)
        self.e2e = QtWidgets.QLabel("")
        ef = self.e2e.font(); ef.setPixelSize(11); self.e2e.setFont(ef)
        self.e2e.setToolTip("Respuesta lenta: de la pregunta a la primera palabra sugerida")
        self.e2e.setVisible(False)
        lay.addWidget(self.e2e)
        lay.addWidget(GripDots())

        # El panel de la pantalla no escucha audio: fuera barras y agente, y en
        # su lugar un cierre (vuelve a quedar solo el hablado).
        self.btn_close = QtWidgets.QPushButton("×")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setStyleSheet(
            f"QPushButton {{ color: {T.TEXT_FAINT}; background: transparent; "
            f"border: none; font-size: 16px; }}"
            f"QPushButton:hover {{ color: {T.TEXT_BRIGHT}; }}")
        self.btn_close.setToolTip("Close the screen panel")
        self.btn_close.clicked.connect(self.closeClicked.emit)
        lay.addWidget(self.btn_close)
        if self.modo == "pantalla":
            self.bars.setVisible(False)
            self.agent_chip.setVisible(False)
            self.agent_chip.setEnabled(False)
        else:
            self.titulo.setVisible(False)
            self.btn_close.setVisible(False)

        # Con selector: sin el, la linea de abajo la hereda cada hijo y sale
        # subrayado el titulo, el estado...
        w.setObjectName("cabecera")
        w.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        w.setStyleSheet(f"#cabecera {{ border-bottom: 1px solid {T.DIVIDER_SOFT}; }}")
        return w

    # ---------------- cuerpo: el hilo de la conversacion
    def _body(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        w.setMinimumHeight(240)

        # Un unico hilo cronologico, como un chat: lo viejo se queda arriba y lo
        # nuevo entra por abajo. Antes cada pregunta borraba la anterior, asi que
        # en cuanto pasabas de turno ya no podias releer nada.
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setStyleSheet(_BARRA_QSS)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        # Barra horizontal solo cuando hace falta de verdad: una linea de codigo
        # con su comentario al final no cabe en un panel estrecho, y sin barra
        # ese trozo no habria forma de leerlo. Se apaga durante el arrastre (ver
        # _congelar_ancho), que ahi el ancho sobrante es un efecto pasajero.
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        cont = QtWidgets.QWidget()
        cont.setStyleSheet("background: transparent;")
        self._cont = cont
        self._descongelar = QtCore.QTimer(self)
        self._descongelar.setSingleShot(True)
        self._descongelar.timeout.connect(self._descongelar_ancho)
        self.feed = QtWidgets.QVBoxLayout(cont)
        # Margen abajo y a la derecha: si no, la ultima linea queda debajo del
        # agarre de redimension y la barra se le monta encima.
        self.feed.setContentsMargins(18, 14, 10, 26)
        self.feed.setSpacing(10)
        self.feed.addStretch()          # el hueco sobrante, siempre al final
        self.scroll.setWidget(cont)
        # El seguimiento del final se crea aqui: set_hint ya lo usa.
        self.nuevo_chip = NewBelowChip()
        self._auto["feed"] = _AutoScroll(self.scroll,
                                         on_nuevo_abajo=self.nuevo_chip.setVisible)
        self.nuevo_chip.clicked.connect(self._auto["feed"].ir_al_final)
        lay.addWidget(self.scroll, 1)

        # Avisos pegados al hilo, no dentro de el, para que no se pierdan hacia
        # arriba cuando siga entrando conversacion: "no voy a responder" a la
        # izquierda y "hay algo nuevo debajo" a la derecha.
        self.skip_pill = SkipPill()
        pie = QtWidgets.QWidget()
        pl = QtWidgets.QHBoxLayout(pie)
        # A la derecha, hueco para el agarre de redimension de la esquina.
        pl.setContentsMargins(18, 0, 28, 10)
        pl.addWidget(self.skip_pill)
        # Pantalla: lo que dijeron parece ir para la solucion; el tester decide
        # si relanzarla con ello (nunca se relanza sola).
        self.relanzar_chip = SuggestionChip()
        self.relanzar_chip.clicked.connect(self.relaunchClicked.emit)
        pl.addWidget(self.relanzar_chip, 1)    # se queda con el ancho libre
        pl.addStretch()
        pl.addWidget(self.nuevo_chip)
        lay.addWidget(pie)

        if self.modo == "pantalla":
            self.set_hint("Screenshots (Caps+S) and their solutions show up here. "
                          "Caps+D to solve.")
        else:
            self.set_hint("Waiting for the first question — the answer will "
                          "draft here.")
        return w

    def set_agents(self, agentes, activo):
        """Agentes para el selector de la cabecera (solo el panel hablado)."""
        if self.modo == "voz":
            self.agent_chip.set_agents(agentes, activo)

    def show_suggestion(self, texto):
        """Ofrece relanzar la solucion con lo que dijeron; "" la retira."""
        self.relanzar_chip.mostrar(texto)

    # -- piezas del hilo ----------------------------------------------------
    def _ancho_burbuja(self):
        # Sin tope: todas las filas ocupan lo mismo. Con burbujas de ancho
        # variable el ojo tiene que reencontrar el margen en cada mensaje, y
        # ademas el codigo se quedaba estrecho justo cuando mas sitio necesita.
        return 16777215

    def _añadir(self, widget, estirar=True):
        """Mete algo en el hilo. Las filas ocupan el ancho completo.

        Quien habla se distingue por el color y por la etiqueta, no por el
        ancho ni por el lado: asi se lee en linea recta. Solo las miniaturas
        conservan su tamaño (estirarlas seria absurdo).
        """
        fila = QtWidgets.QWidget()
        fila.setStyleSheet("background: transparent;")
        fl = QtWidgets.QHBoxLayout(fila)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(widget)
        if not estirar:
            fl.addStretch()
        self.feed.insertWidget(self.feed.count() - 1, fila)   # antes del hueco
        self._podar()
        self._auto["feed"].contenido_nuevo()
        return fila

    def _podar(self):
        """Deja solo los ultimos mensajes vivos (ver MAX_FILAS_HILO).

        Se salta las dos burbujas que aun se estan escribiendo -- la del
        participante mientras se transcribe y la de la sugerencia mientras
        llega. Si no, basta con tomar unas cuantas capturas mientras alguien
        habla para que la burbuja en curso caiga por antiguedad, y el siguiente
        trozo de texto iria a parar a un objeto ya destruido.
        """
        vivas = [b for b in (self._burbuja_viva, self._burbuja_resp)
                 if b is not None]
        i = 0
        while self.feed.count() - 1 > MAX_FILAS_HILO and i < self.feed.count() - 1:
            w = self.feed.itemAt(i).widget()
            if w is None:
                i += 1
                continue
            dentro = w.findChildren(Burbuja)
            if any(b in dentro for b in vivas):
                i += 1                      # esta viva: se quita la siguiente
                continue
            self.feed.takeAt(i)
            # Las burbujas que se van dejan de contar para los botones de copiar
            for b in dentro:
                if b in self._burbujas:
                    self._burbujas.remove(b)
            w.hide()
            w.deleteLater()

    def _nueva_burbuja(self, quien):
        b = Burbuja(quien, self._ancho_burbuja())
        self._burbujas.append(b)
        self._añadir(b)
        return b

    # ---------------- estado visual (borde + animacion)
    def _apply_border(self):
        if self._state == "generating":
            color, width = QtGui.QColor(124, 149, 255), 2
        elif self._state == "listening":
            a = 0.30 + 0.35 * (0.5 + 0.5 * math.sin(self._anim_phase * 0.22))
            color, width = QtGui.QColor(124, 149, 255, int(a * 255)), 1
        else:  # idle
            color, width = QtGui.QColor(210, 220, 223, 36), 1
        self.card.set_borde(color, width)

    def _animate(self):
        self._anim_phase += 1
        if self._anim_phase % 6 == 0:      # ~540 ms
            self._caret_on = not self._caret_on
            if self._state == "listening" and self._burbuja_viva is not None:
                self._render_question()
        if self._state == "listening":
            self._apply_border()

    def set_state(self, state):
        """idle | listening | generating -> cambia el borde y el pulso."""
        self._state = state
        self.bars.set_listening(state in ("listening", "generating"))
        if self.modo == "voz":
            self.agent_chip.set_pensando(state == "generating")
        self._apply_border()
        self._render_question()

    # ---------------- API publica
    def set_level(self, v):
        self.bars.set_level(v)

    def set_mic_level(self, v):
        pass  # el medidor de micro se retiro de la cabecera

    def set_listening(self, on):
        self.set_state("listening" if on else "idle")

    def set_latency(self, ms):
        """Latencia de la transcripcion: solo se ensena si va lenta."""
        if ms < LATENCIA_LENTA_MS:
            self.lat.setVisible(False)
            return
        col = "#e9a23b" if ms < 2 * LATENCIA_LENTA_MS else "#e0554b"   # ambar / rojo
        txt = f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"
        self.lat.setText(txt)
        self.lat.setStyleSheet(
            f"color: {col}; font-family: {T.MONO_STACK}; background: "
            f"rgba(220,228,255,0.05); border-radius: 8px; padding: 2px 7px;")
        self.lat.setVisible(True)

    def set_e2e(self, ms):
        """Total de la carrera (pregunta -> primera palabra): solo si va lenta."""
        if ms < RESPUESTA_LENTA_MS:
            self.e2e.setVisible(False)
            return
        col = "#e9a23b" if ms < 2 * RESPUESTA_LENTA_MS else "#e0554b"   # ambar / rojo
        self.e2e.setText(f"⚡ {ms / 1000:.1f} s")
        self.e2e.setStyleSheet(
            f"color: {col}; font-family: {T.MONO_STACK}; background: "
            f"rgba(220,228,255,0.05); border-radius: 8px; padding: 2px 7px;")
        self.e2e.setVisible(True)

    def clear_latency(self):
        self.lat.setVisible(False)
        self.lat.setText("")
        self.e2e.setVisible(False)
        self.e2e.setText("")

    def set_status(self, texto, kind=None):
        """Actualiza el badge. Si no se da 'kind', se deduce del texto."""
        if kind is None:
            t = texto.lower()
            if "listening" in t:
                kind = "listening"
            elif "loading" in t or "starting" in t or "cargando" in t:
                kind = "loading"
            elif "idle" in t:
                kind = "idle"
            elif "transcrib" in t:
                kind = "transcribing"
            elif "draft" in t or "analy" in t:
                kind = "drafting"
            elif "error" in t or "required" in t:
                kind = "error"
            else:
                kind = "info"
        self.badge.set(texto, kind)

    def _render_question(self):
        """Repinta el caret de la intervencion en curso (parpadeo)."""
        if self._burbuja_viva is not None:
            caret = self._caret_on and self._state == "listening"
            self._burbuja_viva.set_texto(self._burbuja_viva._raw, caret=caret)

    # ---------------- el hilo: participante
    def set_question(self, texto, caret=False):
        """Lo que se esta transcribiendo ahora mismo: actualiza la burbuja viva."""
        if not texto:
            return
        self._auto["feed"].anotar()
        if self._burbuja_viva is None:
            self._burbuja_viva = self._nueva_burbuja("ellos")
        self._burbuja_viva.set_texto(texto, caret=self._state == "listening")
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    def cerrar_intervencion(self, texto):
        """La intervencion termino: deja de ser 'en curso' y se queda en el hilo."""
        self._auto["feed"].anotar()
        if self._burbuja_viva is None:
            self._burbuja_viva = self._nueva_burbuja("ellos")
        self._burbuja_viva.set_texto(texto)
        self._burbuja_viva = None
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    # ---------------- el hilo: sugerencias
    def clear_answer(self):
        """Empieza una sugerencia nueva: se abre otra burbuja, no se borra nada.

        Y se ancla: desde aqui la sugerencia (con su pregunta encima, si cabe)
        se queda arriba mientras la lees, crezca lo que crezca y llegue lo que
        llegue por debajo.
        """
        self._raw = ""
        pregunta = next((b for b in reversed(self._burbujas)
                         if b.quien == "ellos" and isValid(b)), None)
        self._auto["feed"].anotar()
        self._burbuja_resp = self._nueva_burbuja("tu")
        self._ultima_resp = self._burbuja_resp
        self._auto["feed"].anclar(self._burbuja_resp, pregunta)
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    def revisar_respuesta(self):
        """Reescribe en su sitio la ultima sugerencia (no abre otra).

        Lo anadido cambia la respuesta, pero el tester ya la estaba leyendo ahi:
        mismo sitio, mismo borde de arriba, marcada como actualizada. Si ya no
        existe (se podo), se abre una nueva como siempre.
        """
        b = self._ultima_resp
        if b is None or not isValid(b):
            self.clear_answer()
            return
        self._raw = ""
        self._burbuja_resp = b
        b.marcar_actualizada()
        self._auto["feed"].anotar()
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    def append_answer(self, delta):
        """Añade un trozo a la sugerencia en curso y programa el repintado.

        Repintar en cada trozo era insostenible, asi que se agrupan. Y solo se
        repinta la burbuja de la respuesta: lo anterior del hilo ya esta pintado
        y no se toca.
        """
        self._raw += delta
        if not self._repintado_pendiente:
            self._repintado_pendiente = True
            self._timer_repintado.start()

    def _repintar(self):
        self._timer_repintado.stop()
        self._repintado_pendiente = False
        if self._burbuja_resp is None:
            self._burbuja_resp = self._nueva_burbuja("tu")
        with metricas.cronometro(PINTADO):
            self._auto["feed"].anotar()
            self._burbuja_resp.set_markdown(self._raw, self._parrafo, self._vinetas)
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    def cerrar_respuesta(self):
        """Se acabo de generar: el ultimo trozo se pinta y la burbuja se cierra."""
        if self._repintado_pendiente or self._burbuja_resp is None:
            self._repintar()
        self._burbuja_resp = None

    # ---------------- el hilo: capturas y notas
    def add_shot(self, pixmap):
        """La captura enviada entra en el hilo, como un mensaje tuyo."""
        self._auto["feed"].anotar()
        self._añadir(ShotThumb(pixmap), estirar=False)
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    def set_hint(self, texto):
        """Nota discreta en el hilo (arranque, avisos)."""
        lab = QtWidgets.QLabel(texto)
        lab.setWordWrap(True)
        lab.setStyleSheet(
            f"color: {T.TEXT_FAINT}; font-size: 13px; background: transparent;")
        self._auto["feed"].anotar()
        self._añadir(lab)
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    def limpiar_hilo(self):
        """Vacia la conversacion (al empezar una reunion nueva)."""
        self._timer_repintado.stop()
        self._repintado_pendiente = False
        self._burbuja_viva = None
        self._burbuja_resp = None
        self._ultima_resp = None
        self._burbujas = []
        self._raw = ""
        self._auto["feed"].ir_al_final()
        while self.feed.count() > 1:
            it = self.feed.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

    def show_skip(self, texto="No question — Caps+A to answer"):
        """Deja claro que no se esta esperando ninguna respuesta."""
        self._aviso_fugaz.stop()
        self.skip_pill.show_text(texto)

    def aviso(self, texto):
        """Mensaje de paso (no es un estado): en la pastilla unos segundos."""
        self.skip_pill.show_text(texto)
        self._aviso_fugaz.start()

    def set_shots(self, n):
        """Panel de pantalla: el titulo cuenta las capturas de la reunion."""
        texto = "Screen" if not n else f"Screen · {n} shot{'s' if n != 1 else ''}"
        self.titulo._completo = texto
        self.titulo.setText(texto)
        self.titulo.updateGeometry()

    def hide_skip(self):
        self.skip_pill.hide_pill()

    # ---------------- scroll
    def wheel_zones(self):
        """Zonas que capturan la rueda: [(rectangulo, nombre)].

        Las consulta el desviador de rueda (wheelscroll): con click-through la
        ventana no recibe el raton, asi que hay que decirle donde actuar.
        """
        if not self.isVisible():
            return []
        # Con dos paneles, el nombre lleva el modo delante ("pantalla:feed")
        # para que la rueda llegue al panel que esta bajo el cursor.
        return [(auto.zona(), f"{self.modo}:{nombre}")
                for nombre, auto in self._auto.items() if auto.zona()]

    def scroll_zone(self, nombre, muescas):
        """Mueve la zona indicada. muescas positivas = hacia arriba."""
        auto = self._auto.get(nombre.split(":", 1)[-1])
        if auto is not None:
            auto.rueda(muescas)

    # Estilo del `codigo en linea` dentro de un parrafo.
    _CODE_INLINE = (f"font-family: {T.MONO_STACK}; background: rgba(0,0,0,0.35); "
                    f"color: {T.ACCENT_LIGHT};")

    def _parrafo(self, texto):
        lab = QtWidgets.QLabel(
            f'<div style="line-height:150%; color:{T.ANSWER_TEXT}; font-size:14px;">'
            f'{richtext.inline_html(texto, self._CODE_INLINE)}</div>')
        lab.setWordWrap(True)
        lab.setTextFormat(QtCore.Qt.RichText)
        lab.setStyleSheet("background: transparent;")
        return lab

    def _vinetas(self, items):
        filas = "".join(
            f'<tr><td style="color:{T.ACCENT};padding-right:7px;">•</td>'
            f'<td>{richtext.inline_html(it, self._CODE_INLINE)}</td></tr>'
            for it in items)
        lab = QtWidgets.QLabel(
            f'<table style="line-height:150%; color:{T.ANSWER_TEXT}; '
            f'font-size:14px;" cellspacing="0">{filas}</table>')
        lab.setWordWrap(True)
        lab.setTextFormat(QtCore.Qt.RichText)
        lab.setStyleSheet("background: transparent;")
        return lab

    @property
    def _copy_buttons(self):
        """Los botones de copiar de todo el hilo (para el click-through)."""
        vivos = []
        for b in self._burbujas:
            try:
                vivos.extend(b.copy_buttons)
            except RuntimeError:
                pass        # burbuja ya destruida
        return vivos


def parse_sections(raw):
    """Version plana (etiqueta, texto) de la respuesta.

    El panel ya no la usa —pinta bloques con richtext—, pero se mantiene porque
    es una forma comoda de comprobar por fuera que el modelo respeta el formato.
    """
    return richtext.solo_texto(richtext.parse_answer(raw))


# --------------------------------------------------------------- auxiliares

class CollapsedButton(_Draggable, QtWidgets.QWidget):
    """Pildora 'Show overlay' que aparece cuando el overlay esta oculto."""
    clicked = QtCore.Signal()

    def __init__(self):
        super().__init__()
        _frameless(self)
        self._init_drag()
        self.setStyleSheet("CollapsedButton { background: transparent; }")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        b = ClickFrame(drags_window=True)   # click restores, drag moves
        b.setStyleSheet(f"""
            QFrame {{ background: {T.PANEL_TOP}; border: 1px solid {T.PANEL_BORDER};
                      border-radius: {T.R_COLLAPSE}px; }}
            QFrame:hover {{ background: {T.BTN_BG_HOVER}; }}
            QLabel {{ border: none; background: transparent; }}
        """)
        lay = QtWidgets.QHBoxLayout(b)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(8)
        punto = QtWidgets.QLabel()
        punto.setFixedSize(8, 8)
        punto.setStyleSheet(f"background: {T.ACCENT}; border-radius: 4px;")
        lay.addWidget(punto)
        lab = QtWidgets.QLabel("Show overlay")
        lab.setStyleSheet(f"color: {T.TEXT}; font-size: 13px; background: transparent;")
        lay.addWidget(lab)
        lay.addWidget(_keys("Caps", "Q"))
        b.clicked.connect(self.clicked)
        outer.addWidget(b)

    def resizeEvent(self, e):
        _round_mask(self, T.R_COLLAPSE)
        super().resizeEvent(e)


# Aqui vivia FlashOverlay, un destello blanco a pantalla completa al capturar.
# Se elimino: era la unica ventana de la app SIN proteccion de captura, asi que
# todo el overlay era invisible al compartir pantalla menos ese flashazo, que
# ademas podia colarse en la propia imagen enviada al modelo. El acuse de recibo
# de la captura es la miniatura en el panel, que solo ve el usuario.
