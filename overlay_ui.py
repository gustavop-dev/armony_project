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
import theme as T


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
        self.setCursor(QtCore.Qt.PointingHandCursor)

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

        # Orden de izquierda a derecha: 4 (meeting), 3 (generate), 2 (screenshot), 1 (show/hide).

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
        self.card = QtWidgets.QFrame()
        self.card.setObjectName("panel")
        self.card.setStyleSheet(f"""
            QFrame#panel {{
                background: {T.PANEL_BODY};
                border: 1px solid {T.PANEL_BORDER2};
                border-radius: {T.R_PANEL}px;
            }}
        """)
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
        """Zonas que responden al mouse: cabecera (mover), scroll y el agarre."""
        return [self._drag_header, self.scroll.verticalScrollBar(), self.resize_grip]

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

    # ---------------- cuerpo
    def _body(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        w.setMinimumHeight(240)

        # --- izquierda: entrevistador ---
        izq = QtWidgets.QWidget()
        il = QtWidgets.QVBoxLayout(izq)
        il.setContentsMargins(18, 16, 18, 16)
        il.setSpacing(12)
        cab = QtWidgets.QHBoxLayout()
        cab.setSpacing(8)
        # Punto que se ilumina cuando llega audio de la reunion (el participante habla).
        self.part_dot = QtWidgets.QLabel()
        self.part_dot.setFixedSize(8, 8)
        cab.addWidget(self.part_dot)
        self._paint_part(0)
        cab.addWidget(_tracked("Participant", 12, QtGui.QFont.DemiBold, T.TEXT_MUTED, 0))
        cab.addStretch()
        il.addLayout(cab)

        self.lbl_question = QtWidgets.QLabel("")
        self.lbl_question.setWordWrap(True)
        self.lbl_question.setTextFormat(QtCore.Qt.RichText)
        self.lbl_question.setAlignment(QtCore.Qt.AlignTop)
        self.lbl_question.setStyleSheet("background: transparent;")
        il.addWidget(self.lbl_question)
        # Pegada al texto, no al fondo de la columna: se lee como una nota de lo
        # que se acaba de transcribir.
        self.skip_pill = SkipPill()
        il.addWidget(self.skip_pill, 0, QtCore.Qt.AlignLeft)
        il.addStretch(1)
        izq.setStyleSheet(f"border-right: 1px solid {T.DIVIDER_FAINT};")
        lay.addWidget(izq, 35)          # participante: columna mas estrecha

        # --- derecha: respuesta sugerida ---
        der = QtWidgets.QWidget()
        dl = QtWidgets.QVBoxLayout(der)
        dl.setContentsMargins(18, 16, 18, 16)
        dl.setSpacing(12)
        cab2 = QtWidgets.QHBoxLayout()
        cab2.setSpacing(8)
        cab2.addWidget(icons.label("sparkles", T.GOLD, 15))
        cab2.addWidget(_tracked("Suggested answer", 12, QtGui.QFont.Bold, T.GOLD, 0.3))
        cab2.addStretch()
        dl.addLayout(cab2)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        cont = QtWidgets.QWidget()
        cont.setStyleSheet("background: transparent;")
        self.answer_lay = QtWidgets.QVBoxLayout(cont)
        self.answer_lay.setContentsMargins(0, 0, 0, 0)
        self.answer_lay.setSpacing(11)
        self.answer_lay.addStretch()
        self.scroll.setWidget(cont)
        dl.addWidget(self.scroll, 1)
        lay.addWidget(der, 65)          # respuesta: columna mas ancha (mas sitio para capturas)

        self.set_hint("Start the meeting to capture the participant "
                      "and draft a suggested answer.")
        return w

    # ---------------- estado visual (borde + animacion)
    def _apply_border(self):
        if self._state == "generating":
            color, width = T.GOLD, 2
        elif self._state == "listening":
            a = 0.30 + 0.35 * (0.5 + 0.5 * math.sin(self._anim_phase * 0.22))
            color, width = f"rgba(242,201,76,{a:.2f})", 1
        else:  # idle
            color, width = "rgba(210,220,223,0.14)", 1
        self.card.setStyleSheet(
            f"QFrame#panel {{ background: {T.PANEL_BODY}; "
            f"border: {width}px solid {color}; border-radius: {T.R_PANEL}px; }}")

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
        caret = (self._caret_on and self._state == "listening"
                 and bool(self._question_text))
        cursor = f'<span style="color:{T.GOLD};">&#9611;</span>' if caret else ""
        self.lbl_question.setText(
            f'<div style="line-height:155%; color:{T.TEXT_BODY}; font-size:17px;">'
            f'{html.escape(self._question_text)}{cursor}</div>')

    def set_question(self, texto, caret=False):
        self._question_text = texto
        self._render_question()

    def show_skip(self, texto="No question — Alt+5 to answer"):
        """Deja claro que no se esta esperando ninguna respuesta."""
        self.skip_pill.show_text(texto)

    def hide_skip(self):
        self.skip_pill.hide_pill()

    def clear_answer(self):
        self._raw = ""
        self._render([])

    def append_answer(self, delta):
        self._raw += delta
        self._render(parse_sections(self._raw))

    def set_hint(self, texto):
        self._raw = ""
        self._clear_layout()
        lab = QtWidgets.QLabel(texto)
        lab.setWordWrap(True)
        lab.setStyleSheet(
            f"color: {T.TEXT_FAINT}; font-size: 14px; background: transparent;")
        self.answer_lay.insertWidget(0, lab)

    def _clear_layout(self):
        while self.answer_lay.count() > 1:
            it = self.answer_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _render(self, secciones):
        self._clear_layout()
        for i, (etiqueta, texto) in enumerate(secciones):
            bloque = QtWidgets.QWidget()
            bl = QtWidgets.QVBoxLayout(bloque)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(3)
            bloque.setStyleSheet("background: transparent;")
            lab = _tracked(etiqueta, 11, QtGui.QFont.Bold, T.GOLD_LABEL, 1.0, upper=True)
            bl.addWidget(lab)
            cuerpo = QtWidgets.QLabel(
                f'<div style="line-height:150%; color:{T.ANSWER_TEXT}; font-size:14px;">'
                f'{html.escape(texto)}</div>')
            cuerpo.setWordWrap(True)
            cuerpo.setTextFormat(QtCore.Qt.RichText)
            cuerpo.setStyleSheet("background: transparent;")
            bl.addWidget(cuerpo)
            self.answer_lay.insertWidget(i, bloque)
        QtCore.QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))


def parse_sections(raw):
    """Convierte la respuesta del modelo en secciones (etiqueta, texto).

    Formato esperado: lineas '## Etiqueta' seguidas del texto de la seccion.
    Si el modelo no usa secciones, devuelve una sola bajo 'Respuesta'.
    """
    secciones, etiqueta, buf = [], None, []
    for linea in raw.splitlines():
        if linea.startswith("## "):
            if etiqueta:
                secciones.append((etiqueta, " ".join(buf).strip()))
            etiqueta, buf = linea[3:].strip(), []
        elif linea.strip():
            buf.append(linea.strip())
    if etiqueta:
        secciones.append((etiqueta, " ".join(buf).strip()))
    if not secciones and raw.strip():
        secciones = [("Respuesta", raw.strip())]
    return [(e, t) for e, t in secciones if t]


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


class FlashOverlay(QtWidgets.QWidget):
    """Destello blanco al capturar pantalla."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowTransparentForInput
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: white;")
        self._anim = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(500)
        self._anim.setStartValue(0.9)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.hide)

    def flash(self, geo):
        self.setGeometry(geo)
        self.setWindowOpacity(0.9)
        self.show()
        self._anim.stop()
        self._anim.start()
