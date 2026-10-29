"""Ventana de configuracion de Cue. (segun 'Meeting Coach Settings.dc.html').

Vista completa con barra de titulo, sidebar de secciones, campos por tipo
(texto, select, toggle, slider, textarea) y la seccion Contexts (lista + editor).
Reemplaza al overlay mientras esta abierta.
"""
import os

from PySide6 import QtCore, QtGui, QtWidgets

import agents as agents_mod
import config as cfg_mod
import contexts as ctx_mod
import icons
import neu as N
import theme as T

# --- colores: neumorfismo claro (ver neu.py), acento pervinca ---
WIN_BG   = N.BG
TXT_BR   = N.TITULO
TXT_MU   = N.APAGADO
TXT_FA   = N.TENUE
TXT_LB   = N.TEXTO
ACENTO   = N.ACENTO
INK      = "#FFFFFF"            # texto sobre el acento

SANS = N.SANS
MONO = T.MONO_STACK


class ToggleSwitch(N.Toggle):
    """Interruptor: pista hundida y perilla en relieve (ver neu.Toggle)."""

    def __init__(self, checked=False, small=False):
        super().__init__(checked, small)
        self.small = small


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


class Segmented(N.Surface):
    """Control segmentado (p. ej. ES | EN | Ambos): carril hundido y la opcion
    elegida en relieve, en pervinca."""
    changed = QtCore.Signal(str)

    def __init__(self, options, current, small=False):
        super().__init__("hundido", radio=12, prof=4, margen=2)
        self._options = options
        self._current = current
        self._btns = {}
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(2, 0, 2, 0); lay.setSpacing(0)
        for val, label in options:
            b = N.Button(label, variante="plano", radio=10, prof=3)
            f = b.font(); f.setPixelSize(11 if small else 12); b.setFont(f)
            b.setCheckable(True)
            b.setChecked(val == current)
            b.clicked.connect(lambda _c=False, v=val: self._pick(v))
            self._btns[val] = b
            lay.addWidget(b)

    def _pick(self, val):
        for v, b in self._btns.items():
            b.setChecked(v == val)
        if val == self._current:
            return
        self._current = val
        self.changed.emit(val)

    def value(self):
        return self._current


def _schema():
    """Definicion de secciones y campos (espeja el diseno).

    Solo lo que es del usuario: sus claves, el idioma de la reunion, la
    opacidad, sus agentes y sus contextos. El modelo, cuanto razona y cuanto
    escribe, la deteccion de turnos y el audio van fijos en config.FIJAS.
    """
    return [
        ("connection", "bolt", "Conexión",
         "Las claves de los servicios que transcriben y responden.", [
            dict(key="openai_api_key", label="API key de OpenAI", type="text",
                 secret=True, placeholder="sk-proj-…",
                 hint="Genera las respuestas. Sin ella no arranca la reunión."),
            dict(key="assemblyai_api_key", label="API key de AssemblyAI", type="text",
                 secret=True, placeholder="…",
                 hint="Transcripción en vivo. Sin ella no arranca la reunión."),
            dict(key="typesafe_api_key", label="API key de TypeSafe (Jev)", type="text",
                 secret=True, placeholder="apikey_…",
                 hint="Opcional. Decide si lo que añaden a una pregunta cambia la "
                      "respuesta o es ruido. Sin ella, todo añadido es contexto."),
         ]),
        ("general", "window", "General",
         "El idioma de la reunión y cómo se ve el overlay.", [
            dict(key="language", label="Idioma", type="select",
                 hint="Idioma de la reunión. Auto lo detecta solo y admite "
                      "cambios de idioma a mitad de frase.",
                 options=[("es", "Español"), ("en", "English"), ("auto", "Auto")]),
            dict(key="window_opacity", label="Opacidad", type="number",
                 min=0.15, max=1.0, step=0.05, unit="",
                 hint="Transparencia de las ventanas. Bajo = se ve más el fondo."),
         ]),
        ("agents", "chat", "Agentes",
         "Quién te sopla las respuestas: su personalidad y sus reglas, enteras y "
         "editables. Uno se usa en las reuniones; se cambia aquí o desde el overlay.",
         None),
        ("contexts", "puzzle", "Contexts",
         "Documentos markdown que la IA lee al iniciar. Activa los que apliquen "
         "para cada reunión — QUÉ sabe, no cómo responde.", None),
    ]


