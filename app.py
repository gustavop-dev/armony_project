"""Meeting Coach - overlay de entrevista.

Implementa el diseno 'Interview Overlay.dc.html': dos paneles flotantes
translucidos, siempre encima e invisibles al compartir pantalla.

Atajos (convertidos de Mac a Windows):
    Ctrl+B      mostrar / ocultar overlay
    Ctrl+H      captura de pantalla y consulta al modelo
    Ctrl+Enter  generar respuesta
"""
import logging
import sys

from PySide6 import QtCore, QtGui, QtWidgets

import agents as agents_mod
import applog
import avatares
import config as cfg_mod
import theme as T
from engine import CoachEngine
from overlay import (devolver_foco, set_acrylic, set_capture_protection,
                     set_click_through, set_no_activate, traer_al_frente,
                     vidrio_disponible)
from wheelscroll import WheelForwarder
from overlay_ui import AskPanel, TopBar, TranscriptPanel, CollapsedButton
from home_window import HomeWindow
import hotkeys as HK

log = logging.getLogger("armony.app")

# La caja de preguntas se abre con un cuarto del alto de la pantalla (lo justo
# para escribir) y, cuando llega una respuesta, crece hasta la mitad de la
# columna: en un cuarto solo caben cuatro lineas. Con pantallas muy bajas, ni
# ella ni el hablado bajan de esto.
ALTO_MIN_PREGUNTA = 150
ALTO_MIN_VOZ = 260


