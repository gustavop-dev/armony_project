"""OverlayApp tests with real Qt widgets and isolated OS/engine boundaries."""
import base64

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import agents as agents_mod
import app
import config
import theme as T


class FakeEngine(QtCore.QObject):
    sysLevel = QtCore.Signal(int)
    micLevel = QtCore.Signal(int)
    sttLatency = QtCore.Signal(int)
    e2eLatency = QtCore.Signal(int)
    transcript = QtCore.Signal(str, str)
    partial = QtCore.Signal(str)
    noAnswer = QtCore.Signal(str)
    respStart = QtCore.Signal()
    respRevise = QtCore.Signal()
    respDelta = QtCore.Signal(str)
    respDone = QtCore.Signal()
    shotStart = QtCore.Signal()
    shotRevise = QtCore.Signal()
    shotDelta = QtCore.Signal(str)
    shotDone = QtCore.Signal()
    screenSuggest = QtCore.Signal(str)
    askStart = QtCore.Signal()
    askDelta = QtCore.Signal(str)
    askDone = QtCore.Signal()
    askError = QtCore.Signal(str)
    notesStarted = QtCore.Signal(str)
    notesReady = QtCore.Signal(str, bool)
    status = QtCore.Signal(str)
    error = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.modo = "automatico"
        self.permite_capturas = True
        self.starts = []
        self.stops = 0
        self.answers = 0
        self.relaunches = 0
        self.screenshots = []
        self.start_error = None
        self.running = False
        self.resolucion = "manual"
        self.resoluciones = []
        self.redo = False
        self.questions = []
        self.ask_ok = True

    def set_resolucion(self, modo):
        self.resoluciones.append(modo)
        self.resolucion = modo
        return True

    @property
    def hay_solucion(self):
        return self.redo

    def rehacer_pantalla(self):
        self.redos = getattr(self, "redos", 0) + 1
        return self.redo

    def resolver_hablado(self):
        self.spoken = getattr(self, "spoken", 0) + 1
        return getattr(self, "spoken_text", "")

    def preguntar(self, texto):
        self.questions.append(texto)
        return self.ask_ok

    def start(self, cfg, test_mode=False):
        self.starts.append((dict(cfg), test_mode))
        self.running = self.start_error is None
        if self.start_error is not None:
            self.error.emit(self.start_error)

    def stop(self):
        self.stops += 1
        self.running = False

    def answer_now(self):
        self.answers += 1

    def relaunch_screen(self):
        self.relaunches += 1

    def request_screenshots(self, images):
        self.screenshots.append(images)

    def set_agent(self, agent_id):
        self.agents = getattr(self, "agents", []) + [agent_id]
        return None          # no meeting running


class FakeWheel:
    def __init__(self, callback):
        self.callback = callback
        self.installed = False
        self.zones = None

    def install(self):
        self.installed = True

    def uninstall(self):
        self.installed = False

    def set_zones(self, zones):
        self.zones = zones


class FakeRaton(QtCore.QObject):
    """The blue mouse without its low-level hook."""
    cambiado = QtCore.Signal(bool)

    def __init__(self, ventanas, al_rodar=None):
        super().__init__()
        self.ventanas = ventanas
        self.al_rodar = al_rodar
        self.cursor = QtWidgets.QWidget()
        self.atrapa = QtWidgets.QWidget()
        self.activo = False
        self.installed = False

    def instalar(self):
        self.installed = True

    def desinstalar(self):
        self.installed = False

    def activar(self):
        if not self.activo:
            self.activo = True
            self.cambiado.emit(True)

    def desactivar(self):
        if self.activo:
            self.activo = False
            self.cambiado.emit(False)

    def alternar(self):
        self.desactivar() if self.activo else self.activar()
        return self.activo


class FakeScreen:
    def __init__(self, pixmap):
        self.pixmap = pixmap
        self.windows = []

    def grabWindow(self, window):
        self.windows.append(window)
        return self.pixmap

    def devicePixelRatio(self):
        return 1.0

    def availableGeometry(self):
        return QtCore.QRect(0, 0, 1920, 1080)


@pytest.fixture
def cfg():
    return dict(config.DEFAULTS, openai_api_key="fake-openai",
                assemblyai_api_key="fake-stt")


@pytest.fixture
def native(monkeypatch):
    calls = {"capture": [], "activate": [], "click": []}
    monkeypatch.setattr(app, "WheelForwarder", FakeWheel)
    monkeypatch.setattr(app, "SegundoRaton", FakeRaton)
    monkeypatch.setattr(app, "set_capture_protection",
                        lambda handle, active: calls["capture"].append((int(handle), active)))
    calls["deactivate"] = []
    monkeypatch.setattr(app, "set_no_activate",
                        lambda handle, on=True: (calls["activate"] if on
                                                 else calls["deactivate"]).append(int(handle)))
    monkeypatch.setattr(app, "set_click_through",
                        lambda handle, active: calls["click"].append((int(handle), active)))
    calls["front"], calls["back"] = [], []
    monkeypatch.setattr(app, "traer_al_frente",
                        lambda handle: calls["front"].append(int(handle)) or 4242)
    monkeypatch.setattr(app, "devolver_foco",
                        lambda handle: calls["back"].append(int(handle)) or True)
    monkeypatch.setattr(QtWidgets.QApplication, "mouseButtons", lambda: QtCore.Qt.NoButton)
    monkeypatch.setattr(QtGui.QCursor, "pos", lambda: QtCore.QPoint(-10000, -10000))
    return calls


@pytest.fixture
def ui(qtbot, monkeypatch, cfg, native, tmp_path):
    import icons
    save_png = icons.save_png
    # The Home writes its combo arrow icon: keep it in the test's temp dir.
    monkeypatch.setattr(icons, "save_png", lambda name, color, size, path:
                        save_png(name, color, size, str(tmp_path / "chevron.png")))
    monkeypatch.setattr(app, "CoachEngine", FakeEngine)
    monkeypatch.setattr(app.cfg_mod, "load_config", lambda: dict(cfg))
    controller = app.OverlayApp()
    for widget in (controller.top, controller.panel, controller.screen,
                   controller.collapsed, controller.home, controller.raton.cursor,
                   controller.raton.atrapa):
        qtbot.addWidget(widget)
    controller._ct_timer.stop()
    yield controller
    controller._timer.stop()
    if controller.wheel.installed:
        controller.shutdown()
    QtWidgets.QApplication.processEvents()


def badge(ui):
    return ui.panel.badge._lbl.text()