class NavItem(QtWidgets.QFrame):
    """Fila del sidebar. La seccion abierta sale en relieve, con el acento."""
    clicked = QtCore.Signal()

    def __init__(self, icon, label):
        super().__init__()
        self._iconname = icon
        self._activo = False
        self.setCursor(QtCore.Qt.PointingHandCursor)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(24, 18, 22, 18)
        lay.setSpacing(12)
        self._icon = icons.label(icon, TXT_MU, 17)
        lay.addWidget(self._icon)
        self._lab = QtWidgets.QLabel(label)
        lf = self._lab.font(); lf.setPixelSize(14); self._lab.setFont(lf)
        lay.addWidget(self._lab, 1)
        self._badge = QtWidgets.QLabel("")
        self._badge.setStyleSheet(
            f"color: {INK}; background: {ACENTO}; border-radius: 9px; padding: 1px 7px; "
            f"font-size: 11px; font-weight: 700;")
        self._badge.setVisible(False)
        lay.addWidget(self._badge)
        self.setStyleSheet("NavItem { border: none; background: transparent; } "
                           "QLabel { background: transparent; border: none; }")
        self.set_active(False)

    def set_active(self, on):
        self._activo = bool(on)
        col = ACENTO if on else TXT_MU
        self._lab.setStyleSheet(f"color: {col}; background: transparent;")
        self._icon.setPixmap(icons.pixmap(self._iconname, col, 17))
        self.update()

    def paintEvent(self, e):
        if self._activo:
            p = QtGui.QPainter(self)
            p.drawPixmap(0, 0, N.superficie(self.width(), self.height(),
                                            N.margen_relieve(4), 14, "relieve", 4))
            p.end()
        super().paintEvent(e)

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
        self.agents = agents_mod.list_agents()
        if not any(a["id"] == self.values.get("agent") for a in self.agents):
            self.values["agent"] = self.agents[0]["id"]
        self.sel_agent = self.values["agent"]
        self.sel_id = self.contexts[0]["id"] if self.contexts else None
        self._ctx_filter = "all"      # all | es | en (filtro de la lista)
        self._dirty = False
        self._error = None
        self._nav_btns = {}
        self._active = "connection"
        self._drag = None
        self._chevron = icons.save_png(
            "chevron_down", N.APAGADO, 24,
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
        self.setStyleSheet(
            f"QWidget#root {{ background: {WIN_BG}; border-radius: 22px; }}"
            f"QToolTip {{ background: {N.BG}; color: {N.TEXTO}; border: 1px solid #CBD3E3; }}")

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
        self.content.setStyleSheet(
            f"QScrollArea {{ background: {WIN_BG}; border: none; }}" + N.qss_campo())
        mid.addWidget(self.content, 1)
        col.addLayout(mid, 1)
        col.addWidget(self._footer())

        self._show_section("connection")

    def _titlebar(self):
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(68)
        bar.setStyleSheet("background: transparent;")
        lay = QtWidgets.QHBoxLayout(bar); lay.setContentsMargins(16, 6, 16, 0); lay.setSpacing(6)
        # Como la cabecera de la imagen de referencia: botones redondos a los
        # lados y en el centro una etiqueta pequena en mayusculas.
        lay.addWidget(self._win_btn("arrow-left", self._cancel, "Volver a la reunión"))
        lay.addStretch()
        brand = QtWidgets.QLabel(
            f'<span style="color:{ACENTO};font-weight:700;">ARM</span>'
            f'<span style="color:{N.TITULO};font-weight:700;">ONY</span>'
            f'<span style="color:{N.TENUE};"> &nbsp;·&nbsp; AJUSTES</span>')
        f = brand.font(); f.setPixelSize(11)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 2.2); brand.setFont(f)
        brand.setStyleSheet("background: transparent;")
        lay.addWidget(brand)
        lay.addStretch()
        lay.addWidget(self._win_btn("minus", self.showMinimized, "Minimizar"))
        lay.addWidget(self._win_btn("x", lambda: self.closeApp.emit(), "Cerrar Armony.", danger=True))
        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        return bar

    def _win_btn(self, icon, cb, tip, danger=False):
        b = N.Button(icono=icon, redondo=34, prof=4,
                     color_icono=N.PELIGRO if danger else N.APAGADO)
        b.setToolTip(tip)
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
        side.setFixedWidth(244)
        side.setStyleSheet("background: transparent;")
        lay = QtWidgets.QVBoxLayout(side); lay.setContentsMargins(12, 6, 6, 16); lay.setSpacing(0)

        # Volver a la reunion (vista overlay)
        goto = NavItem("arrow-left", "Go to the meeting")
        goto.clicked.connect(self._cancel)
        lay.addWidget(goto)
        lay.addSpacing(10)

        for sid, icon, label, _desc, _fields in _schema():
            item = NavItem(icon, label)
            item.clicked.connect(lambda s=sid: self._show_section(s))
            self._nav_btns[sid] = item
            lay.addWidget(item)
        lay.addStretch()
        nota = QtWidgets.QLabel(
            "Los cambios valen para la próxima reunión. En plena reunión, el "
            "agente se cambia desde el overlay.")
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {N.APAGADO}; font-size: 11px; background: transparent;")
        caja = N.Surface("hundido", radio=14, prof=4, margen=2)
        cl = QtWidgets.QVBoxLayout(caja); cl.setContentsMargins(12, 10, 12, 10)
        cl.addWidget(nota)
        lay.addWidget(caja)
        return side

    def _footer(self):
        bar = QtWidgets.QWidget()
        bar.setStyleSheet("background: transparent;")
        lay = QtWidgets.QHBoxLayout(bar); lay.setContentsMargins(26, 4, 22, 14)
        self.saved_dot = Dot(N.OK, 8)
        self.saved_lbl = QtWidgets.QLabel("Todo guardado")
        self.saved_lbl.setStyleSheet(f"color: {TXT_FA}; font-size: 12px; background: transparent;")
        lay.addWidget(self.saved_dot); lay.addSpacing(7); lay.addWidget(self.saved_lbl)
        lay.addStretch()
        cancel = N.Button("Cancelar", radio=14)
        cancel.clicked.connect(self._cancel)
        save = N.Button("Guardar", variante="acento", radio=14)
        save.clicked.connect(self._save)
        lay.addWidget(cancel); lay.addSpacing(4); lay.addWidget(save)
        self._paint_saved()
        return bar

    # ---------------------------------------------------- navegacion
    def _show_section(self, sid):
        self._active = sid
        # Al cambiar de seccion, Qt destruye las filas anteriores: hay que soltar
        # las referencias o el siguiente cambio de valor tocaria widgets muertos.
        self._condicionales = []
        for k, item in self._nav_btns.items():
            item.set_active(k == sid)
        self._refresh_badges()
        # construir el contenido
        for sid2, _ic, label, desc, fields in _schema():
            if sid2 == sid:
                if sid == "contexts":
                    self.content.setWidget(self._contexts_view(label, desc))
                elif sid == "agents":
                    self.content.setWidget(self._agents_view(label, desc))
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
        hf = h.font(); hf.setPixelSize(22); hf.setWeight(QtGui.QFont.DemiBold); h.setFont(hf)
        h.setStyleSheet(f"color: {TXT_BR}; background: transparent;")
        d = QtWidgets.QLabel(desc); d.setWordWrap(True); d.setMaximumWidth(560)
        d.setStyleSheet(f"color: {N.APAGADO}; font-size: 13px; background: transparent;")
        # Un QLabel con salto de linea no reserva su alto: en una pagina llena
        # (Contexts) el layout lo aplastaba y se cortaba la segunda linea.
        d.setMinimumHeight(d.heightForWidth(560))
        v.addWidget(h); v.addWidget(d)
        return w

    # ---------------------------------------------------- vista de campos
    def _fields_view(self, label, desc, fields):
        page = QtWidgets.QWidget()
        page.setStyleSheet("background: transparent;")
        v = QtWidgets.QVBoxLayout(page); v.setContentsMargins(26, 18, 30, 24); v.setSpacing(0)
        v.addWidget(self._heading(label, desc))
        v.addSpacing(14)
        # Todas las filas en una tarjeta en relieve, sin lineas entre ellas: en
        # el neumorfismo separa el aire, no los bordes.
        tarjeta = N.Surface("relieve", radio=22, prof=7)
        tv = QtWidgets.QVBoxLayout(tarjeta); tv.setContentsMargins(26, 10, 22, 10); tv.setSpacing(0)
        # Filas que solo aplican a cierta configuracion (las que declaran
        # visible_si=(clave, valor)): se guardan con su condicion y se ocultan en
        # cuanto deja de cumplirse.
        self._condicionales = []
        for f in fields:
            fila = self._field_row(f)
            tv.addWidget(fila)
            if f.get("visible_si"):
                self._condicionales.append((fila, f["visible_si"]))
        v.addWidget(tarjeta)
        v.addStretch()
        self._aplicar_visibilidad()
        return page

    def _aplicar_visibilidad(self):
        for fila, (clave, valor) in getattr(self, "_condicionales", []):
            fila.setVisible(self.values.get(clave) == valor)

    def _field_row(self, f):
        row = QtWidgets.QWidget()
        row.setObjectName("fila")
        row.setProperty("clave", f["key"])
        lay = QtWidgets.QHBoxLayout(row); lay.setContentsMargins(0, 14, 0, 14); lay.setSpacing(24)
        # izquierda: label + hint (la clave interna de config no se ensena)
        left = QtWidgets.QWidget(); left.setMaximumWidth(340)
        lv = QtWidgets.QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(3)
        top = QtWidgets.QHBoxLayout(); top.setSpacing(8)
        name = QtWidgets.QLabel(f["label"])
        nf = name.font(); nf.setPixelSize(14); nf.setWeight(QtGui.QFont.DemiBold); name.setFont(nf)
        name.setStyleSheet(f"color: {TXT_LB}; background: transparent;")
        top.addWidget(name); top.addStretch()
        lv.addLayout(top)
        hint = QtWidgets.QLabel(f["hint"]); hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {N.APAGADO}; font-size: 12px; background: transparent;")
        lv.addWidget(hint)
        lay.addWidget(left, 1)
        # derecha: control
        lay.addWidget(self._control(f), 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        if f["type"] == "textarea":
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
            e.setStyleSheet(N.qss_campo(mono=True))
            e.textChanged.connect(lambda _t, e=e, k=key: self._set_value(k, e.text().strip()))
            return N.campo(e, ancho=310)
        if typ == "select":
            c = QtWidgets.QComboBox()
            for v, lab in f["options"]:
                c.addItem(lab, v)
            i = c.findData(val)
            if i >= 0:
                c.setCurrentIndex(i)
            c.setStyleSheet(self._combo_qss())
            c.currentIndexChanged.connect(lambda _i, c=c, k=key: self._set_value(k, c.currentData()))
            return N.campo(c, ancho=250)
        if typ == "toggle":
            sw = ToggleSwitch(bool(val))
            sw.toggled.connect(lambda on, k=key: self._set_value(k, on))
            return sw
        if typ == "number":
            return self._number_control(f, val)
        if typ == "textarea":
            t = QtWidgets.QPlainTextEdit(str(val or ""))
            t.setStyleSheet(N.qss_campo())
            t.textChanged.connect(lambda t=t, k=key: self._set_value(k, t.toPlainText()))
            caja = N.campo(t, ancho=460)
            caja.setFixedHeight(150)
            return caja
        return QtWidgets.QWidget()

    def _set_value(self, key, v):
        self.values[key] = v
        self._aplicar_visibilidad()    # un valor puede mostrar u ocultar filas
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
        disp.setStyleSheet(f"color: {ACENTO}; font-family: {MONO}; font-size: 13px; "
                           f"font-weight: 600; background: transparent;")
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

    # ---------------------------------------------------- vista de agentes
    def _agents_view(self, label, desc):
        page = QtWidgets.QWidget(); page.setStyleSheet("background: transparent;")
        v = QtWidgets.QVBoxLayout(page); v.setContentsMargins(30, 26, 30, 30); v.setSpacing(16)
        v.addWidget(self._heading(label, desc))
        grid = QtWidgets.QHBoxLayout(); grid.setSpacing(20)
        grid.addWidget(self._ag_list(), 0, QtCore.Qt.AlignTop)
        grid.addWidget(self._ag_editor(), 1)
        v.addLayout(grid, 1)
        return page

    def _add_btn(self, texto, cb, tip=""):
        """Boton de alta ("Nuevo agente", "Nuevo contexto"): en relieve, con el
        mas en pervinca."""
        b = N.Button(texto, icono="plus", radio=16, color_icono=ACENTO)
        b.setToolTip(tip)
        b.clicked.connect(cb)
        return b

    def _tarjeta(self, elegida, al_pulsar):
        """Tarjeta de lista: en relieve; la elegida, hundida (como la cancion que
        suena en la imagen de referencia)."""
        # Mismo margen en las dos: la elegida no cambia de ancho al hundirse.
        card = N.Surface("hundido" if elegida else "relieve", radio=16, prof=5,
                         margen=N.margen_relieve(5))
        card.setCursor(QtCore.Qt.PointingHandCursor)
        card.mousePressEvent = lambda e: al_pulsar()
        return card

    def _nombre_tarjeta(self, texto, elegida):
        nm = QtWidgets.QLabel(texto)
        nf = nm.font(); nf.setPixelSize(14); nf.setWeight(QtGui.QFont.DemiBold); nm.setFont(nf)
        nm.setStyleSheet(f"color: {ACENTO if elegida else N.TITULO}; background: transparent;")
        return nm

    def _ag_list(self):
        box = QtWidgets.QWidget(); box.setFixedWidth(262)
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        v.addWidget(self._add_btn(
            "Nuevo agente", self._ag_add,
            "Empieza como copia del Coach: verás todo lo que ya tiene y decides qué cambiar."))
        v.addSpacing(6)
        for a in self.agents:
            v.addWidget(self._ag_card(a))
        v.addStretch()
        return box

    def _ag_card(self, a):
        seld = a["id"] == self.sel_agent
        card = self._tarjeta(seld, lambda aid=a["id"]: self._ag_select(aid))
        card.setObjectName("agente")
        lay = QtWidgets.QHBoxLayout(card); lay.setContentsMargins(14, 8, 6, 8); lay.setSpacing(4)
        lay.addWidget(self._nombre_tarjeta(a["name"], seld), 1)
        if a["id"] == self.values.get("agent"):
            uso = QtWidgets.QLabel("En uso")
            uso.setStyleSheet(
                f"color: {INK}; background: {ACENTO}; border-radius: 8px; "
                f"padding: 2px 8px; font-size: 10px; font-weight: 700;")
            lay.addWidget(uso)
        lay.addWidget(self._mini_btn("duplicate", N.APAGADO,
                                     lambda aid=a["id"]: self._ag_dup(aid)))
        dele = self._mini_btn("trash", N.PELIGRO, lambda aid=a["id"]: self._ag_del(aid))
        dele.setEnabled(len(self.agents) > 1)       # siempre queda al menos uno
        lay.addWidget(dele)
        return card

    def _ag_editor(self):
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        a = next((x for x in self.agents if x["id"] == self.sel_agent), None)
        if a is None:
            return box
        top = QtWidgets.QHBoxLayout(); top.setSpacing(12)
        name = QtWidgets.QLineEdit(a["name"])
        name.setStyleSheet(N.qss_campo() + "QLineEdit { font-weight: 600; font-size: 15px; }")
        name.textChanged.connect(lambda t, aid=a["id"]: self._ag_set(aid, "name", t))
        top.addWidget(N.campo(name), 1)
        uso = QtWidgets.QLabel("Usar en las reuniones")
        uso.setStyleSheet(f"color: {TXT_MU}; font-size: 12px;")
        sw = ToggleSwitch(a["id"] == self.values.get("agent"))
        # Siempre hay uno en uso: se cambia eligiendo otro, no apagando este.
        sw.setEnabled(a["id"] != self.values.get("agent"))
        sw.toggled.connect(lambda on, aid=a["id"]: on and self._ag_use(aid))
        top.addWidget(uso); top.addWidget(sw)
        v.addLayout(top)
        v.addSpacing(6)
        v.addLayout(self._ag_field_head(
            a, "instrucciones", "Instrucciones",
            "Personalidad, tono y cómo responde. Lo que pongas aquí manda."))
        ins = QtWidgets.QPlainTextEdit(a["instrucciones"])
        ins.setObjectName("instrucciones")
        ins.setMinimumHeight(170)
        ins.setStyleSheet(N.qss_campo())
        ins.textChanged.connect(
            lambda aid=a["id"], w=ins: self._ag_set(aid, "instrucciones", w.toPlainText()))
        v.addWidget(N.campo(ins), 1)
        v.addSpacing(6)
        v.addLayout(self._ag_field_head(
            a, "reglas", "Reglas de funcionamiento",
            "Cómo funciona la conversación, el formato con secciones «##», el "
            "código y las capturas. La app depende de ellas: si las cambias, "
            "puede dejar de pintar bien las respuestas."))
        reg = QtWidgets.QPlainTextEdit(a["reglas"])
        reg.setObjectName("reglas")
        reg.setMinimumHeight(170)
        reg.setStyleSheet(N.qss_campo(mono=True))
        reg.textChanged.connect(
            lambda aid=a["id"], w=reg: self._ag_set(aid, "reglas", w.toPlainText()))
        v.addWidget(N.campo(reg), 1)
        return box

    def _ag_field_head(self, a, campo, titulo, ayuda):
        head = QtWidgets.QHBoxLayout(); head.setSpacing(10)
        col = QtWidgets.QVBoxLayout(); col.setSpacing(2)
        t = QtWidgets.QLabel(titulo)
        tf = t.font(); tf.setPixelSize(13); tf.setWeight(QtGui.QFont.DemiBold); t.setFont(tf)
        t.setStyleSheet(f"color: {TXT_LB}; background: transparent;")
        h = QtWidgets.QLabel(ayuda); h.setWordWrap(True)
        h.setStyleSheet(f"color: {N.APAGADO}; font-size: 12px; background: transparent;")
        col.addWidget(t); col.addWidget(h)
        head.addLayout(col, 1)
        cambiado = a[campo] != agents_mod.predeterminado(a)[campo]
        rest = N.Button("Restaurar", radio=12, prof=3)
        f = rest.font(); f.setPixelSize(12); rest.setFont(f)
        rest.setObjectName(f"restaurar-{campo}")
        rest.setEnabled(cambiado)
        rest.setToolTip(f"Vuelve al texto de «{agents_mod.predeterminado(a)['name']}»")
        rest.clicked.connect(lambda _c=False, aid=a["id"], f=campo: self._ag_restore(aid, f))
        head.addWidget(rest, 0, QtCore.Qt.AlignTop)
        return head

    # ---------------------------------------------------- acciones agentes
    def _ag_get(self, aid):
        return next((a for a in self.agents if a["id"] == aid), None)

    def _ag_select(self, aid):
        self.sel_agent = aid
        self._show_section("agents")

    def _ag_use(self, aid):
        self.values["agent"] = aid
        self._dirty_mark()
        self._show_section("agents")

    def _ag_set(self, aid, campo, valor):
        # Sin redibujar: se perderia el cursor del campo que se esta escribiendo.
        a = self._ag_get(aid)
        if a is not None:
            a[campo] = valor
            self._dirty_mark()

    def _ag_restore(self, aid, campo):
        a = self._ag_get(aid)
        if a is not None:
            a[campo] = agents_mod.predeterminado(a)[campo]
            self._dirty_mark()
            self._show_section("agents")

    def _ag_add(self):
        a = agents_mod.nuevo(self.agents)
        self.agents.append(a)
        self.sel_agent = a["id"]
        self._dirty_mark()
        self._show_section("agents")

    def _ag_dup(self, aid):
        src = self._ag_get(aid)
        if src is None:
            return
        copia = dict(src, id=agents_mod.next_id(self.agents),
                     name=src["name"] + " (copia)")
        self.agents.insert(self.agents.index(src) + 1, copia)
        self.sel_agent = copia["id"]
        self._dirty_mark()
        self._show_section("agents")

    def _ag_del(self, aid):
        if len(self.agents) <= 1:
            return
        self.agents = [a for a in self.agents if a["id"] != aid]
        if self.values.get("agent") == aid:
            self.values["agent"] = self.agents[0]["id"]
        if self.sel_agent == aid:
            self.sel_agent = self.values["agent"]
        self._dirty_mark()
        self._show_section("agents")

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
        box = QtWidgets.QWidget(); box.setFixedWidth(296)
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(8)
        v.addWidget(self._add_btn("Nuevo contexto", self._ctx_add))

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
        iv = QtWidgets.QVBoxLayout(inner); iv.setContentsMargins(0, 0, 0, 0); iv.setSpacing(2)
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
        card = self._tarjeta(seld, lambda cid=c["id"]: self._ctx_select(cid))
        v = QtWidgets.QVBoxLayout(card); v.setContentsMargins(14, 8, 8, 8); v.setSpacing(4)
        top = QtWidgets.QHBoxLayout(); top.setSpacing(8)
        top.addWidget(self._nombre_tarjeta(c["name"], seld), 1)
        sw = ToggleSwitch(c["active"], small=True)
        sw.toggled.connect(lambda on, cid=c["id"]: self._ctx_toggle(cid, on))
        top.addWidget(sw)
        v.addLayout(top)
        bot = QtWidgets.QHBoxLayout(); bot.setSpacing(4)
        chip = QtWidgets.QLabel({"es": "ES", "en": "EN", "both": "ES·EN"}.get(c.get("lang", "both")))
        chip.setStyleSheet(
            f"color: {N.APAGADO}; background: transparent; font-size: 10px; "
            f"font-weight: 700; letter-spacing: 1px;")
        bot.addWidget(chip)
        tok = QtWidgets.QLabel(f"~{ctx_mod.estimate_tokens(c['body'])} tok")
        tok.setStyleSheet(f"color: {TXT_FA}; font-family: {MONO}; font-size: 11px;")
        bot.addWidget(tok); bot.addStretch()
        dup = self._mini_btn("duplicate", N.APAGADO, lambda cid=c["id"]: self._ctx_dup(cid))
        dele = self._mini_btn("trash", N.PELIGRO, lambda cid=c["id"]: self._ctx_del(cid))
        bot.addWidget(dup); bot.addWidget(dele)
        v.addLayout(bot)
        return card

    def _mini_btn(self, icon, color, cb):
        b = N.Button(icono=icon, redondo=24, prof=3, color_icono=color)
        b.clicked.connect(lambda: cb())
        return b

    def _ctx_summary(self):
        box = N.Surface("relieve", radio=16, prof=5)
        box.setStyleSheet("QLabel { background: transparent; border: none; }")
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(14, 10, 14, 10); v.setSpacing(6)
        n = sum(1 for c in self.contexts if c["active"])
        tot = sum(ctx_mod.estimate_tokens(c["body"]) for c in self.contexts if c["active"])
        top = QtWidgets.QHBoxLayout()
        a = QtWidgets.QLabel(f"{n} activos"); a.setStyleSheet(f"color: {N.TEXTO}; font-size: 12px;")
        tk = QtWidgets.QLabel(f"~{tot} tok")
        tk.setStyleSheet(f"color: {ACENTO}; font-family: {MONO}; font-size: 12px; font-weight: 600;")
        top.addWidget(a); top.addStretch(); top.addWidget(tk)
        v.addLayout(top)
        if tot > 4000:
            warn = QtWidgets.QLabel("⚠ Contexto grande: puede subir el costo y la latencia de la primera respuesta.")
            warn.setWordWrap(True); warn.setStyleSheet(f"color: {N.AVISO}; font-size: 11px;")
            v.addWidget(warn)
        chip = QtWidgets.QWidget()
        ch = QtWidgets.QHBoxLayout(chip); ch.setContentsMargins(10, 4, 10, 4); ch.setSpacing(6)
        ch.addWidget(icons.label("puzzle", ACENTO, 12))
        cl = QtWidgets.QLabel(f"{n} contexts loaded")
        cl.setStyleSheet(f"color: {ACENTO}; font-size: 11px; font-weight: 600;")
        ch.addWidget(cl)
        chip.setObjectName("chip")
        chip.setStyleSheet("#chip { background: rgba(91,124,250,0.10); border-radius: 11px; }")
        row = QtWidgets.QHBoxLayout(); row.addWidget(chip); row.addStretch()
        v.addLayout(row)
        note = QtWidgets.QLabel("Chip que verás en el overlay al iniciar.")
        note.setStyleSheet(f"color: {N.TENUE}; font-size: 11px;")
        v.addWidget(note)
        return box

    def _ctx_editor(self):
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(14)
        c = next((x for x in self.contexts if x["id"] == self.sel_id), None)
        if c is None:
            empty = QtWidgets.QLabel("Selecciona un contexto para editarlo")
            empty.setAlignment(QtCore.Qt.AlignCenter)
            empty.setStyleSheet(f"color: {N.TENUE}; font-size: 14px; background: transparent;")
            hueco = N.Surface("hundido", radio=18, prof=5, margen=2)
            QtWidgets.QVBoxLayout(hueco).addWidget(empty)
            v.addWidget(hueco, 1)
            return box
        top = QtWidgets.QHBoxLayout(); top.setSpacing(12)
        name = QtWidgets.QLineEdit(c["name"])
        name.setStyleSheet(N.qss_campo() + "QLineEdit { font-weight: 600; font-size: 15px; }")
        name.textChanged.connect(lambda t, cid=c["id"]: self._ctx_set(cid, "name", t))
        top.addWidget(N.campo(name), 1)
        act = QtWidgets.QLabel("Activo"); act.setStyleSheet(f"color: {TXT_MU}; font-size: 12px;")
        sw = ToggleSwitch(c["active"])
        sw.toggled.connect(lambda on, cid=c["id"]: self._ctx_toggle(cid, on))
        top.addWidget(act); top.addWidget(sw)
        v.addLayout(top)
        # selector de idioma del contexto
        langrow = QtWidgets.QHBoxLayout()
        ll = QtWidgets.QLabel("Idioma")
        ll.setToolTip("Solo para organizarlos: todos los contextos activos se le "
                      "mandan a la IA, en el idioma que estén, porque la reunión "
                      "puede cambiar de idioma a media frase.")
        ll.setStyleSheet(f"color: {N.APAGADO}; font-size: 12px;")
        seg = Segmented([("es", "ES"), ("en", "EN"), ("both", "Ambos")],
                        c.get("lang", "both"), small=True)
        seg.changed.connect(lambda val, cid=c["id"]: self._ctx_set_lang(cid, val))
        langrow.addWidget(ll); langrow.addWidget(seg); langrow.addStretch()
        v.addLayout(langrow)
        meta = QtWidgets.QHBoxLayout()
        ml = QtWidgets.QLabel("Markdown · lo lee la IA al iniciar la reunión")
        ml.setStyleSheet(f"color: {N.APAGADO}; font-size: 12px;")
        mt = QtWidgets.QLabel(f"~{ctx_mod.estimate_tokens(c['body'])} tok")
        mt.setStyleSheet(f"color: {TXT_FA}; font-family: {MONO}; font-size: 12px;")
        meta.addWidget(ml); meta.addStretch(); meta.addWidget(mt)
        v.addLayout(meta)
        body = QtWidgets.QPlainTextEdit(c["body"])
        body.setPlaceholderText("# Producto X\nPrecios: plan básico $9/mes…")
        body.setStyleSheet(N.qss_campo(mono=True))
        body.textChanged.connect(
            lambda cid=c["id"], w=body: self._ctx_set(cid, "body", w.toPlainText()))
        v.addWidget(N.campo(body), 1)
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
    def _combo_qss(self):
        arrow = self._chevron.replace("\\", "/")
        return (f"QComboBox {{ background: transparent; border: none; padding: 8px 30px 8px 6px; "
                f"color: {N.TEXTO}; font-size: 13px; }} "
                f"QComboBox::drop-down {{ border: none; width: 28px; subcontrol-position: center right; }} "
                f"QComboBox::down-arrow {{ image: url({arrow}); width: 12px; height: 12px; }} "
                f"QComboBox QAbstractItemView {{ background: {N.BG}; color: {N.TEXTO}; outline: none; "
                f"padding: 4px; border: 1px solid #CBD3E3; border-radius: 10px; "
                f"selection-background-color: rgba(91,124,250,0.16); selection-color: {ACENTO}; }}")

    def _slider_qss(self):
        # Pista hundida (tono mas oscuro del material), tramo recorrido en
        # pervinca y tirador blanco, como la barra de progreso de la referencia.
        return (f"QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; "
                f"background: #D3DAE8; }} "
                f"QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -6px 0; "
                f"border-radius: 9px; background: #FFFFFF; border: 1px solid #D5DCEA; }} "
                f"QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                f"stop:0 {N.ACENTO_LT}, stop:1 {N.ACENTO}); border-radius: 3px; }}")

    # ---------------------------------------------------- guardar / cerrar
    def _dirty_mark(self, *_):
        self._error = None
        if not self._dirty:
            self._dirty = True
        self._paint_saved()

    def _paint_saved(self):
        if getattr(self, "_error", None):
            self.saved_dot.set_color(N.PELIGRO)     # rojo = fallo
            self.saved_lbl.setText(self._error)
            self.saved_lbl.setStyleSheet(f"color: {N.PELIGRO}; font-size: 12px; background: transparent;")
        elif self._dirty:
            self.saved_dot.set_color(N.AVISO)       # ambar = sin guardar
            self.saved_lbl.setText("Cambios sin guardar")
            self.saved_lbl.setStyleSheet(f"color: {N.AVISO}; font-size: 12px; background: transparent;")
        else:
            self.saved_dot.set_color(N.OK)          # verde = guardado
            self.saved_lbl.setText("Todo guardado")
            self.saved_lbl.setStyleSheet(f"color: {TXT_FA}; font-size: 12px; background: transparent;")

    def _save(self):
        # self.values ya esta al dia (cada control escribe en vivo).
        try:
            self.cfg.update(self.values)
            if not cfg_mod.save_config(self.cfg):
                raise IOError("no se pudo escribir config.json")
            ctx_mod.write_all(self.contexts)
            agents_mod.write_all(self.agents)
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
