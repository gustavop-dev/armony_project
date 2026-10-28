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
GOLD = "#f2c94c"
PARTICIPANT_DOT_OFF = "#b98d4a"
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


@pytest.mark.parametrize("texto, color", [
    ("Listening", "#3ddc84"),
    ("Loading model…", "#e7b93a"),
    ("Starting", "#e7b93a"),
    ("Cargando", "#e7b93a"),
    ("Idle", "#8f8674"),
    ("Transcribing…", "#f2c94c"),
    ("Drafting…", "#f2c94c"),
    ("Analyzing…", "#f2c94c"),
    ("Error", "#e0554b"),
    ("API key required", "#e0554b"),
    ("Context saved", "#8f8674"),
])
def test_set_status_infers_kind_from_text(panel, texto, color):
    panel.set_status(texto)

    assert f"background: {color};" in badge_dot_style(panel)


def test_set_status_explicit_kind_wins_over_text(panel):
    panel.set_status("Listening", "error")

    assert "background: #e0554b;" in badge_dot_style(panel)


# --------------------------------------------------------------- skip pill

def test_skip_pill_starts_hidden(panel):
    assert panel.skip_pill.isHidden()


def test_show_skip_uses_default_text(panel):
    panel.show_skip()

    assert panel.skip_pill.text() == "No question — Alt+5 to answer"


def test_show_skip_uses_given_text(panel):
    panel.show_skip("Not a question — Alt+5 to answer")

    assert panel.skip_pill.text() == "Not a question — Alt+5 to answer"


def test_show_skip_makes_pill_visible(panel):
    panel.show_skip()

    assert not panel.skip_pill.isHidden()


def test_hide_skip_hides_pill(panel):
    panel.show_skip()

    panel.hide_skip()

    assert panel.skip_pill.isHidden()


# --------------------------------------------------------------- levels

@pytest.mark.parametrize("level, color", [
    (0, PARTICIPANT_DOT_OFF),
    (8, PARTICIPANT_DOT_OFF),
    (9, GOLD),
    (100, GOLD),
])
def test_set_level_lights_participant_dot(panel, level, color):
    panel.set_level(level)

    assert f"background: {color};" in panel.part_dot.styleSheet()


def test_set_level_dims_dot_when_audio_stops(panel):
    panel.set_level(60)

    panel.set_level(2)

    assert f"background: {PARTICIPANT_DOT_OFF};" in panel.part_dot.styleSheet()


def test_set_mic_level_leaves_participant_dot_off(panel):
    panel.set_mic_level(100)

    assert f"background: {PARTICIPANT_DOT_OFF};" in panel.part_dot.styleSheet()


# --------------------------------------------------------------- latency

def test_latency_labels_start_hidden(panel):
    assert (panel.lat.isHidden(), panel.e2e.isHidden()) == (True, True)


@pytest.mark.parametrize("ms, text", [
    (250, "250 ms"),
    (999, "999 ms"),
    (1000, "1.0 s"),
    (2345, "2.3 s"),
])
def test_set_latency_formats_value(panel, ms, text):
    panel.set_latency(ms)

    assert panel.lat.text() == text


@pytest.mark.parametrize("ms, color", [
    (599, "#3ddc84"),
    (600, "#e7b93a"),
    (1499, "#e7b93a"),
    (1500, "#e0554b"),
])
def test_set_latency_colors_by_speed(panel, ms, color):
    panel.set_latency(ms)

    assert f"color: {color};" in panel.lat.styleSheet()


def test_set_latency_shows_label(panel):
    panel.set_latency(300)

    assert not panel.lat.isHidden()


@pytest.mark.parametrize("ms, text", [(1234, "⚡ 1.2 s"), (450, "⚡ 0.5 s")])
def test_set_e2e_formats_seconds(panel, ms, text):
    panel.set_e2e(ms)

    assert panel.e2e.text() == text


@pytest.mark.parametrize("ms, color", [
    (1499, "#3ddc84"),
    (1500, "#e7b93a"),
    (2999, "#e7b93a"),
    (3000, "#e0554b"),
])
def test_set_e2e_colors_by_speed(panel, ms, color):
    panel.set_e2e(ms)

    assert f"color: {color};" in panel.e2e.styleSheet()


def test_set_e2e_shows_label(panel):
    panel.set_e2e(1200)

    assert not panel.e2e.isHidden()


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
    assert [name for _rect, name in shown_panel.wheel_zones()] == ["feed"]


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
