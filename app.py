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

import applog
import config as cfg_mod
import theme as T
from engine import CoachEngine
from overlay import set_capture_protection, set_no_activate, set_click_through
from wheelscroll import WheelForwarder
from overlay_ui import TopBar, TranscriptPanel, CollapsedButton
from settings_window import SettingsWindow
import hotkeys as HK

log = logging.getLogger("armony.app")


class OverlayApp(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.cfg = cfg_mod.load_config()
        self.engine = CoachEngine()

        self.top = TopBar()
        # Dos paneles: la conversacion hablada (siempre) y la pantalla (solo
        # cuando se usan pantallazos; entonces el hablado se pasa a la izquierda).
        self.panel = TranscriptPanel()
        self.screen = TranscriptPanel(modo="pantalla")
        self.collapsed = CollapsedButton()
        self._modo_pantalla = False

        self._visible = True
        self._running = False
        self._elapsed = 0
        self._responding = False
        self._shots = []          # capturas acumuladas, pendientes de enviar
        self._answer_lleva_capturas = False   # la respuesta en curso las ilustra
        self.settings = None      # ventana de configuracion abierta (o None)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._place()
        self._wire()
        self._protect()
        self._apply_opacity()

        self.top.show()
        self.panel.show()
        self.panel.set_status("Idle")

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
            self.screen.setGeometry(derecha - ancho_pant, arriba, ancho_pant, alto)
        else:
            self.panel.setGeometry(derecha - ancho_voz, arriba, ancho_voz, alto)

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
        for w in (self.top, self.panel, self.screen, self.collapsed):
            set_capture_protection(w.winId(), activo)
            # El overlay nunca roba el foco: al pulsar un boton sigues "dentro"
            # de la aplicacion en la que estabas trabajando.
            set_no_activate(w.winId())

    def _apply_opacity(self):
        op = float(self.cfg.get("window_opacity", 0.30))
        op = max(0.15, min(1.0, op))
        for w in (self.top, self.panel, self.screen, self.collapsed):
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
        zonas_rueda = ((self.panel.wheel_zones() + self.screen.wheel_zones())
                       if self.settings is None else [])
        objetivos = [
            (self.top, self.top.interactive_widgets()),
            (self.panel, self.panel.interactive_widgets()),
            (self.screen, self.screen.interactive_widgets()),
            (self.collapsed, [self.collapsed]),   # el boton de restaurar, entero
        ]
        for win, zonas in objetivos:
            if not win.isVisible():
                continue
            interactivo = self._cursor_over(zonas)
            if win in (self.panel, self.screen) and interactivo:
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
        self.top.settingsClicked.connect(self.open_settings)
        self.top.generateClicked.connect(self.generate)
        self.top.answerNowClicked.connect(self.answer_now)
        self.collapsed.clicked.connect(self.toggle_overlay)

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
        e.status.connect(self.on_status)
        e.error.connect(self.on_error)
        self.screen.relaunchClicked.connect(self.relaunch_screen)
        self.screen.closeClicked.connect(lambda: self.set_screen_mode(False))

    # ------------------------------------------------ acciones
    def toggle_meeting(self):
        if self.settings is not None:
            return                       # con settings abierta, los atajos no actuan
        if self._running:
            self.stop_meeting()
        else:
            self.start_meeting()

    def start_meeting(self):
        self.cfg = cfg_mod.load_config()
        test = bool(self.cfg.get("test_mode", False))
        # En Modo prueba NO se necesita API key: arranca directo.
        # Sin key y sin modo prueba: solo avisa (no salta a settings de golpe).
        if not test and not self.cfg.get("openai_api_key"):
            self.panel.set_status("Add your OpenAI API key in Settings (⚙) to start")
            return
        # La transcripcion en la nube necesita su propia key.
        if not self.cfg.get("assemblyai_api_key"):
            self.panel.set_status("Add your AssemblyAI key in Settings (⚙) to start")
            return
        self._running = True
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
        self.set_screen_mode(False)     # vuelve a haber solo el hablado
        self._answer_lleva_capturas = False
        import contexts as ctx_mod
        # Todos los activos, sin filtrar por idioma: es lo que se le manda.
        n = ctx_mod.active_count("auto")
        chip = f"{n} context{'s' if n != 1 else ''} loaded · " if n else ""
        if test:
            self.panel.set_hint("TEST MODE — audio + transcription only (no AI).")
        else:
            self.panel.set_hint(chip + "Listening for the question — the answer will draft here.")
        self.engine.start(self.cfg, test_mode=test)

    # Nota: los mensajes de estado (set_status) van en ingles para una UI mas pulida,
    # aunque el reconocimiento de voz sigue soportando espanol e ingles.

    def stop_meeting(self):
        self._running = False        # a partir de aqui los eventos en cola se ignoran
        self._timer.stop()
        self.top.set_meeting(False)
        self.panel.set_listening(False)
        self.panel.set_status("Idle")
        self.panel.clear_latency()
        self.panel.hide_skip()
        self.engine.stop()

    def _tick(self):
        self._elapsed += 1
        self.top.set_timer(f"{self._elapsed // 60:02d}:{self._elapsed % 60:02d}")

    def toggle_overlay(self):
        if self.settings is not None:
            return
        self._visible = not self._visible
        if self._visible:
            self.collapsed.hide()
            self.top.show()
            self.panel.show()
            if self._modo_pantalla:
                self.screen.show()
        else:
            self.top.hide()
            self.panel.hide()
            self.screen.hide()
            self.collapsed.show()

    def take_shot(self):
        """Guarda una captura en la cola. No genera nada todavia.

        Puedes encadenar varias (Alt+2) y despues pulsar Generate: asi se
        manda todo junto, que es lo util cuando el enunciado no cabe en una
        sola pantalla.
        """
        if not self._running:
            self.panel.set_status("Start the meeting first")
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
        n = len(self._shots)
        self.screen.set_status(
            f"{n} screenshot{'s' if n != 1 else ''} ready — Alt+3 to generate")

    def generate(self, _=""):
        """Envia las capturas acumuladas y pide la respuesta."""
        if not self._running:
            self.panel.set_status("Start the meeting first")
            return
        if not self._shots:
            self.panel.set_status("Take a screenshot first")
            return
        self.engine.request_screenshots(list(self._shots))
        self._shots.clear()
        # Las miniaturas se quedan: acompañan a la respuesta que van a producir.
        self._answer_lleva_capturas = True
        self.top.set_generate_enabled(False)
        self.screen.set_status("Analyzing…")

    def relaunch_screen(self):
        """Alt+6: actualiza la solucion en pantalla con lo que acaban de decir."""
        if self.settings is not None or not self._running:
            return
        self.screen.show_suggestion("")
        self.engine.relaunch_screen()

    def answer_now(self):
        """Alt+5: fuerza la respuesta a lo ultimo que dijeron.

        Sirve cuando preguntaron pero la transcripcion no puso los signos y el
        filtro lo tomo por contexto.
        """
        if self.settings is not None:
            return
        if not self._running:
            self.panel.set_status("Start the meeting first")
            return
        self.panel.hide_skip()
        self.panel.set_status("Answering…")
        self.engine.answer_now()

    def open_settings(self):
        # No se puede abrir la configuracion con la reunion en curso.
        if self._running:
            self.panel.set_status("Stop the meeting to open settings")
            return
        if self.settings is not None:
            return
        # Releer del disco, no usar la copia cargada al arrancar: al guardar se
        # escribe el formulario entero, y una copia vieja borraria cualquier
        # ajuste cambiado por fuera mientras la app estaba abierta.
        self.cfg = cfg_mod.load_config()
        # La configuracion es una vista aparte: el overlay desaparece mientras esta.
        self.top.hide(); self.panel.hide(); self.collapsed.hide()
        self._ct_timer.stop()
        self.settings = SettingsWindow(self.cfg)
        set_capture_protection(self.settings.winId(),
                               bool(self.cfg.get("invisible_on_share", True)))
        self.settings.saved.connect(self._on_settings_saved)
        self.settings.closed.connect(self._on_settings_closed)
        self.settings.closeApp.connect(self._quit_app)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def _quit_app(self):
        # Boton X de la configuracion: cierra el programa entero.
        if self.settings is not None:
            self.settings.close()
            self.settings = None
        self.shutdown()
        QtWidgets.QApplication.quit()

    def _on_settings_saved(self):
        self.cfg = cfg_mod.load_config()

    def _on_settings_closed(self):
        # Restaurar el overlay tal y como estaba.
        if self._visible:
            self.top.show(); self.panel.show()
        else:
            self.collapsed.show()
        self._protect()
        self._apply_opacity()
        self._ct_state.clear()
        self._ct_timer.start(30)
        self.settings = None

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
            self.panel.show_skip("Not a question — Alt+5 to answer")
        elif motivo == "follow_up":
            # Anadieron algo a la pregunta que estas leyendo o contestando: no
            # se te pone otra respuesta encima, pero puedes pedirla.
            self.panel.show_skip("Added to the current question — Alt+5 for a new answer")
        else:
            self.panel.show_skip("No question yet — Alt+5 to answer")

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
            self.panel.set_status("Listening")
        elif "sigue hablando" in bajo:
            self.panel.set_status("Still talking…")
        elif "sin pregunta" in bajo:
            # El aviso visible es la pastilla (on_no_answer); aqui solo el badge.
            # Nada de set_hint: borraria la respuesta anterior del panel.
            self.panel.set_status("Context saved")
        elif "nada que responder" in bajo:
            self.panel.set_status("Nothing to answer yet")

    def on_error(self, msg):
        # Nada de set_hint: vaciaria el panel y perderias la sugerencia que
        # estabas leyendo, justo en el peor momento. El error va en el badge y
        # en la pastilla, que no tocan la respuesta.
        if self._running and not self.engine.running:
            # The engine failed to start: return the UI to idle (stop_meeting
            # hides the pill, so the error is shown again below).
            self.stop_meeting()
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
    })
    app.installNativeEventFilter(hk)
    ok, fallidos = hk.register()
    if fallidos and not hk.exclusive_alt:
        # Sin el hook de Alt dependemos de RegisterHotKey, y ahi si estorba que
        # otra aplicacion tenga la combinacion tomada.
        ui.panel.set_status("Shortcuts in use: " + ", ".join(fallidos))

    faltan = T.fonts_missing()
    if faltan:
        print("Aviso: sin las fuentes del diseno (" + ", ".join(faltan) +
              "). Se usan alternativas. Deja los .ttf en assets/fonts/.")

    app.aboutToQuit.connect(hk.unregister)
    app.aboutToQuit.connect(ui.shutdown)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
