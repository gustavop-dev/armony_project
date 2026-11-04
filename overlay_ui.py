"""Interfaz del overlay, segun 'Interview Overlay.dc.html'.

Ventanas flotantes, sin marco, translucidas y siempre encima:
  - TopBar          barra de atajos centrada arriba
  - TranscriptPanel ventana de transcripcion + respuesta sugerida, abajo
                    (y otra igual para la pantalla: capturas y soluciones)
  El hablado lleva abajo el campo de preguntas escritas (Bloq Mayus+E); sus
  respuestas salen en el panel grande.
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
HINT_PREGUNTA = ("Type a question (Caps+E) — Enter sends, the answer opens on "
                 "the big panel")

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

    def __init__(self, lenguaje, codigo, titulo=None):
        super().__init__()
        self._codigo = codigo
        lenguaje = (lenguaje or "").lower()
        # Markdown o texto (un prompt para pegar): coloreado como markdown y
        # partido por el ancho del panel. Si va en la seccion del prompt, se
        # rotula PROMPT y el boton dice lo que copia.
        self.prosa = lenguaje in richtext.LENGUAJES_PROSA
        self.es_prompt = self.prosa and "prompt" in (titulo or "").lower()
        self._rotulo_copiar = "Copy prompt" if self.es_prompt else "Copy"
        color_leng = (T.ACCENT if self.prosa
                      else _COLOR_LENGUAJE.get(lenguaje, T.ACCENT_LABEL))
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

        etq = QtWidgets.QLabel("PROMPT" if self.es_prompt else (lenguaje or "code").upper())
        etq.setObjectName("lenguaje")
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
        self.lbl_copy = QtWidgets.QLabel(self._rotulo_copiar)
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

        cuerpo = QtWidgets.QLabel()
        coloreado = None if self.prosa else richtext.resaltar(codigo, lenguaje, numerar=True)
        # white-space:pre-wrap respeta sangria y espacios pero parte las lineas
        # largas por el ancho del panel: nunca hace falta desplazarse en
        # horizontal (el comentario de cada linea va encima, asi que son cortas).
        self.cuerpo = cuerpo
        self._lenguaje = lenguaje
        cuerpo.setTextFormat(QtCore.Qt.RichText)
        self._pintar(codigo, coloreado)
        cuerpo.setWordWrap(True)
        cuerpo.setStyleSheet("background: transparent; padding: 9px 11px;")
        # Seleccionable solo si el panel lo pide (Burbuja), para preguntar por
        # un trozo; siempre con la flecha: el cursor de texto se veria al
        # compartir pantalla aunque la ventana no. Copiar entero: el boton.
        lay.addWidget(cuerpo)

    def _pintar(self, codigo, coloreado=None):
        if self.prosa:
            # Sin numeros de linea: un prompt se lee como texto.
            html_ = richtext.resaltar_markdown(codigo)
            alto = "150%"
        else:
            if coloreado is None:
                coloreado = richtext.resaltar(codigo, self._lenguaje, numerar=True)
            html_ = coloreado or (f'<span style="color:{T.TEXT_BRIGHT};">'
                                  f'{html.escape(codigo)}</span>')
            alto = "145%"
        self.cuerpo.setText(f'<div style="font-family:{T.MONO_STACK}; font-size:12.5px; '
                            f'line-height:{alto}; white-space:pre-wrap;">{html_}</div>')

    def set_codigo(self, codigo):
        """El codigo que sigue llegando: se repinta en el mismo bloque, sin
        rehacerlo (rehacerlo lo dejaba en blanco un instante en cada trozo)."""
        if codigo != self._codigo:
            self._codigo = codigo
            self._pintar(codigo)

    def _copiar(self):
        QtWidgets.QApplication.clipboard().setText(self._codigo)
        self.lbl_copy.setText("Copied")
        # Context-object overload: Qt drops the call if the label is destroyed
        # first (answer re-render, row pruning, limpiar_hilo).
        QtCore.QTimer.singleShot(1400, self.lbl_copy,
                                 lambda: self.lbl_copy.setText(self._rotulo_copiar))


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

    # Etiqueta de cada tipo. En la caja de preguntas la pregunta es tuya y la
    # respuesta de la IA: "Question" / "Answer" en vez de Participant / You.
    ETIQUETAS = {"ellos": "Participant", "tu": "You", "pregunta": "Question",
                 "respuesta": "Answer"}

    def __init__(self, quien, ancho_maximo=700, seleccionable=None):
        super().__init__()
        self.quien = quien                       # 'ellos' | 'tu' | 'pregunta' | 'respuesta'
        # Lo pone el panel: hace seleccionable cada texto que se pinta, para
        # poder subrayar un trozo y pedir que lo expliquen.
        self.seleccionable = seleccionable
        self._raw = ""
        self._label = None                       # etiqueta reutilizada del texto
        self.copy_buttons = []
        self._items, self._ws = [], []           # lo pintado de la respuesta
        mio = quien in ("tu", "respuesta")
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
            cab.addWidget(_tracked(self.ETIQUETAS[quien], 10, QtGui.QFont.Bold,
                                   T.ACCENT, 0.6, upper=True))
        else:
            cab.addWidget(_tracked(self.ETIQUETAS.get(quien, "Participant"), 10,
                                   QtGui.QFont.DemiBold, T.TEXT_FAINT, 0.6, upper=True))
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
        self._items, self._ws = [], []
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
            self._seleccionable(self._label)
            self.cuerpo.addWidget(self._label)
        self._label.setText(html_)

    def set_markdown(self, raw, pintor):
        """Respuesta del modelo: secciones, codigo, listas, tablas...

        Mientras llega se llama en cada trozo. Antes se rehacia todo cada vez:
        durante un instante el globo quedaba vacio y con respuestas largas (y el
        codigo coloreado de nuevo en cada trozo) se volvia ilegible. Ahora lo
        ya pintado se queda: solo se actualiza el bloque que crece y se anaden
        los nuevos.

        pintor (el panel) da los widgets de cada tipo de bloque: _parrafo,
        _lista, _subtitulo, _tabla, _cita y _regla."""
        self._raw = raw
        if self._label is not None:              # venia de texto llano
            self._vaciar()
        nuevos = []
        for etiqueta, bloques in richtext.parse_answer(raw):
            nuevos.append(("etiqueta", etiqueta, None))
            nuevos.extend(("bloque", b, etiqueta) for b in bloques)
        previos = self._items
        comun = 0
        while (comun < min(len(previos), len(nuevos))
               and previos[comun] == nuevos[comun]):
            comun += 1
        desde = comun
        if (comun < len(previos) and comun < len(nuevos)
                and self._actualizar(comun, nuevos[comun], pintor)):
            desde = comun + 1
        for w in self._ws[desde:]:
            self.cuerpo.removeWidget(w)
            w.hide()
            w.deleteLater()
        self._ws = self._ws[:desde]
        for item in nuevos[desde:]:
            w = self._crear(item, pintor)
            self.cuerpo.addWidget(w)
            w.show()          # ya: esperar al show en cola dejaba un hueco
            self._ws.append(w)
        self._items = nuevos
        self.copy_buttons = [w.btn_copy for w in self._ws if isinstance(w, CodeBlock)]

    def _crear(self, item, pintor):
        clase, valor, etiqueta = item
        if clase == "etiqueta":
            return _tracked(valor, 10, QtGui.QFont.Bold, T.ACCENT_LABEL, 0.9, upper=True)
        tipo = valor[0]
        if tipo == richtext.CODE:
            cb = CodeBlock(valor[1], valor[2], titulo=etiqueta)
            self._seleccionable(cb.cuerpo)
            return cb
        if tipo == richtext.RULE:
            return pintor._regla()
        return self._seleccionable(self._etiqueta_de(valor, pintor))

    @staticmethod
    def _etiqueta_de(bloque, pintor):
        tipo = bloque[0]
        if tipo == richtext.LIST:
            return pintor._lista(bloque[1])
        if tipo == richtext.SUBHEAD:
            return pintor._subtitulo(bloque[1])
        if tipo == richtext.TABLE:
            return pintor._tabla(bloque[1], bloque[2])
        if tipo == richtext.QUOTE:
            return pintor._cita(bloque[1])
        return pintor._parrafo(bloque[1])

    def _actualizar(self, i, item, pintor):
        """Pone el contenido nuevo en el widget que ya esta, si es del mismo
        tipo. False si hay que cambiarlo por otro."""
        previo, w = self._items[i], self._ws[i]
        if previo[0] != "bloque" or item[0] != "bloque":
            return False
        antes, ahora = previo[1], item[1]
        if antes[0] != ahora[0] or not isValid(w):
            return False
        if ahora[0] == richtext.CODE:
            if (antes[1], previo[2]) != (ahora[1], item[2]):
                return False                     # otro lenguaje u otra seccion
            w.set_codigo(ahora[2])
            return True
        if ahora[0] == richtext.RULE:
            return True
        nueva = self._etiqueta_de(ahora, pintor)
        w.setText(nueva.text())
        nueva.deleteLater()
        return True

    def _seleccionable(self, label):
        if self.seleccionable is not None:
            self.seleccionable(label)
        return label


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
        self.mostrar_cara = True     # el panel hablado la pone en el companero
        self.activo = ""
        self.clicked.connect(self._abrir)
        self.setVisible(False)

    _CARA = 18                # lado de la mascota junto al nombre

    def set_agents(self, agentes, activo):
        """agentes: [(id, nombre)] o [(id, nombre, (forma, color) de su
        mascota)]; activo: id del que se usa."""
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
        if cara is None or not getattr(self, "mostrar_cara", True):
            self.setIcon(QtGui.QIcon())
            return
        forma, color = cara
        self.setIcon(QtGui.QIcon(avatares.pixmap(color, self._CARA, self._expresion, forma=forma)))
        self.setIconSize(QtCore.QSize(self._CARA, self._CARA))

    def set_pensando(self, on):
        """Mientras redacta la respuesta, la mascota mira hacia arriba."""
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
                forma, color = self._caras[aid]
                accion.setIcon(QtGui.QIcon(avatares.pixmap(color, 18, forma=forma)))
            accion.setCheckable(True)
            accion.setChecked(aid == self.activo)
            accion.triggered.connect(lambda _c=False, a=aid: self.chosen.emit(a))
        if self.antes_de_mostrar is not None:
            self.antes_de_mostrar(self.menu)
        self.menu.popup(self.mapToGlobal(QtCore.QPoint(0, self.height() + 4)))


class SuggestionChip(QtWidgets.QPushButton):
    """'↻ Update the solution with: «…» — Caps+F': relanzar la solucion en pantalla con lo
    que acaban de decir. Lo decide el tester; nunca pasa solo."""

    # Lo que no es la cita: icono, rotulo, atajo y el relleno del estilo.
    _MARCO = "↻ Update the solution with: «» — Caps+F"
    _RELLENO = 26

    def __init__(self, vistoso=False):
        super().__init__("")
        f = self.font(); f.setPixelSize(12 if vistoso else 11)
        if vistoso:
            f.setWeight(QtGui.QFont.DemiBold)
        self.setFont(f)
        # El texto se recorta al ancho que haya ("…"), nunca al reves: con la
        # cita entera de ancho minimo, el panel crecia hasta salirse de la
        # pantalla. La cita completa queda en el tooltip.
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                           QtWidgets.QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        if vistoso:
            # En el hablado tiene que saltar a la vista: relleno de acento.
            self._RELLENO = 34
            self.setStyleSheet(
                "QPushButton {"
                "   color: #ffffff;"
                "   background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                f"  stop:0 {T.ACCENT_BTN_TOP}, stop:1 {T.ACCENT_BTN_BOT});"
                "   border: 1px solid rgba(195,206,255,0.85);"
                "   border-radius: 11px;"
                "   padding: 7px 14px;"
                "   text-align: left;"
                "}"
                "QPushButton:hover { background: #8ea6ff; }")
        else:
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
        self.setText(f"↻ Update the solution with: «{cita}» — Caps+F")

    def sizeHint(self):
        # Pide el ancho de la cita entera; el layout le da lo que haya.
        fm = self.fontMetrics()
        return QtCore.QSize(fm.horizontalAdvance(self._MARCO + self.texto) + self._RELLENO,
                            super().sizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.texto:
            self._rotular()


class ExplainChip(QtWidgets.QPushButton):
    """'✦ Explain': aparece junto al texto que acabas de subrayar en un panel.
    Al pulsarlo, ese trozo va a la caja de preguntas y se explica alli."""

    VISIBLE_MS = 8000            # si no se usa, se va solo

    def __init__(self, parent):
        super().__init__("Explain", parent)
        self.setObjectName("explicar")
        f = self.font(); f.setPixelSize(11); f.setWeight(QtGui.QFont.DemiBold); self.setFont(f)
        self.setIcon(QtGui.QIcon(icons.pixmap("sparkles", T.ACCENT_BTN_INK, 12)))
        self.setIconSize(QtCore.QSize(12, 12))
        self.setToolTip("Explain the selected text in the Ask box")
        self.setStyleSheet(
            "QPushButton#explicar { color: #ffffff; border: none; border-radius: 10px;"
            "  padding: 3px 10px; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"  stop:0 {T.ACCENT_BTN_TOP}, stop:1 {T.ACCENT_BTN_BOT}); }}"
            "QPushButton#explicar:hover { background: #8ea6ff; }")
        self.setVisible(False)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.VISIBLE_MS)
        self._timer.timeout.connect(self.ocultar)

    def mostrar_en(self, punto):
        """Justo debajo de donde se solto el raton, sin salirse del panel."""
        self.adjustSize()
        padre = self.parentWidget()
        x = max(8, min(punto.x() - self.width() // 2, padre.width() - self.width() - 8))
        y = punto.y() + 10
        if y + self.height() > padre.height() - 8:
            y = punto.y() - self.height() - 10       # sin sitio debajo: encima
        self.move(x, max(8, y))
        self.setVisible(True)
        self.raise_()
        self._timer.start()

    def ocultar(self):
        self._timer.stop()
        self.setVisible(False)


class ModoChip(QtWidgets.QFrame):
    """'Manual | AI': como se resuelve lo que hay en pantalla y lo que preguntas
    por escrito. Manual: el reto lo haces tu a mano (codigo explicado linea a
    linea). AI: el reto se hace con un agente de codigo (que construir, las
    decisiones, el prompt para pegarle y como defenderlo). Sale del agente y se
    cambia aqui en plena reunion; el panel de la pantalla y la caja de
    preguntas llevan uno cada uno, siempre en el mismo modo."""
    changed = QtCore.Signal(str)

    OPCIONES = (
        ("manual", "Manual", "Manual — you solve it by hand: full code explained "
                             "line by line"),
        ("ia", "AI", "AI — you solve it with an AI agent: what to build, the "
                     "decisions, the prompt to paste and how to defend it"),
    )

    def __init__(self):
        super().__init__()
        self.setObjectName("modochip")
        self.setStyleSheet(
            "#modochip { background: rgba(220,228,255,0.05); "
            "border: 1px solid rgba(220,228,255,0.14); border-radius: 10px; }"
            "#modochip QPushButton {"
            f"  color: {T.TEXT_FAINT}; background: transparent; border: none;"
            "   border-radius: 8px; padding: 2px 10px; }"
            "#modochip QPushButton:checked {"
            f"  color: {T.TEXT_BRIGHT}; background: rgba(124,149,255,0.32); }}"
            f"#modochip QPushButton:hover:!checked {{ color: {T.TEXT}; }}")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        grupo = QtWidgets.QButtonGroup(self)
        grupo.setExclusive(True)
        self.botones = {}
        for clave, texto, ayuda in self.OPCIONES:
            b = QtWidgets.QPushButton(texto)
            f = b.font(); f.setPixelSize(11); f.setWeight(QtGui.QFont.DemiBold); b.setFont(f)
            b.setObjectName(f"modo-{clave}")
            b.setCheckable(True)
            b.setToolTip(ayuda)
            b.clicked.connect(lambda _c=False, k=clave: self._elegir(k))
            grupo.addButton(b)
            lay.addWidget(b)
            self.botones[clave] = b
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.modo = "manual"
        self.botones["manual"].setChecked(True)

    def set_modo(self, modo):
        """Lo pone sin avisar (cuando el cambio viene de fuera)."""
        if modo in self.botones:
            self.modo = modo
            self.botones[modo].setChecked(True)

    def _elegir(self, clave):
        if clave != self.modo:
            self.modo = clave
            self.changed.emit(clave)


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
    askClicked = QtCore.Signal()
    spokenClicked = QtCore.Signal()
    mouseClicked = QtCore.Signal()

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

        # Leyenda: todos los atajos son Bloq Mayus + la letra de cada boton.
        leyenda = QtWidgets.QWidget()
        ll = QtWidgets.QHBoxLayout(leyenda)
        ll.setContentsMargins(4, 0, 2, 0)
        ll.setSpacing(4)
        ll.addWidget(_kbd("Caps"))
        mas = QtWidgets.QLabel("+")
        mas.setStyleSheet(f"color: {T.TEXT_FAINT}; background: transparent;")
        ll.addWidget(mas)
        leyenda.setToolTip("Hold Caps Lock and press the letter of each button")
        lay.addWidget(leyenda)

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
        bl.addWidget(_keys("Esc"))
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
        self.keys_gen = _keys("D")
        gl.addWidget(self.keys_gen)
        self.btn_gen.clicked.connect(self.generateClicked)
        lay.addWidget(self.btn_gen)
        self.set_generate_enabled(False)

        # --- responder ahora (red de seguridad si no se detecto la pregunta) ---
        self.btn_answer = self._pill("Answer", ("Caps", "A"), icono="chat")
        self.btn_answer.setToolTip(
            "Responde a lo último que dijeron, aunque no pareciera una pregunta")
        self.btn_answer.clicked.connect(self.answerNowClicked)
        lay.addWidget(self.btn_answer)

        # --- lo hablado, resuelto en grande en el panel de la pantalla ---
        self.btn_spoken = self._pill("Solve", ("Caps", "R"), icono="code")
        self.btn_spoken.setToolTip("Solve what they said out loud on the big panel")
        self.btn_spoken.clicked.connect(self.spokenClicked)
        lay.addWidget(self.btn_spoken)

        # --- captura de pantalla ---
        self.btn_shot = self._pill("Shot", ("Caps", "S"), icono="camera")
        self.btn_shot.clicked.connect(self.screenshotClicked)
        lay.addWidget(self.btn_shot)

        # --- preguntar por escrito (abre la caja de preguntas) ---
        self.btn_ask = self._pill("Ask", ("Caps", "E"), icono="pencil")
        self.btn_ask.setToolTip("Type a question about the screen or the meeting")
        self.btn_ask.clicked.connect(self.askClicked)
        lay.addWidget(self.btn_ask)

        # --- el raton azul ---
        self.btn_mouse = self._pill("Mouse", ("Caps", "Q"), icono="cursor")
        self.btn_mouse.setToolTip("Blue mouse: use the overlay without moving your "
                                  "real cursor")
        self.btn_mouse.clicked.connect(self.mouseClicked)
        lay.addWidget(self.btn_mouse)
        self._lbl_mouse = self.btn_mouse.findChildren(QtWidgets.QLabel)[1]

        # --- minimizar / restaurar ---
        self.btn_toggle = self._pill("Hide", ("Caps", "W"), icono="eye")
        self.btn_toggle.clicked.connect(self.toggleClicked)
        lay.addWidget(self.btn_toggle)
        # Los ajustes viven en la Home, que vuelve al terminar la reunion.

    def interactive_widgets(self):
        """Zonas que SI responden al mouse (el resto deja pasar el clic)."""
        return [self.drag_zone]

    def set_raton(self, activo):
        """La pildora del raton azul se enciende mientras esta activo."""
        self._lbl_mouse.setStyleSheet(
            f"color: {'#6fa0ff' if activo else T.TEXT}; background: transparent;"
            + ("font-weight: 600;" if activo else ""))

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
            # Todas van con Bloq Mayus, que se dice una vez al principio de la
            # barra: aqui solo la letra (con "Caps" en cada una no cabia).
            lay.addWidget(_keys(*[t for t in teclas if t != "Caps"]))
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
      Abajo, el campo para escribir una pregunta (Bloq Mayus+E): la respuesta
      sale en el panel grande, que es donde se lee bien.
    - "pantalla": el panel grande. Capturas y sus soluciones, lo que se pide
      resolver de lo hablado (Bloq Mayus+R) y las respuestas a lo que escribes.
    Los dos llevan el selector Manual | AI (ModoChip), siempre en el mismo modo.
    """
    relaunchClicked = QtCore.Signal()
    closeClicked = QtCore.Signal()
    agentChosen = QtCore.Signal(str)
    # El campo de preguntas (solo el hablado): enviar, pulsarlo (hay que darle
    # el teclado) y salir con Esc.
    submitted = QtCore.Signal(str)
    entradaPulsada = QtCore.Signal()
    entradaSalir = QtCore.Signal()
    # Subrayaste un trozo y pulsaste Explain: (texto, "modo:quien"), p. ej.
    # "pantalla:tu" para la solucion o "voz:ellos" para lo que dijeron.
    explainRequested = QtCore.Signal(str, str)

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

        # Subrayar un trozo de texto -> boton "Explain" al lado.
        self._label_sel = None
        self._seleccion = ("", "")
        self.chip_explicar = ExplainChip(self.card)
        self.chip_explicar.clicked.connect(self._pedir_explicacion)

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
        if self.chip_explicar.isVisible():
            zonas.append(self.chip_explicar)
        if getattr(self, "entrada", None) is not None:
            zonas += [self.entrada, self.btn_enviar]
        for extra in (self.relanzar_chip, self.btn_close, self.agent_chip,
                      self.modo_chip):
            if extra.isVisible():
                zonas.append(extra)
        # La horizontal solo esta cuando el codigo no cabe de ancho; si no se
        # puede arrastrar, el trozo que sobresale seguiria sin poder leerse.
        if self.scroll.horizontalScrollBar().isVisible():
            zonas.append(self.scroll.horizontalScrollBar())
        # Con texto en el hilo, el hilo recibe el raton: se puede subrayar un
        # trozo para pedir que lo expliquen (y desplazarlo con el panel tactil).
        if self.scroll.verticalScrollBar().maximum() > 0 or self._burbujas:
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
        # El companero: la mascota del agente, viva. En el hablado sustituye a
        # las barras: bota con la voz, piensa, habla y se alegra.
        self.compa = avatares.Avatar(avatares.COLOR_POR_DEFECTO, 38, vivo=True)
        self.compa.setObjectName("compa")
        self.compa.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)  # se arrastra igual
        lay.addWidget(self.compa)

        # Hablado: el titulo es el agente. Pantalla: "Screen · N shots".
        self.agent_chip = AgentChip()
        self.agent_chip.chosen.connect(self.agentChosen.emit)
        lay.addWidget(self.agent_chip)
        base = _tracked("Screen", 13, QtGui.QFont.DemiBold, T.TEXT_BRIGHT, 0)
        self.titulo = _TituloElastico("Screen", base.font(), T.TEXT_BRIGHT)
        base.deleteLater()
        lay.addWidget(self.titulo)

        lay.addStretch()
        # Manual | AI: en la cabecera del panel grande; en el hablado va junto
        # al campo de preguntas (en su cabecera no cabe con el agente y el estado).
        if self.modo == "pantalla":
            self.modo_chip = ModoChip()
            lay.addWidget(self.modo_chip)
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
            self.compa.setVisible(False)
            self.agent_chip.setVisible(False)
            self.agent_chip.setEnabled(False)
        else:
            self.bars.setVisible(False)          # el companero ya dice que hay audio
            self.agent_chip.mostrar_cara = False  # su cara va en el companero
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
        self._cuerpo = w

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
        # Nunca barra horizontal: el panel tiene su ancho y todo se parte a el
        # (el codigo con pre-wrap y los comentarios encima de cada linea).
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
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
        pl.addStretch()
        pl.addWidget(self.nuevo_chip)
        lay.addWidget(pie)
        # Lo que dijeron parece pedir un cambio en la solucion del panel grande:
        # se ofrece aqui, en el hablado (que es donde miras mientras hablan) y
        # bien visible. El tester decide; nunca se relanza sola.
        self.relanzar_chip = SuggestionChip(vistoso=True)
        self.relanzar_chip.clicked.connect(self.relaunchClicked.emit)
        fila_chip = QtWidgets.QWidget()
        fc = QtWidgets.QHBoxLayout(fila_chip)
        fc.setContentsMargins(14, 0, 28, 8)
        fc.addWidget(self.relanzar_chip, 1)
        lay.addWidget(fila_chip)
        if self.modo == "voz":
            lay.addWidget(self._entrada())

        if self.modo == "pantalla":
            self.set_hint("Screenshots (Caps+S), what they asked out loud (Caps+R) "
                          "and your typed questions get solved here.")
        else:
            self.set_hint("Waiting for the first question — the answer will "
                          "draft here.")
        return w

    def set_agents(self, agentes, activo):
        """Agentes para el selector de la cabecera (solo el panel hablado)."""
        if self.modo == "voz":
            self.agent_chip.set_agents(agentes, activo)
            cara = next((a[2] for a in agentes if a[0] == activo and len(a) > 2), None)
            if cara is not None:
                forma, color = cara
                self.compa.set_color(color, forma)

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
        b = Burbuja(quien, self._ancho_burbuja(), seleccionable=self._hacer_seleccionable)
        self._burbujas.append(b)
        self._añadir(b)
        return b

    # ---------------- el campo de preguntas (solo el hablado)
    def _entrada(self):
        w = QtWidgets.QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QtWidgets.QHBoxLayout(w)
        # A la derecha, hueco para el agarre de redimension de la esquina.
        lay.setContentsMargins(14, 2, 30, 12)
        lay.setSpacing(8)
        self.entrada = _CajaPregunta()
        self.entrada.setObjectName("entrada")
        self.entrada.setPlaceholderText(HINT_PREGUNTA)
        self.entrada.setTabChangesFocus(True)
        # Flecha tambien aqui: el cursor de texto se veria al compartir pantalla.
        self.entrada.viewport().setCursor(QtCore.Qt.ArrowCursor)
        self.entrada.viewport().installEventFilter(self)
        f = self.entrada.font(); f.setPixelSize(14); self.entrada.setFont(f)
        self.entrada.setStyleSheet(
            "QPlainTextEdit#entrada {"
            f"  color: {T.TEXT_BRIGHT}; background: rgba(220,228,255,0.06);"
            "   border: 1px solid rgba(124,149,255,0.38); border-radius: 10px;"
            "   padding: 4px 6px; selection-background-color: rgba(124,149,255,0.45);"
            "}"
            "QPlainTextEdit#entrada QScrollBar:vertical { background: transparent; "
            "width: 8px; margin: 3px 2px 3px 0; }"
            "QPlainTextEdit#entrada QScrollBar::handle:vertical { "
            "background: rgba(124,149,255,0.28); border-radius: 4px; min-height: 14px; }"
            "QPlainTextEdit#entrada QScrollBar::add-line:vertical, "
            "QPlainTextEdit#entrada QScrollBar::sub-line:vertical { height: 0; }")
        # Dos lineas a la vista; si escribes mas, se desplaza dentro.
        self.entrada.setFixedHeight(self.entrada.fontMetrics().lineSpacing() * 2 + 20)
        self.entrada.enviar.connect(self._enviar)
        self.entrada.salir.connect(self.entradaSalir.emit)
        self.modo_chip = ModoChip()
        lay.addWidget(self.modo_chip, 0, QtCore.Qt.AlignBottom)
        lay.addWidget(self.entrada, 1)
        self.btn_enviar = QtWidgets.QPushButton()
        self.btn_enviar.setObjectName("enviar")
        self.btn_enviar.setIcon(QtGui.QIcon(icons.pixmap("chevron_right", T.ACCENT_BTN_INK, 16)))
        self.btn_enviar.setFixedSize(34, 34)
        self.btn_enviar.setToolTip("Send (Enter) — the answer opens on the big panel")
        self.btn_enviar.setStyleSheet(
            "QPushButton#enviar { border: none; border-radius: 17px; background: "
            f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {T.ACCENT_BTN_TOP}, "
            f"stop:1 {T.ACCENT_BTN_BOT}); }}"
            "QPushButton#enviar:hover { background: #8ea6ff; }")
        self.btn_enviar.clicked.connect(self._enviar)
        lay.addWidget(self.btn_enviar, 0, QtCore.Qt.AlignBottom)
        return w

    def _enviar(self):
        texto = self.entrada.toPlainText().strip()
        if not texto:
            return
        self.entrada.clear()
        self.submitted.emit(texto)

    def enfocar(self):
        """El cursor, en el campo de preguntas."""
        self.entrada.setFocus(QtCore.Qt.ActiveWindowFocusReason)

    def tiene_foco(self):
        return self.isVisible() and self.isActiveWindow() and self.entrada.hasFocus()

    def citar(self, texto):
        """Empieza la pregunta citando un trozo subrayado: «...» y tu pregunta."""
        if self.entrada.toPlainText().strip():
            return                        # no se pisa lo que ya escribias
        self.entrada.setPlainText(f"«{texto}» ")
        self.entrada.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def add_question(self, texto):
        """Una pregunta escrita, en el hilo: su respuesta llegara debajo."""
        self._auto["feed"].anotar()
        b = self._nueva_burbuja("pregunta")
        b.set_texto(texto)
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    # ---------------- subrayar para preguntar
    def _hacer_seleccionable(self, label):
        """Texto que se puede subrayar con el raton, con la flecha de siempre."""
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        label.setCursor(QtCore.Qt.ArrowCursor)
        # El subrayado en el pervinca del overlay, no en el azul de Windows.
        pal = label.palette()
        for grupo in (QtGui.QPalette.Active, QtGui.QPalette.Inactive):
            pal.setColor(grupo, QtGui.QPalette.Highlight, QtGui.QColor(124, 149, 255, 120))
            pal.setColor(grupo, QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
        label.setPalette(pal)
        label.installEventFilter(self)

    def eventFilter(self, obj, ev):
        entrada = getattr(self, "entrada", None)
        if (entrada is not None and obj is entrada.viewport()
                and ev.type() == QtCore.QEvent.MouseButtonPress):
            # El panel no se activa al pulsarlo (no roba el foco): para
            # escribir hay que darle el teclado a proposito.
            self.entradaPulsada.emit()
        if isinstance(obj, QtWidgets.QLabel):
            tipo = ev.type()
            if tipo == QtCore.QEvent.MouseButtonPress:
                # Una seleccion cada vez: la de otro texto se borra.
                previa = self._label_sel
                if previa is not None and previa is not obj and isValid(previa):
                    previa.setSelection(0, 0)
                self.chip_explicar.ocultar()
            elif tipo == QtCore.QEvent.MouseButtonRelease:
                punto = ev.position().toPoint()
                # La etiqueta termina la seleccion al procesar este evento.
                QtCore.QTimer.singleShot(0, self, lambda o=obj, p=punto: self._tras_soltar(o, p))
        return super().eventFilter(obj, ev)

    def _tras_soltar(self, label, punto):
        if not isValid(label):
            return
        texto = label.selectedText().strip()
        if not texto:
            self.chip_explicar.ocultar()
            return
        burbuja = label.parentWidget()
        while burbuja is not None and not isinstance(burbuja, Burbuja):
            burbuja = burbuja.parentWidget()
        quien = burbuja.quien if burbuja is not None else ""
        self._label_sel = label
        self._seleccion = (texto, f"{self.modo}:{quien}")
        self.chip_explicar.mostrar_en(label.mapTo(self.card, punto))

    def seleccion(self):
        """(texto, origen) subrayado ahora mismo, o ("", "")."""
        label = self._label_sel
        if label is None or not isValid(label) or not label.hasSelectedText():
            return ("", "")
        return self._seleccion

    def limpiar_seleccion(self):
        if self._label_sel is not None and isValid(self._label_sel):
            self._label_sel.setSelection(0, 0)
        self._label_sel = None
        self._seleccion = ("", "")
        self.chip_explicar.ocultar()

    def _pedir_explicacion(self):
        texto, origen = self.seleccion()
        self.limpiar_seleccion()
        if texto:
            self.explainRequested.emit(texto, origen)

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
            self.compa.set_estado({"generating": avatares.PENSANDO_E,
                                   "listening": avatares.ESCUCHANDO}.get(state, avatares.REPOSO))
        self._apply_border()
        self._render_question()

    # ---------------- API publica
    def set_level(self, v):
        self.bars.set_level(v)
        self.compa.set_nivel(v)

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
    def clear_answer(self, quien="tu"):
        """Empieza una sugerencia nueva: se abre otra burbuja, no se borra nada.

        Y se ancla: desde aqui la sugerencia (con su pregunta encima, si cabe)
        se queda arriba mientras la lees, crezca lo que crezca y llegue lo que
        llegue por debajo. quien="respuesta": la respuesta a una pregunta
        escrita, debajo de esa pregunta.
        """
        self._raw = ""
        self._quien_resp = quien
        buscadas = ("pregunta",) if quien == "respuesta" else ("ellos",)
        pregunta = next((b for b in reversed(self._burbujas)
                         if b.quien in buscadas and isValid(b)), None)
        self._auto["feed"].anotar()
        self._burbuja_resp = self._nueva_burbuja(quien)
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
        if self.compa.estado == avatares.PENSANDO_E:
            self.compa.set_estado(avatares.HABLANDO)   # llega la respuesta: la dice
        if not self._repintado_pendiente:
            self._repintado_pendiente = True
            self._timer_repintado.start()

    def _repintar(self):
        self._timer_repintado.stop()
        self._repintado_pendiente = False
        if self._burbuja_resp is None:
            self._burbuja_resp = self._nueva_burbuja(getattr(self, "_quien_resp", "tu"))
        with metricas.cronometro(PINTADO):
            self._auto["feed"].anotar()
            self._burbuja_resp.set_markdown(self._raw, self)
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    def cerrar_respuesta(self):
        """Se acabo de generar: el ultimo trozo se pinta y la burbuja se cierra."""
        if self._repintado_pendiente or self._burbuja_resp is None:
            self._repintar()
        self._burbuja_resp = None
        if self._raw.strip():
            self.compa.set_estado(avatares.CONTENTO)   # un saltito: ya esta

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
        self.limpiar_seleccion()
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

    @staticmethod
    def _etiqueta_rica(html_):
        lab = QtWidgets.QLabel(html_)
        lab.setWordWrap(True)
        lab.setTextFormat(QtCore.Qt.RichText)
        lab.setStyleSheet("background: transparent;")
        return lab

    def _lista(self, items):
        """Lista con su numero o su punto, y sublistas sangradas."""
        # Las columnas de una tabla son comunes a todas las filas, asi que una
        # sublista no puede tener su propia columna de sangria: su punto va
        # dentro de la columna del texto, debajo del texto de su padre (como en
        # ChatGPT o Claude), y cada nivel mas, un poco mas adentro.
        filas = []
        for nivel, marca, texto in items:
            numero = marca != "•"
            contenido = richtext.inline_html(texto, self._CODE_INLINE)
            peso = "font-weight:600;" if numero else ""
            if nivel == 0:
                filas.append(
                    f'<tr><td align="right" style="color:{T.ACCENT};padding-right:8px;'
                    f'{peso}">{marca}</td><td>{contenido}</td></tr>')
            else:
                punto = marca if numero else "◦"
                filas.append(
                    f'<tr><td></td><td style="padding-left:{16 * (nivel - 1)}px;">'
                    f'<span style="color:{T.ACCENT};{peso}">{punto}</span>'
                    f'&nbsp;&nbsp;{contenido}</td></tr>')
        return self._etiqueta_rica(
            f'<table style="line-height:150%; color:{T.ANSWER_TEXT}; font-size:14px;" '
            f'cellspacing="0" cellpadding="1">{"".join(filas)}</table>')

    def _vinetas(self, items):
        """Lista simple de puntos (compatibilidad)."""
        return self._lista([(0, "•", t) for t in items])

    def _subtitulo(self, texto):
        lab = self._etiqueta_rica(
            f'<div style="color:{T.TEXT_BRIGHT}; font-size:14.5px; font-weight:600;">'
            f'{richtext.inline_html(texto, self._CODE_INLINE)}</div>')
        lab.setContentsMargins(0, 4, 0, 0)
        return lab

    def _tabla(self, cabecera, filas):
        """Tabla con la cabecera marcada y filas separadas, como en un chat."""
        ancho = max([len(cabecera)] + [len(f) for f in filas])

        def celdas(valores, etiqueta, estilo, extra=""):
            valores = list(valores) + [""] * (ancho - len(valores))
            return "".join(f'<{etiqueta}{extra} style="{estilo}">'
                           f'{richtext.inline_html(v, self._CODE_INLINE)}</{etiqueta}>'
                           for v in valores)

        borde = "border-bottom:1px solid rgba(220,228,255,0.12);"
        # Color de celda (atributo, opaco): con un fondo translucido Qt lo
        # pintaba dos veces, en la celda y detras del texto.
        cab = ("<tr>"
               + celdas(cabecera, "th", f"color:{T.TEXT_BRIGHT}; text-align:left; "
                                        f"font-weight:600; padding:5px 10px; {borde}",
                        extra=' bgcolor="#2a3150"')
               + "</tr>")
        cuerpo = "".join(
            f'<tr>{celdas(f, "td", f"padding:5px 10px; {borde}")}</tr>' for f in filas)
        return self._etiqueta_rica(
            f'<table style="color:{T.ANSWER_TEXT}; font-size:13.5px;" cellspacing="0" '
            f'cellpadding="5" border="0">{cab}{cuerpo}</table>')

    def _cita(self, texto):
        lab = self._etiqueta_rica(
            f'<div style="color:{T.TEXT_MUTED}; font-size:14px; font-style:italic; '
            f'line-height:150%;">{richtext.inline_html(texto, self._CODE_INLINE)}</div>')
        lab.setStyleSheet(f"background: rgba(124,149,255,0.06); border: none; "
                          f"border-left: 3px solid {T.ACCENT}; padding: 6px 10px; "
                          f"border-radius: 4px;")
        return lab

    def _regla(self):
        linea = QtWidgets.QFrame()
        linea.setFixedHeight(1)
        linea.setStyleSheet(f"background: {T.DIVIDER}; border: none; margin: 4px 0;")
        return linea

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


class _CajaPregunta(QtWidgets.QPlainTextEdit):
    """Donde se escribe la pregunta: Enter la manda, Mayus+Enter salta de
    linea (para pegar un trozo de codigo) y Esc cierra la caja."""
    enviar = QtCore.Signal()
    salir = QtCore.Signal()

    def keyPressEvent(self, e):
        enter = e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter)
        if enter and not e.modifiers() & QtCore.Qt.ShiftModifier:
            self.enviar.emit()
            return
        if e.key() == QtCore.Qt.Key_Escape:
            self.salir.emit()
            return
        super().keyPressEvent(e)


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
        lay.addWidget(_keys("Caps", "W"))
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
