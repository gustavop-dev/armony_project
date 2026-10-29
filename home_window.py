"""Home de Armony: donde se aterriza al abrir la app.

Como la de ChatGPT, Claude o Grok, pero para reuniones:

  - a la izquierda, tus agentes y, debajo de cada uno, sus reuniones pasadas
    (el historial); arriba "Nuevo agente" y abajo "Ajustes".
  - en el centro, el agente elegido: su nombre, sus instrucciones, sus reglas y
    su conocimiento (documentos), y el boton para iniciar la reunion con el.
  - una reunion pasada se abre en el centro con su transcripcion.
  - "Ajustes" es una vista aparte: claves, idioma y opacidad.

Todo se guarda solo, un momento despues de cada cambio. Borrar un agente o
una reunion pide un segundo clic. Al iniciar la reunion la Home se oculta y
queda el overlay; al terminar, vuelve.
"""
import os

from PySide6 import QtCore, QtGui, QtWidgets

import agents as agents_mod
import config as cfg_mod
import contexts as ctx_mod
import icons
import neu as N
import sesiones
import theme as T

TXT_BR = N.TITULO
TXT_MU = N.APAGADO
TXT_FA = N.TENUE
TXT_LB = N.TEXTO
ACENTO = N.ACENTO
INK = "#FFFFFF"            # texto sobre el acento
MONO = T.MONO_STACK

# Retraso del guardado automatico: junta las teclas seguidas en una escritura.
GUARDADO_MS = 600
# Cuanto espera la confirmacion de un borrado antes de volver atras.
CONFIRMAR_MS = 3000
# Reuniones que se ensenan bajo cada agente en la barra lateral.
REUNIONES_POR_AGENTE = 5
# Por encima de esto el conocimiento encarece y retrasa la primera respuesta.
AVISO_TOKENS = 4000


# ------------------------------------------------------------------ piezas
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
    """Control segmentado: carril hundido y la opcion elegida en relieve."""
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


class NavItem(QtWidgets.QFrame):
    """Fila de la barra lateral: agente o "Ajustes". La abierta, en relieve."""
    clicked = QtCore.Signal()

    def __init__(self, icon, label, pequeno=False):
        super().__init__()
        self._iconname = icon
        self._activo = False
        self._pequeno = pequeno
        self.setCursor(QtCore.Qt.PointingHandCursor)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(24, 16, 22, 16)
        lay.setSpacing(12)
        self._icon = icons.label(icon, TXT_MU, 17)
        lay.addWidget(self._icon)
        self._lab = QtWidgets.QLabel(label)
        lf = self._lab.font(); lf.setPixelSize(14); self._lab.setFont(lf)
        lay.addWidget(self._lab, 1)
        self.setStyleSheet("NavItem { border: none; background: transparent; } "
                           "QLabel { background: transparent; border: none; }")
        self.set_active(False)

    def set_text(self, texto):
        self._lab.setText(texto)

    def set_active(self, on):
        self._activo = bool(on)
        col = ACENTO if on else TXT_MU
        self._lab.setStyleSheet(f"color: {col if on else N.TEXTO}; background: transparent;")
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


class SessionItem(QtWidgets.QFrame):
    """Una reunion pasada bajo su agente: titulo y cuando fue."""
    clicked = QtCore.Signal()

    def __init__(self, sesion):
        super().__init__()
        self.sid = sesion["id"]
        self.setCursor(QtCore.Qt.PointingHandCursor)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(52, 4, 18, 4)
        lay.setSpacing(0)
        self._titulo = QtWidgets.QLabel(sesion["title"])
        self._titulo.setToolTip(sesion["title"])
        # Un titulo largo se recorta con "…" (resizeEvent); sin esto su ancho
        # ensanchaba toda la lista y el texto se cortaba en seco.
        self._titulo.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                   QtWidgets.QSizePolicy.Preferred)
        self._titulo.setMinimumWidth(1)
        self._fecha = QtWidgets.QLabel(sesiones.etiqueta_fecha(sesion["started"]))
        lay.addWidget(self._titulo)
        lay.addWidget(self._fecha)
        self.setStyleSheet("SessionItem { background: transparent; border: none; }")
        self.set_active(False)

    def set_active(self, on):
        self._titulo.setStyleSheet(
            f"color: {ACENTO if on else N.TEXTO}; font-size: 12px; background: transparent;"
            + (" font-weight: 600;" if on else ""))
        self._fecha.setStyleSheet(f"color: {TXT_FA}; font-size: 10px; background: transparent;")

    def resizeEvent(self, e):
        fm = self._titulo.fontMetrics()
        m = self.layout().contentsMargins()
        self._titulo.setText(fm.elidedText(self._titulo.toolTip(), QtCore.Qt.ElideRight,
                                           max(20, self.width() - m.left() - m.right())))
        super().resizeEvent(e)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()


