"""OverlayApp tests with real Qt widgets and isolated OS/engine boundaries."""
import base64

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

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
    status = QtCore.Signal(str)
    error = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.starts = []
        self.stops = 0
        self.answers = 0
        self.relaunches = 0
        self.screenshots = []
        self.start_error = None
        self.running = False

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
    monkeypatch.setattr(app, "set_capture_protection",
                        lambda handle, active: calls["capture"].append((int(handle), active)))
    monkeypatch.setattr(app, "set_no_activate",
                        lambda handle: calls["activate"].append(int(handle)))
    monkeypatch.setattr(app, "set_click_through",
                        lambda handle, active: calls["click"].append((int(handle), active)))
    monkeypatch.setattr(QtWidgets.QApplication, "mouseButtons", lambda: QtCore.Qt.NoButton)
    monkeypatch.setattr(QtGui.QCursor, "pos", lambda: QtCore.QPoint(-10000, -10000))
    return calls


@pytest.fixture
def ui(qtbot, monkeypatch, cfg, native):
    monkeypatch.setattr(app, "CoachEngine", FakeEngine)
    monkeypatch.setattr(app.cfg_mod, "load_config", lambda: dict(cfg))
    controller = app.OverlayApp()
    for widget in (controller.top, controller.panel, controller.screen,
                   controller.collapsed):
        qtbot.addWidget(widget)
    controller._ct_timer.stop()
    yield controller
    if controller.settings is not None:
        controller.settings.close()
    if controller.wheel.installed:
        controller.shutdown()
    QtWidgets.QApplication.processEvents()


@pytest.fixture
def settings_assets(monkeypatch, tmp_path):
    """Keep the real settings widget's generated icon in its temporary directory."""
    import icons

    save_png = icons.save_png
    monkeypatch.setattr(icons, "save_png", lambda name, color, size, path:
                        save_png(name, color, size, str(tmp_path / "chevron.png")))


def open_registered_settings(ui, qtbot):
    ui.open_settings()
    qtbot.addWidget(ui.settings)
    return ui.settings


def badge(ui):
    return ui.panel.badge._lbl.text()


class TestMeeting:
    def test_missing_openai_key_blocks_start(self, ui, cfg):
        """Catch a live session starting without the LLM credential."""
        cfg["openai_api_key"] = ""
        expected = "Add your OpenAI API key in Settings (⚙) to start"

        ui.start_meeting()

        assert badge(ui) == expected
        assert ui.engine.starts == []
        assert ui._running is False
        assert ui._timer.isActive() is False

    @pytest.mark.parametrize("test_mode", [False, True])
    def test_start_requires_stream_key(self, ui, cfg, test_mode):
        """Catch test mode bypassing the required STT credential."""
        cfg.update(assemblyai_api_key="", test_mode=test_mode)

        ui.start_meeting()

        assert badge(ui) == "Add your AssemblyAI key in Settings (⚙) to start"
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

        assert (badge(ui), ui.panel.skip_pill.text()) == (
            "Error", "Error: No se pudo iniciar OpenAI: bad key")

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

        assert badge(ui) == "Start the meeting first"
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
        assert ui.screen.badge._lbl.text() == "1 screenshot ready — Alt+3 to generate"
        assert ui.top.keys_gen.isEnabled() is True
        assert ui.engine.screenshots == []

    def test_generate_requires_screenshots(self, ui):
        """Catch Generate submitting an empty screenshot batch."""
        ui.start_meeting()

        ui.generate()

        assert badge(ui) == "Take a screenshot first"
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
        ui.toggle_overlay()

        assert (ui.top.isVisible(), ui.panel.isVisible(), ui.collapsed.isVisible()) == (False, False, True)
        assert ui._visible is False

    def test_toggle_restores_overlay(self, ui):
        """Catch the restore control failing to restore both overlay windows."""
        ui.toggle_overlay()

        ui.toggle_overlay()

        assert (ui.top.isVisible(), ui.panel.isVisible(), ui.collapsed.isVisible()) == (True, True, False)
        assert ui._visible is True


