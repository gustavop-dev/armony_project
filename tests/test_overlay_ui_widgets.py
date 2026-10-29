"""Widget tests for the standalone pieces of overlay_ui.

Covers TopBar, CollapsedButton, ClickFrame, CodeBlock, StatusBadge, SkipPill,
AudioBars, the hand-painted decorations and parse_sections. Runs on the
offscreen Qt platform; this module makes no Win32 calls, so nothing is mocked
except the optional syntax highlighter in one fallback test.
"""
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import overlay_ui


def mouse(kind, global_pos, button=QtCore.Qt.LeftButton,
          buttons=QtCore.Qt.LeftButton):
    pos = QtCore.QPointF(*global_pos)
    return QtGui.QMouseEvent(kind, QtCore.QPointF(1, 1), pos, button, buttons,
                             QtCore.Qt.NoModifier)


def send(widget, event):
    """Deliver an event through Qt dispatch, as a real mouse would."""
    QtWidgets.QApplication.sendEvent(widget, event)


def label_texts(widget):
    return [lab.text() for lab in widget.findChildren(QtWidgets.QLabel)]


@pytest.fixture
def bar(qtbot):
    b = overlay_ui.TopBar()
    qtbot.addWidget(b)
    return b


@pytest.fixture
def code_block(qtbot):
    """Build a CodeBlock; on teardown wait out a pending 'Copy' reset timer.

    The reset is a plain lambda, so Qt would run it after the widget is gone.
    """
    made = []

    def make(lang, code):
        cb = overlay_ui.CodeBlock(lang, code)
        made.append(cb)
        return cb

    yield make
    # Not registered with qtbot.addWidget: pytest-qt would close the widget
    # before this teardown runs.
    for cb in made:
        qtbot.waitUntil(lambda: cb.lbl_copy.text() == "Copy", timeout=3000)
        cb.deleteLater()


@pytest.fixture
def frame(qtbot):
    f = overlay_ui.ClickFrame()
    f.resize(80, 30)
    qtbot.addWidget(f)
    return f


# --------------------------------------------------------------- TopBar

@pytest.mark.parametrize("button, signal", [
    ("btn_meeting", "startStopClicked"),
    ("btn_shot", "screenshotClicked"),
    ("btn_toggle", "toggleClicked"),
    ("btn_gen", "generateClicked"),
    ("btn_answer", "answerNowClicked"),
])
def test_topbar_button_emits_signal(qtbot, bar, button, signal):
    with qtbot.waitSignal(getattr(bar, signal), timeout=1000):
        qtbot.mouseClick(getattr(bar, button), QtCore.Qt.LeftButton)


def test_topbar_starts_with_start_meeting_label(bar):
    assert bar.lbl_meeting.text() == "Start meeting"


def test_set_meeting_on_shows_stop_label(bar):
    bar.set_meeting(True)

    assert bar.lbl_meeting.text() == "Stop meeting"


def test_set_meeting_off_shows_start_label(bar):
    bar.set_meeting(True)

    bar.set_meeting(False)

    assert bar.lbl_meeting.text() == "Start meeting"


def test_set_meeting_off_clears_timer(bar):
    bar.set_meeting(True)
    bar.set_timer("03:41")

    bar.set_meeting(False)

    assert bar.lbl_timer.text() == ""


def test_set_meeting_on_keeps_timer(bar):
    bar.set_timer("00:12")

    bar.set_meeting(True)

    assert bar.lbl_timer.text() == "00:12"


@pytest.mark.parametrize("active, color", [(True, "#f6d9d4"), (False, "#b4c3ff")])
def test_set_meeting_recolors_label(bar, active, color):
    bar.set_meeting(active)

    assert f"color: {color}" in bar.lbl_meeting.styleSheet()


def test_set_timer_shows_text(bar):
    bar.set_timer("12:34")

    assert bar.lbl_timer.text() == "12:34"


def test_generate_starts_disabled(bar):
    assert bar.keys_gen.isEnabled() is False