class ConfirmDelete(QtWidgets.QWidget):
    """Papelera que pide un segundo clic: al primero se convierte en un boton
    rojo "Eliminar" durante unos segundos. Con guardado automatico no hay
    "Cancelar" que valga, asi que borrar no puede ser un clic suelto."""
    confirmed = QtCore.Signal()

    def __init__(self, tamano=24):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.papelera = N.Button(icono="trash", redondo=tamano, prof=3, color_icono=N.PELIGRO)
        self.papelera.setToolTip("Eliminar")
        self.confirmar = N.Button("Eliminar", variante="peligro", radio=10, prof=3)
        f = self.confirmar.font(); f.setPixelSize(11); self.confirmar.setFont(f)
        self.confirmar.setVisible(False)
        lay.addWidget(self.papelera); lay.addWidget(self.confirmar)
        self._vuelta = QtCore.QTimer(self)
        self._vuelta.setSingleShot(True)
        self._vuelta.setInterval(CONFIRMAR_MS)
        self._vuelta.timeout.connect(self.desarmar)
        self.papelera.clicked.connect(self.armar)
        self.confirmar.clicked.connect(self._confirmar)

    def setEnabled(self, on):
        self.papelera.setEnabled(on)

    def armar(self):
        self.papelera.setVisible(False)
        self.confirmar.setVisible(True)
        self._vuelta.start()

    def desarmar(self):
        self._vuelta.stop()
        self.confirmar.setVisible(False)
        self.papelera.setVisible(True)

    def _confirmar(self):
        self.desarmar()
        self.confirmed.emit()


