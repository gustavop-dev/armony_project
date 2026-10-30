"""Widget tests for the chrome of overlay_ui.TranscriptPanel.

Covers the header (status badge, level dot, latency meters), the skip pill,
visual state, click-through zones, wheel scrolling with auto-follow, and the
drag / resize handles. Runs on the offscreen Qt platform; this module makes no
Win32 calls, so nothing is mocked.
"""
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import overlay_ui

CARET = "&#9611;"
GOLD = "#7c95ff"
PARTICIPANT_DOT_OFF = "#8e9bb8"
LONG = "word " * 120


# --------------------------------------------------------------- helpers

def flush_deletes():
    """Destroy widgets scheduled with deleteLater so findChildren skips them."""
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def bubbles(panel, who):
    """Live bubbles of one speaker ('ellos' = participant, 'tu' = suggestion)."""
    flush_deletes()
    return [b for b in panel.findChildren(overlay_ui.Burbuja) if b.quien == who]


def texts(widget):
    """Text of every QLabel under a widget, in creation order."""
    flush_deletes()
    return [lab.text() for lab in widget.findChildren(QtWidgets.QLabel)]


def joined(widget):
    return "\n".join(texts(widget))


def badge_dot_style(panel):
    return panel.badge.findChildren(QtWidgets.QLabel)[0].styleSheet()


def badge_text(panel):
    return panel.badge.findChildren(QtWidgets.QLabel)[1].text()


def mouse(kind, global_pos, button=QtCore.Qt.LeftButton,
          buttons=QtCore.Qt.LeftButton):
    pos = QtCore.QPointF(*global_pos)
    return QtGui.QMouseEvent(kind, QtCore.QPointF(1, 1), pos, button, buttons,
                             QtCore.Qt.NoModifier)


def send(widget, event):
    """Deliver an event through Qt dispatch, as a real mouse would."""
    QtWidgets.QApplication.sendEvent(widget, event)


@pytest.fixture
def panel(qtbot):
    p = overlay_ui.TranscriptPanel()
    qtbot.addWidget(p)
    yield p
    # The panel schedules single-shot timers on plain Python callables, which
    # Qt does not cancel when the widget dies. Drain them while it still lives
    # so they cannot fire inside the next test.
    qtbot.wait(overlay_ui.INTERVALO_REPINTADO + 20)


@pytest.fixture
def shown_panel(qtbot, panel):
    panel.resize(640, 340)
    panel.show()
    qtbot.waitExposed(panel)
    # Showing is itself a width change: let that resize settle first.
    qtbot.waitUntil(lambda: panel.scroll.horizontalScrollBarPolicy()
                    == QtCore.Qt.ScrollBarAsNeeded, timeout=2000)
    return panel


@pytest.fixture
def scrollable_panel(qtbot, shown_panel):
    """A visible panel whose thread overflows, scrolled to the bottom."""
    for _ in range(6):
        shown_panel.set_hint(LONG)
    sb = shown_panel.scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: sb.maximum() > 0 and sb.value() == sb.maximum())
    return shown_panel


# --------------------------------------------------------------- status badge

def test_badge_starts_idle(panel):
    assert badge_text(panel) == "Idle"


def test_set_status_shows_text(panel):
    panel.set_status("Listening")

    assert badge_text(panel) == "Listening"











# --------------------------------------------------------------- latency

def test_latency_labels_start_hidden(panel):
    assert (panel.lat.isHidden(), panel.e2e.isHidden()) == (True, True)




















def test_clear_latency_hides_both_meters(panel):
    panel.set_latency(300)
    panel.set_e2e(1200)

    panel.clear_latency()

    assert (panel.lat.isHidden(), panel.e2e.isHidden()) == (True, True)


def test_clear_latency_empties_both_meters(panel):
    panel.set_latency(300)
    panel.set_e2e(1200)

    panel.clear_latency()

    assert (panel.lat.text(), panel.e2e.text()) == ("", "")


# --------------------------------------------------------------- state / border