class TestMeeting:
    def test_missing_openai_key_blocks_start(self, ui, cfg):
        """Catch a live session starting without the LLM credential."""
        cfg["openai_api_key"] = ""

        ui.start_meeting()

        assert ui.home._aviso == "Añade tu API key de OpenAI para iniciar la reunión."
        assert (ui.home.vista, ui.home.isVisible()) == (("ajustes", None), True)
        assert ui.engine.starts == []
        assert ui._running is False
        assert ui._timer.isActive() is False

    @pytest.mark.parametrize("test_mode", [False, True])
    def test_start_requires_stream_key(self, ui, cfg, test_mode):
        """Catch test mode bypassing the required STT credential."""
        cfg.update(assemblyai_api_key="", test_mode=test_mode)

        ui.start_meeting()

        assert ui.home._aviso == "Añade tu API key de AssemblyAI para iniciar la reunión."
        assert ui.engine.starts == []
        assert ui._running is False

    @pytest.mark.parametrize("test_mode,key", [
        (False, "fake-key"),
        (True, ""),
    ])
    def test_start_uses_reloaded_configuration(self, ui, cfg, test_mode, key):
        """Catch cached settings or key checks blocking valid live/test sessions."""
        cfg.update(test_mode=test_mode, openai_api_key=key,
                   assemblyai_api_key="fake-stt", language="en")

        ui.start_meeting()

        assert ui.engine.starts == [(cfg, test_mode)]
        assert ui._running is True
        assert ui._timer.isActive() is True
        assert ui._timer.interval() == 1000
        assert ui.top.lbl_meeting.text() == "Stop meeting"
        assert ui.top.lbl_timer.text() == "00:00"
        assert ui.panel._state == "listening"
        assert badge(ui) == "Loading…"

    def test_start_swaps_the_home_for_the_overlay(self, ui):
        ui.start_meeting()

        assert (ui.home.isVisible(), ui.top.isVisible(), ui.panel.isVisible()) == (
            False, True, True)

    def test_stop_returns_to_the_home(self, ui):
        ui.start_meeting()

        ui.stop_meeting()

        assert (ui.home.isVisible(), ui.top.isVisible(), ui.panel.isVisible()) == (
            True, False, False)

    def test_stop_restores_idle(self, ui):
        """Catch stopping a session leaving timer, listening state or latency visible."""
        ui.start_meeting()
        ui.engine.sttLatency.emit(250)
        ui.engine.noAnswer.emit("no_question")

        ui.stop_meeting()

        assert ui._running is False
        assert ui._timer.isActive() is False
        assert ui.top.lbl_meeting.text() == "Start meeting"
        assert ui.top.lbl_timer.text() == ""
        assert ui.panel._state == "idle"
        assert ui.panel.lat.text() == ""
        assert ui.panel.skip_pill.isHidden() is True
        assert badge(ui) == "Idle"
        assert ui.engine.stops == 1

    def test_toggle_starts_idle_meeting(self, ui):
        """Catch the start/stop control failing to start an idle session."""
        ui.toggle_meeting()

        assert len(ui.engine.starts) == 1
        assert ui.top.lbl_meeting.text() == "Stop meeting"

    def test_toggle_stops_running_meeting(self, ui):
        """Catch the start/stop control starting a second session."""
        ui.start_meeting()

        ui.toggle_meeting()

        assert ui.engine.stops == 1
        assert ui.top.lbl_meeting.text() == "Start meeting"

    @pytest.mark.parametrize("elapsed,expected", [(0, "00:01"), (59, "01:00"), (3599, "60:00")])
    def test_tick_formats_elapsed_time(self, ui, elapsed, expected):
        """Catch minute rollover or missing zero padding in the meeting timer."""
        ui._elapsed = elapsed

        ui._tick()

        assert ui.top.lbl_timer.text() == expected

    def test_initialization_error_restores_idle(self, ui):
        """Catch a failed engine initialization leaving a false running UI."""
        ui.engine.start_error = "No se pudo conectar con AssemblyAI: connect failed"

        ui.start_meeting()

        assert (ui._running, ui._timer.isActive(), ui.top.lbl_meeting.text(),
                ui.panel._state) == (False, False, "Start meeting", "idle")


    def test_initialization_error_stays_visible(self, ui):
        """Catch the idle reset hiding the start-up error from the user."""
        ui.engine.start_error = "No se pudo iniciar OpenAI: bad key"

        ui.start_meeting()

        assert ui.home._aviso == ("No se pudo iniciar la reunión: "
                                  "No se pudo iniciar OpenAI: bad key")
        assert ui.home.isVisible() is True

    def test_start_after_initialization_error_starts_engine(self, ui):
        """Catch the first Start press after a failure only stopping the UI."""
        ui.engine.start_error = "No se pudo iniciar OpenAI: bad key"
        ui.start_meeting()
        ui.engine.start_error = None

        ui.toggle_meeting()

        assert (len(ui.engine.starts), ui._running) == (2, True)

    def test_runtime_error_keeps_meeting_running(self, ui):
        """Catch a transient LLM error ending a healthy meeting."""
        ui.start_meeting()

        ui.engine.error.emit("Error code: 529 overloaded")

        assert (ui._running, ui._timer.isActive()) == (True, True)