@pytest.mark.parametrize("on, enabled", [(True, True), (False, False), (1, True)])
def test_set_generate_enabled_toggles_shortcut_keys(bar, on, enabled):
    bar.set_generate_enabled(on)

    assert bar.keys_gen.isEnabled() is enabled


@pytest.mark.parametrize("on, color", [(True, "#e3e7f2"), (False, "#7d869c")])
def test_set_generate_enabled_dims_label(bar, on, color):
    bar.set_generate_enabled(on)

    assert f"color: {color};" in bar.lbl_gen.styleSheet()


def test_topbar_interactive_widget_is_the_drag_zone(bar):
    assert bar.interactive_widgets() == [bar.drag_zone]


def test_topbar_has_no_brand_or_settings(bar):
    textos = " ".join(lab.text() for lab in bar.findChildren(QtWidgets.QLabel))

    assert ("Armony" not in textos, hasattr(bar, "btn_cfg")) == (True, False)


def test_topbar_is_frameless_tool_window_on_top(bar):
    flags = bar.windowFlags()
    wanted = (QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
              | QtCore.Qt.Tool)

    assert flags & wanted == wanted


def test_topbar_uses_uniform_window_opacity(bar):
    assert bar.windowOpacity() == pytest.approx(0.65, abs=0.01)


def test_topbar_resize_rounds_corners(qtbot, bar):
    bar.show()
    qtbot.waitExposed(bar)

    bar.resize(1400, 80)

    mask = bar.mask()
    assert (mask.contains(QtCore.QPoint(0, 0)),
            mask.contains(bar.rect().center())) == (False, True)


def test_topbar_drag_from_empty_area_moves_window(qtbot, bar):
    bar.show()
    qtbot.waitExposed(bar)
    bar.move(100, 100)

    send(bar, mouse(QtCore.QEvent.MouseButtonPress, (110, 110)))
    send(bar, mouse(QtCore.QEvent.MouseMove, (160, 140), button=QtCore.Qt.NoButton))

    assert bar.pos() == QtCore.QPoint(150, 130)


def test_topbar_drag_from_grip_zone_moves_window(qtbot, bar):
    bar.show()
    qtbot.waitExposed(bar)
    bar.move(100, 100)

    send(bar.drag_zone, mouse(QtCore.QEvent.MouseButtonPress, (110, 110)))
    send(bar.drag_zone, mouse(QtCore.QEvent.MouseMove, (160, 140), button=QtCore.Qt.NoButton))

    assert bar.pos() == QtCore.QPoint(150, 130)


def test_topbar_button_press_does_not_move_window(qtbot, bar):
    bar.show()
    qtbot.waitExposed(bar)
    bar.move(100, 100)

    send(bar.btn_shot, mouse(QtCore.QEvent.MouseButtonPress, (110, 110)))
    send(bar.btn_shot, mouse(QtCore.QEvent.MouseMove, (160, 140), button=QtCore.Qt.NoButton))

    assert bar.pos() == QtCore.QPoint(100, 100)


# --------------------------------------------------------------- CollapsedButton

def test_collapsed_button_click_emits_clicked(qtbot):
    btn = overlay_ui.CollapsedButton()
    qtbot.addWidget(btn)

    with qtbot.waitSignal(btn.clicked, timeout=1000):
        qtbot.mouseClick(btn.findChild(overlay_ui.ClickFrame), QtCore.Qt.LeftButton)


def test_collapsed_button_shows_label(qtbot):
    btn = overlay_ui.CollapsedButton()
    qtbot.addWidget(btn)

    assert "Show overlay" in label_texts(btn)


def test_collapsed_button_resize_rounds_corners(qtbot):
    btn = overlay_ui.CollapsedButton()
    qtbot.addWidget(btn)
    btn.show()
    qtbot.waitExposed(btn)

    btn.resize(400, 60)

    mask = btn.mask()
    assert (mask.contains(QtCore.QPoint(0, 0)),
            mask.contains(btn.rect().center())) == (False, True)