@pytest.mark.parametrize("state, width", [
    ("idle", 1),
    ("listening", 1),
    ("generating", 2),
])
def test_set_state_sets_border_width(panel, state, width):
    panel.set_state(state)

    assert panel.card._grosor == width


def test_listening_border_pulses(qtbot, panel):
    panel.set_state("listening")
    first = panel.card._color.alpha()

    qtbot.waitUntil(lambda: panel.card._color.alpha() != first, timeout=2000)


def test_generating_state_hides_caret(panel):
    panel.set_state("generating")

    panel.set_question("Tell me about")

    assert CARET not in joined(bubbles(panel, "ellos")[0])


# --------------------------------------------------------------- interactive zones

def test_interactive_widgets_include_header_scrollbar_and_grip(panel):
    zones = panel.interactive_widgets()

    assert [panel._drag_header, panel.scroll.verticalScrollBar(),
            panel.resize_grip] == zones[:3]


def test_interactive_widgets_skip_viewport_without_overflow(panel):
    assert panel.scroll.viewport() not in panel.interactive_widgets()


def test_interactive_widgets_include_viewport_with_overflow(scrollable_panel):
    assert scrollable_panel.scroll.viewport() in scrollable_panel.interactive_widgets()


# --------------------------------------------------------------- wheel / scroll

def test_wheel_zones_empty_when_hidden(panel):
    assert panel.wheel_zones() == []


def test_wheel_zones_name_feed_when_visible(shown_panel):
    # With two panels on screen the zone carries the panel mode in front.
    assert [name for _rect, name in shown_panel.wheel_zones()] == ["voz:feed"]


def test_wheel_zone_rect_matches_scroll_area_size(shown_panel):
    (_x, _y, w, h), _name = shown_panel.wheel_zones()[0]

    assert (w, h) == (shown_panel.scroll.width(), shown_panel.scroll.height())


def test_scroll_zone_up_leaves_bottom(scrollable_panel):
    sb = scrollable_panel.scroll.verticalScrollBar()

    scrollable_panel.scroll_zone("feed", 1)

    assert sb.value() < sb.maximum()


def test_scroll_zone_down_returns_to_bottom(scrollable_panel):
    sb = scrollable_panel.scroll.verticalScrollBar()
    scrollable_panel.scroll_zone("feed", 1)

    scrollable_panel.scroll_zone("feed", -1)

    assert sb.value() == sb.maximum()


def test_scroll_zone_unknown_name_is_ignored(scrollable_panel):
    sb = scrollable_panel.scroll.verticalScrollBar()
    before = sb.value()

    scrollable_panel.scroll_zone("answer", 1)

    assert sb.value() == before


def test_new_content_keeps_following_bottom(qtbot, scrollable_panel):
    sb = scrollable_panel.scroll.verticalScrollBar()
    old_max = sb.maximum()

    scrollable_panel.set_hint(LONG * 3)

    qtbot.waitUntil(lambda: sb.maximum() > old_max and sb.value() == sb.maximum())


def test_new_content_keeps_position_after_scrolling_up(qtbot, scrollable_panel):
    sb = scrollable_panel.scroll.verticalScrollBar()
    scrollable_panel.scroll_zone("feed", 1)
    held = sb.value()
    old_max = sb.maximum()

    scrollable_panel.set_hint(LONG * 3)
    qtbot.waitUntil(lambda: sb.maximum() > old_max)

    assert sb.value() == held


def test_manual_scrollbar_drag_stops_following(qtbot, scrollable_panel):
    sb = scrollable_panel.scroll.verticalScrollBar()
    sb.setValue(0)
    old_max = sb.maximum()

    scrollable_panel.set_hint(LONG * 3)
    qtbot.waitUntil(lambda: sb.maximum() > old_max)

    assert sb.value() == 0


# --------------------------------------------------------------- move / resize

def test_resize_grip_sits_in_bottom_right_corner(shown_panel):
    shown_panel.resize(800, 420)
    card = shown_panel.card

    assert shown_panel.resize_grip.geometry().bottomRight() == QtCore.QPoint(
        card.width() - 8, card.height() - 8)