class TestActions:
    @pytest.mark.parametrize("action", ["take_shot", "generate", "answer_now"])
    def test_idle_action_requests_meeting(self, ui, action):
        """Catch model or screen actions proceeding before a meeting starts."""
        getattr(ui, action)()

        assert badge(ui) == "Idle"
        assert ui._shots == []
        assert ui.engine.screenshots == []
        assert ui.engine.answers == 0

    @pytest.mark.parametrize("width,height,expected", [(1600, 800, (1280, 640)),
                                                      (640, 320, (640, 320))])
    def test_capture_encodes_scaled_png(self, ui, monkeypatch, width, height, expected):
        """Catch oversized uploads, non-PNG encoding or unexpected screen selection."""
        ui.start_meeting()
        pixmap = QtGui.QPixmap(width, height)
        pixmap.fill(QtGui.QColor("red"))
        screen = FakeScreen(pixmap)
        monkeypatch.setattr(QtWidgets.QApplication, "primaryScreen",
                            staticmethod(lambda: screen))

        ui.take_shot()

        assert screen.windows == [0]
        assert len(ui._shots) == 1
        raw = base64.b64decode(ui._shots[0], validate=True)
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        decoded = QtGui.QImage.fromData(raw, "PNG")
        assert (decoded.width(), decoded.height()) == expected
        assert decoded.pixelColor(0, 0).name() == "#ff0000"
        assert ui.screen.badge._lbl.text() == "Pending"
        assert ui.screen.skip_pill.text() == "1 screenshot ready — Caps+D to solve"
        assert ui.screen.titulo.text() == "Screen · 1 shot"
        assert ui.top.keys_gen.isEnabled() is True
        assert ui.engine.screenshots == []

    def test_generate_requires_screenshots(self, ui):
        """Catch Generate submitting an empty screenshot batch."""
        ui.start_meeting()

        ui.generate()

        assert ui.panel.skip_pill.text() == ("Take a screenshot first (Caps+S) — or "
                                             "Caps+R to solve what they said")
        assert ui.engine.screenshots == []

    def test_generate_transfers_snapshot(self, ui):
        """Catch clearing the pending shots also clearing the submitted images."""
        ui.start_meeting()
        ui._shots = ["png-a", "png-b"]

        ui.generate()

        assert ui.engine.screenshots == [["png-a", "png-b"]]
        assert ui._shots == []
        assert ui._answer_lleva_capturas is True
        assert ui.top.keys_gen.isEnabled() is False
        assert ui.screen.badge._lbl.text() == "Analyzing…"

    def test_manual_answer_clears_skip_notice(self, ui):
        """Catch forced answering retaining a stale no-question notice."""
        ui.start_meeting()
        ui.engine.noAnswer.emit("no_question")

        ui.answer_now()

        assert ui.engine.answers == 1
        assert ui.panel.skip_pill.isHidden() is True
        assert badge(ui) == "Answering…"

    def test_toggle_hides_overlay(self, ui):
        """Catch hiding the overlay also hiding the restore control."""
        ui.start_meeting()
        ui.toggle_overlay()

        assert (ui.top.isVisible(), ui.panel.isVisible(), ui.collapsed.isVisible()) == (False, False, True)
        assert ui._visible is False

    def test_toggle_restores_overlay(self, ui):
        """Catch the restore control failing to restore both overlay windows."""
        ui.start_meeting()
        ui.toggle_overlay()

        ui.toggle_overlay()

        assert (ui.top.isVisible(), ui.panel.isVisible(), ui.collapsed.isVisible()) == (True, True, False)
        assert ui._visible is True


class TestEvents:
    @pytest.mark.parametrize("message,expected", [
        ("Cargando modelo de transcripcion...", "Loading model…"),
        ("Escuchando la reunion.", "Listening"),
        ("Sigue hablando...", "Still talking…"),
        # not states: the pill already explains them, the badge keeps its state
        ("Sin pregunta todavia: guardado como contexto.", "Loading…"),
        ("Aun no hay nada que responder.", "Loading…"),
        ("Modelo listo.", "Loading…"),
    ])
    def test_engine_status_maps_to_badge(self, ui, message, expected):
        """Catch untranslated engine messages or unrelated messages replacing the badge."""
        ui.start_meeting()

        ui.engine.status.emit(message)

        assert badge(ui) == expected

    @pytest.mark.parametrize("reason,expected", [
        ("model_declined", "Not a question — Caps+A to answer"),
        ("no_question", "No question yet — Caps+A to answer"),
        ("follow_up", "Added to the current question — Caps+A for a new answer"),
    ])
    def test_no_answer_explains_reason(self, ui, reason, expected):
        """Catch model refusal being indistinguishable from the lexical filter."""
        ui.start_meeting()

        ui.engine.noAnswer.emit(reason)

        assert ui.panel.skip_pill.text() == expected
        assert ui.panel.skip_pill.isHidden() is False

    def test_partial_updates_live_bubble(self, ui):
        """Catch live transcription failing to replace a stale skip notice."""
        ui.start_meeting()
        ui.engine.noAnswer.emit("no_question")

        ui.engine.partial.emit("¿Podemos")

        assert ui.panel._burbuja_viva._raw == "¿Podemos"
        assert ui.panel.skip_pill.isHidden() is True

    def test_system_transcript_closes_bubble(self, ui):
        """Catch finalized participant speech remaining an editable partial."""
        ui.start_meeting()
        ui.engine.partial.emit("¿Podemos")

        ui.engine.transcript.emit("system", "¿Podemos empezar?")

        assert ui.panel._burbuja_viva is None
        assert ui.panel._burbujas[-1]._raw == "¿Podemos empezar?"
        assert badge(ui) == "Transcribing…"

    def test_microphone_transcript_does_not_replace_question(self, ui):
        """Catch local speech appearing as the other participant's question."""
        ui.start_meeting()

        ui.engine.transcript.emit("mic", "Sí.")

        assert ui.panel._burbujas == []
        assert badge(ui) == "Loading…"

    def test_response_start_opens_answer_bubble(self, ui):
        """Catch model output starting without a fresh generating bubble."""
        ui.start_meeting()
        ui.engine.noAnswer.emit("no_question")

        ui.engine.respStart.emit()

        assert ui._responding is True
        assert ui.panel._state == "generating"
        assert ui.panel._burbuja_resp._raw == ""
        assert ui.panel.skip_pill.isHidden() is True
        assert badge(ui) == "Drafting…"

    def test_response_done_renders_final_delta(self, ui):
        """Catch buffered final response text disappearing when generation finishes."""
        ui.start_meeting()
        ui.engine.respStart.emit()
        ui.engine.respDelta.emit("Ready to start.")

        ui.engine.respDone.emit()

        assert ui._responding is False
        assert ui.panel._burbuja_resp is None
        assert ui.panel._burbujas[-1]._raw == "Ready to start."
        assert ui.panel._state == "listening"
        assert badge(ui) == "Listening"

    def test_response_revise_rewrites_last_answer(self, ui):
        """Catch a follow-up revision stacking a second suggestion instead of rewriting."""
        ui.start_meeting()
        ui.engine.respStart.emit()
        ui.engine.respDelta.emit("First draft.")
        ui.engine.respDone.emit()
        first = ui.panel._burbujas[-1]
        count = len(ui.panel._burbujas)
        ui.engine.noAnswer.emit("follow_up")

        ui.engine.respRevise.emit()
        ui.engine.respDelta.emit("Revised draft.")

        assert ui._responding is True
        assert ui.panel._state == "generating"
        assert badge(ui) == "Updating…"
        assert ui.panel.skip_pill.isHidden() is True
        assert ui.panel._burbuja_resp is first
        assert first.actualizada is True
        ui.engine.respDone.emit()
        assert len(ui.panel._burbujas) == count
        assert first._raw == "Revised draft."

    def test_fast_latency_stays_out_of_sight(self, ui):
        ui.start_meeting()

        ui.engine.sttLatency.emit(250)
        ui.engine.e2eLatency.emit(1250)

        assert (ui.panel.lat.isHidden(), ui.panel.e2e.isHidden()) == (True, True)

    def test_slow_latency_signal_updates_label(self, ui):
        """Catch STT latency signals disconnected from their displayed value."""
        ui.start_meeting()

        ui.engine.sttLatency.emit(2000)

        assert (ui.panel.lat.text(), ui.panel.lat.isHidden()) == ("2.0 s", False)

    def test_slow_e2e_signal_updates_label(self, ui):
        """Catch end-to-end latency signals disconnected from their displayed value."""
        ui.start_meeting()

        ui.engine.e2eLatency.emit(3500)

        assert ui.panel.e2e.text() == "⚡ 3.5 s"

    def test_error_preserves_existing_answer(self, ui):
        """Catch an error erasing the suggestion already visible to the user."""
        ui.start_meeting()
        ui.engine.respStart.emit()
        ui.engine.respDelta.emit("Keep this answer.")
        ui.engine.respDone.emit()

        ui.engine.error.emit("provider unavailable")

        assert ui.panel._burbujas[-1]._raw == "Keep this answer."
        assert badge(ui) == "Error"
        assert ui.panel.skip_pill.text() == "Error: provider unavailable"