class OverlayApp(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.cfg = cfg_mod.load_config()
        self.engine = CoachEngine()

        # Vidrio solo si este Windows sigue ocultando al compartir pantalla una
        # ventana translucida; se decide antes de crear las ventanas.
        if not T.VIDRIO and vidrio_disponible():
            T.activar_vidrio()

        self.top = TopBar()
        # Dos paneles: la conversacion hablada (siempre) y la pantalla (solo
        # cuando se usan pantallazos; entonces el hablado se pasa a la izquierda).
        self.panel = TranscriptPanel()
        self.screen = TranscriptPanel(modo="pantalla")
        # La caja de preguntas escritas (Bloq Mayus+E): solo mientras se usa,
        # debajo del hablado, que le cede un cuarto del alto de la pantalla.
        self.ask = AskPanel()
        self._alto_voz = None        # alto del hablado antes de partir la columna
        self._foco_previo = 0        # la ventana a la que se le devuelve el teclado
        self._ask_oculta = False     # estaba abierta al ocultar el overlay
        self._preguntando = False    # hay una respuesta en camino en la caja
        self._preguntas_en_cola = []  # las escritas mientras tanto, en orden
        self._caja_grande = False    # hay respuesta que leer: media columna
        self.collapsed = CollapsedButton()
        self._modo_pantalla = False

        self._visible = True
        self._running = False
        # Atajos globales (hotkeys.GlobalHotkeys), solo activos en la reunion:
        # fuera de ella Bloq Mayus y Alt+1..7 son de las demas apps.
        self.atajos = None
        self._elapsed = 0
        self._responding = False
        self._shots = []          # capturas acumuladas, pendientes de enviar
        self._capturas_reunion = 0  # todas las de la reunion (titulo del panel)
        self._answer_lleva_capturas = False   # la respuesta en curso las ilustra

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._place()
        self._wire()
        self._protect()
        self._apply_opacity()

        self.panel.set_status("Idle")
        self._refresh_agents()

        # Se aterriza en la Home (agentes, historial, ajustes); el overlay solo
        # aparece durante la reunion.
        agents_mod.migrar_contextos(self.cfg.get("agent"))
        self.home = HomeWindow(self.cfg)
        self.home.startMeeting.connect(self.start_meeting)
        self.home.closeApp.connect(self._quit_app)
        self.home.saved.connect(self._on_home_saved)
        self.home.proteger_ventana = lambda ventana: set_capture_protection(
            ventana.winId(), bool(self.cfg.get("invisible_on_share", True)))
        set_capture_protection(self.home.winId(),
                               bool(self.cfg.get("invisible_on_share", True)))
        self.home.show()

        # Click-through: la app es "de cristal" salvo en los controles (grip,
        # engranaje, boton de restaurar). Un temporizador comprueba donde esta el
        # cursor y enciende/apaga el paso de clics por ventana.
        self._ct_state = {}
        self._ct_timer = QtCore.QTimer(self)
        self._ct_timer.timeout.connect(self._update_click_through)
        self._ct_timer.start(30)

        # La rueda sobre la respuesta la desvia un hook: con click-through la
        # ventana no recibe raton, ni siquiera la rueda.
        self.wheel = WheelForwarder(self._scroll_zone)
        self.wheel.install()

    # ------------------------------------------------ colocacion en pantalla
    def _place(self):
        geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.top.adjustSize()
        self.top.move(geo.x() + (geo.width() - self.top.width()) // 2,
                      geo.y() + T.TOP_OFFSET)
        self._place_columns()

        self.collapsed.adjustSize()
        self.collapsed.move(geo.x() + (geo.width() - self.collapsed.width()) // 2,
                            geo.y() + T.TOP_OFFSET)

    def _place_columns(self):
        """Columnas a los lados; el centro (la llamada, el editor) queda libre.

        Solo el hablado: a la derecha. Con la pantalla activa: el hablado a la
        izquierda y la pantalla, mas ancha para el codigo, a la derecha.
        """
        geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
        arriba = geo.y() + T.TOP_OFFSET + self.top.height() + T.COLUMN_GAP
        alto = geo.y() + geo.height() - T.BOTTOM_OFFSET - arriba
        hueco = geo.width() - 3 * T.SIDE_MARGIN
        ancho_voz = min(T.COLUMN_WIDTH, hueco // 2)
        ancho_pant = min(T.SCREEN_WIDTH, hueco - ancho_voz)
        derecha = geo.x() + geo.width() - T.SIDE_MARGIN
        if self._modo_pantalla:
            self.panel.setGeometry(geo.x() + T.SIDE_MARGIN, arriba, ancho_voz, alto)
            self._pegar_derecha(self.screen, derecha, arriba, ancho_pant, alto)
        else:
            self._pegar_derecha(self.panel, derecha, arriba, ancho_voz, alto)
        if self.ask.isVisible() or self._ask_oculta:
            self._alto_voz = None             # la columna se acaba de recolocar
            self._partir_columna()

    def _partir_columna(self):
        """La caja de preguntas, debajo del hablado y con su mismo ancho: un
        cuarto del alto de la pantalla, que el hablado cede mientras esta
        abierta (ver _cerrar_columna)."""
        geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
        g = self.panel.geometry()
        completo = self._alto_voz or g.height()
        self._alto_voz = completo
        alto_caja = max(ALTO_MIN_PREGUNTA, geo.height() // 4)
        if self._caja_grande:
            alto_caja = max(alto_caja, completo // 2)
        self.panel.resize(g.width(), max(ALTO_MIN_VOZ, completo - alto_caja - T.COLUMN_GAP))
        arriba = g.y() + self.panel.height() + T.COLUMN_GAP
        self.ask.setGeometry(g.x(), arriba, g.width(),
                             max(ALTO_MIN_PREGUNTA, g.y() + completo - arriba))

    def _cerrar_columna(self):
        """El hablado recupera el alto que le cedio a la caja."""
        if self._alto_voz:
            self.panel.resize(self.panel.width(), self._alto_voz)
        self._alto_voz = None

    @staticmethod
    def _pegar_derecha(panel, derecha, arriba, ancho, alto):
        """Columna pegada al borde derecho. Si el contenido pide mas ancho del
        previsto, crece hacia dentro, nunca por fuera de la pantalla."""
        panel.setGeometry(derecha - ancho, arriba, ancho, alto)
        if panel.width() != ancho:
            panel.move(derecha - panel.width(), arriba)

    def set_screen_mode(self, activo):
        """Muestra (o retira) el panel de la pantalla y recoloca el hablado."""
        if activo == self._modo_pantalla:
            return
        self._modo_pantalla = activo
        self._place_columns()
        if activo and self._visible:
            self.screen.show()
        elif not activo:
            self.screen.hide()

    def _scroll_zone(self, nombre, muescas):
        """La rueda va al panel cuya zona esta bajo el cursor ("modo:zona")."""
        if nombre.startswith("pantalla:"):
            panel = self.screen
        elif nombre.startswith("pregunta:"):
            panel = self.ask
        else:
            panel = self.panel
        panel.scroll_zone(nombre, muescas)

    def _protect(self):
        """Excluye las ventanas de la captura de pantalla y evita que tomen el foco."""
        activo = bool(self.cfg.get("invisible_on_share", True))
        for w in (self.top, self.panel, self.screen, self.collapsed, self.ask):
            set_capture_protection(w.winId(), activo)
            # El overlay nunca roba el foco: al pulsar un boton sigues "dentro"
            # de la aplicacion en la que estabas trabajando. Salvo la caja de
            # preguntas, que es para escribir en ella.
            if w is not self.ask:
                set_no_activate(w.winId())

    def _apply_opacity(self):
        op = float(self.cfg.get("window_opacity", 0.30))
        op = max(0.15, min(1.0, op))
        for w in (self.top, self.panel, self.screen, self.collapsed, self.ask):
            if T.VIDRIO:
                # La opacidad pasa al tinte del acrilico: el texto no se atenua.
                w.setWindowOpacity(1.0)
                set_acrylic(w.winId(), alpha=0.15 + op * 0.75)
            else:
                w.setWindowOpacity(op)

    def _cursor_over(self, widgets):
        """True si el cursor esta sobre alguno de esos widgets (visibles)."""
        pos = QtGui.QCursor.pos()
        for w in widgets:
            if w is not None and w.isVisible():
                tl = w.mapToGlobal(QtCore.QPoint(0, 0))
                if QtCore.QRect(tl, w.size()).contains(pos):
                    return True
        return False

    def _update_click_through(self):
        # Durante un arrastre (boton pulsado) no cambiamos el estado, para no
        # cortar el movimiento a medio camino.
        if QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton:
            return
        zonas_rueda = ((self.panel.wheel_zones() + self.screen.wheel_zones()
                        + self.ask.wheel_zones()) if self._running else [])
        objetivos = [
            (self.top, self.top.interactive_widgets()),
            (self.panel, self.panel.interactive_widgets()),
            (self.screen, self.screen.interactive_widgets()),
            (self.ask, self.ask.interactive_widgets()),
            (self.collapsed, [self.collapsed]),   # el boton de restaurar, entero
        ]
        for win, zonas in objetivos:
            if not win.isVisible():
                continue
            interactivo = self._cursor_over(zonas)
            if win in (self.panel, self.screen, self.ask) and interactivo:
                # Con el panel activo, Qt ya recibe la rueda por su cuenta: si
                # ademas la desviara el hook, cada muesca contaria dos veces.
                zonas_rueda = []
            # click_through activo = NO interactivo (deja pasar el clic)
            deseado = not interactivo
            if self._ct_state.get(win) != deseado:
                set_click_through(win.winId(), deseado)
                self._ct_state[win] = deseado
        self.wheel.set_zones(zonas_rueda)

    # ------------------------------------------------ conexiones
    def _wire(self):
        self.top.startStopClicked.connect(self.toggle_meeting)
        self.top.screenshotClicked.connect(self.take_shot)
        self.top.toggleClicked.connect(self.toggle_overlay)
        self.top.generateClicked.connect(self.generate)
        self.top.answerNowClicked.connect(self.answer_now)
        self.top.askClicked.connect(self.toggle_ask)
        self.collapsed.clicked.connect(self.toggle_overlay)
        self.ask.submitted.connect(self.ask_question)
        self.ask.closeClicked.connect(self.close_ask)
        for chip in (self.screen.modo_chip, self.ask.modo_chip):
            chip.changed.connect(self.set_resolucion)

        e = self.engine
        e.sysLevel.connect(self.panel.set_level)
        e.micLevel.connect(self.panel.set_mic_level)
        e.sttLatency.connect(self.on_latency)
        e.e2eLatency.connect(lambda ms: self._running and self.panel.set_e2e(ms))
        e.transcript.connect(self.on_transcript)
        e.partial.connect(self.on_partial)
        e.noAnswer.connect(self.on_no_answer)
        e.respStart.connect(self.on_resp_start)
        e.respRevise.connect(self.on_resp_revise)
        e.respDelta.connect(self.panel.append_answer)
        e.respDone.connect(self.on_resp_done)
        e.shotStart.connect(self.on_shot_start)
        e.shotRevise.connect(self.on_shot_revise)
        e.shotDelta.connect(self.screen.append_answer)
        e.shotDone.connect(self.on_shot_done)
        e.screenSuggest.connect(self.on_screen_suggest)
        e.askStart.connect(self.on_ask_start)
        e.askDelta.connect(self.ask.append_answer)
        e.askDone.connect(self.on_ask_done)
        e.askError.connect(self.on_ask_error)
        # Las notas se generan cuando la Home ya esta a la vista.
        e.notesStarted.connect(lambda sid: self.home.notas_en_curso(sid))
        e.notesReady.connect(lambda sid, ok: self.home.notas_listas(sid, ok))
        e.status.connect(self.on_status)
        e.error.connect(self.on_error)
        self.screen.relaunchClicked.connect(self.relaunch_screen)
        self.screen.closeClicked.connect(lambda: self.set_screen_mode(False))
        self.panel.agentChosen.connect(self.choose_agent)
        # El menu de agentes es otra ventana: tan invisible al compartir como
        # el resto del overlay.
        self.panel.agent_chip.antes_de_mostrar = lambda menu: set_capture_protection(
            menu.winId(), bool(self.cfg.get("invisible_on_share", True)))

    # ------------------------------------------------ agentes
    def _refresh_agents(self):
        """El selector del panel, con los agentes del disco y el que esta en uso."""
        try:
            lista = agents_mod.list_agents()
        except OSError as e:
            log.warning("Agents not readable (%s)", type(e).__name__)
            return
        activo = agents_mod.get(self.cfg.get("agent"))["id"]
        self.panel.set_agents([(a["id"], a["name"], avatares.de_agente(a)) for a in lista],
                              activo)

    def choose_agent(self, agent_id):
        """Elegido en el overlay: se guarda y, si hay reunion, la siguiente
        respuesta ya sale con el (la conversacion sigue con todo lo hablado)."""
        cfg = cfg_mod.load_config()
        cfg["agent"] = agent_id
        if not cfg_mod.save_config(cfg):
            self.panel.aviso("Could not save the agent choice")
        self.cfg = cfg
        self._refresh_agents()
        # Es un aviso de paso, no un estado: el badge sigue diciendo que hace.
        if self.engine.set_agent(agent_id):
            self._mostrar_resolucion(self.engine.resolucion)   # la del agente nuevo
            agente = agents_mod.get(agent_id)
            hace = ("takes notes" if agents_mod.modo(agente) == agents_mod.NOTETAKER
                    else "answers")
            self.panel.aviso(f"{agente['name']} {hace} from now on")

    # ------------------------------------------------ acciones
    def toggle_meeting(self):
        if self._running:
            self.stop_meeting()
        else:
            self.start_meeting(self.home.agente_actual())

    def start_meeting(self, agent_id=None):
        """Desde la Home (boton Iniciar reunion): la Home se oculta y queda el
        overlay. Sin claves no arranca: se vuelve a Ajustes con el aviso."""
        self.home.guardar_ya()
        self.cfg = cfg_mod.load_config()
        if agent_id and agent_id != self.cfg.get("agent"):
            self.cfg["agent"] = agent_id
            cfg_mod.save_config(self.cfg)
        test = bool(self.cfg.get("test_mode", False))
        falta = None
        # En Modo prueba NO se necesita la key de OpenAI: arranca directo.
        if not test and not self.cfg.get("openai_api_key"):
            falta = "Añade tu API key de OpenAI para iniciar la reunión."
        elif not self.cfg.get("assemblyai_api_key"):
            falta = "Añade tu API key de AssemblyAI para iniciar la reunión."
        if falta:
            self.home.mostrar_aviso(falta)
            self.home.ir_a_ajustes()
            self._mostrar_home()
            return
        self.home.mostrar_aviso("")
        self.home.hide()
        self._visible = True
        self.collapsed.hide()
        self.top.show()
        self.panel.show()
        self._refresh_agents()
        self._running = True
        self._activar_atajos(True)
        self._elapsed = 0
        self.top.set_meeting(True)
        self.top.set_timer("00:00")
        self._timer.start(1000)
        self.panel.set_listening(True)
        self.panel.set_status("Loading…", "loading")   # feedback inmediato
        self.panel.limpiar_hilo()       # reunion nueva, conversacion nueva
        self.panel.hide_skip()
        self.screen.limpiar_hilo()
        self.screen.show_suggestion("")
        self.ask.hide()
        self.ask.limpiar_hilo()
        self._alto_voz = None
        self._ask_oculta = False
        self._preguntando = False
        self._preguntas_en_cola = []
        self._caja_grande = False
        self._capturas_reunion = 0
        self.screen.set_shots(0)
        self.set_screen_mode(False)     # vuelve a haber solo el hablado
        self._answer_lleva_capturas = False
        agente = agents_mod.get(self.cfg.get("agent"))
        self._mostrar_resolucion(agents_mod.resolucion(agente))
        n = len(agente["conocimiento"])
        chip = f"{n} document{'s' if n != 1 else ''} loaded · " if n else ""
        modo = agents_mod.modo(agente)
        if test:
            self.panel.set_hint("TEST MODE — audio + transcription only (no AI).")
        elif modo == agents_mod.NOTETAKER:
            self.panel.set_hint("Taking notes — no answers. The notes will be in the "
                                "Home when the meeting ends.")
        elif modo == agents_mod.MANUAL:
            self.panel.set_hint(chip + "Answers only when you ask — Caps+A.")
        else:
            self.panel.set_hint(chip + "Listening for the question — the answer will draft here.")
        self.engine.start(self.cfg, test_mode=test)

    # Nota: los mensajes de estado (set_status) van en ingles para una UI mas pulida,
    # aunque el reconocimiento de voz sigue soportando espanol e ingles.

    def stop_meeting(self):
        self._running = False        # a partir de aqui los eventos en cola se ignoran
        self._activar_atajos(False)
        self._timer.stop()
        self.top.set_meeting(False)
        self.panel.set_listening(False)
        self.panel.set_status("Idle")
        self.panel.clear_latency()
        self.panel.hide_skip()
        self.close_ask(devolver=False)   # el hablado recupera su alto
        self._ask_oculta = False
        self.engine.stop()          # deja la reunion en el historial
        # Fin de la reunion: fuera el overlay y de vuelta a la Home, con la
        # reunion recien terminada abierta.
        for w in (self.top, self.panel, self.screen, self.collapsed):
            w.hide()
        self.home.refrescar(abrir_ultima=True)
        self._mostrar_home()

    def _activar_atajos(self, on):
        if self.atajos is None:
            return
        ocupados = self.atajos.set_activo(on)
        if on and not self.atajos.hook_instalado:
            # Sin el hook no hay Bloq Mayus: quedan los Alt+1..7 de respaldo.
            aviso = "Caps Lock shortcuts unavailable — use Alt+1…7"
            if ocupados:
                aviso += f" (in use: {', '.join(ocupados)})"
            self.panel.aviso(aviso)

    def _mostrar_home(self):
        self.home.show()
        self.home.raise_()
        self.home.activateWindow()

    def _tick(self):
        self._elapsed += 1
        self.top.set_timer(f"{self._elapsed // 60:02d}:{self._elapsed % 60:02d}")

    def toggle_overlay(self):
        if not self._running:
            return                       # fuera de la reunion no hay overlay
        self._visible = not self._visible
        if self._visible:
            self.collapsed.hide()
            self.top.show()
            self.panel.show()
            if self._modo_pantalla:
                self.screen.show()
            if self._ask_oculta:
                self.ask.show()
            self._ask_oculta = False
        else:
            self._ask_oculta = self.ask.isVisible()
            self.top.hide()
            self.panel.hide()
            self.screen.hide()
            self.ask.hide()
            self.collapsed.show()

    def take_shot(self):
        """Guarda una captura en la cola. No genera nada todavia.

        Puedes encadenar varias (Bloq Mayus+S) y despues pulsar Generate: asi se
        manda todo junto, que es lo util cuando el enunciado no cabe en una
        sola pantalla.
        """
        if not self._running:
            return
        if not self.engine.permite_capturas:
            self.panel.aviso("This agent doesn't use screenshots")
            return
        # Sin destello ni aviso de ningun tipo: la captura tiene que ser
        # indistinguible de no hacer nada. El unico acuse de recibo es la
        # miniatura en el panel, que solo ves tu (el panel esta excluido de
        # cualquier grabacion o compartir pantalla).
        pantalla = QtWidgets.QApplication.primaryScreen()
        pm = pantalla.grabWindow(0)
        if pm.width() > 1280:
            pm = pm.scaledToWidth(1280, QtCore.Qt.SmoothTransformation)
        ba = QtCore.QByteArray()
        buf = QtCore.QBuffer(ba)
        buf.open(QtCore.QIODevice.WriteOnly)
        pm.save(buf, "PNG")
        self._shots.append(bytes(ba.toBase64()).decode("ascii"))
        # Verla en el panel confirma que se capturo lo que querias, antes de
        # gastar una llamada al modelo. La primera captura abre el panel de la
        # pantalla (y el hablado se pasa a la izquierda).
        self.set_screen_mode(True)
        self.screen.add_shot(pm)
        self.top.set_generate_enabled(True)
        self._capturas_reunion += 1
        self.screen.set_shots(self._capturas_reunion)
        n = len(self._shots)
        # Estado: hay capturas sin resolver. Lo que hay que hacer, de paso.
        self.screen.set_status("Pending")
        self.screen.aviso(f"{n} screenshot{'s' if n != 1 else ''} ready — Caps+D to solve")

    def generate(self, _=""):
        """Envia las capturas acumuladas y pide la respuesta."""
        if not self._running:
            return
        if not self._shots:
            self.panel.aviso("Take a screenshot first (Caps+S)")
            return
        self.engine.request_screenshots(list(self._shots))
        self._shots.clear()
        # Las miniaturas se quedan: acompañan a la respuesta que van a producir.
        self._answer_lleva_capturas = True
        self.top.set_generate_enabled(False)
        self.screen.set_status("Analyzing…")

    def relaunch_screen(self):
        """Bloq Mayus+F: actualiza la solucion en pantalla con lo que acaban de decir."""
        if not self._running:
            return
        self.screen.show_suggestion("")
        self.engine.relaunch_screen()

    def answer_now(self):
        """Bloq Mayus+A: fuerza la respuesta a lo ultimo que dijeron.

        Sirve cuando preguntaron pero la transcripcion no puso los signos y el
        filtro lo tomo por contexto.
        """
        if not self._running:
            return
        if self.engine.modo == agents_mod.NOTETAKER:
            self.panel.aviso("This agent only takes notes")
            return
        self.panel.hide_skip()
        self.panel.set_status("Answering…")
        self.engine.answer_now()

    # ------------------------------------------------ la caja de preguntas
    def toggle_ask(self):
        """Bloq Mayus+E: abre la caja (con el teclado), la enfoca si ya estaba
        abierta y escribias en otra app, o la cierra si ya estabas en ella."""
        if not self._running:
            return
        if not self._visible:
            self.toggle_overlay()
        if not self.ask.isVisible():
            self._partir_columna()
            self.ask.show()
            self._enfocar_pregunta()
        elif self.ask.tiene_foco():
            self.close_ask()
        else:
            self._enfocar_pregunta()

    def _enfocar_pregunta(self):
        previo = traer_al_frente(self.ask.winId())
        if previo:
            self._foco_previo = previo
        self.ask.raise_()
        self.ask.activateWindow()
        self.ask.enfocar()

    def close_ask(self, devolver=True):
        """Cierra la caja: el hablado recupera su alto y, si estabas
        escribiendo en ella, el teclado vuelve a la app de antes."""
        if not self.ask.isVisible() and not self._ask_oculta:
            return
        # El teclado se devuelve ANTES de ocultarla: mientras es la ventana
        # activa, Windows deja que la app le pase el foco a otra.
        if devolver and self.ask.tiene_foco() and self._foco_previo:
            devolver_foco(self._foco_previo)
        self._foco_previo = 0
        self.ask.hide()
        self._ask_oculta = False
        self._cerrar_columna()
        self._caja_grande = False          # se vuelve a abrir pequena

    def ask_question(self, texto):
        """Una pregunta escrita. De una en una: si aun llega la respuesta de la
        anterior, espera su turno (asi cada respuesta va bajo su pregunta)."""
        if not self._running:
            return
        if self._preguntando:
            self._preguntas_en_cola.append(texto)
            n = len(self._preguntas_en_cola)
            self.ask.aviso(f"{n} question{'s' if n != 1 else ''} queued — "
                           f"after this answer")
            return
        self._mandar_pregunta(texto)

    def _mandar_pregunta(self, texto):
        self.ask.add_question(texto)
        if self.engine.preguntar(texto):
            self._preguntando = True
            self.ask.set_state("generating")
            self.ask.set_status("Thinking…", "drafting")

    def _siguiente_pregunta(self):
        self._preguntando = False
        if self._preguntas_en_cola and self._running:
            self._mandar_pregunta(self._preguntas_en_cola.pop(0))

    def on_ask_start(self):
        if not self._running:
            return
        self.ask.clear_answer()
        self.ask.set_status("Answering…", "drafting")
        if not self._caja_grande and (self.ask.isVisible() or self._ask_oculta):
            self._caja_grande = True           # hay algo que leer: mas sitio
            self._partir_columna()

    def on_ask_done(self):
        if self.ask._burbuja_resp is not None or self.ask._repintado_pendiente:
            self.ask.cerrar_respuesta()
        if not self._running:
            return
        self.ask.set_state("idle")
        self.ask.set_status("Ready", "idle")
        self._siguiente_pregunta()

    def on_ask_error(self, msg):
        if self.ask._burbuja_resp is not None or self.ask._repintado_pendiente:
            self.ask.cerrar_respuesta()        # lo que llego a escribirse se queda
        if not self._running:
            return
        self.ask.set_state("idle")
        self.ask.set_status("Error")
        self.ask.show_skip(f"Error: {msg[:80]}")
        self._siguiente_pregunta()

    # ------------------------------------------------ manual / IA
    def _mostrar_resolucion(self, modo):
        for chip in (self.screen.modo_chip, self.ask.modo_chip):
            chip.set_modo(modo)

    def set_resolucion(self, modo):
        """Manual | AI desde cualquiera de los dos paneles: los dos lo
        muestran y, si ya hay una solucion en pantalla, se rehace en ese modo."""
        self._mostrar_resolucion(modo)
        if not self._running:
            return
        rehace = self.engine.set_resolucion(modo)
        nombre = "AI" if modo == "ia" else "Manual"
        if rehace:
            self.screen.aviso(f"{nombre} mode — redoing the solution")
        else:
            panel = self.ask if self.ask.isVisible() else self.screen
            panel.aviso(f"{nombre} mode")

    def _quit_app(self):
        # Boton X de la Home: cierra el programa entero.
        self.home.close()
        self.shutdown()
        QtWidgets.QApplication.quit()

    def _on_home_saved(self):
        self.cfg = cfg_mod.load_config()
        self._refresh_agents()
        self._apply_opacity()

    # ------------------------------------------------ eventos del motor
    # Se ignoran si la reunion ya se detuvo, para que un evento en cola no deje
    # el badge "pegado" (bug que se veia tras Detener).
    def on_latency(self, ms):
        if self._running:
            self.panel.set_latency(ms)

    def on_partial(self, texto):
        """Texto provisional: se repinta mientras la persona sigue hablando."""
        if self._running:
            self.panel.hide_skip()       # vuelven a hablar: el aviso ya no aplica
            self.panel.set_question(texto, caret=True)

    def on_no_answer(self, motivo):
        """Avisa de que no va a haber sugerencia, para no dejarte esperando."""
        if not self._running:
            return
        if motivo == "model_declined":
            self.panel.show_skip("Not a question — Caps+A to answer")
        elif motivo == "manual":
            # Agente "al pedir": hay pregunta, pero solo responde si se lo pides.
            self.panel.show_skip("Question — Caps+A to answer")
        elif motivo == "follow_up":
            # Anadieron algo a la pregunta que estas leyendo o contestando: no
            # se te pone otra respuesta encima, pero puedes pedirla.
            self.panel.show_skip("Added to the current question — Caps+A for a new answer")
        else:
            self.panel.show_skip("No question yet — Caps+A to answer")

    def on_transcript(self, fuente, texto):
        if not self._running:
            return
        # Intervencion cerrada: se queda fija en el hilo y entra la siguiente.
        if fuente == "system":
            self.panel.cerrar_intervencion(texto)
            self.panel.set_status("Transcribing…")

    def on_resp_start(self):
        if not self._running:
            return
        self._responding = True
        self.panel.hide_skip()           # ya hay respuesta en camino
        self._answer_lleva_capturas = False
        self.panel.clear_answer()        # abre una burbuja nueva en el hilo
        self.panel.set_state("generating")   # borde dorado vivo mientras genera
        self.panel.set_status("Drafting…")

    def on_resp_revise(self):
        """Lo que anadieron cambia la respuesta: se reescribe en su sitio."""
        if not self._running:
            return
        self._responding = True
        self.panel.hide_skip()
        self.panel.revisar_respuesta()   # misma burbuja, marcada "Updated"
        self.panel.set_state("generating")
        self.panel.set_status("Updating…")

    # El carril de la pantalla: lo mismo, en su panel.
    def on_shot_start(self):
        if not self._running:
            return
        self.set_screen_mode(True)
        self.screen.clear_answer()
        self.screen.set_state("generating")
        self.screen.set_status("Solving…")

    def on_shot_revise(self):
        if not self._running:
            return
        self.set_screen_mode(True)
        self.screen.revisar_respuesta()      # misma solucion, marcada "Updated"
        self.screen.set_state("generating")
        self.screen.set_status("Updating…")

    def on_shot_done(self):
        self.screen.cerrar_respuesta()
        if not self._running:
            return
        self.screen.set_state("idle")
        self.screen.set_status("Ready")

    def on_screen_suggest(self, texto):
        if not self._running:
            return
        self.screen.show_suggestion(texto)

    def on_resp_done(self):
        self._responding = False
        self.panel.cerrar_respuesta()         # pinta el ultimo trozo y cierra
        if not self._running:
            return
        self.panel.set_state("listening")     # vuelve al pulso de escucha
        self.panel.set_status("Listening")

    def on_status(self, msg):
        if not self._running:
            return
        bajo = msg.lower()
        if "cargando" in bajo:
            self.panel.set_status("Loading model…")
        elif "escuchando" in bajo:
            notas = self.engine.modo == agents_mod.NOTETAKER
            self.panel.set_status("Taking notes" if notas else "Listening")
        elif "sigue hablando" in bajo:
            self.panel.set_status("Still talking…")
        # "Sin pregunta" / "nada que responder" no son estados: el aviso ya va
        # en la pastilla (on_no_answer) y el badge sigue en Listening.

    def on_error(self, msg):
        # Nada de set_hint: vaciaria el panel y perderias la sugerencia que
        # estabas leyendo, justo en el peor momento. El error va en el badge y
        # en la pastilla, que no tocan la respuesta.
        if self._running and not self.engine.running:
            # The engine failed to start: back to the Home, with the reason.
            self.stop_meeting()
            self.home.mostrar_aviso(f"No se pudo iniciar la reunión: {msg[:160]}")
            return
        self.panel.set_status("Error")
        self.panel.show_skip(f"Error: {msg[:80]}")

    def shutdown(self):
        self._timer.stop()
        self._ct_timer.stop()
        self.wheel.uninstall()
        try:
            self.engine.sysLevel.disconnect()
            self.engine.micLevel.disconnect()
            self.engine.transcript.disconnect()
            self.engine.partial.disconnect()
            self.engine.noAnswer.disconnect()
            self.engine.respStart.disconnect()
            self.engine.respRevise.disconnect()
            self.engine.respDelta.disconnect()
            self.engine.respDone.disconnect()
            self.engine.shotStart.disconnect()
            self.engine.shotRevise.disconnect()
            self.engine.shotDelta.disconnect()
            self.engine.shotDone.disconnect()
            self.engine.screenSuggest.disconnect()
            self.engine.askStart.disconnect()
            self.engine.askDelta.disconnect()
            self.engine.askDone.disconnect()
            self.engine.askError.disconnect()
            self.engine.notesStarted.disconnect()
            self.engine.notesReady.disconnect()
            self.engine.status.disconnect()
            self.engine.error.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.engine.stop()


def main():
    # File log first: failures while building the UI must already reach disk.
    try:
        ruta_log = applog.setup(cfg_mod.data_dir())
        log.info("Session log started: %s (frozen=%s)", ruta_log,
                 bool(getattr(sys, "frozen", False)))
    except OSError as e:
        print(f"File logging disabled: {e}", file=sys.stderr)

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # son ventanas tipo Tool

    T.load_fonts()
    ui = OverlayApp()

    # Atajos globales: funcionan aunque el foco este en Zoom / Meet / Teams.
    hk = HK.GlobalHotkeys({
        HK.ACTION_TOGGLE: ui.toggle_overlay,
        HK.ACTION_SHOT: ui.take_shot,
        HK.ACTION_GENERATE: ui.generate,
        HK.ACTION_MEETING: ui.toggle_meeting,
        HK.ACTION_ANSWER: ui.answer_now,
        HK.ACTION_RELAUNCH: ui.relaunch_screen,
        HK.ACTION_ASK: ui.toggle_ask,
    })
    app.installNativeEventFilter(hk)
    # Instalados pero apagados: se encienden al iniciar la reunion.
    hk.instalar()
    ui.atajos = hk

    faltan = T.fonts_missing()
    if faltan:
        print("Aviso: sin las fuentes del diseno (" + ", ".join(faltan) +
              "). Se usan alternativas. Deja los .ttf en assets/fonts/.")

    app.aboutToQuit.connect(hk.unregister)
    app.aboutToQuit.connect(ui.shutdown)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
