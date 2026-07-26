"""Ventana de configuracion de Cue. (segun 'Meeting Coach Settings.dc.html').

Vista completa con barra de titulo, sidebar de secciones, campos por tipo
(texto, select, toggle, slider, textarea) y la seccion Contexts (lista + editor).
Reemplaza al overlay mientras esta abierta.
"""
import os

from PySide6 import QtCore, QtGui, QtWidgets

import config as cfg_mod
import contexts as ctx_mod
import icons
import theme as T

# --- colores propios del diseno de settings ---
WIN_BG   = "#1c1a14"
BAR_BG   = "#232019"
SIDE_BG  = "#211e18"
TXT_BR   = "#f3ead4"
TXT_MU   = "#b8af9a"
TXT_FA   = "#8f8674"
TXT_LB   = "#ece3cd"
GOLD     = "#f2c94c"
GOLD_LT  = "#f7e39a"
INK      = "#2a2410"
INPUT_BG = "rgba(0,0,0,0.28)"
INPUT_BD = "rgba(243,234,212,0.14)"
DIV      = "rgba(243,234,212,0.07)"

SANS = T.SANS_STACK
MONO = T.MONO_STACK


class ToggleSwitch(QtWidgets.QAbstractButton):
    """Interruptor pista+perilla del diseno."""

    def __init__(self, checked=False, small=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self._w, self._h = (34, 20) if small else (42, 24)
        self._k = 15 if small else 18
        self.setFixedSize(self._w, self._h)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        on = self.isChecked()
        p.setBrush(QtGui.QColor(GOLD) if on else QtGui.QColor(243, 234, 212, 41))
        p.drawRoundedRect(0, 0, self._w, self._h, self._h / 2, self._h / 2)
        p.setBrush(QtGui.QColor(INK) if on else QtGui.QColor("#efe7d4"))
        x = (self._w - self._k - 3) if on else 3
        p.drawEllipse(QtCore.QRectF(x, 3, self._k, self._k))
        p.end()


class Dot(QtWidgets.QWidget):
    """Circulo de estado (pintado, siempre redondo)."""

    def __init__(self, color="#28c840", d=8):
        super().__init__()
        self._c = QtGui.QColor(color)
        self._d = d
        self.setFixedSize(d, d)

    def set_color(self, color):
        self._c = QtGui.QColor(color)
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(self._c)
        p.drawEllipse(0, 0, self._d, self._d)
        p.end()


class Segmented(QtWidgets.QWidget):
    """Control segmentado (p. ej. ES | EN | Ambos)."""
    changed = QtCore.Signal(str)

    def __init__(self, options, current, small=False):
        super().__init__()
        self._options = options
        self._current = current
        self._btns = {}
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        pad = "4px 10px" if small else "6px 14px"
        for i, (val, label) in enumerate(options):
            b = QtWidgets.QPushButton(label)
            b.setCursor(QtCore.Qt.PointingHandCursor)
            fs = "11px" if small else "12px"
            b.setStyleSheet(self._qss(val == current, pad, fs))
            b.clicked.connect(lambda _c=False, v=val: self._pick(v))
            self._btns[val] = (b, pad, fs)
            lay.addWidget(b)

    def _qss(self, on, pad, fs):
        if on:
            return (f"QPushButton {{ border: 1px solid rgba(242,201,76,0.5); background: rgba(242,201,76,0.16); "
                    f"color: #f7e39a; font-size: {fs}; font-weight: 600; padding: {pad}; border-radius: 8px; }}")
        return (f"QPushButton {{ border: 1px solid rgba(243,234,212,0.12); background: transparent; "
                f"color: #b8af9a; font-size: {fs}; padding: {pad}; border-radius: 8px; }} "
                f"QPushButton:hover {{ background: rgba(243,234,212,0.06); }}")

    def _pick(self, val):
        if val == self._current:
            return
        self._current = val
        for v, (b, pad, fs) in self._btns.items():
            b.setStyleSheet(self._qss(v == val, pad, fs))
        self.changed.emit(val)

    def value(self):
        return self._current


class BilingualPrompt(QtWidgets.QWidget):
    """Editor del prompt del coach con conmutador ES | EN (uno por idioma)."""

    def __init__(self, es, en, on_change):
        super().__init__()
        self._texts = {"es": es or "", "en": en or ""}
        self._on_change = on_change
        self._lang = "es"
        v = QtWidgets.QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(8)
        head = QtWidgets.QHBoxLayout()
        self._seg = Segmented([("es", "Español"), ("en", "English")], "es")
        self._seg.changed.connect(self._switch)
        head.addWidget(self._seg); head.addStretch()
        v.addLayout(head)
        self._edit = QtWidgets.QPlainTextEdit(self._texts["es"])
        self._edit.setFixedSize(460, 150)
        self._edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {INPUT_BG}; border: 1px solid {INPUT_BD}; border-radius: 10px; "
            f"padding: 10px 13px; color: #f0e8d6; font-size: 13px; }} "
            f"QPlainTextEdit:focus {{ border: 1px solid rgba(242,201,76,0.55); }}")
        self._edit.textChanged.connect(self._on_text)
        v.addWidget(self._edit)

    def _switch(self, lang):
        self._texts[self._lang] = self._edit.toPlainText()
        self._lang = lang
        self._edit.blockSignals(True)
        self._edit.setPlainText(self._texts[lang])
        self._edit.blockSignals(False)

    def _on_text(self):
        self._texts[self._lang] = self._edit.toPlainText()
        self._on_change(self._lang, self._texts[self._lang])