class TestLateEvents:
    @pytest.mark.parametrize("signal,args", [
        ("status", ("Escuchando la reunion",)),
        ("partial", ("late speech",)),
        ("transcript", ("system", "late transcript")),
        ("noAnswer", ("model_declined",)),
        ("respStart", ()),
        ("respRevise", ()),
        ("sttLatency", (500,)),
        ("e2eLatency", (800,)),
    ])
    def test_stopped_ui_ignores_late_signal(self, ui, signal, args):
        """Catch late engine events changing the idle UI after Stop."""
        ui.start_meeting()
        ui.stop_meeting()

        getattr(ui.engine, signal).emit(*args)

        assert badge(ui) == "Idle"
        assert ui.panel._burbujas == []
        assert ui.panel._state == "idle"
        assert ui.panel.lat.text() == ""
        assert ui.panel.e2e.text() == ""
        assert ui.panel.skip_pill.isHidden() is True

    def test_late_response_done_preserves_idle_badge(self, ui):
        """Catch response completion restoring Listening after Stop."""
        ui.start_meeting()
        ui.engine.respStart.emit()
        ui.engine.respDelta.emit("Final answer.")
        ui.stop_meeting()

        ui.engine.respDone.emit()

        assert badge(ui) == "Idle"
        assert ui.panel._state == "idle"
        assert ui._responding is False


class TestHome:
    def test_app_lands_on_the_home(self, ui):
        assert ui.home.isVisible() is True
        assert (ui.top.isVisible(), ui.panel.isVisible()) == (False, False)

    def test_home_starts_the_meeting_with_its_agent(self, ui):
        ui.home.startMeeting.emit("grok")

        assert ui.engine.starts[-1][0]["agent"] == "grok"
        assert ui.panel.agent_chip.activo == "grok"

    def test_shortcut_starts_with_the_agent_open_in_the_home(self, ui):
        ui.home.abrir_agente("senior")

        ui.toggle_meeting()

        assert ui.engine.starts[-1][0]["agent"] == "senior"

    def test_overlay_toggle_does_nothing_outside_a_meeting(self, ui):
        ui.toggle_overlay()

        assert (ui.top.isVisible(), ui.collapsed.isVisible(), ui._visible) == (
            False, False, True)

    def test_home_saved_reloads_configuration(self, ui, cfg):
        """Catch saved configuration leaving the controller's cache stale."""
        cfg["window_opacity"] = 0.8

        ui.home.saved.emit()

        assert ui.cfg["window_opacity"] == 0.8

    def test_quit_from_home_releases_resources(self, ui, monkeypatch):
        """Catch the close-app action leaving engine or mouse hook alive."""
        quits = []
        monkeypatch.setattr(QtWidgets.QApplication, "quit", lambda: quits.append("quit"))

        ui.home.closeApp.emit()

        assert quits == ["quit"]
        assert ui.home.isVisible() is False
        assert ui.engine.stops == 1
        assert ui.wheel.installed is False


class TestWindows:
    @pytest.mark.parametrize("value,expected", [(-1, 0.15), (0.6, 0.6), (2, 1.0)])
    def test_opacity_is_clamped(self, ui, value, expected):
        """Catch opacity settings making an overlay invisible or exceeding full opacity."""
        ui.cfg["window_opacity"] = value

        ui._apply_opacity()

        assert ui.top.windowOpacity() == pytest.approx(expected, abs=1 / 255)
        assert ui.panel.windowOpacity() == pytest.approx(expected, abs=1 / 255)
        assert ui.collapsed.windowOpacity() == pytest.approx(expected, abs=1 / 255)

    def test_constructor_protects_all_windows(self, ui, native):
        """Catch a new overlay window missing capture protection or no-activate styling."""
        ventanas = [int(w.winId()) for w in (ui.top, ui.panel, ui.screen, ui.collapsed,
                                             ui.raton.cursor, ui.raton.atrapa)]
        assert native["capture"] == ([(w, True) for w in ventanas]
                                     + [(int(ui.home.winId()), True)])
        assert native["activate"] == ventanas
        assert ui.wheel.installed is True

    def test_click_through_only_writes_on_change(self, ui, native):
        """Catch redundant Win32 style writes on every polling tick."""
        ui.start_meeting()
        ui._update_click_through()

        ui._update_click_through()

        assert native["click"] == [(int(ui.top.winId()), True), (int(ui.panel.winId()), True)]

    def test_real_mouse_passes_through_even_over_controls(self, ui, native, monkeypatch):
        """Only the blue mouse touches the overlay: the real one goes through,
        even over the drag handle or a panel, and its wheel too."""
        ui.start_meeting()
        ui._update_click_through()
        native["click"].clear()
        for widget in (ui.top.drag_zone, ui.panel._drag_header, ui.panel.entrada):
            position = widget.mapToGlobal(widget.rect().center())
            monkeypatch.setattr(QtGui.QCursor, "pos", lambda p=position: p)

            ui._update_click_through()

        assert native["click"] == []                 # stays click-through
        assert ui.wheel.zones == []

    def test_shutdown_releases_engine_hooks(self, ui):
        """Catch application shutdown retaining a running timer or mouse hook."""
        ui.start_meeting()
        ui._ct_timer.start(30)

        ui.shutdown()

        assert ui._timer.isActive() is False
        assert ui._ct_timer.isActive() is False
        assert ui.wheel.installed is False
        assert ui.engine.stops == 1
        ui.engine.status.emit("Escuchando la reunion")
        assert badge(ui) == "Loading…"

    def test_shutdown_disconnects_revise(self, ui):
        """Catch a late revision repainting the panel after shutdown."""
        ui.start_meeting()

        ui.shutdown()
        ui.engine.respRevise.emit()

        assert badge(ui) == "Loading…"
        assert ui._responding is False


