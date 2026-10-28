"""Widget tests for the conversation thread of overlay_ui.TranscriptPanel.

Covers participant bubbles (set_question / cerrar_intervencion), streamed
suggestion bubbles (clear_answer / append_answer / cerrar_respuesta and the
sections, bullets and code blocks they render), screenshots, hints, pruning
and limpiar_hilo. Runs on the offscreen Qt platform; this module makes no
Win32 calls, so nothing is mocked.
"""
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import overlay_ui

CARET = "&#9611;"


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


def feed_rows(panel):
    """Rows in the thread (the trailing stretch is not a row)."""
    return panel.feed.count() - 1


@pytest.fixture
def panel(qtbot):
    p = overlay_ui.TranscriptPanel()
    qtbot.addWidget(p)
    yield p
    # The panel schedules single-shot timers on plain Python callables, which
    # Qt does not cancel when the widget dies. Drain them while it still lives
    # so they cannot fire inside the next test.
    qtbot.wait(overlay_ui.INTERVALO_REPINTADO + 20)


def render_answer(panel, raw):
    panel.clear_answer()
    panel.append_answer(raw)
    panel.cerrar_respuesta()
    return bubbles(panel, "tu")[-1]


# --------------------------------------------------------------- participant

def test_set_question_opens_participant_bubble(panel):
    panel.set_question("How would you scale it?")

    assert len(bubbles(panel, "ellos")) == 1


def test_set_question_escapes_html(panel):
    panel.set_question("is a < b?")

    assert "is a &lt; b?" in joined(bubbles(panel, "ellos")[0])


def test_set_question_ignores_empty_text(panel):
    panel.set_question("")

    assert bubbles(panel, "ellos") == []


def test_set_question_updates_live_bubble(panel):
    panel.set_question("How would")
    panel.set_question("How would you scale it?")

    assert len(bubbles(panel, "ellos")) == 1


def test_set_question_shows_latest_text(panel):
    panel.set_question("How would")
    panel.set_question("How would you scale it?")

    assert "How would you scale it?" in joined(bubbles(panel, "ellos")[0])


def test_set_question_shows_caret_while_listening(panel):
    panel.set_state("listening")

    panel.set_question("Tell me about")

    assert CARET in joined(bubbles(panel, "ellos")[0])


def test_set_question_hides_caret_when_idle(panel):
    panel.set_question("Tell me about")

    assert CARET not in joined(bubbles(panel, "ellos")[0])


@pytest.mark.xfail(strict=True, reason="[KNOWN-502] _animate only re-renders when "
                   "_question_text is set, and nothing ever sets it")
def test_caret_blinks_while_listening(qtbot, panel):
    panel.set_state("listening")
    panel.set_question("Tell me about")
    bubble = bubbles(panel, "ellos")[0]

    qtbot.waitUntil(lambda: CARET not in joined(bubble), timeout=1500)


def test_set_listening_on_enables_caret(panel):
    panel.set_listening(True)

    panel.set_question("Tell me about")

    assert CARET in joined(bubbles(panel, "ellos")[0])


def test_set_listening_off_removes_caret(panel):
    panel.set_listening(True)
    panel.set_question("Tell me about")

    panel.set_listening(False)

    assert CARET not in joined(bubbles(panel, "ellos")[0])


def test_cerrar_intervencion_drops_caret(panel):
    panel.set_state("listening")
    panel.set_question("Tell me about")

    panel.cerrar_intervencion("Tell me about yourself.")

    assert CARET not in joined(bubbles(panel, "ellos")[0])


def test_cerrar_intervencion_sets_final_text(panel):
    panel.set_question("Tell me about")

    panel.cerrar_intervencion("Tell me about yourself.")

    assert "Tell me about yourself." in joined(bubbles(panel, "ellos")[0])


def test_cerrar_intervencion_without_live_bubble_adds_one(panel):
    panel.cerrar_intervencion("Thanks for coming.")

    assert len(bubbles(panel, "ellos")) == 1


def test_question_after_cerrar_intervencion_opens_new_bubble(panel):
    panel.set_question("First question")
    panel.cerrar_intervencion("First question?")

    panel.set_question("Second")

    assert len(bubbles(panel, "ellos")) == 2