def test_round_mask_skips_empty_window(qtbot):
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    w.resize(0, 0)

    overlay_ui._round_mask(w, 8)

    assert w.mask().isEmpty()


# --------------------------------------------------------------- ClickFrame

def test_click_frame_left_click_emits(qtbot, frame):
    with qtbot.waitSignal(frame.clicked, timeout=1000):
        qtbot.mouseClick(frame, QtCore.Qt.LeftButton)


def test_click_frame_right_click_does_not_emit(qtbot, frame):
    with qtbot.assertNotEmitted(frame.clicked):
        qtbot.mouseClick(frame, QtCore.Qt.RightButton)


def test_click_frame_release_outside_does_not_emit(qtbot, frame):
    with qtbot.assertNotEmitted(frame.clicked):
        qtbot.mousePress(frame, QtCore.Qt.LeftButton, pos=QtCore.QPoint(10, 10))
        qtbot.mouseRelease(frame, QtCore.Qt.LeftButton, pos=QtCore.QPoint(200, 10))


class PressRecorder(QtWidgets.QWidget):
    """Parent that records the mouse presses it receives."""

    def __init__(self):
        super().__init__()
        self.presses = 0

    def mousePressEvent(self, e):
        self.presses += 1


def test_click_frame_press_does_not_reach_parent(qtbot):
    parent = PressRecorder()
    qtbot.addWidget(parent)
    child = overlay_ui.ClickFrame()
    child.setParent(parent)
    child.resize(40, 20)

    qtbot.mousePress(child, QtCore.Qt.LeftButton, pos=QtCore.QPoint(5, 5))

    assert parent.presses == 0


# --------------------------------------------------------------- CodeBlock

def test_code_block_copy_puts_code_on_clipboard(qtbot, code_block):
    cb = code_block("python", "def f():\n    return 1")

    qtbot.mouseClick(cb.btn_copy, QtCore.Qt.LeftButton)

    assert QtWidgets.QApplication.clipboard().text() == "def f():\n    return 1"


def test_code_block_copy_confirms_with_label(qtbot, code_block):
    cb = code_block("python", "x = 1")

    qtbot.mouseClick(cb.btn_copy, QtCore.Qt.LeftButton)

    assert cb.lbl_copy.text() == "Copied"


def test_code_block_copy_label_resets(qtbot, code_block):
    cb = code_block("python", "x = 1")
    qtbot.mouseClick(cb.btn_copy, QtCore.Qt.LeftButton)

    qtbot.waitUntil(lambda: cb.lbl_copy.text() == "Copy", timeout=3000)


def test_code_block_destroyed_after_copy_raises_nothing(qtbot):
    cb = overlay_ui.CodeBlock("python", "x = 1")
    qtbot.mouseClick(cb.btn_copy, QtCore.Qt.LeftButton)
    cb.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    qtbot.wait(1600)


@pytest.mark.parametrize("lang, tag", [
    ("python", "PYTHON"),
    ("SQL", "SQL"),
    ("", "CODE"),
    (None, "CODE"),
])
def test_code_block_header_shows_language(qtbot, code_block, lang, tag):
    cb = code_block(lang, "x = 1")

    assert tag in label_texts(cb)


def test_code_block_highlights_as_rich_text(qtbot, code_block):
    cb = code_block("python", "a = 1\nb = 2")

    body = cb.findChildren(QtWidgets.QLabel)[-1]
    assert body.textFormat() == QtCore.Qt.RichText


def test_code_block_falls_back_to_plain_text(code_block, monkeypatch):
    monkeypatch.setattr(overlay_ui.richtext, "resaltar", lambda *a, **k: None)
    cb = code_block("python", "a = 1\n    b = 2")

    body = cb.findChildren(QtWidgets.QLabel)[-1]
    assert (body.textFormat(), body.text()) == (QtCore.Qt.PlainText,
                                                "a = 1\n    b = 2")