def _schema():
    """Definicion de secciones y campos (espeja el diseno)."""
    return [
        ("connection", "bolt", "Conexión",
         "Credenciales y modelos que alimentan la transcripción y las respuestas.", [
            dict(key="llm_provider", label="Proveedor de respuestas", type="select",
                 hint="Quién redacta las sugerencias. Cada proveedor usa su propia "
                      "clave y su propio modelo, elegidos abajo.",
                 options=[("anthropic", "Anthropic (Claude)"),
                          ("openai", "OpenAI (GPT)")]),
            dict(key="anthropic_api_key", label="API key de Anthropic", type="text",
                 secret=True, placeholder="sk-ant-…",
                 hint="Solo si el proveedor es Anthropic."),
            dict(key="llm_model", label="Modelo de Anthropic", type="select",
                 hint="Haiku = más rápido; Opus = más inteligente.",
                 options=[("claude-haiku-4-5", "Claude Haiku 4.5"),
                          ("claude-opus-4-8", "Claude Opus 4.8"),
                          ("claude-sonnet-5", "Claude Sonnet 5")]),
            dict(key="openai_api_key", label="API key de OpenAI", type="text",
                 secret=True, placeholder="sk-proj-…",
                 hint="Solo si el proveedor es OpenAI."),
            dict(key="openai_model", label="Modelo de OpenAI", type="select",
                 hint="nano = el más rápido; mini = equilibrado; el grande da "
                      "mejores respuestas pero tarda más.",
                 options=[("gpt-5.4-nano", "GPT-5.4 nano — el más rápido"),
                          ("gpt-5.4-mini", "GPT-5.4 mini — equilibrado (recomendado)"),
                          ("gpt-5.4", "GPT-5.4 — más calidad, más lento")]),
            dict(key="assemblyai_api_key", label="API key de AssemblyAI", type="text",
                 secret=True, placeholder="…",
                 hint="Transcripción en vivo en la nube. Sin ella solo funciona "
                      "el modo offline."),
            dict(key="language", label="Idioma", type="select",
                 hint="Idioma del reconocimiento de voz. Auto detecta solo y "
                      "admite cambios de idioma a mitad de frase.",
                 options=[("es", "Español"), ("en", "English"), ("auto", "Auto")]),
            dict(key="end_of_turn_threshold", label="Confianza de fin de turno",
                 type="number", min=0.1, max=0.9, step=0.05, unit="",
                 hint="Cuánta seguridad exige para dar por terminado el turno. "
                      "Bajo = responde antes; alto = espera más y se corta menos."),
         ]),
        ("offline", "chip", "Modo offline",
         "Transcripción local con Whisper: sin internet y sin que el audio salga "
         "del equipo. A cambio no hay texto en vivo y hay más retardo.", [
            dict(key="offline_mode", label="Activar modo offline", type="toggle",
                 hint="Apagado: transcribe AssemblyAI en vivo. Encendido: Whisper "
                      "local en este equipo."),
            dict(key="whisper_size", label="Tamaño Whisper", type="select",
                 hint="Solo en modo offline. En GPU, 'small' mejora bastante la "
                      "transcripción y sigue siendo rápido (recomendado).",
                 options=[("tiny", "1 · tiny — el más rápido, menos preciso"),
                          ("base", "2 · base — equilibrado"),
                          ("small", "3 · small — preciso (recomendado)"),
                          ("medium", "4 · medium — máxima precisión, más lento")]),
            dict(key="whisper_device", label="Dispositivo STT", type="select",
                 hint="Solo en modo offline. cuda = GPU NVIDIA · cpu = procesador "
                      "· auto = detecta.",
                 options=[("auto", "auto"), ("cpu", "cpu"), ("cuda", "cuda")]),
         ]),
        ("overlay", "window", "Overlay",
         "Cómo se ve y se comporta la ventana flotante sobre tus reuniones.", [
            dict(key="invisible_on_share", label="Invisible al compartir pantalla",
                 type="toggle", hint="Excluye el overlay de cualquier captura o screen-share."),
            dict(key="test_mode", label="Modo prueba", type="toggle",
                 hint="Arranca sin API key: solo audio + transcripción."),
            dict(key="window_opacity", label="Opacidad", type="number",
                 min=0.15, max=1.0, step=0.05, unit="",
                 hint="Transparencia de las ventanas. Bajo = se ve más el fondo."),
         ]),
        ("audio", "microphone", "Sensibilidad de audio",
         "Cómo se capta y limpia el audio antes de detectar voz.", [
            dict(key="gain_system", label="Ganancia reunión", type="number",
                 min=0.5, max=10, step=0.5, unit="x",
                 hint="Amplifica el audio del sistema antes de medir nivel."),
            dict(key="gain_mic", label="Ganancia micrófono", type="number",
                 min=0.5, max=10, step=0.5, unit="x",
                 hint="Amplifica tu micro (y también el ruido de fondo)."),
            dict(key="speech_threshold", label="Umbral de voz", type="number",
                 min=0.001, max=0.1, step=0.002, unit="",
                 hint="Energía mínima para considerar que hay voz. Menor = más sensible."),
            dict(key="transcribe_mic", label="Transcribir también mi voz", type="toggle",
                 hint="Solo en modo offline. Añade tus intervenciones al contexto; "
                      "nunca dispara una sugerencia sola."),
            dict(key="mic_echo_gate", label="Anti-eco del micrófono", type="toggle",
                 hint="Ignora el micro mientras suena la reunión. Con auriculares es indiferente."),
            dict(key="auto_normalize", label="Normalizar cada frase", type="toggle",
                 hint="Solo en modo offline: lleva cada frase al nivel óptimo antes "
                      "de Whisper."),
         ]),
        ("phrases", "scissors", "Detección de frases",
         "Cuándo se da una frase por terminada y se dispara la respuesta.", [
            dict(key="silence_hang", label="Pausa de fin de turno", type="number",
                 min=0.3, max=2, step=0.1, unit=" s",
                 hint="Pausa que espera antes de responder. Con la transcripción en "
                      "vivo agrupa las frases seguidas de una misma intervención."),
            dict(key="max_utterance", label="Corte de monólogo largo", type="number",
                 min=3, max=20, step=1, unit=" s",
                 hint="Solo en modo offline. Corte de seguridad en monólogos; esos "
                      "fragmentos NO disparan respuesta."),
         ]),
        ("coach", "chat", "Coach",
         "Cómo se comporta la IA. Un prompt por idioma; el qué sabe vive en Contexts.", [
            dict(key="system_prompt", label="Prompt del coach (por idioma)",
                 type="prompt_bilingual",
                 hint="ES y EN por separado — cada instrucción en su idioma. "
                      "Define tono y reglas, no qué sabe."),
            dict(key="max_tokens", label="Longitud máx. de respuesta", type="number",
                 min=100, max=1000, step=50, unit=" tok",
                 hint="Cuánto puede extenderse la respuesta de la IA."),
         ]),
        ("contexts", "puzzle", "Contexts",
         "Documentos markdown que la IA lee al iniciar. Activa los que apliquen "
         "para cada reunión — QUÉ sabe, no cómo responde.", None),
    ]