class TestDualOverlay:
    """Spoken panel alone on the right; with screenshots it moves left and the
    screen panel takes the right column."""

    @pytest.fixture
    def screen_1080p(self, monkeypatch):
        pixmap = QtGui.QPixmap(800, 400)
        pixmap.fill(QtGui.QColor("white"))
        fake = FakeScreen(pixmap)
        monkeypatch.setattr(QtWidgets.QApplication, "primaryScreen",
                            staticmethod(lambda: fake))
        return fake

    def _columns(self, ui):
        ui._place_columns()
        return ui.panel.geometry(), ui.screen.geometry()

    def test_only_the_spoken_panel_exists_at_first_on_the_right(self, ui, screen_1080p):
        voz, _ = self._columns(ui)

        assert ui.screen.isVisible() is False
        assert voz.right() == 1920 - T.SIDE_MARGIN - 1
        assert voz.width() == T.COLUMN_WIDTH

    def test_first_screenshot_moves_spoken_left_and_opens_screen_right(self, ui, screen_1080p):
        ui.start_meeting()
        rows_voz, rows_pant = ui.panel.feed.count(), ui.screen.feed.count()

        ui.take_shot()

        voz, pant = self._columns(ui)
        assert ui._modo_pantalla is True and ui.screen.isVisible() is True
        # Both fill the screen side to side: no empty column in the middle.
        hueco = 1920 - 3 * T.SIDE_MARGIN
        assert voz.left() == T.SIDE_MARGIN
        assert voz.width() == round(hueco * app.PROPORCION_VOZ)
        assert pant.left() == voz.right() + 1 + T.SIDE_MARGIN
        assert pant.right() == 1920 - T.SIDE_MARGIN - 1
        assert voz.top() == pant.top() and voz.height() == pant.height()
        # The thumbnail goes to the screen panel, not to the conversation.
        assert ui.screen.feed.count() == rows_pant + 1
        assert ui.panel.feed.count() == rows_voz

    def test_screen_lane_signals_render_in_the_screen_panel_only(self, ui, screen_1080p):
        ui.start_meeting()
        voice_bubbles = len(ui.panel._burbujas)

        ui.engine.shotStart.emit()
        ui.engine.shotDelta.emit("## Solución\n```py\nprint(1)\n```")
        ui.engine.shotDone.emit()

        assert len(ui.panel._burbujas) == voice_bubbles
        tu = [b for b in ui.screen._burbujas if b.quien == "tu"]
        assert len(tu) == 1 and "print(1)" in tu[0]._raw
        assert ui.screen.isVisible() and ui.screen.badge._lbl.text() == "Ready"

    def test_screen_revision_rewrites_the_same_solution(self, ui, screen_1080p):
        ui.start_meeting()
        ui.engine.shotStart.emit()
        ui.engine.shotDelta.emit("## Solución\nv1")
        ui.engine.shotDone.emit()
        first = [b for b in ui.screen._burbujas if b.quien == "tu"][0]

        ui.engine.shotRevise.emit()
        ui.engine.shotDelta.emit("## Solución\nv2")
        ui.engine.shotDone.emit()

        tu = [b for b in ui.screen._burbujas if b.quien == "tu"]
        assert tu == [first] and first.actualizada and first._raw == "## Solución\nv2"

    def test_suggestion_shows_and_click_relaunches(self, ui, screen_1080p):
        ui.start_meeting()
        ui.set_screen_mode(True)

        ui.engine.screenSuggest.emit("Hay un error en el bucle.")
        # Offered in the spoken panel, where you look while they talk.
        chip = ui.panel.relanzar_chip
        assert chip.isVisible() and chip.texto == "Hay un error en el bucle."
        assert chip in ui.panel.interactive_widgets()
        assert ui.screen.relanzar_chip.isVisible() is False

        chip.click()

        assert ui.engine.relaunches == 1
        assert chip.isVisible() is False

    def test_alt6_relaunches_only_during_a_meeting(self, ui, screen_1080p):
        ui.relaunch_screen()
        assert ui.engine.relaunches == 0

        ui.start_meeting()
        ui.relaunch_screen()
        assert ui.engine.relaunches == 1

    def test_empty_suggestion_hides_the_chip(self, ui, screen_1080p):
        ui.start_meeting()
        ui.set_screen_mode(True)
        ui.engine.screenSuggest.emit("algo")

        ui.engine.screenSuggest.emit("")

        assert ui.panel.relanzar_chip.isVisible() is False

    def test_closing_the_screen_panel_returns_the_spoken_panel_right(self, ui, screen_1080p):
        ui.start_meeting()
        ui.set_screen_mode(True)

        ui.screen.btn_close.click()

        voz, _ = self._columns(ui)
        assert ui._modo_pantalla is False and ui.screen.isVisible() is False
        assert voz.right() == 1920 - T.SIDE_MARGIN - 1

    def test_new_meeting_starts_with_the_spoken_panel_alone(self, ui, screen_1080p):
        ui.start_meeting()
        ui.set_screen_mode(True)
        ui.stop_meeting()

        ui.start_meeting()

        assert ui._modo_pantalla is False and ui.screen.isVisible() is False

    def test_hiding_the_overlay_hides_both_panels_and_restores_both(self, ui, screen_1080p):
        ui.start_meeting()
        ui.set_screen_mode(True)

        ui.toggle_overlay()
        assert (ui.panel.isVisible(), ui.screen.isVisible()) == (False, False)
        ui.toggle_overlay()
        assert (ui.panel.isVisible(), ui.screen.isVisible()) == (True, True)

    def test_wheel_goes_to_the_panel_named_in_the_zone(self, ui, monkeypatch):
        calls = []
        monkeypatch.setattr(ui.panel, "scroll_zone", lambda n, m: calls.append(("voz", n, m)))
        monkeypatch.setattr(ui.screen, "scroll_zone", lambda n, m: calls.append(("pant", n, m)))

        ui._scroll_zone("pantalla:feed", 2)
        ui._scroll_zone("voz:feed", -1)

        assert calls == [("pant", "pantalla:feed", 2), ("voz", "voz:feed", -1)]

    def test_screen_panel_hides_audio_widgets_and_shows_close(self, ui):
        assert ui.screen.bars.isVisibleTo(ui.screen) is False
        assert ui.screen.btn_close.isVisibleTo(ui.screen) is True
        assert ui.panel.btn_close.isVisibleTo(ui.panel) is False

    def test_screen_panel_header_is_inside_the_panel(self, ui):
        # Regression: the header builder reused its own variable name and
        # returned an 8 px dot instead of the header in screen mode.
        header = ui.screen._drag_header
        assert header.window() is ui.screen
        assert ui.screen.btn_close.window() is ui.screen

    def test_long_suggestion_never_pushes_the_screen_panel_off_screen(self, ui, screen_1080p):
        # Regression: the chip's full quote was its minimum width and widened
        # the screen panel past the right edge (640 -> 883 px).
        ui.start_meeting()
        ui.set_screen_mode(True)
        ui.screen.show()
        ui.engine.screenSuggest.emit("Hay un error en el bucle; " * 20)
        QtWidgets.QApplication.processEvents()

        voz, pant = self._columns(ui)

        assert voz.width() == round((1920 - 3 * T.SIDE_MARGIN) * app.PROPORCION_VOZ)
        assert pant.right() <= 1920 - T.SIDE_MARGIN - 1
        assert "…" in ui.panel.relanzar_chip.text()
        assert ui.panel.relanzar_chip.toolTip().startswith("Hay un error en el bucle;")