@pytest.mark.parametrize("lang, color", [
    ("python", "#7ee0c6"),
    ("JS", "#7c95ff"),
    ("brainfuck", "#93a8ff"),
])
def test_code_block_edge_uses_language_color(qtbot, code_block, lang, color):
    cb = code_block(lang, "x")

    assert f"border-left: 2px solid {color};" in cb.styleSheet()


# --------------------------------------------------------------- StatusBadge

def test_status_badge_starts_idle(qtbot):
    badge = overlay_ui.StatusBadge()
    qtbot.addWidget(badge)

    assert label_texts(badge)[1] == "Idle"


def test_status_badge_set_changes_text(qtbot):
    badge = overlay_ui.StatusBadge()
    qtbot.addWidget(badge)

    badge.set("Listening", "listening")

    assert label_texts(badge)[1] == "Listening"


@pytest.mark.parametrize("kind, label_color", [
    ("listening", "#3ddc84"),
    ("error", "#e0554b"),
    ("idle", "#9aa3b8"),
    ("unknown-kind", "#9aa3b8"),
])
def test_status_badge_label_color_by_kind(qtbot, kind, label_color):
    badge = overlay_ui.StatusBadge()
    qtbot.addWidget(badge)

    badge.set("x", kind)

    assert f"color: {label_color};" in badge.findChildren(QtWidgets.QLabel)[1].styleSheet()


@pytest.mark.parametrize("kind, background", [
    ("error", "rgba(224,85,75,0.14)"),
    ("info", "rgba(220,228,255,0.05)"),
])
def test_status_badge_tints_background(qtbot, kind, background):
    badge = overlay_ui.StatusBadge()
    qtbot.addWidget(badge)

    badge.set("x", kind)

    assert f"background: {background};" in badge.styleSheet()


# --------------------------------------------------------------- SkipPill

def test_skip_pill_hidden_by_default(qtbot):
    pill = overlay_ui.SkipPill()
    qtbot.addWidget(pill)

    assert pill.isHidden()


def test_skip_pill_show_text_sets_text(qtbot):
    pill = overlay_ui.SkipPill()
    qtbot.addWidget(pill)

    pill.show_text("No question yet")

    assert pill.text() == "No question yet"


def test_skip_pill_show_text_unhides(qtbot):
    pill = overlay_ui.SkipPill()
    qtbot.addWidget(pill)

    pill.show_text("No question yet")

    assert not pill.isHidden()


def test_skip_pill_hide_pill_hides(qtbot):
    pill = overlay_ui.SkipPill()
    qtbot.addWidget(pill)
    pill.show_text("No question yet")

    pill.hide_pill()

    assert pill.isHidden()


# --------------------------------------------------------------- AudioBars

@pytest.mark.parametrize("value, stored", [(150, 100), (-5, 0), (42.7, 42), (0, 0)])
def test_audio_bars_clamp_level(qtbot, value, stored):
    bars = overlay_ui.AudioBars()
    qtbot.addWidget(bars)

    bars.set_level(value)

    assert bars._level == stored


def test_audio_bars_animate_while_listening(qtbot):
    bars = overlay_ui.AudioBars()
    qtbot.addWidget(bars)

    bars.set_listening(True)

    qtbot.waitUntil(lambda: bars._phase > 0, timeout=1000)


def test_audio_bars_stay_still_when_not_listening(qtbot):
    bars = overlay_ui.AudioBars()
    qtbot.addWidget(bars)

    qtbot.wait(200)

    assert bars._phase == 0.0


# --------------------------------------------------------------- painting

@pytest.mark.parametrize("factory", [
    overlay_ui.GripDots,
    overlay_ui.ResizeGrip,
    overlay_ui.AudioBars,
    overlay_ui.PanelCard,
], ids=["grip-dots", "resize-grip", "audio-bars", "panel-card"])
def test_decoration_renders_at_widget_size(qtbot, factory):
    w = factory()
    qtbot.addWidget(w)
    w.resize(max(w.width(), 20), max(w.height(), 20))

    assert w.grab().size() == w.size()