class NavItem(QtWidgets.QFrame):
    """Fila del sidebar (contenedor fiable, a diferencia de QPushButton con layout)."""
    clicked = QtCore.Signal()

    def __init__(self, icon, label):
        super().__init__()
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._iconname = icon
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(11, 9, 11, 9)
        lay.setSpacing(10)
        self._icon = icons.label(icon, TXT_MU, 17)
        lay.addWidget(self._icon)
        self._lab = QtWidgets.QLabel(label)
        lf = self._lab.font(); lf.setPixelSize(14); self._lab.setFont(lf)
        lay.addWidget(self._lab, 1)
        self._badge = QtWidgets.QLabel("")
        self._badge.setStyleSheet(
            f"color: {INK}; background: {GOLD}; border-radius: 9px; padding: 1px 7px; "
            f"font-size: 11px; font-weight: 700;")
        self._badge.setVisible(False)
        lay.addWidget(self._badge)
        self.set_active(False)

    def set_active(self, on):
        self.setStyleSheet(
            f"NavItem {{ border: none; border-radius: 10px; "
            f"background: {'rgba(242,201,76,0.14)' if on else 'transparent'}; }} "
            f"QLabel {{ background: transparent; border: none; }}")
        col = GOLD_LT if on else TXT_MU
        self._lab.setStyleSheet(f"color: {col}; background: transparent;")
        self._icon.setPixmap(icons.pixmap(self._iconname, col, 17))

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()