# --------------------------------------------------------------- answers

def test_clear_answer_opens_suggestion_bubble(panel):
    panel.clear_answer()

    assert len(bubbles(panel, "tu")) == 1


def test_clear_answer_keeps_previous_suggestions(panel):
    render_answer(panel, "First answer")

    panel.clear_answer()

    assert len(bubbles(panel, "tu")) == 2


def test_append_answer_defers_rendering(panel):
    panel.clear_answer()

    panel.append_answer("Hello there")

    assert "Hello there" not in joined(bubbles(panel, "tu")[0])


def test_append_answer_renders_after_interval(qtbot, panel):
    panel.clear_answer()
    panel.append_answer("Hello there")
    bubble = bubbles(panel, "tu")[0]

    qtbot.waitUntil(lambda: "Hello there" in joined(bubble), timeout=2000)


def test_append_answer_concatenates_chunks(panel):
    panel.clear_answer()
    panel.append_answer("Hel")
    panel.append_answer("lo world")

    panel.cerrar_respuesta()

    assert "Hello world" in joined(bubbles(panel, "tu")[0])


def test_append_answer_without_clear_answer_opens_bubble(qtbot, panel):
    panel.append_answer("Orphan chunk")

    qtbot.waitUntil(lambda: len(bubbles(panel, "tu")) == 1, timeout=2000)


def test_cerrar_respuesta_renders_pending_text(panel):
    panel.clear_answer()
    panel.append_answer("Final words")

    panel.cerrar_respuesta()

    assert "Final words" in joined(bubbles(panel, "tu")[0])


@pytest.mark.xfail(strict=True, reason="[KNOWN-501] cerrar_respuesta leaves the "
                   "throttle timer armed, which later repaints into a new bubble")
def test_cerrar_respuesta_does_not_duplicate_answer(qtbot, panel):
    panel.clear_answer()
    panel.append_answer("Final words")
    panel.cerrar_respuesta()

    qtbot.wait(overlay_ui.INTERVALO_REPINTADO + 150)

    assert len(bubbles(panel, "tu")) == 1


def test_answer_without_heading_uses_default_section(panel):
    bubble = render_answer(panel, "Just say yes.")

    assert "ANSWER" in texts(bubble)


def test_answer_sections_render_in_order(panel):
    bubble = render_answer(panel, "## Context\nWe use Kafka.\n## Answer\nSay yes.")

    assert [t for t in texts(bubble) if t in ("CONTEXT", "ANSWER")] == [
        "CONTEXT", "ANSWER"]


def test_answer_bold_becomes_html(panel):
    bubble = render_answer(panel, "Use **idempotent** consumers.")

    assert "<b>idempotent</b>" in joined(bubble)


def test_answer_bullets_render_one_row_per_item(panel):
    bubble = render_answer(panel, "- first\n- second\n- third")

    assert joined(bubble).count("<tr>") == 3


def test_answer_code_fence_renders_code_block(panel):
    bubble = render_answer(panel, "Try:\n```python\nprint(1)\n```\nDone.")

    assert len(bubble.findChildren(overlay_ui.CodeBlock)) == 1


def test_answer_code_block_shows_language(panel):
    bubble = render_answer(panel, "```python\nprint(1)\n```")

    assert "PYTHON" in texts(bubble.findChildren(overlay_ui.CodeBlock)[0])


def test_unclosed_code_fence_still_renders_code_block(panel):
    bubble = render_answer(panel, "```sql\nSELECT 1")

    assert len(bubble.findChildren(overlay_ui.CodeBlock)) == 1


def test_rerender_replaces_previous_blocks(qtbot, panel):
    panel.clear_answer()
    panel.append_answer("```python\nx = 1\n```")
    bubble = bubbles(panel, "tu")[0]
    qtbot.waitUntil(lambda: len(bubble.findChildren(overlay_ui.CodeBlock)) == 1)

    panel.append_answer("\n```python\ny = 2\n```")
    panel.cerrar_respuesta()
    flush_deletes()

    assert len(bubble.findChildren(overlay_ui.CodeBlock)) == 2