def test_listening_audio_bars_render(qtbot):
    bars = overlay_ui.AudioBars()
    qtbot.addWidget(bars)
    bars.set_listening(True)
    bars.set_level(80)

    assert bars.grab().size() == QtCore.QSize(17, 14)


def test_panel_card_set_borde_ignores_same_value(qtbot):
    card = overlay_ui.PanelCard()
    qtbot.addWidget(card)
    color = QtGui.QColor(1, 2, 3)
    card.set_borde(color, 2)

    card.set_borde(QtGui.QColor(1, 2, 3), 2)

    assert (card._color, card._grosor) == (QtGui.QColor(1, 2, 3), 2)


# --------------------------------------------------------------- drag bar

def test_drag_bar_ignores_right_button(qtbot):
    win = QtWidgets.QWidget()
    qtbot.addWidget(win)
    bar = overlay_ui.DragBar()
    bar.setParent(win)
    win.move(100, 100)

    send(bar, mouse(QtCore.QEvent.MouseButtonPress, (110, 110),
                    button=QtCore.Qt.RightButton, buttons=QtCore.Qt.RightButton))
    send(bar, mouse(QtCore.QEvent.MouseMove, (160, 140), button=QtCore.Qt.NoButton,
                    buttons=QtCore.Qt.RightButton))

    assert win.pos() == QtCore.QPoint(100, 100)


# --------------------------------------------------------------- parse_sections

@pytest.mark.parametrize("raw, expected", [
    ("## Answer\nSay yes.", [("Answer", "Say yes.")]),
    ("Just text", [("Answer", "Just text")]),
    ("## Tips\n- one\n- two", [("Tips", "one two")]),
    ("```py\nx = 1\n```", [("Answer", "x = 1")]),
    ("## Context\nKafka\n## Answer\nYes", [("Context", "Kafka"), ("Answer", "Yes")]),
    ("line one\nline two", [("Answer", "line one line two")]),
    ("", []),
    ("## Empty\n\n## Answer\nOk", [("Answer", "Ok")]),
])
def test_parse_sections_flattens_answer(raw, expected):
    assert overlay_ui.parse_sections(raw) == expected


# --------------------------------------------------------------- CollapsedButton drag
@pytest.fixture
def collapsed(qtbot):
    btn = overlay_ui.CollapsedButton()
    qtbot.addWidget(btn)
    btn.show()
    qtbot.waitExposed(btn)
    btn.move(300, 300)
    return btn


def _press_move_release(widget, start, end):
    send(widget, mouse(QtCore.QEvent.MouseButtonPress, start))
    send(widget, mouse(QtCore.QEvent.MouseMove, end, button=QtCore.Qt.NoButton))
    send(widget, mouse(QtCore.QEvent.MouseButtonRelease, end, buttons=QtCore.Qt.NoButton))


def test_collapsed_button_drag_moves_window(collapsed):
    frame = collapsed.findChild(overlay_ui.ClickFrame)

    _press_move_release(frame, (310, 310), (360, 340))

    assert collapsed.pos() == QtCore.QPoint(350, 330)


def test_collapsed_button_drag_does_not_click(qtbot, collapsed):
    frame = collapsed.findChild(overlay_ui.ClickFrame)
    clicks = []
    collapsed.clicked.connect(lambda: clicks.append(1))

    _press_move_release(frame, (310, 310), (360, 340))

    assert clicks == []


def test_collapsed_button_small_jitter_still_clicks(qtbot, collapsed):
    frame = collapsed.findChild(overlay_ui.ClickFrame)
    clicks = []
    collapsed.clicked.connect(lambda: clicks.append(1))

    _press_move_release(frame, (310, 310), (311, 310))

    assert (clicks, collapsed.pos()) == ([1], QtCore.QPoint(300, 300))


def test_plain_click_frame_does_not_move_window(frame):
    frame.show()
    frame.move(50, 50)

    _press_move_release(frame, (60, 60), (120, 90))

    assert frame.pos() == QtCore.QPoint(50, 50)