class TestAgents:
    def test_panel_shows_the_agent_in_use(self, ui):
        chip = ui.panel.agent_chip

        assert (chip.activo, chip.isVisibleTo(ui.panel)) == ("coach", True)
        assert chip.text().startswith("Coach")

    def test_screen_panel_has_no_agent_selector(self, ui):
        assert ui.screen.agent_chip.isVisibleTo(ui.screen) is False

    def test_choosing_an_agent_saves_it(self, ui, isolated_data_dir):
        import json

        ui.choose_agent("grok")

        stored = json.loads((isolated_data_dir / "config.json").read_text(encoding="utf-8"))
        assert (stored["agent"], ui.cfg["agent"]) == ("grok", "grok")
        assert ui.panel.agent_chip.activo == "grok"

    def test_choosing_an_agent_without_meeting_only_selects_it(self, ui):
        ui.choose_agent("grok")

        assert ui.engine.agents == ["grok"]
        assert ui.panel.skip_pill.isHidden() is True

    def test_choosing_an_agent_mid_meeting_says_so_without_touching_the_state(self, ui):
        ui.start_meeting()
        ui.engine.set_agent = lambda aid: {"grok": "Grok"}[aid]

        ui.choose_agent("grok")

        assert ui.panel.skip_pill.text() == "Grok answers from now on"
        assert badge(ui) == "Loading…"

    def test_menu_lists_agents_and_emits_the_choice(self, ui, qtbot):
        chip = ui.panel.agent_chip
        protegidos = []
        chip.antes_de_mostrar = protegidos.append
        chip._abrir()
        acciones = chip.menu.actions()
        marcadas = [a.isChecked() for a in acciones]

        with qtbot.waitSignal(ui.panel.agentChosen) as elegido:
            acciones[2].trigger()

        assert [a.text() for a in acciones] == ["Coach", "Directo", "Grok", "Senior técnico"]
        assert marcadas == [True, False, False, False]
        assert elegido.args == ["grok"] and protegidos == [chip.menu]
        chip.menu.hide()

    def test_long_agent_name_never_widens_the_spoken_panel(self, ui):
        ui.panel.set_agents([("x", "Un agente con un nombre larguísimo de verdad")], "x")

        assert ui.panel.minimumSizeHint().width() <= T.COLUMN_WIDTH


class TestGlass:
    def test_glass_moves_opacity_to_the_acrylic_tint(self, ui, monkeypatch):
        llamadas = []
        monkeypatch.setattr(app.T, "VIDRIO", True)
        monkeypatch.setattr(app, "set_acrylic",
                            lambda hwnd, alpha: llamadas.append(round(alpha, 4)))
        ui.cfg["window_opacity"] = 0.65

        ui._apply_opacity()

        assert llamadas == [round(0.15 + 0.65 * 0.75, 4)] * 4
        assert ui.panel.windowOpacity() == 1.0

    def test_without_glass_opacity_dims_the_whole_window(self, ui):
        ui.cfg["window_opacity"] = 0.5

        ui._apply_opacity()

        assert round(ui.panel.windowOpacity(), 2) == 0.5


class TestModes:
    def test_screenshot_is_refused_when_the_agent_has_no_screens(self, ui):
        ui.start_meeting()
        ui.engine.permite_capturas = False

        ui.take_shot()

        assert ui._shots == [] and ui.panel.skip_pill.text() == "This agent doesn't use screenshots"

    def test_notetaker_does_not_answer_on_demand(self, ui):
        ui.start_meeting()
        ui.engine.modo = "notetaker"

        ui.answer_now()

        assert ui.engine.answers == 0 and ui.panel.skip_pill.text() == "This agent only takes notes"

    def test_manual_question_offers_the_shortcut(self, ui):
        ui.start_meeting()

        ui.engine.noAnswer.emit("manual")

        assert ui.panel.skip_pill.text() == "Question — Caps+A to answer"

    def test_notetaker_listens_as_taking_notes(self, ui):
        ui.start_meeting()
        ui.engine.modo = "notetaker"

        ui.engine.status.emit("Escuchando la reunion.")

        assert badge(ui) == "Taking notes"

    def test_notetaker_meeting_says_no_answers(self, ui, cfg):
        import agents
        lista = agents.list_agents()
        lista[0]["modo"] = "notetaker"
        agents.write_all(lista)

        ui.start_meeting("coach")

        assert any("Taking notes — no answers" in t for t in
                   [lab.text() for lab in ui.panel.scroll.widget().findChildren(QtWidgets.QLabel)])

    def test_notes_signals_reach_the_home(self, ui):
        ui.engine.notesStarted.emit("sesion-x")
        assert ui.home._notas_estado == {"sesion-x": "generando"}

        ui.engine.notesReady.emit("sesion-x", False)

        assert ui.home._notas_estado == {"sesion-x": "error"}


class FakeAtajos:
    def __init__(self, hook=True, ocupados=()):
        self.hook_instalado = hook
        self.ocupados = list(ocupados)
        self.estados = []

    def set_activo(self, on):
        self.estados.append(on)
        return self.ocupados if on else []