class TestEvents:
    @pytest.mark.parametrize("message,expected", [
        ("Cargando modelo de transcripcion...", "Loading model…"),
        ("Escuchando la reunion.", "Listening"),
        ("Sigue hablando...", "Still talking…"),
        ("Sin pregunta todavia: guardado como contexto.", "Context saved"),
        ("Aun no hay nada que responder.", "Nothing to answer yet"),
        ("Modelo listo.", "Loading…"),
    ])
    def test_engine_status_maps_to_badge(self, ui, message, expected):
        """Catch untranslated engine messages or unrelated messages replacing the badge."""
        ui.start_meeting()

        ui.engine.status.emit(message)

        assert badge(ui) == expected

    @pytest.mark.parametrize("reason,expected", [
        ("model_declined", "Not a question — Alt+5 to answer"),
        ("no_question", "No question yet — Alt+5 to answer"),
        ("follow_up", "Added to the current question — Alt+5 for a new answer"),
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

    def test_latency_signal_updates_label(self, ui):
        """Catch STT latency signals disconnected from their displayed value."""
        ui.start_meeting()

        ui.engine.sttLatency.emit(250)

        assert ui.panel.lat.text() == "250 ms"

    def test_e2e_signal_updates_label(self, ui):
        """Catch end-to-end latency signals disconnected from their displayed value."""
        ui.start_meeting()

        ui.engine.e2eLatency.emit(1250)

        assert ui.panel.e2e.text() == "⚡ 1.2 s"

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


class TestSettings:
    def test_running_meeting_blocks_settings(self, ui):
        """Catch configuration opening while an audio session is active."""
        ui.start_meeting()

        ui.open_settings()

        assert ui.settings is None
        assert badge(ui) == "Stop the meeting to open settings"

    def test_settings_hides_overlay(self, ui, qtbot, settings_assets, cfg):
        """Catch settings opening with stale configuration or overlapping overlays."""
        cfg["language"] = "en"

        window = open_registered_settings(ui, qtbot)

        assert window.cfg["language"] == "en"
        assert window.isVisible() is True
        assert (ui.top.isVisible(), ui.panel.isVisible(), ui.collapsed.isVisible()) == (False, False, False)
        assert ui._ct_timer.isActive() is False

    @pytest.mark.parametrize("action", ["toggle_meeting", "toggle_overlay", "answer_now", "open_settings"])
    def test_settings_blocks_overlay_action(self, ui, qtbot, settings_assets, action):
        """Catch shortcuts acting on the hidden overlay while settings is open."""
        window = open_registered_settings(ui, qtbot)

        getattr(ui, action)()

        assert ui.settings is window
        assert ui.engine.starts == []
        assert ui.engine.answers == 0
        assert ui._visible is True
        assert (ui.top.isVisible(), ui.panel.isVisible(), ui.collapsed.isVisible()) == (False, False, False)

    @pytest.mark.parametrize("visible,expected", [(True, (True, True, False)),
                                                (False, (False, False, True))])
    def test_settings_closed_restores_visibility(self, ui, qtbot, settings_assets, visible, expected):
        """Catch closing settings losing the previous expanded/collapsed state."""
        ui._visible = visible
        window = open_registered_settings(ui, qtbot)
        ui._ct_state[ui.top] = True
        window.close()

        window.closed.emit()

        assert ui.settings is None
        assert (ui.top.isVisible(), ui.panel.isVisible(), ui.collapsed.isVisible()) == expected
        assert ui._ct_timer.interval() == 30
        assert ui._ct_timer.isActive() is True
        assert ui._ct_state == {}

    def test_settings_saved_reloads_configuration(self, ui, qtbot, settings_assets, cfg):
        """Catch saved configuration leaving the controller's cache stale."""
        window = open_registered_settings(ui, qtbot)
        cfg["window_opacity"] = 0.8

        window.saved.emit()

        assert ui.cfg["window_opacity"] == 0.8

    def test_quit_from_settings_releases_resources(self, ui, qtbot, settings_assets, monkeypatch):
        """Catch the settings close-app action leaving engine or mouse hook alive."""
        window = open_registered_settings(ui, qtbot)
        quits = []
        monkeypatch.setattr(QtWidgets.QApplication, "quit", lambda: quits.append("quit"))

        window.closeApp.emit()

        assert quits == ["quit"]
        assert ui.settings is None
        assert window.isVisible() is False
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
        ventanas = [int(w.winId()) for w in (ui.top, ui.panel, ui.screen, ui.collapsed)]
        assert native["capture"] == [(w, True) for w in ventanas]
        assert native["activate"] == ventanas
        assert ui.wheel.installed is True

    def test_click_through_only_writes_on_change(self, ui, native):
        """Catch redundant Win32 style writes on every polling tick."""
        ui._update_click_through()

        ui._update_click_through()

        assert native["click"] == [(int(ui.top.winId()), True), (int(ui.panel.winId()), True)]

    def test_interactive_control_disables_click_through(self, ui, native, monkeypatch):
        """Catch the settings control remaining click-through under the cursor."""
        ui._update_click_through()
        native["click"].clear()
        position = ui.top.btn_cfg.mapToGlobal(ui.top.btn_cfg.rect().center())
        monkeypatch.setattr(QtGui.QCursor, "pos", lambda: position)

        ui._update_click_through()

        assert native["click"] == [(int(ui.top.winId()), False)]

    def test_drag_suspends_click_through_changes(self, ui, native, monkeypatch):
        """Catch polling changing mouse transparency midway through a drag."""
        monkeypatch.setattr(QtWidgets.QApplication, "mouseButtons", lambda: QtCore.Qt.LeftButton)

        ui._update_click_through()

        assert native["click"] == []
        assert ui.wheel.zones is None

    def test_interactive_panel_disables_wheel_forwarding(self, ui, monkeypatch):
        """Catch Qt and the mouse hook both processing the same wheel event."""
        position = ui.panel._drag_header.mapToGlobal(ui.panel._drag_header.rect().center())
        monkeypatch.setattr(QtGui.QCursor, "pos", lambda: position)

        ui._update_click_through()

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
        assert voz.left() == T.SIDE_MARGIN
        assert pant.right() == 1920 - T.SIDE_MARGIN - 1
        assert pant.width() == T.SCREEN_WIDTH
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
        chip = ui.screen.relanzar_chip
        assert chip.isVisible() and "Hay un error en el bucle." in chip.text()
        assert chip in ui.screen.interactive_widgets()

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

        assert ui.screen.relanzar_chip.isVisible() is False

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

        _voz, pant = self._columns(ui)

        assert pant.width() == T.SCREEN_WIDTH
        assert pant.right() <= 1920 - T.SIDE_MARGIN - 1
        assert "…" in ui.screen.relanzar_chip.text()
        assert ui.screen.relanzar_chip.toolTip().startswith("Hay un error en el bucle;")
