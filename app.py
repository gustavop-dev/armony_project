"""Meeting Coach - overlay de entrevista.

Implementa el diseno 'Interview Overlay.dc.html': dos paneles flotantes
translucidos, siempre encima e invisibles al compartir pantalla.

Atajos (convertidos de Mac a Windows):
    Ctrl+B      mostrar / ocultar overlay
    Ctrl+H      captura de pantalla y consulta al modelo
    Ctrl+Enter  generar respuesta
"""
import sys

from PySide6 import QtCore, QtGui, QtWidgets

import config as cfg_mod
import theme as T
from engine import CoachEngine
from overlay import set_capture_protection, set_no_activate, set_click_through
from overlay_ui import TopBar, TranscriptPanel, CollapsedButton, FlashOverlay
from settings_window import SettingsWindow
import hotkeys as HK


class OverlayApp(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.cfg = cfg_mod.load_config()
        self.engine = CoachEngine()

        self.top = TopBar()
        self.panel = TranscriptPanel()
        self.collapsed = CollapsedButton()
        self.flash = FlashOverlay()

        self._visible = True
        self._running = False
        self._elapsed = 0
        self._responding = False
        self._shots = []          # capturas acumuladas, pendientes de enviar
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

    # ------------------------------------------------ colocacion en pantalla
    def _place(self):
        geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
        ancho = min(T.PANEL_WIDTH, geo.width() - T.PANEL_MARGIN)
        self.panel.resize(ancho, 340)
        self.panel.move(geo.x() + (geo.width() - ancho) // 2,
                        geo.y() + geo.height() - self.panel.height() - T.BOTTOM_OFFSET)

        self.top.adjustSize()
        self.top.move(geo.x() + (geo.width() - self.top.width()) // 2,
                      geo.y() + T.TOP_OFFSET)

        self.collapsed.adjustSize()
        self.collapsed.move(geo.x() + (geo.width() - self.collapsed.width()) // 2,
                            geo.y() + T.TOP_OFFSET)

    def _protect(self):
        """Excluye las ventanas de la captura de pantalla y evita que tomen el foco."""
        activo = bool(self.cfg.get("invisible_on_share", True))
        for w in (self.top, self.panel, self.collapsed):
            set_capture_protection(w.winId(), activo)
            # El overlay nunca roba el foco: al pulsar un boton sigues "dentro"
            # de la aplicacion en la que estabas trabajando.
            set_no_activate(w.winId())

    def _apply_opacity(self):
        op = float(self.cfg.get("window_opacity", 0.30))
        op = max(0.15, min(1.0, op))
        for w in (self.top, self.panel, self.collapsed):
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
        objetivos = [
            (self.top, self.top.interactive_widgets()),
            (self.panel, self.panel.interactive_widgets()),
            (self.collapsed, [self.collapsed]),   # el boton de restaurar, entero
        ]
        for win, zonas in objetivos:
            if not win.isVisible():
                continue
            interactivo = self._cursor_over(zonas)
            # click_through activo = NO interactivo (deja pasar el clic)
            deseado = not interactivo
            if self._ct_state.get(win) != deseado:
                set_click_through(win.winId(), deseado)
                self._ct_state[win] = deseado

    # ------------------------------------------------ conexiones
    def _wire(self):
        self.top.startStopClicked.connect(self.toggle_meeting)
        self.top.screenshotClicked.connect(self.take_shot)
        self.top.toggleClicked.connect(self.toggle_overlay)
        self.top.settingsClicked.connect(self.open_settings)
        self.top.generateClicked.connect(self.generate)
        self.collapsed.clicked.connect(self.toggle_overlay)

        e = self.engine
        e.sysLevel.connect(self.panel.set_level)
        e.micLevel.connect(self.panel.set_mic_level)
        e.sttLatency.connect(self.on_latency)
        e.transcript.connect(self.on_transcript)
        e.respStart.connect(self.on_resp_start)
        e.respDelta.connect(self.panel.append_answer)
        e.respDone.connect(self.on_resp_done)
        e.status.connect(self.on_status)
        e.error.connect(self.on_error)

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
        if not test and not self.cfg.get("anthropic_api_key"):
            self.panel.set_status("Add your API key in Settings (⚙) to start")
            return
        self._running = True
        self._elapsed = 0
        self.top.set_meeting(True)
        self.top.set_timer("00:00")
        self._timer.start(1000)
        self.panel.set_listening(True)
        self.panel.set_status("Loading…", "loading")   # feedback inmediato
        self.panel.set_question("")
        import contexts as ctx_mod
        n = ctx_mod.active_count(self.cfg.get("language", "es"))
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
        else:
            self.top.hide()
            self.panel.hide()
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
        pantalla = QtWidgets.QApplication.primaryScreen()
        self.flash.flash(pantalla.geometry())
        pm = pantalla.grabWindow(0)
        if pm.width() > 1280:
            pm = pm.scaledToWidth(1280, QtCore.Qt.SmoothTransformation)
        ba = QtCore.QByteArray()
        buf = QtCore.QBuffer(ba)
        buf.open(QtCore.QIODevice.WriteOnly)
        pm.save(buf, "PNG")
        self._shots.append(bytes(ba.toBase64()).decode("ascii"))
        self.top.set_generate_enabled(True)
        n = len(self._shots)
        self.panel.set_status(
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
        self.top.set_generate_enabled(False)
        self.panel.set_status("Analyzing…")

    def open_settings(self):
        # No se puede abrir la configuracion con la reunion en curso.
        if self._running:
            self.panel.set_status("Stop the meeting to open settings")
            return
        if self.settings is not None:
            return
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

    def on_transcript(self, fuente, texto):
        if not self._running:
            return
        # El panel izquierdo es del participante: solo mostramos lo que dicen ellos.
        if fuente == "system":
            self.panel.set_question(texto)
            self.panel.set_status("Transcribing…")

    def on_resp_start(self):
        if not self._running:
            return
        self._responding = True
        self.panel.clear_answer()
        self.panel.set_state("generating")   # borde dorado vivo mientras genera
        self.panel.set_status("Drafting…")

    def on_resp_done(self):
        self._responding = False
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

    def on_error(self, msg):
        self.panel.set_status("Error")
        self.panel.set_hint(f"Error: {msg}")

    def shutdown(self):
        self._timer.stop()
        self._ct_timer.stop()
        try:
            self.engine.sysLevel.disconnect()
            self.engine.micLevel.disconnect()
            self.engine.transcript.disconnect()
            self.engine.respStart.disconnect()
            self.engine.respDelta.disconnect()
            self.engine.respDone.disconnect()
            self.engine.status.disconnect()
            self.engine.error.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.engine.stop()


def main():
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