class TestShortcutsOnlyInMeetings:
    def test_meeting_switches_shortcuts_on_and_off(self, ui):
        ui.atajos = FakeAtajos()

        ui.start_meeting()
        ui.stop_meeting()

        assert ui.atajos.estados == [True, False]

    def test_blocked_start_never_switches_them_on(self, ui, cfg):
        ui.atajos = FakeAtajos()
        cfg["openai_api_key"] = ""

        ui.start_meeting()

        assert ui.atajos.estados == []

    def test_failed_start_switches_them_off_again(self, ui):
        ui.atajos = FakeAtajos()
        ui.engine.start_error = "No se pudo conectar"

        ui.start_meeting()

        assert ui.atajos.estados == [True, False]

    def test_without_hook_the_meeting_points_to_alt(self, ui):
        ui.atajos = FakeAtajos(hook=False, ocupados=["Alt+2"])

        ui.start_meeting()

        assert ui.panel.skip_pill.text() == "Caps Lock shortcuts unavailable — use Alt+1…9 (in use: Alt+2)"


class TestTypedQuestions:
    """Caps+E: the question field lives in the spoken panel; the answer opens
    on the big panel, under the question."""

    @pytest.fixture
    def meeting(self, ui):
        ui.start_meeting()
        yield ui
        QtWidgets.QApplication.processEvents()

    @pytest.fixture
    def activations(self, monkeypatch):
        calls = []
        monkeypatch.setattr(app, "set_no_activate",
                            lambda handle, on=True: calls.append((int(handle), on)))
        return calls

    def test_does_nothing_outside_a_meeting(self, ui, native):
        ui.toggle_ask()

        assert native["front"] == [] and ui._escribiendo is False

    def test_caps_e_gives_the_spoken_panel_the_keyboard(self, meeting, native, activations):
        ui = meeting

        ui.toggle_ask()

        assert ui._escribiendo is True
        assert activations == [(int(ui.panel.winId()), False)]   # may take focus now
        assert native["front"] == [int(ui.panel.winId())]

    def test_esc_gives_the_keyboard_back_and_stops_stealing_focus(self, meeting, native,
                                                                 activations, monkeypatch):
        ui = meeting
        ui.toggle_ask()
        monkeypatch.setattr(ui.panel, "isActiveWindow", lambda: True)

        ui.panel.entradaSalir.emit()

        assert ui._escribiendo is False
        assert native["back"] == [4242]
        assert activations[-1] == (int(ui.panel.winId()), True)

    def test_caps_e_again_while_typing_gives_the_keyboard_back(self, meeting, native,
                                                               monkeypatch):
        ui = meeting
        ui.toggle_ask()
        monkeypatch.setattr(ui.panel, "tiene_foco", lambda: True)
        monkeypatch.setattr(ui.panel, "isActiveWindow", lambda: True)

        ui.toggle_ask()

        assert ui._escribiendo is False and native["back"] == [4242]

    def test_clicking_the_field_takes_the_keyboard(self, meeting, native):
        ui = meeting

        ui.panel.entradaPulsada.emit()

        assert ui._escribiendo is True and native["front"] == [int(ui.panel.winId())]

    def test_question_shows_on_the_big_panel_and_goes_to_the_engine(self, meeting):
        ui = meeting

        ui.panel.submitted.emit("¿Y si lo hago recursivo?")

        assert ui.engine.questions == ["¿Y si lo hago recursivo?"]
        assert ui._modo_pantalla is True and ui.screen.isVisible()
        assert [b.quien for b in ui.screen._burbujas] == ["pregunta"]
        assert ui.panel._burbujas == []
        assert ui.screen.badge._lbl.text() == "Thinking…"

    def test_answer_streams_into_the_big_panel(self, meeting, qtbot):
        ui = meeting
        ui.panel.submitted.emit("¿Y si lo hago recursivo?")

        ui.engine.askStart.emit()
        ui.engine.askDelta.emit("## Respuesta\nAsí.")
        ui.engine.askDone.emit()

        assert [b.quien for b in ui.screen._burbujas] == ["pregunta", "respuesta"]
        assert ui.screen._burbujas[-1]._raw == "## Respuesta\nAsí."
        assert ui.screen.badge._lbl.text() == "Ready"
        qtbot.wait(5)

    def test_questions_wait_their_turn(self, meeting, qtbot):
        ui = meeting
        ui.panel.submitted.emit("primera")

        ui.panel.submitted.emit("segunda")

        assert ui.engine.questions == ["primera"]
        assert ui.panel.skip_pill.text() == "1 question queued — after this answer"
        ui.engine.askStart.emit()
        ui.engine.askDelta.emit("uno")
        ui.engine.askDone.emit()
        assert ui.engine.questions == ["primera", "segunda"]
        qtbot.wait(5)

    def test_error_is_reported_without_an_empty_answer(self, meeting):
        ui = meeting
        ui.panel.submitted.emit("hola")

        ui.engine.askError.emit("503 overloaded")

        assert ui.screen.badge._lbl.text() == "Error"
        assert ui.panel.skip_pill.text() == "Error: 503 overloaded"
        assert [b.quien for b in ui.screen._burbujas] == ["pregunta"]

    def test_hiding_the_panels_gives_the_keyboard_back(self, meeting, native, monkeypatch):
        ui = meeting
        ui.toggle_ask()
        monkeypatch.setattr(ui.panel, "isActiveWindow", lambda: True)

        ui.toggle_overlay()

        assert ui._escribiendo is False and native["back"] == [4242]

    def test_new_meeting_starts_with_an_empty_field(self, meeting):
        ui = meeting
        ui.panel.entrada.setPlainText("a medias")
        ui.stop_meeting()

        ui.start_meeting()

        assert ui.panel.entrada.toPlainText() == "" and ui._preguntando is False


class TestSolveSpoken:
    """Caps+R: what they said, solved big on the big panel (no screenshot)."""

    def test_solves_on_the_big_panel(self, ui):
        ui.start_meeting()
        ui.engine.spoken_text = "Implementa una cola con dos pilas"

        ui.resolve_spoken()

        assert ui.engine.spoken == 1
        assert ui._modo_pantalla is True and ui.screen.badge._lbl.text() == "Solving…"

    def test_nothing_said_yet_is_explained(self, ui):
        ui.start_meeting()

        ui.resolve_spoken()

        assert ui.panel.skip_pill.text() == "Nothing said yet to solve"
        assert ui._modo_pantalla is False

    def test_notetaker_does_not_solve(self, ui):
        ui.start_meeting()
        ui.engine.modo = "notetaker"

        ui.resolve_spoken()

        assert getattr(ui.engine, "spoken", 0) == 0


