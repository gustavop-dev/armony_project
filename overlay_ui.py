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

import icons
import richtext
import theme as T

# Cada cuanto se repinta la respuesta mientras llega. Bastante mas rapido que
# leer, pero mil veces menos trabajo que reconstruir el panel en cada trozo.
INTERVALO_REPINTADO = 90    # ms


# --------------------------------------------------------------- utilidades

def _frameless(win):
    """Ventana sin marco, siempre encima y fuera de la barra de tareas.

    IMPORTANTE: NO se usa WA_TranslucentBackground. Ese atributo (alpha por-pixel)
    convierte la ventana en 'layered' y hace que Windows rechace ocultarla al
    compartir pantalla. En su lugar: fondo solido + opacidad de ventana uniforme
    (compatible con la invisibilidad) + esquinas redondeadas por mascara.
    """
    win.setWindowFlags(
        QtCore.Qt.FramelessWindowHint
        | QtCore.Qt.WindowStaysOnTopHint
        | QtCore.Qt.Tool
    )
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

    def __init__(self):
        super().__init__()
        # A proposito NO se cambia el cursor. La ventana es invisible al compartir
        # pantalla, pero el cursor NO lo es: si se volviera una manita al pasar
        # sobre un boton, quien te ve compartiendo pantalla veria el puntero
        # transformandose encima de la nada. El overlay se delataria solo.

    def mousePressEvent(self, e):
        e.accept()          # no propagar: evita arrastrar la ventana al pulsar

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self.rect().contains(e.position().toPoint()):
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

    _center_child = None

    def __init__(self):
        super().__init__()
        # Sin cambio de cursor: la senal de que se puede arrastrar son los
        # punticos (GripDots), no el puntero.
        self._off = None

    def resizeEvent(self, e):
        # Centra un hijo (los punticos) en el ancho REAL de la barra, no en el
        # espacio que sobra a un lado.
        if self._center_child is not None:
            c = self._center_child
            c.move((self.width() - c.width()) // 2, (self.height() - c.height()) // 2)
            c.raise_()
        super().resizeEvent(e)

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
        "idle":        ("#8f8674", False),
        "loading":     ("#e7b93a", True),
        "listening":   ("#3ddc84", True),   # verde bonito
        "transcribing": ("#f2c94c", True),
        "drafting":    ("#f2c94c", True),
        "analyzing":   ("#f2c94c", True),
        "error":       ("#e0554b", True),
        "info":        ("#8f8674", False),
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
        self._lbl.setStyleSheet(f"color: {color if tinted else '#a89f8a'}; background: transparent;")
        rgb = QtGui.QColor(color)
        bg = (f"rgba({rgb.red()},{rgb.green()},{rgb.blue()},0.14)" if tinted
              else "rgba(243,234,212,0.05)")
        bd = (f"rgba({rgb.red()},{rgb.green()},{rgb.blue()},0.45)" if tinted
              else "rgba(243,234,212,0.10)")
        self.setStyleSheet(
            f"StatusBadge {{ background: {bg}; border: 1px solid {bd}; border-radius: 11px; }}")
        self._lbl.setText(texto)


class _AutoScroll:
    """Mantiene un area pegada al final mientras no subas a leer.

    Dos detalles que parecen tonterias y no lo son:

    1. El alto definitivo del contenido no se sabe al pintar, sino cuando Qt
       recalcula el layout, que es cuando se emite rangeChanged. Bajar antes deja
       el texto arriba.
    2. Repintar destruye y recrea los widgets; al vaciarlos el rango cae a cero y
       con el la posicion. Sin guardarla, subir a releer no serviria de nada.
    """

    MARGEN = 8      # pixeles de tolerancia para considerarse "al final"

    def __init__(self, scroll):
        self.scroll = scroll
        self.seguir = True
        self.objetivo = None
        scroll.verticalScrollBar().rangeChanged.connect(
            lambda *_: self.restaurar())

    def anotar(self):
        """Antes de repintar: recuerda donde estabas y si venias siguiendo."""
        sb = self.scroll.verticalScrollBar()
        self.seguir = sb.value() >= sb.maximum() - self.MARGEN
        self.objetivo = sb.value()

    def restaurar(self):
        sb = self.scroll.verticalScrollBar()
        if self.seguir:
            sb.setValue(sb.maximum())
        elif self.objetivo is not None:
            sb.setValue(min(self.objetivo, sb.maximum()))

    def rueda(self, muescas):
        """muescas positivas = hacia arriba."""
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.value() - muescas * 3 * sb.singleStep())
        # Si te quedas al final se vuelve a seguir; si subes, se deja de seguir.
        self.seguir = sb.value() >= sb.maximum() - self.MARGEN
        self.objetivo = sb.value()

    def zona(self):
        """Rectangulo en pantalla, para el desviador de rueda."""
        if not self.scroll.isVisible():
            return None
        tl = self.scroll.mapToGlobal(QtCore.QPoint(0, 0))
        return (tl.x(), tl.y(), self.scroll.width(), self.scroll.height())