def _ajustes():
    """Lo que el usuario configura (el resto va fijo en config.FIJAS)."""
    return [
        ("Conexión", "Las claves de los servicios que transcriben y responden.", [
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
        ("General", "El idioma de la reunión y cómo se ve el overlay.", [
            dict(key="language", label="Idioma", type="select",
                 hint="Idioma de la reunión. Auto lo detecta solo y admite "
                      "cambios de idioma a mitad de frase.",
                 options=[("es", "Español"), ("en", "English"), ("auto", "Auto")]),
            dict(key="window_opacity", label="Opacidad", type="number",
                 min=0.15, max=1.0, step=0.05, unit="",
                 hint="Cuánto se oscurece el vidrio del overlay. Bajo = se ve más "
                      "lo de detrás."),
        ]),
    ]


# ------------------------------------------------------------------ ventana
class HomeWindow(QtWidgets.QWidget):
    startMeeting = QtCore.Signal(str)   # iniciar la reunion con ese agente
    closeApp = QtCore.Signal()          # cerrar el programa entero (boton X)
    saved = QtCore.Signal()             # tras cada guardado

    def __init__(self, cfg):
        super().__init__()
        self.cfg = dict(cfg)
        self.values = dict(cfg)
        self.agents = agents_mod.list_agents()
        if not any(a["id"] == self.values.get("agent") for a in self.agents):
            self.values["agent"] = self.agents[0]["id"]
        self.sesiones = sesiones.listar()
        self.vista = ("agente", self.values["agent"])
        self.pestana = "instrucciones"
        self.sel_doc = None
        self._dirty = False
        self._error = None
        self._aviso = ""
        self._drag = None
        self._filas_agente = {}
        self._filas_sesion = {}
        self._condicionales = []
        self._guardado = QtCore.QTimer(self)
        self._guardado.setSingleShot(True)
        self._guardado.setInterval(GUARDADO_MS)
        self._guardado.timeout.connect(self.guardar_ya)
        self._chevron = icons.save_png(
            "chevron_down", N.APAGADO, 24,
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "_chevron.png"))

        # Ventana (no Tool) para que tenga entrada en la barra de tareas.
        self.setWindowTitle("Armony.")
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window)
        self._build()

    # ---------------------------------------------------- estructura
    def _build(self):
        scr = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = min(1120, int(scr.width() * 0.92))
        h = min(740, int(scr.height() * 0.92))
        self.resize(w, h)
        self.move(scr.x() + (scr.width() - w) // 2, scr.y() + (scr.height() - h) // 2)
        self.setStyleSheet(
            f"QWidget#root {{ background: {N.BG}; border-radius: 22px; }}"
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
            f"QScrollArea {{ background: {N.BG}; border: none; }}" + N.qss_campo())
        mid.addWidget(self.content, 1)
        col.addLayout(mid, 1)
        self._mostrar()

    def _titlebar(self):
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(64)
        bar.setStyleSheet("background: transparent;")
        lay = QtWidgets.QHBoxLayout(bar); lay.setContentsMargins(22, 6, 16, 0); lay.setSpacing(6)
        # Estado del guardado automatico, a la izquierda (siempre a la vista).
        self.saved_dot = Dot(N.OK, 8)
        self.saved_lbl = QtWidgets.QLabel("Todo guardado")
        lay.addWidget(self.saved_dot); lay.addSpacing(6); lay.addWidget(self.saved_lbl)
        lay.addStretch()
        brand = QtWidgets.QLabel(
            f'<span style="color:{ACENTO};font-weight:700;">ARM</span>'
            f'<span style="color:{N.TITULO};font-weight:700;">ONY</span>')
        f = brand.font(); f.setPixelSize(11)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 2.2); brand.setFont(f)
        brand.setStyleSheet("background: transparent;")
        lay.addWidget(brand)
        lay.addStretch()
        lay.addWidget(self._win_btn("minus", self.showMinimized, "Minimizar"))
        lay.addWidget(self._win_btn("x", self._cerrar_app, "Cerrar Armony.", danger=True))
        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        self._pintar_guardado()
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
        side.setFixedWidth(272)
        side.setStyleSheet("background: transparent;")
        lay = QtWidgets.QVBoxLayout(side); lay.setContentsMargins(12, 4, 6, 14); lay.setSpacing(4)
        nuevo = N.Button("Nuevo agente", icono="plus", radio=16, color_icono=ACENTO)
        nuevo.setToolTip("Empieza como copia del Coach: verás todo lo que ya tiene "
                         "y decides qué cambiar.")
        nuevo.clicked.connect(self._ag_add)
        lay.addWidget(nuevo)
        lay.addSpacing(6)
        cap = QtWidgets.QLabel("AGENTES")
        cf = cap.font(); cf.setPixelSize(10); cf.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 1.8)
        cap.setFont(cf)
        cap.setStyleSheet(f"color: {TXT_FA}; background: transparent; padding-left: 22px;")
        lay.addWidget(cap)
        self.lista = QtWidgets.QScrollArea()
        self.lista.setWidgetResizable(True)
        self.lista.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.lista.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.lista.setStyleSheet("QScrollArea { background: transparent; }" + N.qss_campo())
        self.lista.viewport().setStyleSheet("background: transparent;")
        lay.addWidget(self.lista, 1)
        self.nav_ajustes = NavItem("cog", "Ajustes")
        self.nav_ajustes.clicked.connect(self.ir_a_ajustes)
        lay.addWidget(self.nav_ajustes)
        self._rellenar_lista()
        return side

    def _rellenar_lista(self):
        inner = QtWidgets.QWidget(); inner.setStyleSheet("background: transparent;")
        v = QtWidgets.QVBoxLayout(inner); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        self._filas_agente, self._filas_sesion = {}, {}
        ids = {a["id"] for a in self.agents}
        for a in self.agents:
            fila = NavItem("chat", a["name"])
            fila.setObjectName("agente")
            fila.setProperty("agente", a["id"])
            fila.clicked.connect(lambda aid=a["id"]: self.abrir_agente(aid))
            self._filas_agente[a["id"]] = fila
            v.addWidget(fila)
            for s in [s for s in self.sesiones if s["agent"] == a["id"]][:REUNIONES_POR_AGENTE]:
                v.addWidget(self._fila_sesion(s))
        huerfanas = [s for s in self.sesiones if s["agent"] not in ids]
        if huerfanas:
            otras = QtWidgets.QLabel("OTRAS REUNIONES")
            of = otras.font(); of.setPixelSize(10)
            of.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 1.8); otras.setFont(of)
            otras.setStyleSheet(f"color: {TXT_FA}; background: transparent; "
                                f"padding: 14px 0 4px 22px;")
            v.addWidget(otras)
            for s in huerfanas[:REUNIONES_POR_AGENTE]:
                v.addWidget(self._fila_sesion(s))
        v.addStretch()
        self.lista.setWidget(inner)
        self._marcar_activos()

    def _fila_sesion(self, s):
        fila = SessionItem(s)
        fila.clicked.connect(lambda sid=s["id"]: self.abrir_sesion(sid))
        self._filas_sesion[s["id"]] = fila
        return fila

    def _marcar_activos(self):
        tipo, cual = self.vista
        for aid, fila in self._filas_agente.items():
            fila.set_active(tipo == "agente" and aid == cual)
        for sid, fila in self._filas_sesion.items():
            fila.set_active(tipo == "sesion" and sid == cual)
        self.nav_ajustes.set_active(tipo == "ajustes")

    # ---------------------------------------------------- navegacion
    def abrir_agente(self, aid, pestana=None):
        self.vista = ("agente", aid)
        if pestana:
            self.pestana = pestana
        self._mostrar()

    def abrir_sesion(self, sid):
        self.vista = ("sesion", sid)
        self._mostrar()

    def ir_a_ajustes(self):
        self.vista = ("ajustes", None)
        self._mostrar()

    def agente_actual(self):
        """El agente con el que arrancaria la reunion ahora mismo."""
        tipo, cual = self.vista
        if tipo == "agente" and self._ag_get(cual):
            return cual
        if tipo == "sesion":
            s = next((x for x in self.sesiones if x["id"] == cual), None)
            if s and self._ag_get(s["agent"]):
                return s["agent"]
        return self.values.get("agent") or self.agents[0]["id"]

    def refrescar(self, abrir_ultima=False):
        """Tras una reunion: relee el historial y, si se pide, abre la ultima."""
        self.sesiones = sesiones.listar()
        if abrir_ultima and self.sesiones:
            self.vista = ("sesion", self.sesiones[0]["id"])
        self._rellenar_lista()
        self._mostrar()

    def mostrar_aviso(self, texto):
        """Mensaje que no se puede perder (falta una clave...): arriba del todo."""
        self._aviso = texto
        self._mostrar()

    def _mostrar(self):
        # Al cambiar de vista Qt destruye los widgets anteriores: soltar las
        # referencias o el siguiente cambio de valor tocaria widgets muertos.
        self._condicionales = []
        tipo, cual = self.vista
        if tipo == "agente" and not self._ag_get(cual):
            self.vista = tipo, cual = ("agente", self.agents[0]["id"])
        if tipo == "sesion" and not any(s["id"] == cual for s in self.sesiones):
            self.vista = tipo, cual = ("agente", self.agente_actual())
        if tipo == "agente":
            pagina = self._vista_agente(self._ag_get(cual))
        elif tipo == "sesion":
            pagina = self._vista_sesion(cual)
        else:
            pagina = self._vista_ajustes()
        self.content.setWidget(pagina)
        self._marcar_activos()

    def _pagina(self):
        page = QtWidgets.QWidget(); page.setStyleSheet("background: transparent;")
        v = QtWidgets.QVBoxLayout(page); v.setContentsMargins(22, 6, 30, 24); v.setSpacing(10)
        if self._aviso:
            aviso = QtWidgets.QLabel(self._aviso)
            aviso.setObjectName("aviso")
            aviso.setWordWrap(True)
            aviso.setStyleSheet(
                f"color: {N.PELIGRO}; background: rgba(224,96,122,0.10); "
                f"border-radius: 12px; padding: 10px 14px; font-size: 13px;")
            v.addWidget(aviso)
        return page, v

    def _heading(self, label, desc):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w); v.setContentsMargins(4, 0, 0, 0); v.setSpacing(4)
        h = QtWidgets.QLabel(label)
        hf = h.font(); hf.setPixelSize(22); hf.setWeight(QtGui.QFont.DemiBold); h.setFont(hf)
        h.setStyleSheet(f"color: {TXT_BR}; background: transparent;")
        v.addWidget(h)
        if desc:
            d = QtWidgets.QLabel(desc); d.setWordWrap(True); d.setMaximumWidth(620)
            d.setStyleSheet(f"color: {N.APAGADO}; font-size: 13px; background: transparent;")
            # Un QLabel con salto de linea no reserva su alto: en una pagina
            # llena el layout lo aplastaba y se cortaba la segunda linea.
            d.setMinimumHeight(d.heightForWidth(620))
            v.addWidget(d)
        return w

    # ---------------------------------------------------- vista: agente
    def _vista_agente(self, a):
        page, v = self._pagina()
        top = QtWidgets.QHBoxLayout(); top.setSpacing(8)
        name = QtWidgets.QLineEdit(a["name"])
        name.setObjectName("nombre-agente")
        name.setStyleSheet(N.qss_campo() + "QLineEdit { font-weight: 600; font-size: 18px; }")
        name.textChanged.connect(lambda t, aid=a["id"]: self._ag_set(aid, "name", t))
        top.addWidget(N.campo(name), 1)
        dup = N.Button(icono="duplicate", redondo=26, prof=3, color_icono=N.APAGADO)
        dup.setToolTip("Duplicar")
        dup.clicked.connect(lambda _c=False, aid=a["id"]: self._ag_dup(aid))
        top.addWidget(dup)
        borrar = ConfirmDelete(26)
        borrar.setObjectName("borrar-agente")
        borrar.setEnabled(len(self.agents) > 1)     # siempre queda al menos uno
        borrar.confirmed.connect(lambda aid=a["id"]: self._ag_del(aid))
        top.addWidget(borrar)
        top.addSpacing(6)
        iniciar = N.Button("Iniciar reunión", icono="play", variante="acento", radio=16)
        iniciar.setObjectName("iniciar")
        iniciar.setToolTip("Empieza la reunión con este agente (Bloq Mayús+Esc)")
        iniciar.clicked.connect(lambda _c=False, aid=a["id"]: self.iniciar(aid))
        top.addWidget(iniciar)
        v.addLayout(top)

        n_docs = len(a["conocimiento"])
        tabs = Segmented([("instrucciones", "Instrucciones"), ("reglas", "Reglas"),
                          ("conocimiento", f"Conocimiento · {n_docs}" if n_docs else "Conocimiento")],
                         self.pestana)
        tabs.setObjectName("pestanas")
        tabs.changed.connect(lambda p, aid=a["id"]: self.abrir_agente(aid, p))
        fila = QtWidgets.QHBoxLayout(); fila.addWidget(tabs); fila.addStretch()
        v.addLayout(fila)

        if self.pestana == "conocimiento":
            v.addLayout(self._conocimiento(a), 1)
        else:
            campo = self.pestana
            if campo == "instrucciones":
                ayuda = "Personalidad, tono y cómo responde. Lo que pongas aquí manda."
            else:
                ayuda = ("Cómo funciona la conversación, el formato con secciones «##», "
                         "el código y las capturas. La app depende de ellas: si las "
                         "cambias, puede dejar de pintar bien las respuestas.")
            v.addLayout(self._cabecera_campo(a, campo, ayuda))
            texto = QtWidgets.QPlainTextEdit(a[campo])
            texto.setObjectName(campo)
            texto.setMinimumHeight(300)
            texto.setStyleSheet(N.qss_campo(mono=campo == "reglas"))
            texto.textChanged.connect(
                lambda aid=a["id"], w=texto, c=campo: self._ag_set(aid, c, w.toPlainText()))
            v.addWidget(N.campo(texto), 1)
        return page

    def _cabecera_campo(self, a, campo, ayuda):
        head = QtWidgets.QHBoxLayout(); head.setSpacing(10)
        h = QtWidgets.QLabel(ayuda); h.setWordWrap(True)
        h.setStyleSheet(f"color: {N.APAGADO}; font-size: 12px; background: transparent; "
                        f"padding-left: 4px;")
        head.addWidget(h, 1)
        rest = N.Button("Restaurar", radio=12, prof=3)
        f = rest.font(); f.setPixelSize(12); rest.setFont(f)
        rest.setObjectName(f"restaurar-{campo}")
        rest.setEnabled(a[campo] != agents_mod.predeterminado(a)[campo])
        rest.setToolTip(f"Vuelve al texto de «{agents_mod.predeterminado(a)['name']}»")
        rest.clicked.connect(lambda _c=False, aid=a["id"], c=campo: self._ag_restore(aid, c))
        head.addWidget(rest, 0, QtCore.Qt.AlignTop)
        return head

    def _conocimiento(self, a):
        grid = QtWidgets.QHBoxLayout(); grid.setSpacing(16)
        col = QtWidgets.QVBoxLayout(); col.setSpacing(2)
        ayuda = QtWidgets.QLabel("Documentos que este agente lee al empezar la reunión: "
                                 "tu CV, la oferta, el producto…")
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(f"color: {N.APAGADO}; font-size: 12px; background: transparent; "
                            f"padding: 0 4px 6px 4px;")
        col.addWidget(ayuda)
        add = N.Button("Añadir documento", icono="plus", radio=14, color_icono=ACENTO)
        add.setObjectName("anadir-documento")
        add.clicked.connect(lambda _c=False, aid=a["id"]: self._doc_add(aid))
        col.addWidget(add)
        docs = a["conocimiento"]
        if self.sel_doc not in {d["id"] for d in docs}:
            self.sel_doc = docs[0]["id"] if docs else None
        for d in docs:
            col.addWidget(self._tarjeta_doc(a, d))
        total = sum(ctx_mod.estimate_tokens(d["body"]) for d in docs)
        resumen = QtWidgets.QLabel(f"~{total} tokens en total")
        resumen.setStyleSheet(f"color: {ACENTO}; font-family: {MONO}; font-size: 11px; "
                              f"background: transparent; padding: 8px 6px 0 6px;")
        col.addWidget(resumen)
        if total > AVISO_TOKENS:
            warn = QtWidgets.QLabel("⚠ Mucho texto: sube el coste y el tiempo de la "
                                    "primera respuesta.")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {N.AVISO}; font-size: 11px; background: transparent; "
                               f"padding: 0 6px;")
            col.addWidget(warn)
        col.addStretch()
        lista = QtWidgets.QWidget(); lista.setFixedWidth(270); lista.setLayout(col)
        grid.addWidget(lista)
        grid.addWidget(self._editor_doc(a), 1)
        return grid

    def _tarjeta_doc(self, a, d):
        elegido = d["id"] == self.sel_doc
        card = N.Surface("hundido" if elegido else "relieve", radio=14, prof=4,
                         margen=N.margen_relieve(4))
        card.setObjectName("documento")
        card.setCursor(QtCore.Qt.PointingHandCursor)
        card.mousePressEvent = lambda e, did=d["id"], aid=a["id"]: self._doc_select(aid, did)
        lay = QtWidgets.QHBoxLayout(card); lay.setContentsMargins(12, 6, 4, 6); lay.setSpacing(4)
        col = QtWidgets.QVBoxLayout(); col.setSpacing(0)
        nm = QtWidgets.QLabel(d["name"])
        nm.setStyleSheet(f"color: {ACENTO if elegido else N.TITULO}; font-weight: 600; "
                         f"font-size: 13px; background: transparent;")
        tk = QtWidgets.QLabel(f"~{ctx_mod.estimate_tokens(d['body'])} tok")
        tk.setStyleSheet(f"color: {TXT_FA}; font-family: {MONO}; font-size: 10px; "
                         f"background: transparent;")
        col.addWidget(nm); col.addWidget(tk)
        lay.addLayout(col, 1)
        borrar = ConfirmDelete(22)
        borrar.confirmed.connect(lambda aid=a["id"], did=d["id"]: self._doc_del(aid, did))
        lay.addWidget(borrar)
        return card

    def _editor_doc(self, a):
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(8)
        d = next((x for x in a["conocimiento"] if x["id"] == self.sel_doc), None)
        if d is None:
            vacio = QtWidgets.QLabel("Este agente aún no tiene documentos.\n"
                                     "Añade tu CV, la oferta o lo que deba saber.")
            vacio.setAlignment(QtCore.Qt.AlignCenter)
            vacio.setStyleSheet(f"color: {TXT_FA}; font-size: 13px; background: transparent;")
            hueco = N.Surface("hundido", radio=18, prof=5, margen=2)
            QtWidgets.QVBoxLayout(hueco).addWidget(vacio)
            v.addWidget(hueco, 1)
            return box
        nombre = QtWidgets.QLineEdit(d["name"])
        nombre.setObjectName("nombre-documento")
        nombre.setStyleSheet(N.qss_campo() + "QLineEdit { font-weight: 600; font-size: 14px; }")
        nombre.textChanged.connect(
            lambda t, aid=a["id"], did=d["id"]: self._doc_set(aid, did, "name", t))
        v.addWidget(N.campo(nombre))
        cuerpo = QtWidgets.QPlainTextEdit(d["body"])
        cuerpo.setObjectName("cuerpo-documento")
        cuerpo.setPlaceholderText("# Mi CV\nSoy desarrollador backend con 6 años…")
        cuerpo.setStyleSheet(N.qss_campo(mono=True))
        cuerpo.textChanged.connect(
            lambda aid=a["id"], did=d["id"], w=cuerpo: self._doc_set(aid, did, "body",
                                                                     w.toPlainText()))
        v.addWidget(N.campo(cuerpo), 1)
        return box

    # ---------------------------------------------------- vista: reunion
    def _vista_sesion(self, sid):
        page, v = self._pagina()
        s = next(x for x in self.sesiones if x["id"] == sid)
        top = QtWidgets.QHBoxLayout(); top.setSpacing(8)
        agente = self._ag_get(s["agent"])
        sub = " · ".join(x for x in (sesiones.etiqueta_fecha(s["started"]),
                                     agente["name"] if agente else s["agent_name"]) if x)
        top.addWidget(self._heading(s["title"], sub), 1)
        borrar = ConfirmDelete(26)
        borrar.setObjectName("borrar-sesion")
        borrar.confirmed.connect(lambda: self._sesion_del(sid))
        top.addWidget(borrar, 0, QtCore.Qt.AlignTop)
        v.addLayout(top)
        try:
            texto = sesiones.leer(sid)
        except OSError:
            texto = "No se pudo leer esta reunión."
        lector = QtWidgets.QTextBrowser()
        lector.setObjectName("transcripcion")
        lector.setOpenExternalLinks(False)
        lector.setMarkdown(texto)
        lector.setStyleSheet(N.qss_campo().replace("QPlainTextEdit", "QTextBrowser")
                             + "QTextBrowser { font-size: 13px; }")
        caja = N.campo(lector)
        v.addWidget(caja, 1)
        return page

    # ---------------------------------------------------- vista: ajustes
    def _vista_ajustes(self):
        page, v = self._pagina()
        v.addWidget(self._heading("Ajustes", "Lo que cambies aquí vale para la próxima reunión."))
        for titulo, desc, campos in _ajustes():
            cap = QtWidgets.QLabel(titulo.upper())
            cf = cap.font(); cf.setPixelSize(10)
            cf.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 1.8); cap.setFont(cf)
            cap.setStyleSheet(f"color: {TXT_FA}; background: transparent; padding: 10px 0 0 6px;")
            v.addWidget(cap)
            tarjeta = N.Surface("relieve", radio=22, prof=7)
            tv = QtWidgets.QVBoxLayout(tarjeta); tv.setContentsMargins(26, 8, 22, 8); tv.setSpacing(0)
            for f in campos:
                fila = self._field_row(f)
                tv.addWidget(fila)
                if f.get("visible_si"):
                    self._condicionales.append((fila, f["visible_si"]))
            v.addWidget(tarjeta)
        v.addStretch()
        self._aplicar_visibilidad()
        return page

    def _aplicar_visibilidad(self):
        for fila, (clave, valor) in self._condicionales:
            fila.setVisible(self.values.get(clave) == valor)

    def _field_row(self, f):
        row = QtWidgets.QWidget()
        row.setObjectName("fila")
        row.setProperty("clave", f["key"])
        lay = QtWidgets.QHBoxLayout(row); lay.setContentsMargins(0, 14, 0, 14); lay.setSpacing(24)
        left = QtWidgets.QWidget(); left.setMaximumWidth(360)
        lv = QtWidgets.QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(3)
        name = QtWidgets.QLabel(f["label"])
        nf = name.font(); nf.setPixelSize(14); nf.setWeight(QtGui.QFont.DemiBold); name.setFont(nf)
        name.setStyleSheet(f"color: {TXT_LB}; background: transparent;")
        lv.addWidget(name)
        hint = QtWidgets.QLabel(f["hint"]); hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {N.APAGADO}; font-size: 12px; background: transparent;")
        lv.addWidget(hint)
        lay.addWidget(left, 1)
        lay.addWidget(self._control(f), 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
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
        return QtWidgets.QWidget()

    def _set_value(self, key, v):
        self.values[key] = v
        self._aplicar_visibilidad()    # un valor puede mostrar u ocultar filas
        self._marcar()

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
        # Pista hundida, tramo recorrido en pervinca y tirador blanco.
        return (f"QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; "
                f"background: #D3DAE8; }} "
                f"QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -6px 0; "
                f"border-radius: 9px; background: #FFFFFF; border: 1px solid #D5DCEA; }} "
                f"QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                f"stop:0 {N.ACENTO_LT}, stop:1 {N.ACENTO}); border-radius: 3px; }}")

    # ---------------------------------------------------- acciones: agentes
    def _ag_get(self, aid):
        return next((a for a in self.agents if a["id"] == aid), None)

    def _ag_set(self, aid, campo, valor):
        # Sin redibujar: se perderia el cursor del campo que se esta escribiendo.
        a = self._ag_get(aid)
        if a is None:
            return
        a[campo] = valor
        if campo == "name" and aid in self._filas_agente:
            self._filas_agente[aid].set_text(valor)
        self._marcar()

    def _ag_restore(self, aid, campo):
        a = self._ag_get(aid)
        if a is not None:
            a[campo] = agents_mod.predeterminado(a)[campo]
            self._marcar()
            self._mostrar()

    def _ag_add(self):
        a = agents_mod.nuevo(self.agents)
        self.agents.append(a)
        self.pestana = "instrucciones"
        self.vista = ("agente", a["id"])
        self._marcar()
        self._rellenar_lista()
        self._mostrar()
        campo = self.content.widget().findChild(QtWidgets.QLineEdit, "nombre-agente")
        if campo is not None:
            campo.setFocus(); campo.selectAll()

    def _ag_dup(self, aid):
        src = self._ag_get(aid)
        if src is None:
            return
        copia = dict(src, id=agents_mod.next_id(self.agents), name=src["name"] + " (copia)",
                     conocimiento=[dict(d) for d in src["conocimiento"]])
        self.agents.insert(self.agents.index(src) + 1, copia)
        self.vista = ("agente", copia["id"])
        self._marcar()
        self._rellenar_lista()
        self._mostrar()

    def _ag_del(self, aid):
        if len(self.agents) <= 1:
            return
        self.agents = [a for a in self.agents if a["id"] != aid]
        if self.values.get("agent") == aid:
            self.values["agent"] = self.agents[0]["id"]
        self.vista = ("agente", self.values["agent"])
        self._marcar()
        self._rellenar_lista()
        self._mostrar()

    # ---------------------------------------------------- acciones: conocimiento
    def _doc_add(self, aid):
        a = self._ag_get(aid)
        doc = agents_mod.nuevo_documento(a)
        a["conocimiento"].append(doc)
        self.sel_doc = doc["id"]
        self._marcar()
        self._mostrar()

    def _doc_select(self, aid, did):
        self.sel_doc = did
        self._mostrar()

    def _doc_set(self, aid, did, campo, valor):
        a = self._ag_get(aid)
        d = next((x for x in a["conocimiento"] if x["id"] == did), None) if a else None
        if d is not None:
            d[campo] = valor
            self._marcar()

    def _doc_del(self, aid, did):
        a = self._ag_get(aid)
        if a is not None:
            a["conocimiento"] = [d for d in a["conocimiento"] if d["id"] != did]
            self._marcar()
            self._mostrar()

    # ---------------------------------------------------- acciones: reuniones
    def _sesion_del(self, sid):
        sesiones.borrar(sid)
        s = next((x for x in self.sesiones if x["id"] == sid), None)
        self.sesiones = [x for x in self.sesiones if x["id"] != sid]
        self.vista = ("agente", s["agent"] if s and self._ag_get(s["agent"])
                      else self.agente_actual())
        self._rellenar_lista()
        self._mostrar()

    def iniciar(self, aid=None):
        """Guarda lo pendiente y pide empezar la reunion con ese agente."""
        aid = aid or self.agente_actual()
        self.values["agent"] = aid
        self._marcar()
        self.guardar_ya()
        self._aviso = ""
        self.startMeeting.emit(aid)

    # ---------------------------------------------------- guardado automatico
    def _marcar(self, *_):
        self._error = None
        self._dirty = True
        self._pintar_guardado()
        self._guardado.start()

    def guardar_ya(self):
        """Escribe ya lo pendiente (config y agentes). True si quedo guardado."""
        self._guardado.stop()
        if not self._dirty:
            return True
        try:
            self.cfg.update(self.values)
            if not cfg_mod.save_config(self.cfg):
                raise IOError("no se pudo escribir config.json")
            agents_mod.write_all(self.agents)
        except Exception as e:
            self._error = f"Error al guardar: {e}"
            self._pintar_guardado()
            return False
        self._dirty = False
        self._pintar_guardado()
        self.saved.emit()
        return True

    def _pintar_guardado(self):
        if not hasattr(self, "saved_lbl"):
            return
        if self._error:
            color, texto = N.PELIGRO, self._error
        elif self._dirty:
            color, texto = N.AVISO, "Guardando…"
        else:
            color, texto = N.OK, "Todo guardado"
        self.saved_dot.set_color(color)
        self.saved_lbl.setText(texto)
        self.saved_lbl.setStyleSheet(
            f"color: {color if self._error else TXT_FA}; font-size: 12px; background: transparent;")

    def _cerrar_app(self):
        self.guardar_ya()
        self.closeApp.emit()

    def hideEvent(self, e):
        # Al ocultarse (empieza la reunion) o minimizar, nada queda sin guardar.
        self.guardar_ya()
        super().hideEvent(e)