def test_width_change_hides_horizontal_scrollbar_while_dragging(shown_panel):
    shown_panel.resize(700, 340)

    assert (shown_panel.scroll.horizontalScrollBarPolicy()
            == QtCore.Qt.ScrollBarAlwaysOff)


def test_width_change_restores_horizontal_scrollbar_after_pause(qtbot, shown_panel):
    shown_panel.resize(700, 340)

    qtbot.waitUntil(lambda: shown_panel.scroll.horizontalScrollBarPolicy()
                    == QtCore.Qt.ScrollBarAsNeeded, timeout=2000)


def test_width_change_unfreezes_to_viewport_width(qtbot, shown_panel):
    shown_panel.resize(760, 340)
    qtbot.waitUntil(lambda: shown_panel.scroll.horizontalScrollBarPolicy()
                    == QtCore.Qt.ScrollBarAsNeeded, timeout=2000)

    assert shown_panel._cont.maximumWidth() == 16777215


def test_height_change_keeps_horizontal_scrollbar_policy(shown_panel):
    shown_panel.resize(640, 400)

    assert (shown_panel.scroll.horizontalScrollBarPolicy()
            == QtCore.Qt.ScrollBarAsNeeded)


def test_resize_grip_drag_grows_window(shown_panel):
    grip = shown_panel.resize_grip
    shown_panel.resize(640, 340)

    send(grip, mouse(QtCore.QEvent.MouseButtonPress, (500, 500)))
    send(grip, mouse(QtCore.QEvent.MouseMove, (560, 540),
                              button=QtCore.Qt.NoButton))

    assert shown_panel.size() == QtCore.QSize(700, 380)


def test_resize_grip_drag_respects_minimum_size(shown_panel):
    grip = shown_panel.resize_grip

    send(grip, mouse(QtCore.QEvent.MouseButtonPress, (500, 500)))
    send(grip, mouse(QtCore.QEvent.MouseMove, (0, 0),
                              button=QtCore.Qt.NoButton))

    assert shown_panel.width() == 520


def test_resize_grip_ignores_move_after_release(shown_panel):
    grip = shown_panel.resize_grip
    shown_panel.resize(640, 340)
    send(grip, mouse(QtCore.QEvent.MouseButtonPress, (500, 500)))
    send(grip, mouse(QtCore.QEvent.MouseButtonRelease, (500, 500)))

    send(grip, mouse(QtCore.QEvent.MouseMove, (560, 540),
                              button=QtCore.Qt.NoButton))

    assert shown_panel.size() == QtCore.QSize(640, 340)


def test_header_drag_moves_panel(shown_panel):
    shown_panel.move(100, 100)
    header = shown_panel._drag_header

    send(header, mouse(QtCore.QEvent.MouseButtonPress, (150, 110)))
    send(header, mouse(QtCore.QEvent.MouseMove, (200, 140),
                                button=QtCore.Qt.NoButton))

    assert shown_panel.pos() == QtCore.QPoint(150, 130)


def test_header_drag_stops_after_release(shown_panel):
    shown_panel.move(100, 100)
    header = shown_panel._drag_header
    send(header, mouse(QtCore.QEvent.MouseButtonPress, (150, 110)))
    send(header, mouse(QtCore.QEvent.MouseButtonRelease, (150, 110)))

    send(header, mouse(QtCore.QEvent.MouseMove, (200, 140),
                                button=QtCore.Qt.NoButton))

    assert shown_panel.pos() == QtCore.QPoint(100, 100)


# ------------------------------------------------------- latency: only when slow
@pytest.mark.parametrize("ms", [250, 1499])
def test_fast_transcription_latency_stays_hidden(panel, ms):
    panel.set_latency(ms)

    assert panel.lat.isVisibleTo(panel) is False


@pytest.mark.parametrize("ms, texto, color", [(1500, "1.5 s", "#e9a23b"),
                                              (3000, "3.0 s", "#e0554b")])
