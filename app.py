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
import precarga
import theme as T
from engine import CoachEngine
from overlay import (devolver_foco, set_acrylic, set_capture_protection,
                     set_click_through, set_no_activate, traer_al_frente,
                     vidrio_disponible)
from raton2 import SegundoRaton
from wheelscroll import WheelForwarder
from overlay_ui import TopBar, TranscriptPanel, CollapsedButton
from home_window import HomeWindow
import hotkeys as HK

log = logging.getLogger("armony.app")

# Con los dos paneles a la vista llenan la pantalla de lado a lado: el hablado
# a la izquierda con esta parte del ancho y el grande con el resto.
PROPORCION_VOZ = 0.38
ANCHO_MIN_VOZ = 380

# Subrayar un trozo y pulsar Explain: de donde sale, para decirselo al modelo.
ORIGEN_SUBRAYADO = {
    "voz:tu": "lo que me sugeriste decir en voz alta",
    "voz:ellos": "lo que dijeron en la reunión",
    "pantalla:tu": "tu solución en pantalla",
    "pantalla:respuesta": "tu respuesta en el panel grande",
    "pantalla:pregunta": "mi pregunta",
}
MAX_SUBRAYADO = 2000          # caracteres del trozo que se mandan


def pregunta_subrayado(texto, origen):
    """La pregunta que sale al pulsar Explain sobre un trozo subrayado."""
    texto = " ".join(texto.split())
    if len(texto) > MAX_SUBRAYADO:
        texto = texto[:MAX_SUBRAYADO] + "…"
    donde = ORIGEN_SUBRAYADO.get(origen)
    return (f"Explícame esto de {donde}: «{texto}»" if donde
            else f"Explícame esto: «{texto}»")


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
        # Dos paneles: la conversacion hablada (siempre, con el campo de
        # preguntas abajo) y el grande (capturas, lo hablado resuelto en grande y
        # las respuestas a lo que escribes). Con los dos, llenan la pantalla.
        self.panel = TranscriptPanel()
        self.screen = TranscriptPanel(modo="pantalla")
        self._foco_previo = 0        # la ventana a la que se le devuelve el teclado
        self._escribiendo = False    # el campo de preguntas tiene el teclado
        self._preguntando = False    # hay una respuesta escrita en camino
        self._preguntas_en_cola = []  # las escritas mientras tanto, en orden
        self.collapsed = CollapsedButton()
        self._modo_pantalla = False
        # El segundo raton (Bloq Mayus+Q): azul, invisible al compartir, para
        # usar el overlay sin mover el cursor real.
        self.raton = SegundoRaton(self._ventanas_overlay, al_rodar=self._rodar_virtual)
        self.raton.cambiado.connect(self._on_raton)

        self._visible = True
        self._running = False
        # Atajos globales (hotkeys.GlobalHotkeys), solo activos en la reunion:
        # fuera de ella Bloq Mayus y Alt+1..9 son de las demas apps.
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
        # Al abrir un agente en la Home se precarga su conocimiento en la cache
        # del modelo: al iniciar la reunion la primera respuesta ya no lo paga.
        self.home.al_ver_agente = lambda agente: agente is not None and \
            precarga.precalentar(self.cfg, agente)
        self.home.al_ver_agente(agents_mod.get(self.cfg.get("agent")))   # el de arranque
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
        self.raton.instalar()

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
        """Solo el hablado: columna a la derecha. Con el panel grande: los dos
        llenan la pantalla, el hablado a la izquierda (PROPORCION_VOZ del ancho)
        y el grande, para el codigo y lo que se lee, con el resto."""
        geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
        arriba = geo.y() + T.TOP_OFFSET + self.top.height() + T.COLUMN_GAP
        alto = geo.y() + geo.height() - T.BOTTOM_OFFSET - arriba
        hueco = geo.width() - 3 * T.SIDE_MARGIN
        derecha = geo.x() + geo.width() - T.SIDE_MARGIN
        if self._modo_pantalla:
            ancho_voz = max(min(ANCHO_MIN_VOZ, hueco // 2), round(hueco * PROPORCION_VOZ))
            izquierda = geo.x() + T.SIDE_MARGIN
            self.panel.setGeometry(izquierda, arriba, ancho_voz, alto)
            self._pegar_derecha(self.screen, derecha, arriba, hueco - ancho_voz, alto)
        else:
            ancho_voz = min(T.COLUMN_WIDTH, hueco // 2)
            self._pegar_derecha(self.panel, derecha, arriba, ancho_voz, alto)

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
        panel = self.screen if nombre.startswith("pantalla:") else self.panel
        panel.scroll_zone(nombre, muescas)

    def _protect(self):
        """Excluye las ventanas de la captura de pantalla y evita que tomen el foco."""
        activo = bool(self.cfg.get("invisible_on_share", True))
        for w in (self.top, self.panel, self.screen, self.collapsed, self.raton.cursor,
                  self.raton.atrapa):
            set_capture_protection(w.winId(), activo)
            # El overlay nunca roba el foco: al pulsar un boton sigues "dentro"
            # de la aplicacion en la que estabas trabajando. El campo de
            # preguntas lo quita solo mientras escribes (_enfocar_pregunta).
            set_no_activate(w.winId())

    def _apply_opacity(self):
        op = float(self.cfg.get("window_opacity", 0.30))
        op = max(0.15, min(1.0, op))
        for w in (self.top, self.panel, self.screen, self.collapsed):
            if T.VIDRIO:
                # La opacidad pasa al tinte del acrilico: el texto no se atenua.
                w.setWindowOpacity(1.0)
                set_acrylic(w.winId(), alpha=0.15 + op * 0.75)
            else:
                w.setWindowOpacity(op)

    def _update_click_through(self):
        """El raton real atraviesa siempre el overlay, como si fuera de cristal
        (clics y rueda van a la app de debajo): ni se ve tocar nada invisible
        al compartir pantalla ni se mueve nada sin querer. El overlay solo se
        toca con el raton azul (Bloq Mayus+Q), que no usa el cursor real."""
        if self._escribiendo and not self.panel.isActiveWindow():
            self._soltar_pregunta(devolver=False)     # se fue a otra app
        for win in (self.top, self.panel, self.screen, self.collapsed):
            if win.isVisible() and self._ct_state.get(win) is not True:
                set_click_through(win.winId(), True)
                self._ct_state[win] = True
        self.wheel.set_zones([])

    # ------------------------------------------------ conexiones
    def _wire(self):
        self.top.startStopClicked.connect(self.toggle_meeting)
        self.top.screenshotClicked.connect(self.take_shot)
        self.top.toggleClicked.connect(self.toggle_overlay)
        self.top.generateClicked.connect(self.generate)
        self.top.answerNowClicked.connect(self.answer_now)
        self.top.askClicked.connect(self.toggle_ask)
        self.top.spokenClicked.connect(self.resolve_spoken)
        self.top.mouseClicked.connect(self.toggle_mouse)
        self.collapsed.clicked.connect(self.toggle_overlay)
        self.panel.submitted.connect(self.ask_question)
        self.panel.entradaPulsada.connect(self._enfocar_pregunta)
        self.panel.entradaSalir.connect(self.close_ask)
        for chip in (self.panel.modo_chip, self.screen.modo_chip):
            chip.changed.connect(self.set_resolucion)
        for p in (self.panel, self.screen):
            p.explainRequested.connect(self.explicar)

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
        e.askDelta.connect(self.screen.append_answer)
        e.askDone.connect(self.on_ask_done)
        e.askError.connect(self.on_ask_error)
        # Las notas se generan cuando la Home ya esta a la vista.
        e.notesStarted.connect(lambda sid: self.home.notas_en_curso(sid))
        e.notesReady.connect(lambda sid, ok: self.home.notas_listas(sid, ok))
        e.status.connect(self.on_status)
        e.error.connect(self.on_error)
        self.panel.relaunchClicked.connect(self.relaunch_screen)
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
        self.panel.show_suggestion("")
        self.panel.entrada.clear()
        self._preguntando = False
        self._preguntas_en_cola = []
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
        self.raton.desactivar()          # el raton real vuelve a ser el raton
        self._soltar_pregunta(devolver=False)
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
            # Sin el hook no hay Bloq Mayus: quedan los Alt+1..9 de respaldo.
            aviso = "Caps Lock shortcuts unavailable — use Alt+1…9"
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
        """Bloq Mayus+W: minimiza los paneles (queda la pildora para volver) o
        los restaura. Minimizado no hay raton azul."""
        if not self._running:
            return                       # fuera de la reunion no hay overlay
        self._visible = not self._visible
        if self._visible:
            self.collapsed.hide()
            self.top.show()
            self.panel.show()
            if self._modo_pantalla:
                self.screen.show()
        else:
            self.raton.desactivar()
            self._soltar_pregunta()
            self.top.hide()
            self.panel.hide()
            self.screen.hide()
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
        """Bloq Mayus+D: envia las capturas acumuladas. Sin capturas nuevas,
        rehace la ultima solucion del panel grande en el modo actual (para
        cuando cambias de Manual a AI o al reves)."""
        if not self._running:
            return
        if not self._shots:
            if self.engine.rehacer_pantalla():
                nombre = "AI" if self.engine.resolucion == "ia" else "Manual"
                self.screen.set_status("Redoing…", "drafting")
                self.screen.aviso(f"Redoing the solution in {nombre} mode")
            else:
                self.panel.aviso("Take a screenshot first (Caps+S) — or Caps+R to "
                                 "solve what they said")
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
        self.panel.show_suggestion("")
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

    # ------------------------------------------------ preguntas escritas
    def toggle_ask(self):
        """Bloq Mayus+E: el teclado al campo de preguntas del hablado (o de
        vuelta a la app de antes si ya estabas en el). Con un trozo subrayado,
        la pregunta empieza citandolo."""
        if not self._running:
            return
        if not self._visible:
            self.toggle_overlay()
        texto, _origen = self._subrayado()
        if texto:
            self._limpiar_subrayados()
            self.panel.citar(texto)
        if self._escribiendo and self.panel.tiene_foco() and not texto:
            self.close_ask()
        else:
            self._enfocar_pregunta()

    def _subrayado(self):
        """(texto, origen) subrayado en algun panel, o ("", "")."""
        for p in (self.screen, self.panel):
            texto, origen = p.seleccion()
            if texto:
                return texto, origen
        return "", ""

    def _limpiar_subrayados(self):
        for p in (self.panel, self.screen):
            p.limpiar_seleccion()

    def explicar(self, texto, origen):
        """Explain sobre un trozo subrayado: la respuesta sale en el panel
        grande, sin quitarte el teclado (solo hay que leer)."""
        if not self._running or not texto.strip():
            return
        if not self._visible:
            self.toggle_overlay()
        self.ask_question(pregunta_subrayado(texto, origen))

    def _enfocar_pregunta(self):
        """El panel hablado no se activa nunca (no roba el foco), salvo para
        escribir: se le quita esa marca y se pone delante con el teclado."""
        if not self._running:
            return
        set_no_activate(self.panel.winId(), False)
        previo = traer_al_frente(self.panel.winId())
        if previo and not self._escribiendo:
            self._foco_previo = previo
        self._escribiendo = True
        self.panel.raise_()
        self.panel.activateWindow()
        self.panel.enfocar()

    def _soltar_pregunta(self, devolver=True):
        """Deja de escribir: el teclado vuelve a la app de antes (si se pide y
        aun lo tenia el panel) y el panel vuelve a no robar el foco."""
        if not self._escribiendo:
            return
        if devolver and self.panel.isActiveWindow() and self._foco_previo:
            devolver_foco(self._foco_previo)
        self._foco_previo = 0
        self._escribiendo = False
        self.panel.entrada.clearFocus()
        set_no_activate(self.panel.winId(), True)

    def close_ask(self, devolver=True):
        """Esc en el campo, o Bloq Mayus+E otra vez: el teclado vuelve."""
        self._soltar_pregunta(devolver)

    def ask_question(self, texto):
        """Una pregunta escrita. Su respuesta sale en el panel grande, debajo de
        la pregunta. De una en una: si aun llega la anterior, espera su turno."""
        if not self._running:
            return
        if self._preguntando:
            self._preguntas_en_cola.append(texto)
            n = len(self._preguntas_en_cola)
            self.panel.aviso(f"{n} question{'s' if n != 1 else ''} queued — "
                             f"after this answer")
            return
        self._mandar_pregunta(texto)

    def _mandar_pregunta(self, texto):
        self.set_screen_mode(True)
        self.screen.add_question(texto)
        if self.engine.preguntar(texto):
            self._preguntando = True
            self.screen.set_state("generating")
            self.screen.set_status("Thinking…", "drafting")

    def _siguiente_pregunta(self):
        self._preguntando = False
        if self._preguntas_en_cola and self._running:
            self._mandar_pregunta(self._preguntas_en_cola.pop(0))

    def on_ask_start(self):
        if not self._running:
            return
        self.set_screen_mode(True)
        self.screen.clear_answer("respuesta")
        self.screen.set_status("Answering…", "drafting")

    def on_ask_done(self):
        if self.screen._burbuja_resp is not None or self.screen._repintado_pendiente:
            self.screen.cerrar_respuesta()
        if not self._running:
            return
        self.screen.set_state("idle")
        self.screen.set_status("Ready", "idle")
        self._siguiente_pregunta()

    def on_ask_error(self, msg):
        if self.screen._burbuja_resp is not None or self.screen._repintado_pendiente:
            self.screen.cerrar_respuesta()      # lo que llego a escribirse se queda
        if not self._running:
            return
        self.screen.set_state("idle")
        self.screen.set_status("Error")
        self.panel.show_skip(f"Error: {msg[:80]}")
        self._siguiente_pregunta()

    # ------------------------------------------------ lo hablado, en grande
    def resolve_spoken(self):
        """Bloq Mayus+R: lo ultimo que plantearon hablando (un ejercicio
        dictado, algo que pide mas que una respuesta para decir) se resuelve en
        el panel grande, en el modo actual. Para cuando no hay captura."""
        if not self._running:
            return
        if self.engine.modo == agents_mod.NOTETAKER:
            self.panel.aviso("This agent only takes notes")
            return
        texto = self.engine.resolver_hablado()
        if not texto:
            self.panel.aviso("Nothing said yet to solve")
            return
        self.set_screen_mode(True)
        self.screen.set_state("generating")
        self.screen.set_status("Solving…", "drafting")

    # ------------------------------------------------ el raton azul
    def _ventanas_overlay(self):
        """Lo que el raton azul puede tocar, de arriba a abajo."""
        return [self.top, self.panel, self.screen, self.collapsed]

    def toggle_mouse(self):
        """Bloq Mayus+Q: enciende o apaga el raton azul (solo con los paneles a
        la vista: minimizados no hay nada que tocar)."""
        if not self._running or not self._visible:
            return
        self.raton.alternar()

    def _on_raton(self, activo):
        self._ct_state.clear()              # que el click-through se recalcule
        self.top.set_raton(activo)
        if activo:
            self.panel.aviso("Blue mouse on — your real mouse stays put. Caps+Q to switch off")

    def _rodar_virtual(self, pos, muescas):
        """La rueda del raton azul: al panel cuya zona de scroll esta debajo."""
        for (x, y, ancho, alto), nombre in (self.panel.wheel_zones()
                                            + self.screen.wheel_zones()):
            if QtCore.QRect(x, y, ancho, alto).contains(pos):
                self._scroll_zone(nombre, muescas)
                return

    # ------------------------------------------------ manual / IA
    def _mostrar_resolucion(self, modo):
        for chip in (self.panel.modo_chip, self.screen.modo_chip):
            chip.set_modo(modo)

    def set_resolucion(self, modo):
        """Manual | AI desde cualquiera de los dos paneles: solo cambia el modo
        de lo siguiente. No rehace nada solo; para rehacer la solucion del
        panel grande en este modo, Bloq Mayus+D."""
        self._mostrar_resolucion(modo)
        if not self._running:
            return
        self.engine.set_resolucion(modo)
        nombre = "AI" if modo == "ia" else "Manual"
        extra = " — Caps+D redoes the solution in this mode" if self.engine.hay_solucion else ""
        (self.screen if self._modo_pantalla else self.panel).aviso(f"{nombre} mode{extra}")

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
        """Lo que dijeron parece pedir un cambio en la solucion: se ofrece en el
        hablado, que es donde estas mirando mientras hablan."""
        if not self._running:
            return
        self.panel.show_suggestion(texto)

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
        self.raton.desinstalar()
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
        HK.ACTION_MOUSE: ui.toggle_mouse,
        HK.ACTION_SPOKEN: ui.resolve_spoken,
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