def test_code_copy_button_is_interactive(panel):
    bubble = render_answer(panel, "```python\nprint(1)\n```")
    btn = bubble.findChildren(overlay_ui.CodeBlock)[0].btn_copy

    assert btn in panel.interactive_widgets()


# --------------------------------------------------------------- thread rows

def test_new_panel_shows_start_hint(panel):
    assert ("Start the meeting to capture the participant and draft a "
            "suggested answer.") in texts(panel.scroll.widget())


def test_set_hint_adds_row(panel):
    panel.set_hint("Mic muted")

    assert feed_rows(panel) == 2


def test_set_hint_shows_text(panel):
    panel.set_hint("Mic muted")

    assert "Mic muted" in texts(panel.scroll.widget())


def test_add_shot_adds_thumbnail(panel):
    pix = QtGui.QPixmap(400, 200)
    pix.fill(QtGui.QColor("white"))

    panel.add_shot(pix)

    assert len(panel.findChildren(overlay_ui.ShotThumb)) == 1


def test_add_shot_labels_thumbnail(panel):
    pix = QtGui.QPixmap(400, 200)
    pix.fill(QtGui.QColor("white"))

    panel.add_shot(pix)

    assert "screenshot sent" in texts(panel.findChildren(overlay_ui.ShotThumb)[0])


def test_add_shot_scales_thumbnail_to_190px(panel):
    pix = QtGui.QPixmap(400, 200)
    pix.fill(QtGui.QColor("white"))

    panel.add_shot(pix)

    thumb = panel.findChildren(overlay_ui.ShotThumb)[0]
    img = thumb.findChildren(QtWidgets.QLabel)[0]
    assert (img.pixmap().width(), img.pixmap().height()) == (190, 95)


def test_thread_is_capped_at_max_rows(panel):
    for i in range(15):
        panel.set_hint(f"hint {i}")

    assert feed_rows(panel) == 10


def test_pruning_drops_oldest_rows(panel):
    for i in range(15):
        panel.set_hint(f"hint {i}")

    shown = [t for t in texts(panel.scroll.widget()) if t.startswith("hint")]
    assert shown == [f"hint {i}" for i in range(5, 15)]


def test_pruning_keeps_live_participant_bubble(panel):
    panel.set_question("Still talking")
    for i in range(12):
        panel.set_hint(f"hint {i}")

    panel.set_question("Still talking about it")

    assert len(bubbles(panel, "ellos")) == 1


def test_pruning_keeps_live_answer_bubble(panel):
    panel.clear_answer()
    for i in range(12):
        panel.set_hint(f"hint {i}")

    panel.append_answer("Late answer")
    panel.cerrar_respuesta()

    assert "Late answer" in joined(bubbles(panel, "tu")[0])


def test_pruned_code_block_leaves_interactive_widgets(panel):
    bubble = render_answer(panel, "```python\nprint(1)\n```")
    btn = bubble.findChildren(overlay_ui.CodeBlock)[0].btn_copy
    for i in range(12):
        panel.set_hint(f"hint {i}")

    assert btn not in panel.interactive_widgets()


def test_limpiar_hilo_removes_all_rows(panel):
    panel.set_question("Hi")
    render_answer(panel, "Hello")

    panel.limpiar_hilo()

    assert feed_rows(panel) == 0


def test_limpiar_hilo_destroys_bubbles(panel):
    panel.set_question("Hi")
    render_answer(panel, "Hello")

    panel.limpiar_hilo()

    assert bubbles(panel, "ellos") + bubbles(panel, "tu") == []


def test_question_after_limpiar_hilo_opens_fresh_bubble(panel):
    panel.set_question("Old meeting")
    panel.limpiar_hilo()

    panel.set_question("New meeting")

    assert len(bubbles(panel, "ellos")) == 1


def test_limpiar_hilo_drops_copy_buttons(panel):
    bubble = render_answer(panel, "```python\nprint(1)\n```")
    btn = bubble.findChildren(overlay_ui.CodeBlock)[0].btn_copy

    panel.limpiar_hilo()

    assert btn not in panel.interactive_widgets()