def test_slow_transcription_latency_is_shown(panel, ms, texto, color):
    panel.set_latency(ms)

    assert (panel.lat.text(), panel.lat.isVisibleTo(panel)) == (texto, True)
    assert f"color: {color};" in panel.lat.styleSheet()


def test_fast_answer_hides_a_previous_slow_one(panel):
    panel.set_e2e(4000)

    panel.set_e2e(1200)

    assert panel.e2e.isVisibleTo(panel) is False


@pytest.mark.parametrize("ms, texto, color", [(3000, "⚡ 3.0 s", "#e9a23b"),
                                              (6500, "⚡ 6.5 s", "#e0554b")])
def test_slow_answer_is_shown(panel, ms, texto, color):
    panel.set_e2e(ms)

    assert (panel.e2e.text(), panel.e2e.isVisibleTo(panel)) == (texto, True)
    assert f"color: {color};" in panel.e2e.styleSheet()


# ------------------------------------------------------- header: only what is useful
def test_spoken_header_has_no_decorative_title(panel):
    textos = [lab.text() for lab in panel._drag_header.findChildren(QtWidgets.QLabel)
              if lab.isVisibleTo(panel)]

    assert "Live Transcription" not in textos


def test_spoken_header_title_is_the_agent(panel):
    panel.set_agents([("grok", "Grok")], "grok")

    assert panel.agent_chip.isVisibleTo(panel) and panel.agent_chip.text().startswith("Grok")


def test_screen_header_counts_the_shots(qtbot):
    pantalla = overlay_ui.TranscriptPanel(modo="pantalla")
    qtbot.addWidget(pantalla)

    pantalla.set_shots(2)

    assert pantalla.titulo.text() == "Screen · 2 shots"
    assert pantalla.agent_chip.isVisibleTo(pantalla) is False
    # same drain as the panel fixture: pending single-shot timers die with it
    qtbot.wait(overlay_ui.INTERVALO_REPINTADO + 20)


def test_passing_notice_hides_itself(panel, qtbot):
    panel._aviso_fugaz.setInterval(10)

    panel.aviso("Grok answers from now on")

    assert panel.skip_pill.text() == "Grok answers from now on"
    qtbot.waitUntil(lambda: panel.skip_pill.isHidden(), timeout=1000)


@pytest.mark.parametrize("nombre", ["Coach", "Grok", "Directo"])
def test_agent_name_that_fits_is_never_cut(panel, qtbot, nombre):
    panel.set_agents([("a", nombre)], "a")
    panel.resize(460, 300)
    panel.show()
    qtbot.waitExposed(panel)

    assert panel.agent_chip.text() == f"{nombre} ▾"


def test_spoken_panel_has_the_agent_as_companion(panel):
    panel.set_agents([("grok", "Grok", ("triangulo", "naranja"))], "grok")

    assert (panel.compa.forma, panel.compa.color) == ("triangulo", "naranja")
    assert panel.compa.isVisibleTo(panel) and not panel.bars.isVisibleTo(panel)
    assert panel.agent_chip.icon().isNull() is True      # the face is the companion


def test_companion_follows_the_meeting(panel):
    estados = []
    panel.set_state("listening"); estados.append(panel.compa.estado)
    panel.set_state("generating"); estados.append(panel.compa.estado)
    panel.clear_answer()
    panel.append_answer("Usaría"); estados.append(panel.compa.estado)
    panel.cerrar_respuesta()
    contento = panel.compa.contento
    panel.set_state("listening"); estados.append(panel.compa.estado)

    assert estados == ["escuchando", "pensando", "hablando", "escuchando"]
    assert contento is True


def test_companion_hears_the_audio_level(panel):
    panel.set_level(80)

    assert panel.compa.nivel == 80


def test_screen_panel_has_no_companion(qtbot):
    pantalla = overlay_ui.TranscriptPanel(modo="pantalla")
    qtbot.addWidget(pantalla)

    assert pantalla.compa.isVisibleTo(pantalla) is False
    qtbot.wait(overlay_ui.INTERVALO_REPINTADO + 20)