class CodeBlock(QtWidgets.QFrame):
    """Bloque de codigo: cabecera con el lenguaje, boton de copiar y el cuerpo.

    El cuerpo va en texto plano y monoespaciado a proposito: asi los saltos de
    linea y la indentacion salen tal cual los escribio el modelo, que es lo unico
    que hace legible el codigo.
    """

    def __init__(self, lenguaje, codigo):
        super().__init__()
        self._codigo = codigo
        self.setStyleSheet(f"""
            CodeBlock {{
                background: {T.KBD_BG};
                border: 1px solid {T.DIVIDER_FAINT};
                border-radius: 8px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        cab = QtWidgets.QWidget()
        cl = QtWidgets.QHBoxLayout(cab)
        cl.setContentsMargins(10, 5, 6, 5)
        cl.setSpacing(8)
        etq = QtWidgets.QLabel((lenguaje or "code").upper())
        ef = etq.font(); ef.setPixelSize(10); ef.setWeight(QtGui.QFont.DemiBold)
        ef.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 0.8)
        etq.setFont(ef)
        etq.setStyleSheet(f"color: {T.GOLD_LABEL}; background: transparent;")
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

        cuerpo = QtWidgets.QLabel(codigo)
        cuerpo.setTextFormat(QtCore.Qt.PlainText)      # respeta saltos y espacios
        cuerpo.setWordWrap(True)
        cuerpo.setStyleSheet(
            f"font-family: {T.MONO_STACK}; font-size: 12.5px; "
            f"color: {T.TEXT_BRIGHT}; background: transparent; padding: 9px 11px;")
        # Nada de texto seleccionable: Qt pondria el cursor de texto encima, y el
        # cursor si se ve al compartir pantalla aunque la ventana no. Ademas la
        # seleccion no funcionaria (esta zona deja pasar los clics): para eso esta
        # el boton de copiar.
        lay.addWidget(cuerpo)

    def _copiar(self):
        QtWidgets.QApplication.clipboard().setText(self._codigo)
        self.lbl_copy.setText("Copied")
        QtCore.QTimer.singleShot(1400, lambda: self.lbl_copy.setText("Copy"))


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
        p.setBrush(QtGui.QColor(T.PANEL_BODY))
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
                background: {'rgba(242,201,76,0.07)' if mio else 'rgba(243,234,212,0.04)'};
                border: 1px solid {'rgba(242,201,76,0.28)' if mio else T.DIVIDER_FAINT};
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
        if mio:
            cab.addStretch()
            cab.addWidget(icons.label("sparkles", T.GOLD, 12))
            cab.addWidget(_tracked("You", 10, QtGui.QFont.Bold, T.GOLD, 0.6, upper=True))
        else:
            cab.addWidget(_tracked("Participant", 10, QtGui.QFont.DemiBold,
                                   T.TEXT_FAINT, 0.6, upper=True))
            cab.addStretch()
        lay.addLayout(cab)

        self.cuerpo = QtWidgets.QVBoxLayout()
        self.cuerpo.setContentsMargins(0, 0, 0, 0)
        self.cuerpo.setSpacing(7)
        lay.addLayout(self.cuerpo)

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
        cursor = f'<span style="color:{T.GOLD};">&#9611;</span>' if caret else ""
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
                                           T.GOLD_LABEL, 0.9, upper=True))
            for bloque in bloques:
                if bloque[0] == richtext.CODE:
                    cb = CodeBlock(bloque[1], bloque[2])
                    self.copy_buttons.append(cb.btn_copy)
                    self.cuerpo.addWidget(cb)
                elif bloque[0] == richtext.BULLETS:
                    self.cuerpo.addWidget(vinetas(bloque[1]))
                else:
                    self.cuerpo.addWidget(parrafo(bloque[1]))


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
            "   background: rgba(243,234,212,0.05);"
            "   border: 1px solid rgba(243,234,212,0.10);"
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
        color = QtGui.QColor(T.GOLD)
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

class TopBar(QtWidgets.QWidget, _Draggable):
    startStopClicked = QtCore.Signal()
    screenshotClicked = QtCore.Signal()
    generateClicked = QtCore.Signal()
    answerNowClicked = QtCore.Signal()
    toggleClicked = QtCore.Signal()
    settingsClicked = QtCore.Signal()

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

        self.setStyleSheet(f"background: {T.PANEL_TOP};")
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

        # --- marca "Cue." (C dorada, resto blanco), sin icono de limon ---
        marca = QtWidgets.QWidget()
        ml = QtWidgets.QHBoxLayout(marca)
        ml.setContentsMargins(8, 6, 8, 6)
        ml.setSpacing(8)
        nombre = QtWidgets.QLabel(
            f'<span style="color:{T.GOLD};font-weight:700;">Arm</span>'
            f'<span style="color:#ffffff;font-weight:700;">ony.</span>')
        nf = nombre.font(); nf.setPixelSize(15); nombre.setFont(nf)
        nombre.setStyleSheet("background: transparent;")
        ml.addWidget(nombre)
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
        self.ico_meeting = icons.label("play", "#f7e39a", 15)
        bl.addWidget(self.ico_meeting)
        self.lbl_meeting = QtWidgets.QLabel("Start meeting")
        f = self.lbl_meeting.font(); f.setPixelSize(13); f.setWeight(QtGui.QFont.DemiBold)
        self.lbl_meeting.setFont(f)
        bl.addWidget(self.lbl_meeting)
        self.lbl_timer = QtWidgets.QLabel("")
        self.lbl_timer.setStyleSheet(
            f"font-family: {T.MONO_STACK}; font-size: 12px; color: {T.TEXT}; background: transparent;")
        bl.addWidget(self.lbl_timer)
        bl.addWidget(_keys("Alt", "4"))
        self.btn_meeting.clicked.connect(self.startStopClicked)
        lay.addWidget(self.btn_meeting)
        self._paint_meeting()

        # Orden de izquierda a derecha: 4 (meeting), 3 (generate), 5 (answer now),
        # 2 (screenshot), 1 (show/hide). No es el orden de los numeros: se agrupan
        # los dos que hacen responder a la IA (3 y 5), que es como se usan.

        # --- generar (se ilumina cuando hay capturas listas) ---
        self.btn_gen = ClickFrame()
        gl = QtWidgets.QHBoxLayout(self.btn_gen)
        gl.setContentsMargins(12, 8, 12, 8)
        gl.setSpacing(7)
        self.ico_gen = icons.label("sparkles", T.GOLD_BTN_INK, 16)
        gl.addWidget(self.ico_gen)
        self.lbl_gen = QtWidgets.QLabel("Generate")
        gf = self.lbl_gen.font(); gf.setPixelSize(13); gf.setWeight(QtGui.QFont.Bold)
        self.lbl_gen.setFont(gf)
        gl.addWidget(self.lbl_gen)
        self.keys_gen = _keys("Alt", "3", light=True)
        gl.addWidget(self.keys_gen)
        self.btn_gen.clicked.connect(self.generateClicked)
        lay.addWidget(self.btn_gen)
        self.set_generate_enabled(False)

        # --- responder ahora (red de seguridad si no se detecto la pregunta) ---
        self.btn_answer = self._pill("Answer now", ("Alt", "5"), icono="chat")
        self.btn_answer.setToolTip(
            "Responde a lo último que dijeron, aunque no pareciera una pregunta")
        self.btn_answer.clicked.connect(self.answerNowClicked)
        lay.addWidget(self.btn_answer)

        # --- captura de pantalla ---
        self.btn_shot = self._pill("Screenshot", ("Alt", "2"), icono="camera")
        self.btn_shot.clicked.connect(self.screenshotClicked)
        lay.addWidget(self.btn_shot)

        # --- mostrar / ocultar ---
        self.btn_toggle = self._pill("Show / Hide", ("Alt", "1"), icono="eye")
        self.btn_toggle.clicked.connect(self.toggleClicked)
        lay.addWidget(self.btn_toggle)

        # --- ajustes (necesario para la API key; no estaba en el diseno) ---
        self.btn_cfg = self._pill("", None, icono="cog", ancho=40)
        self.btn_cfg.setToolTip("Settings")
        self.btn_cfg.clicked.connect(self.settingsClicked)
        lay.addWidget(self.btn_cfg)

    def interactive_widgets(self):
        """Zonas que SI responden al mouse (el resto deja pasar el clic)."""
        return [self.btn_cfg]

    def set_generate_enabled(self, on):
        """Encendido = hay capturas listas. Se maneja por Alt+3; aqui solo se ve."""
        on = bool(on)
        if on:
            self.btn_gen.setStyleSheet(f"""
                QFrame {{ border: none; border-radius: {T.R_BTN}px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {T.GOLD_BTN_TOP}, stop:1 {T.GOLD_BTN_BOT}); }}
                QLabel {{ border: none; background: transparent; }}
            """)
            self.lbl_gen.setStyleSheet(f"color: {T.GOLD_BTN_INK}; background: transparent;")
            self.ico_gen.setPixmap(icons.pixmap("sparkles", T.GOLD_BTN_INK, 16))
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
            borde, fondo, texto = "rgba(242,201,76,0.5)", "rgba(242,201,76,0.16)", "#f7e39a"
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

class TranscriptPanel(QtWidgets.QWidget, _Draggable):
    def __init__(self):
        super().__init__()
        _frameless(self)
        self._init_drag()
        self._raw = ""
        self._state = "idle"
        self._question_text = ""
        self._caret_on = True
        self._anim_phase = 0
        self._part_last = None
        self._burbujas = []         # todas las del hilo, para los botones copiar
        self._burbuja_viva = None   # la intervencion que se esta transcribiendo
        self._burbuja_resp = None   # la sugerencia que se esta generando
        self._repintado_pendiente = False
        self._auto = {}             # se llena en _body, al crear el hilo
        self._build()
        # Animacion: pulso del borde (listening) + caret parpadeante.
        self._anim = QtCore.QTimer(self)
        self._anim.timeout.connect(self._animate)
        self._anim.start(90)
        self._apply_border()

    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.setStyleSheet(f"background: {T.PANEL_BODY};")
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
        super().resizeEvent(e)

    def interactive_widgets(self):
        """Zonas que responden al mouse: cabecera (mover), scroll, agarre y copiar.

        Se consulta cada 30 ms desde app.py, asi que los botones de copiar que se
        crean en cada render entran solos.
        """
        return ([self._drag_header, self.scroll.verticalScrollBar(),
                 self.resize_grip] + self._copy_buttons)

    # ---------------- encabezado
    def _header(self):
        w = DragBar()          # arrastrar desde aqui mueve todo el panel
        self._drag_header = w
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(10)

        self.bars = AudioBars()
        lay.addWidget(self.bars)

        titulo = _tracked("Live Transcription", 13, QtGui.QFont.DemiBold, T.TEXT_BRIGHT, 0)
        lay.addWidget(titulo)

        # Punto que se ilumina cuando llega audio de la reunion. Antes vivia
        # sobre la columna del participante, que ya no existe.
        self.part_dot = QtWidgets.QLabel()
        self.part_dot.setFixedSize(8, 8)
        lay.addWidget(self.part_dot)
        self._paint_part(0)

        self.badge = StatusBadge()
        lay.addWidget(self.badge)
        # medidor de latencia de transcripcion (a la derecha del badge)
        self.lat = QtWidgets.QLabel("")
        lf = self.lat.font(); lf.setPixelSize(11); self.lat.setFont(lf)
        self.lat.setToolTip("Tiempo que tardó la última transcripción")
        self.lat.setVisible(False)
        lay.addWidget(self.lat)
        lay.addStretch()

        # Punticos de agarre: hijo flotante centrado en el ancho real de la barra.
        grip = GripDots()
        grip.setParent(w)
        w._center_child = grip
        grip.raise_()

        w.setStyleSheet(f"border-bottom: 1px solid {T.DIVIDER_SOFT};")
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
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        cont = QtWidgets.QWidget()
        cont.setStyleSheet("background: transparent;")
        self.feed = QtWidgets.QVBoxLayout(cont)
        self.feed.setContentsMargins(18, 14, 18, 14)
        self.feed.setSpacing(10)
        self.feed.addStretch()          # el hueco sobrante, siempre al final
        self.scroll.setWidget(cont)
        # El seguimiento del final se crea aqui: set_hint ya lo usa.
        self._auto["feed"] = _AutoScroll(self.scroll)
        lay.addWidget(self.scroll, 1)

        # Aviso de "no voy a responder": va pegado al hilo, no dentro de el, para
        # que no se pierda hacia arriba cuando siga entrando conversacion.
        self.skip_pill = SkipPill()
        pie = QtWidgets.QWidget()
        pl = QtWidgets.QHBoxLayout(pie)
        pl.setContentsMargins(18, 0, 18, 10)
        pl.addWidget(self.skip_pill)
        pl.addStretch()
        lay.addWidget(pie)

        self.set_hint("Start the meeting to capture the participant "
                      "and draft a suggested answer.")
        return w

    # -- piezas del hilo ----------------------------------------------------
    def _ancho_burbuja(self):
        return max(260, int(self.width() * 0.78))

    def _añadir(self, widget, lado):
        """Mete algo en el hilo, alineado a un lado."""
        fila = QtWidgets.QWidget()
        fila.setStyleSheet("background: transparent;")
        fl = QtWidgets.QHBoxLayout(fila)
        fl.setContentsMargins(0, 0, 0, 0)
        if lado == "der":
            fl.addStretch()
            fl.addWidget(widget)
        else:
            fl.addWidget(widget)
            fl.addStretch()
        self.feed.insertWidget(self.feed.count() - 1, fila)   # antes del hueco
        return fila

    def _nueva_burbuja(self, quien):
        b = Burbuja(quien, self._ancho_burbuja())
        self._burbujas.append(b)
        self._añadir(b, "der" if quien == "tu" else "izq")
        return b

    # ---------------- estado visual (borde + animacion)
    def _apply_border(self):
        if self._state == "generating":
            color, width = QtGui.QColor(242, 201, 76), 2
        elif self._state == "listening":
            a = 0.30 + 0.35 * (0.5 + 0.5 * math.sin(self._anim_phase * 0.22))
            color, width = QtGui.QColor(242, 201, 76, int(a * 255)), 1
        else:  # idle
            color, width = QtGui.QColor(210, 220, 223, 36), 1
        self.card.set_borde(color, width)

    def _animate(self):
        self._anim_phase += 1
        if self._anim_phase % 6 == 0:      # ~540 ms
            self._caret_on = not self._caret_on
            if self._state == "listening" and self._question_text:
                self._render_question()
        if self._state == "listening":
            self._apply_border()

    def set_state(self, state):
        """idle | listening | generating -> cambia el borde y el pulso."""
        self._state = state
        self.bars.set_listening(state in ("listening", "generating"))
        self._apply_border()
        self._render_question()

    def _paint_part(self, nivel):
        # El punto del participante se ilumina (dorado) cuando llega su audio.
        encendido = int(nivel) > 8
        if encendido != self._part_last:
            col = T.GOLD if encendido else T.INTERVIEWER_DOT
            self.part_dot.setStyleSheet(f"background: {col}; border-radius: 4px;")
            self._part_last = encendido

    # ---------------- API publica
    def set_level(self, v):
        self.bars.set_level(v)
        self._paint_part(v)

    def set_mic_level(self, v):
        pass  # el medidor de micro se retiro de la cabecera

    def set_listening(self, on):
        self.set_state("listening" if on else "idle")

    def set_latency(self, ms):
        """Muestra la latencia de la última transcripción, con color por rapidez."""
        if ms < 600:
            col = "#3ddc84"          # verde: muy rápido
        elif ms < 1500:
            col = "#e7b93a"          # ámbar
        else:
            col = "#e0554b"          # rojo: lento
        txt = f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"
        self.lat.setText(txt)
        self.lat.setStyleSheet(
            f"color: {col}; font-family: {T.MONO_STACK}; background: "
            f"rgba(243,234,212,0.05); border-radius: 8px; padding: 2px 7px;")
        self.lat.setVisible(True)

    def clear_latency(self):
        self.lat.setVisible(False)
        self.lat.setText("")

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
        """Empieza una sugerencia nueva: se abre otra burbuja, no se borra nada."""
        self._raw = ""
        self._auto["feed"].anotar()
        self._burbuja_resp = self._nueva_burbuja("tu")
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
            QtCore.QTimer.singleShot(INTERVALO_REPINTADO, self._repintar)

    def _repintar(self):
        self._repintado_pendiente = False
        if self._burbuja_resp is None:
            self._burbuja_resp = self._nueva_burbuja("tu")
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
        self._añadir(ShotThumb(pixmap), "der")
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    def set_hint(self, texto):
        """Nota discreta en el hilo (arranque, avisos)."""
        lab = QtWidgets.QLabel(texto)
        lab.setWordWrap(True)
        lab.setStyleSheet(
            f"color: {T.TEXT_FAINT}; font-size: 13px; background: transparent;")
        self._auto["feed"].anotar()
        self._añadir(lab, "izq")
        QtCore.QTimer.singleShot(0, self._auto["feed"].restaurar)

    def limpiar_hilo(self):
        """Vacia la conversacion (al empezar una reunion nueva)."""
        self._burbuja_viva = None
        self._burbuja_resp = None
        self._burbujas = []
        self._raw = ""
        while self.feed.count() > 1:
            it = self.feed.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

    def show_skip(self, texto="No question — Alt+5 to answer"):
        """Deja claro que no se esta esperando ninguna respuesta."""
        self.skip_pill.show_text(texto)

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
        return [(auto.zona(), nombre) for nombre, auto in self._auto.items()
                if auto.zona()]

    def scroll_zone(self, nombre, muescas):
        """Mueve la zona indicada. muescas positivas = hacia arriba."""
        auto = self._auto.get(nombre)
        if auto is not None:
            auto.rueda(muescas)

    # Estilo del `codigo en linea` dentro de un parrafo.
    _CODE_INLINE = (f"font-family: {T.MONO_STACK}; background: rgba(0,0,0,0.35); "
                    f"color: {T.GOLD_LIGHT};")

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
            f'<tr><td style="color:{T.GOLD};padding-right:7px;">•</td>'
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

class CollapsedButton(QtWidgets.QWidget, _Draggable):
    """Pildora 'Show overlay' que aparece cuando el overlay esta oculto."""
    clicked = QtCore.Signal()

    def __init__(self):
        super().__init__()
        _frameless(self)
        self._init_drag()
        self.setStyleSheet(f"background: {T.PANEL_TOP};")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        b = ClickFrame()
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
        punto.setStyleSheet(f"background: {T.GOLD}; border-radius: 4px;")
        lay.addWidget(punto)
        lab = QtWidgets.QLabel("Show overlay")
        lab.setStyleSheet(f"color: {T.TEXT}; font-size: 13px; background: transparent;")
        lay.addWidget(lab)
        lay.addWidget(_keys("Alt", "1"))
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