class SettingsWindow(QtWidgets.QWidget):
    closed = QtCore.Signal()      # volver al overlay (mantiene la app viva)
    closeApp = QtCore.Signal()    # cerrar el programa entero (boton X)
    saved = QtCore.Signal()       # se emite tras guardar

    def __init__(self, cfg):
        super().__init__()
        self.cfg = dict(cfg)
        self.values = dict(cfg)
        self.contexts = ctx_mod.list_contexts()
        self.sel_id = self.contexts[0]["id"] if self.contexts else None
        self._ctx_filter = "all"      # all | es | en (filtro de la lista)
        self._dirty = False
        self._error = None
        self._nav_btns = {}
        self._active = "connection"
        self._drag = None
        self._chevron = icons.save_png(
            "chevron_down", TXT_MU, 24,
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "_chevron.png"))

        # Ventana (no Tool) para que tenga entrada en la barra de tareas y se pueda minimizar.
        self.setWindowTitle("Armony.")
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window)
        self._build()

    # ---------------------------------------------------- estructura
    def _build(self):
        scr = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = min(1040, int(scr.width() * 0.92))
        h = min(720, int(scr.height() * 0.9))
        self.resize(w, h)
        self.move(scr.x() + (scr.width() - w) // 2, scr.y() + (scr.height() - h) // 2)
        self.setStyleSheet(f"QWidget#root {{ background: {WIN_BG}; border-radius: 14px; }}")

        root = QtWidgets.QWidget(self); root.setObjectName("root")
        outer = QtWidgets.QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)
        col = QtWidgets.QVBoxLayout(root); col.setContentsMargins(0, 0, 0, 0); col.setSpacing(0)

        col.addWidget(self._titlebar())
        mid = QtWidgets.QHBoxLayout(); mid.setContentsMargins(0, 0, 0, 0); mid.setSpacing(0)
        mid.addWidget(self._sidebar())
        self.content = QtWidgets.QScrollArea()
        self.content.setWidgetResizable(True)
        self.content.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.content.setStyleSheet(f"QScrollArea {{ background: {WIN_BG}; border: none; }}")
        mid.addWidget(self.content, 1)
        col.addLayout(mid, 1)
        col.addWidget(self._footer())

        self._show_section("connection")

    def _titlebar(self):
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(52)
        bar.setStyleSheet(f"background: {BAR_BG};")
        lay = QtWidgets.QHBoxLayout(bar); lay.setContentsMargins(18, 0, 12, 0); lay.setSpacing(10)
        # marca Armony. (Arm dorado, resto blanco)
        brand = QtWidgets.QLabel(
            f'<span style="color:{GOLD};font-weight:700;">Arm</span>'
            f'<span style="color:#ffffff;font-weight:700;">ony.</span>'
            f'<span style="color:#7c7565;"> &nbsp;·&nbsp; </span>'
            f'<span style="color:{TXT_MU};">Settings</span>')
        f = brand.font(); f.setPixelSize(14); brand.setFont(f)
        brand.setStyleSheet("background: transparent;")
        lay.addWidget(brand)
        lay.addStretch()
        # botones de ventana: back (volver al overlay), minimizar, cerrar app
        lay.addWidget(self._win_btn("arrow-left", self._cancel, "Volver a la reunión"))
        lay.addWidget(self._win_btn("minus", self.showMinimized, "Minimizar"))
        lay.addWidget(self._win_btn("x", lambda: self.closeApp.emit(), "Cerrar Armony.", danger=True))
        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        return bar

    def _win_btn(self, icon, cb, tip, danger=False):
        b = QtWidgets.QPushButton()
        b.setFixedSize(30, 30)
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.setToolTip(tip)
        hover = "rgba(217,74,61,0.9)" if danger else "rgba(243,234,212,0.12)"
        b.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: 8px; background: transparent; }} "
            f"QPushButton:hover {{ background: {hover}; }}")
        b.setIcon(QtGui.QIcon(icons.pixmap(icon, TXT_MU, 15)))
        b.clicked.connect(lambda: cb())
        return b

    def _bar_press(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _bar_move(self, e):
        if self._drag is not None and e.buttons() & QtCore.Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def _sidebar(self):
        side = QtWidgets.QWidget()
        side.setFixedWidth(236)
        side.setStyleSheet(f"background: {SIDE_BG}; border-right: 1px solid rgba(255,255,255,0.05);")
        lay = QtWidgets.QVBoxLayout(side); lay.setContentsMargins(12, 14, 12, 14); lay.setSpacing(3)

        # Volver a la reunion (vista overlay)
        goto = NavItem("arrow-left", "Go to the meeting")
        goto.clicked.connect(self._cancel)
        lay.addWidget(goto)
        sep = QtWidgets.QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255,255,255,0.06); margin: 6px 4px;")
        lay.addWidget(sep)

        for sid, icon, label, _desc, _fields in _schema():
            item = NavItem(icon, label)
            item.clicked.connect(lambda s=sid: self._show_section(s))
            self._nav_btns[sid] = item
            lay.addWidget(item)
        lay.addStretch()
        nota = QtWidgets.QLabel(
            "Los cambios de audio y frases se aplican al iniciar la próxima reunión.")
        nota.setWordWrap(True)
        nota.setStyleSheet(
            f"color: {TXT_FA}; font-size: 11px; background: rgba(243,234,212,0.04); "
            f"border: 1px solid rgba(243,234,212,0.08); border-radius: 10px; padding: 10px 12px;")
        lay.addWidget(nota)
        return side

    def _footer(self):
        bar = QtWidgets.QWidget()
        bar.setStyleSheet(f"background: {BAR_BG};")   # sin linea encima (minimalista)
        lay = QtWidgets.QHBoxLayout(bar); lay.setContentsMargins(22, 14, 22, 14)
        self.saved_dot = Dot("#28c840", 8)
        self.saved_lbl = QtWidgets.QLabel("Todo guardado")
        self.saved_lbl.setStyleSheet(f"color: {TXT_FA}; font-size: 12px; background: transparent;")
        lay.addWidget(self.saved_dot); lay.addSpacing(7); lay.addWidget(self.saved_lbl)
        lay.addStretch()
        cancel = QtWidgets.QPushButton("Cancelar")
        cancel.setCursor(QtCore.Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{ padding: 10px 18px; border-radius: 10px; border: 1px solid {INPUT_BD}; "
            f"background: transparent; color: #cec5b0; font-size: 13px; }}"
            f"QPushButton:hover {{ background: rgba(243,234,212,0.06); }}")
        cancel.clicked.connect(self._cancel)
        save = QtWidgets.QPushButton("Guardar")
        save.setCursor(QtCore.Qt.PointingHandCursor)
        save.setStyleSheet(
            f"QPushButton {{ padding: 10px 22px; border-radius: 10px; border: none; "
            f"background: {GOLD}; color: {INK}; font-size: 13px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {GOLD_LT}; }}")
        save.clicked.connect(self._save)
        lay.addWidget(cancel); lay.addSpacing(10); lay.addWidget(save)
        self._paint_saved()
        return bar

    # ---------------------------------------------------- navegacion
    def _show_section(self, sid):
        self._active = sid
        for k, item in self._nav_btns.items():
            item.set_active(k == sid)
        self._refresh_badges()
        # construir el contenido
        for sid2, _ic, label, desc, fields in _schema():
            if sid2 == sid:
                if sid == "contexts":
                    self.content.setWidget(self._contexts_view(label, desc))
                else:
                    self.content.setWidget(self._fields_view(label, desc, fields))
                break

    def _refresh_badges(self):
        n = sum(1 for c in self.contexts if c["active"])
        b = self._nav_btns["contexts"]._badge
        b.setText(str(n)); b.setVisible(n > 0)

    def _heading(self, label, desc):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(5)
        h = QtWidgets.QLabel(label)
        hf = h.font(); hf.setPixelSize(21); hf.setWeight(QtGui.QFont.Bold); h.setFont(hf)
        h.setStyleSheet(f"color: {TXT_BR}; background: transparent;")
        d = QtWidgets.QLabel(desc); d.setWordWrap(True); d.setMaximumWidth(560)
        d.setStyleSheet(f"color: #a89f8a; font-size: 13px; background: transparent;")
        v.addWidget(h); v.addWidget(d)
        return w

    # ---------------------------------------------------- vista de campos
    def _fields_view(self, label, desc, fields):
        page = QtWidgets.QWidget()
        page.setStyleSheet("background: transparent;")
        v = QtWidgets.QVBoxLayout(page); v.setContentsMargins(30, 26, 30, 30); v.setSpacing(0)
        v.addWidget(self._heading(label, desc))
        v.addSpacing(16)
        for f in fields:
            v.addWidget(self._field_row(f))
        v.addStretch()
        return page

    def _field_row(self, f):
        row = QtWidgets.QWidget()
        row.setStyleSheet(f"border-bottom: 1px solid {DIV};")
        lay = QtWidgets.QHBoxLayout(row); lay.setContentsMargins(0, 16, 0, 16); lay.setSpacing(24)
        # izquierda: label + key + hint
        left = QtWidgets.QWidget(); left.setMaximumWidth(340)
        lv = QtWidgets.QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(3)
        top = QtWidgets.QHBoxLayout(); top.setSpacing(8)
        name = QtWidgets.QLabel(f["label"])
        nf = name.font(); nf.setPixelSize(14); nf.setWeight(QtGui.QFont.DemiBold); name.setFont(nf)
        name.setStyleSheet(f"color: {TXT_LB}; background: transparent;")
        key = QtWidgets.QLabel(f["key"])
        key.setStyleSheet(
            f"color: #8a826f; background: rgba(243,234,212,0.05); border-radius: 5px; "
            f"padding: 1px 6px; font-family: {MONO}; font-size: 10px;")
        top.addWidget(name); top.addWidget(key); top.addStretch()
        lv.addLayout(top)
        hint = QtWidgets.QLabel(f["hint"]); hint.setWordWrap(True)
        hint.setStyleSheet(f"color: #948b78; font-size: 12px; background: transparent;")
        lv.addWidget(hint)
        lay.addWidget(left, 1)
        # derecha: control
        lay.addWidget(self._control(f), 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        if f["type"] in ("textarea", "prompt_bilingual"):
            lay.setAlignment(left, QtCore.Qt.AlignTop)
        return row

    def _control(self, f):
        key, typ = f["key"], f["type"]
        val = self.values.get(key)
        if typ == "text":
            e = QtWidgets.QLineEdit(str(val or ""))
            if f.get("secret"):
                e.setEchoMode(QtWidgets.QLineEdit.Password)
            e.setPlaceholderText(f.get("placeholder", ""))
            e.setFixedWidth(300)
            e.setStyleSheet(self._input_qss(mono=True))
            e.textChanged.connect(lambda _t, e=e, k=key: self._set_value(k, e.text().strip()))
            return e
        if typ == "select":
            c = QtWidgets.QComboBox(); c.setFixedWidth(240)
            for v, lab in f["options"]:
                c.addItem(lab, v)
            i = c.findData(val)
            if i >= 0:
                c.setCurrentIndex(i)
            c.setStyleSheet(self._combo_qss())
            c.currentIndexChanged.connect(lambda _i, c=c, k=key: self._set_value(k, c.currentData()))
            return c
        if typ == "toggle":
            sw = ToggleSwitch(bool(val))
            sw.toggled.connect(lambda on, k=key: self._set_value(k, on))
            return sw
        if typ == "number":
            return self._number_control(f, val)
        if typ == "textarea":
            t = QtWidgets.QPlainTextEdit(str(val or ""))
            t.setFixedSize(460, 150)
            t.setStyleSheet(self._input_qss())
            t.textChanged.connect(lambda t=t, k=key: self._set_value(k, t.toPlainText()))
            return t
        if typ == "prompt_bilingual":
            return BilingualPrompt(
                self.values.get("system_prompt_es", ""),
                self.values.get("system_prompt_en", ""),
                lambda lang, txt: self._set_value(f"system_prompt_{lang}", txt))
        return QtWidgets.QWidget()

    def _set_value(self, key, v):
        self.values[key] = v
        self._dirty_mark()

    def _number_control(self, f, val):
        wrap = QtWidgets.QWidget(); wrap.setFixedWidth(300)
        lay = QtWidgets.QHBoxLayout(wrap); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)
        mn, mx, st = f["min"], f["max"], f["step"]
        steps = int(round((mx - mn) / st))
        s = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        s.setRange(0, steps)
        s.setValue(int(round((float(val) - mn) / st)))
        s.setStyleSheet(self._slider_qss())
        disp = QtWidgets.QLabel()
        disp.setMinimumWidth(62); disp.setAlignment(QtCore.Qt.AlignRight)
        disp.setStyleSheet(f"color: {GOLD_LT}; font-family: {MONO}; font-size: 13px; background: transparent;")
        dec = 0 if st >= 1 else (1 if st >= 0.1 else (2 if st >= 0.01 else 3))
        unit = f.get("unit", "")

        def real():
            return round(mn + s.value() * st, 3)

        def upd():
            disp.setText(f"{real():.{dec}f}{unit}")

        s.valueChanged.connect(upd)
        s.valueChanged.connect(lambda _v, k=f["key"]: self._set_value(k, real()))
        upd()
        lay.addWidget(s, 1); lay.addWidget(disp)
        return wrap

    # ---------------------------------------------------- vista de contextos
    def _contexts_view(self, label, desc):
        page = QtWidgets.QWidget(); page.setStyleSheet("background: transparent;")
        v = QtWidgets.QVBoxLayout(page); v.setContentsMargins(30, 26, 30, 30); v.setSpacing(16)
        v.addWidget(self._heading(label, desc))
        grid = QtWidgets.QHBoxLayout(); grid.setSpacing(20)
        grid.addWidget(self._ctx_list(), 0)
        grid.addWidget(self._ctx_editor(), 1)
        v.addLayout(grid, 1)
        return page

    def _ctx_list(self):
        box = QtWidgets.QWidget(); box.setFixedWidth(288)
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)

        # boton "Nuevo contexto" (fijo arriba)
        add = QtWidgets.QPushButton()
        add.setCursor(QtCore.Qt.PointingHandCursor)
        add.setFixedHeight(42)
        al = QtWidgets.QHBoxLayout(add); al.setContentsMargins(11, 0, 11, 0); al.setSpacing(8)
        al.addStretch(); al.addWidget(icons.label("plus", GOLD_LT, 15))
        pl = QtWidgets.QLabel("Nuevo contexto")
        pl.setStyleSheet(f"color: {GOLD_LT}; font-weight: 600; font-size: 13px; background: transparent;")
        al.addWidget(pl); al.addStretch()
        add.setStyleSheet(
            f"QPushButton {{ border: 1px dashed rgba(242,201,76,0.4); background: rgba(242,201,76,0.08); "
            f"border-radius: 11px; }} QPushButton:hover {{ background: rgba(242,201,76,0.14); }} "
            f"QLabel {{ border: none; }}")
        add.clicked.connect(self._ctx_add)
        v.addWidget(add)

        # filtro por idioma
        filt = Segmented([("all", "Todos"), ("es", "ES"), ("en", "EN")],
                         self._ctx_filter, small=True)
        filt.changed.connect(self._ctx_set_filter)
        v.addWidget(filt)

        # tarjetas (scroll en el medio, para que nunca corten el boton ni el resumen)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")
        scroll.viewport().setStyleSheet("background: transparent;")
        inner = QtWidgets.QWidget(); inner.setStyleSheet("background: transparent;")
        iv = QtWidgets.QVBoxLayout(inner); iv.setContentsMargins(0, 0, 0, 0); iv.setSpacing(10)
        visibles = [c for c in self.contexts
                    if self._ctx_filter == "all" or c.get("lang", "both") in (self._ctx_filter, "both")]
        for c in visibles:
            iv.addWidget(self._ctx_card(c))
        if not visibles:
            vac = QtWidgets.QLabel("Sin contextos en este idioma.")
            vac.setStyleSheet(f"color: {TXT_FA}; font-size: 12px; padding: 8px;")
            iv.addWidget(vac)
        iv.addStretch()
        scroll.setWidget(inner)
        v.addWidget(scroll, 1)

        # resumen (fijo abajo)
        v.addWidget(self._ctx_summary())
        return box

    def _ctx_card(self, c):
        seld = c["id"] == self.sel_id
        card = QtWidgets.QFrame()
        card.setCursor(QtCore.Qt.PointingHandCursor)
        card.setStyleSheet(
            f"QFrame {{ border-radius: 12px; border: 1px solid "
            f"{'rgba(242,201,76,0.45)' if seld else 'rgba(243,234,212,0.09)'}; "
            f"background: {'rgba(242,201,76,0.09)' if seld else 'rgba(243,234,212,0.03)'}; }} "
            f"QLabel {{ border: none; background: transparent; }}")
        card.mousePressEvent = lambda e, cid=c["id"]: self._ctx_select(cid)
        v = QtWidgets.QVBoxLayout(card); v.setContentsMargins(14, 12, 14, 12); v.setSpacing(8)
        top = QtWidgets.QHBoxLayout(); top.setSpacing(8)
        nm = QtWidgets.QLabel(c["name"]); nm.setStyleSheet(f"color: #f0e8d6; font-weight: 600; font-size: 14px;")
        nf = nm.font(); nf.setPixelSize(14); nm.setFont(nf)
        top.addWidget(nm, 1)
        sw = ToggleSwitch(c["active"], small=True)
        sw.toggled.connect(lambda on, cid=c["id"]: self._ctx_toggle(cid, on))
        top.addWidget(sw)
        v.addLayout(top)
        bot = QtWidgets.QHBoxLayout(); bot.setSpacing(6)
        chip = QtWidgets.QLabel({"es": "ES", "en": "EN", "both": "ES·EN"}.get(c.get("lang", "both")))
        chip.setStyleSheet(
            f"color: {TXT_MU}; background: rgba(243,234,212,0.06); border-radius: 5px; "
            f"padding: 1px 6px; font-family: {MONO}; font-size: 10px;")
        bot.addWidget(chip)
        tok = QtWidgets.QLabel(f"~{ctx_mod.estimate_tokens(c['body'])} tok")
        tok.setStyleSheet(f"color: {TXT_FA}; font-family: {MONO}; font-size: 11px;")
        bot.addWidget(tok); bot.addStretch()
        dup = self._mini_btn("duplicate", "#b8af9a", lambda cid=c["id"]: self._ctx_dup(cid))
        dele = self._mini_btn("trash", "#e39a90", lambda cid=c["id"]: self._ctx_del(cid))
        bot.addWidget(dup); bot.addWidget(dele)
        v.addLayout(bot)
        return card

    def _mini_btn(self, icon, color, cb):
        b = QtWidgets.QPushButton(); b.setFixedSize(26, 26); b.setCursor(QtCore.Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{ border: 1px solid rgba(243,234,212,0.1); background: rgba(243,234,212,0.04); "
            f"border-radius: 7px; }} QPushButton:hover {{ background: rgba(243,234,212,0.12); }}")
        b.setIcon(QtGui.QIcon(icons.pixmap(icon, color, 13)))
        b.clicked.connect(lambda: cb())
        return b

    def _ctx_summary(self):
        box = QtWidgets.QFrame()
        box.setStyleSheet(
            f"QFrame {{ background: rgba(243,234,212,0.04); border: 1px solid rgba(243,234,212,0.08); "
            f"border-radius: 11px; }} QLabel {{ background: transparent; border: none; }}")
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(14, 12, 14, 12); v.setSpacing(8)
        n = sum(1 for c in self.contexts if c["active"])
        tot = sum(ctx_mod.estimate_tokens(c["body"]) for c in self.contexts if c["active"])
        top = QtWidgets.QHBoxLayout()
        a = QtWidgets.QLabel(f"{n} activos"); a.setStyleSheet(f"color: {TXT_MU}; font-size: 12px;")
        tk = QtWidgets.QLabel(f"~{tot} tok"); tk.setStyleSheet(f"color: {GOLD_LT}; font-family: {MONO}; font-size: 12px;")
        top.addWidget(a); top.addStretch(); top.addWidget(tk)
        v.addLayout(top)
        if tot > 4000:
            warn = QtWidgets.QLabel("⚠ Contexto grande: puede subir el costo y la latencia de la primera respuesta.")
            warn.setWordWrap(True); warn.setStyleSheet(f"color: #e7b93a; font-size: 11px;")
            v.addWidget(warn)
        chip = QtWidgets.QWidget()
        ch = QtWidgets.QHBoxLayout(chip); ch.setContentsMargins(10, 5, 10, 5); ch.setSpacing(6)
        ch.addWidget(icons.label("puzzle", GOLD, 12))
        cl = QtWidgets.QLabel(f"{n} contexts loaded")
        cl.setStyleSheet(f"color: {TXT_LB}; font-size: 11px;")
        ch.addWidget(cl)
        chip.setStyleSheet(
            "background: rgba(24,22,16,0.55); border: 1px solid rgba(242,201,76,0.3); border-radius: 12px;")
        row = QtWidgets.QHBoxLayout(); row.addWidget(chip); row.addStretch()
        v.addLayout(row)
        note = QtWidgets.QLabel("Chip que verás en el overlay al iniciar.")
        note.setStyleSheet(f"color: #7c7565; font-size: 11px;")
        v.addWidget(note)
        return box

    def _ctx_editor(self):
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(14)
        c = next((x for x in self.contexts if x["id"] == self.sel_id), None)
        if c is None:
            empty = QtWidgets.QLabel("Selecciona un contexto para editarlo")
            empty.setAlignment(QtCore.Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: #7c7565; font-size: 14px; border: 1px dashed rgba(243,234,212,0.12); "
                f"border-radius: 12px;")
            v.addWidget(empty, 1)
            return box
        top = QtWidgets.QHBoxLayout(); top.setSpacing(12)
        name = QtWidgets.QLineEdit(c["name"])
        name.setStyleSheet(self._input_qss() + "font-weight: 600; font-size: 15px;")
        name.textChanged.connect(lambda t, cid=c["id"]: self._ctx_set(cid, "name", t))
        top.addWidget(name, 1)
        act = QtWidgets.QLabel("Activo"); act.setStyleSheet(f"color: {TXT_MU}; font-size: 12px;")
        sw = ToggleSwitch(c["active"])
        sw.toggled.connect(lambda on, cid=c["id"]: self._ctx_toggle(cid, on))
        top.addWidget(act); top.addWidget(sw)
        v.addLayout(top)
        # selector de idioma del contexto
        langrow = QtWidgets.QHBoxLayout()
        ll = QtWidgets.QLabel("Idioma"); ll.setStyleSheet(f"color: #948b78; font-size: 12px;")
        seg = Segmented([("es", "ES"), ("en", "EN"), ("both", "Ambos")],
                        c.get("lang", "both"), small=True)
        seg.changed.connect(lambda val, cid=c["id"]: self._ctx_set_lang(cid, val))
        langrow.addWidget(ll); langrow.addWidget(seg); langrow.addStretch()
        v.addLayout(langrow)
        meta = QtWidgets.QHBoxLayout()
        ml = QtWidgets.QLabel("Markdown · lo lee la IA al iniciar la reunión")
        ml.setStyleSheet(f"color: #948b78; font-size: 12px;")
        mt = QtWidgets.QLabel(f"~{ctx_mod.estimate_tokens(c['body'])} tok")
        mt.setStyleSheet(f"color: {TXT_FA}; font-family: {MONO}; font-size: 12px;")
        meta.addWidget(ml); meta.addStretch(); meta.addWidget(mt)
        v.addLayout(meta)
        body = QtWidgets.QPlainTextEdit(c["body"])
        body.setPlaceholderText("# Producto X\nPrecios: plan básico $9/mes…")
        body.setStyleSheet(self._input_qss(mono=True))
        body.textChanged.connect(
            lambda cid=c["id"], w=body: self._ctx_set(cid, "body", w.toPlainText()))
        v.addWidget(body, 1)
        return box

    # ---------------------------------------------------- acciones contextos
    def _ctx_select(self, cid):
        self.sel_id = cid
        self._show_section("contexts")

    def _ctx_toggle(self, cid, on):
        for c in self.contexts:
            if c["id"] == cid:
                c["active"] = bool(on)
        self._dirty_mark()
        self._show_section("contexts")

    def _ctx_set(self, cid, field, value):
        for c in self.contexts:
            if c["id"] == cid:
                c[field] = value
        self._dirty_mark()
        self._refresh_badges()

    def _ctx_set_filter(self, val):
        self._ctx_filter = val
        self._show_section("contexts")

    def _ctx_set_lang(self, cid, val):
        for c in self.contexts:
            if c["id"] == cid:
                c["lang"] = val
        self._dirty_mark()
        self._show_section("contexts")

    def _ctx_add(self):
        cid = ctx_mod.next_id(self.contexts)
        lang = self._ctx_filter if self._ctx_filter in ("es", "en") else "both"
        self.contexts.append({"id": cid, "name": "Nuevo contexto", "active": False,
                              "lang": lang, "body": ""})
        self.sel_id = cid
        self._dirty_mark()
        self._show_section("contexts")

    def _ctx_dup(self, cid):
        src = next((c for c in self.contexts if c["id"] == cid), None)
        if not src:
            return
        nid = ctx_mod.next_id(self.contexts)
        copia = {"id": nid, "name": src["name"] + " (copia)", "active": False,
                 "lang": src.get("lang", "both"), "body": src["body"]}
        i = self.contexts.index(src)
        self.contexts.insert(i + 1, copia)
        self.sel_id = nid
        self._dirty_mark()
        self._show_section("contexts")

    def _ctx_del(self, cid):
        self.contexts = [c for c in self.contexts if c["id"] != cid]
        if self.sel_id == cid:
            self.sel_id = self.contexts[0]["id"] if self.contexts else None
        self._dirty_mark()
        self._show_section("contexts")

    # ---------------------------------------------------- estilos de input
    def _input_qss(self, mono=False):
        fam = MONO if mono else SANS
        return (f"QLineEdit, QPlainTextEdit {{ background: {INPUT_BG}; border: 1px solid {INPUT_BD}; "
                f"border-radius: 10px; padding: 10px 13px; color: #f0e8d6; font-family: {fam}; "
                f"font-size: 13px; }} "
                f"QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid rgba(242,201,76,0.55); }}")

    def _combo_qss(self):
        arrow = self._chevron.replace("\\", "/")
        return (f"QComboBox {{ background: {INPUT_BG}; border: 1px solid {INPUT_BD}; border-radius: 10px; "
                f"padding: 9px 34px 9px 13px; color: #f0e8d6; font-size: 13px; }} "
                f"QComboBox:focus {{ border: 1px solid rgba(242,201,76,0.55); }} "
                f"QComboBox::drop-down {{ border: none; width: 30px; subcontrol-position: center right; }} "
                f"QComboBox::down-arrow {{ image: url({arrow}); width: 12px; height: 12px; }} "
                f"QComboBox QAbstractItemView {{ background: {BAR_BG}; color: #f0e8d6; "
                f"selection-background-color: rgba(242,201,76,0.25); border: 1px solid {INPUT_BD}; }}")

    def _slider_qss(self):
        return (f"QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; "
                f"background: rgba(243,234,212,0.16); }} "
                f"QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; "
                f"border-radius: 8px; background: {GOLD}; }} "
                f"QSlider::sub-page:horizontal {{ background: rgba(242,201,76,0.5); border-radius: 2px; }}")

    # ---------------------------------------------------- guardar / cerrar
    def _dirty_mark(self, *_):
        self._error = None
        if not self._dirty:
            self._dirty = True
        self._paint_saved()

    def _paint_saved(self):
        if getattr(self, "_error", None):
            self.saved_dot.set_color("#e0554b")     # rojo = fallo
            self.saved_lbl.setText(self._error)
            self.saved_lbl.setStyleSheet("color: #e39a90; font-size: 12px; background: transparent;")
        elif self._dirty:
            self.saved_dot.set_color("#f2c94c")     # amarillo = sin guardar
            self.saved_lbl.setText("Cambios sin guardar")
            self.saved_lbl.setStyleSheet("color: #f7e39a; font-size: 12px; background: transparent;")
        else:
            self.saved_dot.set_color("#28c840")     # verde = guardado
            self.saved_lbl.setText("Todo guardado")
            self.saved_lbl.setStyleSheet(f"color: {TXT_FA}; font-size: 12px; background: transparent;")

    def _save(self):
        # self.values ya esta al dia (cada control escribe en vivo).
        try:
            self.cfg.update(self.values)
            if not cfg_mod.save_config(self.cfg):
                raise IOError("no se pudo escribir config.json")
            ctx_mod.write_all(self.contexts)
        except Exception as e:
            # Fallo al guardar: se indica en rojo y NO se cierra la ventana.
            self._error = f"Error al guardar: {e}"
            self._paint_saved()
            return
        self._error = None
        self._dirty = False
        self._paint_saved()
        self.saved.emit()
        self._close()

    def _cancel(self):
        self._close()

    def _close(self):
        self.closed.emit()
        self.close()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(e)