class TestResolution:
    """Manual | AI: one mode for both panels; switching never redoes on its own."""

    def test_meeting_starts_in_the_agents_mode(self, ui, isolated_data_dir):
        lista = agents_mod.list_agents()
        lista[0]["resolucion"] = "ia"
        agents_mod.write_all(lista)

        ui.start_meeting("coach")

        assert ui.panel.modo_chip.modo == "ia" and ui.screen.modo_chip.modo == "ia"

    def test_switching_on_one_panel_switches_both_and_redoes_nothing(self, ui, qtbot):
        ui.start_meeting()

        qtbot.mouseClick(ui.panel.modo_chip.botones["ia"], QtCore.Qt.LeftButton)

        assert ui.engine.resoluciones == ["ia"]
        assert ui.screen.modo_chip.modo == "ia"
        assert getattr(ui.engine, "redos", 0) == 0
        assert ui.panel.skip_pill.text() == "AI mode"

    def test_with_a_solution_it_says_how_to_redo(self, ui):
        ui.start_meeting()
        ui.engine.redo = True
        ui.set_screen_mode(True)

        ui.screen.modo_chip.changed.emit("ia")

        assert ui.screen.skip_pill.text() == "AI mode — Caps+D redoes the solution in this mode"
        assert getattr(ui.engine, "redos", 0) == 0

    def test_caps_d_without_new_shots_redoes_in_the_current_mode(self, ui):
        ui.start_meeting()
        ui.engine.redo = True
        ui.engine.resolucion = "ia"

        ui.generate()

        assert ui.engine.redos == 1 and ui.engine.screenshots == []
        assert ui.screen.skip_pill.text() == "Redoing the solution in AI mode"

    def test_switch_outside_a_meeting_only_moves_the_chips(self, ui):
        ui.set_resolucion("ia")

        assert ui.engine.resoluciones == []
        assert ui.screen.modo_chip.modo == "ia"


class TestExplainSelection:
    """Underline text in any panel, Explain -> answered on the big panel."""

    @pytest.fixture
    def meeting(self, ui):
        ui.start_meeting()
        yield ui
        QtWidgets.QApplication.processEvents()

    def test_explain_answers_on_the_big_panel_without_taking_the_keyboard(self, meeting,
                                                                         native):
        ui = meeting

        ui.panel.explainRequested.emit("idempotencia", "voz:tu")

        assert native["front"] == []
        assert ui.engine.questions == [
            "Explícame esto de lo que me sugeriste decir en voz alta: «idempotencia»"]
        assert ui._modo_pantalla is True

    def test_explain_outside_a_meeting_does_nothing(self, ui):
        ui.screen.explainRequested.emit("x", "pantalla:tu")

        assert ui.engine.questions == []

    def test_caps_e_with_a_selection_quotes_it_in_the_field(self, meeting, native,
                                                           monkeypatch):
        ui = meeting
        monkeypatch.setattr(ui.screen, "seleccion", lambda: ("ledger", "pantalla:tu"))
        limpiadas = []
        monkeypatch.setattr(ui.screen, "limpiar_seleccion", lambda: limpiadas.append(1))

        ui.toggle_ask()

        assert ui.panel.entrada.toPlainText() == "«ledger» "
        assert native["front"] == [int(ui.panel.winId())] and limpiadas == [1]


class TestBlueMouse:
    """Caps+Q: the blue mouse, only while the panels are on screen."""

    def test_toggles_only_in_a_meeting_with_the_panels_visible(self, ui):
        ui.toggle_mouse()
        assert ui.raton.activo is False

        ui.start_meeting()
        ui.toggle_mouse()
        assert ui.raton.activo is True
        assert ui.panel.skip_pill.text().startswith("Blue mouse on")

        ui.toggle_mouse()
        assert ui.raton.activo is False

    def test_hiding_the_panels_switches_it_off(self, ui):
        ui.start_meeting()
        ui.toggle_mouse()

        ui.toggle_overlay()

        assert ui.raton.activo is False
        ui.toggle_mouse()                   # minimized: nothing to touch
        assert ui.raton.activo is False

    def test_ending_the_meeting_switches_it_off(self, ui):
        ui.start_meeting()
        ui.toggle_mouse()

        ui.stop_meeting()

        assert ui.raton.activo is False

    def test_with_it_on_the_real_mouse_never_touches_the_overlay(self, ui, native):
        ui.start_meeting()
        ui.toggle_mouse()
        native["click"].clear()

        ui._update_click_through()

        assert all(on for _h, on in native["click"])
        assert ui.wheel.zones == []

    def test_its_wheel_scrolls_the_panel_under_it(self, ui, monkeypatch):
        ui.start_meeting()
        ui.set_screen_mode(True)
        movidas = []
        monkeypatch.setattr(ui, "_scroll_zone", lambda nombre, m: movidas.append((nombre, m)))
        monkeypatch.setattr(ui.screen, "wheel_zones",
                            lambda: [((100, 100, 200, 200), "pantalla:feed")])
        monkeypatch.setattr(ui.panel, "wheel_zones", lambda: [])

        ui._rodar_virtual(QtCore.QPoint(150, 150), 2)
        ui._rodar_virtual(QtCore.QPoint(10, 10), 1)

        assert movidas == [("pantalla:feed", 2)]

    def test_it_can_touch_every_overlay_window(self, ui):
        assert ui._ventanas_overlay() == [ui.top, ui.panel, ui.screen, ui.collapsed]


@pytest.mark.parametrize("texto, origen, esperado", [
    ("a   b\nc", "voz:ellos", "Explícame esto de lo que dijeron en la reunión: «a b c»"),
    ("x", "pantalla:respuesta", "Explícame esto de tu respuesta en el panel grande: «x»"),
    ("x", "raro:otro", "Explícame esto: «x»"),
])
def test_explain_question_text(texto, origen, esperado):
    assert app.pregunta_subrayado(texto, origen) == esperado


def test_explain_question_is_capped():
    pregunta = app.pregunta_subrayado("a" * 5000, "pantalla:tu")

    assert pregunta.endswith("a…»") and len(pregunta) < app.MAX_SUBRAYADO + 80


class TestPrewarm:
    def test_starting_agent_is_prewarmed_and_opening_another_too(self, ui, no_prewarm):
        assert no_prewarm[0] == ui.cfg.get("agent", "coach")

        ui.home.abrir_agente("grok")

        assert no_prewarm[-1] == "grok"
