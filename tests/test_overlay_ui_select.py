"""Underline a piece of text in a panel and ask for an explanation.

Offscreen Qt. Selection is set with QLabel.setSelection and the release goes
through the panel's event filter, as a real mouse drag would.
"""
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import overlay_ui

ANSWER = ("## Decisiones\nUso **bloqueo pesimista** con select_for_update.\n"
          "- Postgres real, no SQLite\n"
          "```python\ncuenta = CreditAccount.objects.select_for_update().get(id=1)\n```")


def release(label, x=5, y=5):
    p = QtCore.QPointF(x, y)
    return QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease, p, label.mapToGlobal(p),
                             QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier)


def press(label):
    p = QtCore.QPointF(5, 5)
    return QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, p, label.mapToGlobal(p),
                             QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)


def label_with(panel, fragment):
    return next(lab for lab in panel.findChildren(QtWidgets.QLabel)
                if fragment in lab.text() and lab.textInteractionFlags()
                & QtCore.Qt.TextSelectableByMouse)


def select(panel, qtbot, fragment, start=0, length=10):
    lab = label_with(panel, fragment)
    lab.setSelection(start, length)
    panel.eventFilter(lab, release(lab))
    qtbot.wait(5)
    return lab


@pytest.fixture
def screen(qtbot):
    panel = overlay_ui.TranscriptPanel(modo="pantalla")
    qtbot.addWidget(panel)
    panel.resize(640, 500)
    panel.show()
    panel.clear_answer()
    panel.append_answer(ANSWER)
    panel.cerrar_respuesta()
    qtbot.wait(5)
    yield panel
    qtbot.wait(5)


def test_answer_text_and_code_can_be_selected_with_the_arrow_cursor(screen):
    for fragment in ("bloqueo pesimista", "Postgres real", "CreditAccount"):
        lab = label_with(screen, fragment)
        assert lab.cursor().shape() == QtCore.Qt.ArrowCursor


def test_spoken_text_can_be_selected_too(qtbot):
    voz = overlay_ui.TranscriptPanel()
    qtbot.addWidget(voz)
    voz.cerrar_intervencion("¿Por qué Postgres y no MySQL?")

    assert label_with(voz, "Postgres y no MySQL")
    qtbot.wait(5)


def test_selecting_shows_explain_next_to_it(screen, qtbot):
    select(screen, qtbot, "bloqueo pesimista", 4, 17)

    assert screen.chip_explicar.isVisible() is True
    assert screen.seleccion() == ("bloqueo pesimista", "pantalla:tu")
    assert screen.chip_explicar in screen.interactive_widgets()


def test_explain_sends_the_selection_once_and_clears_it(screen, qtbot):
    pedidos = []
    screen.explainRequested.connect(lambda t, o: pedidos.append((t, o)))
    lab = select(screen, qtbot, "bloqueo pesimista", 4, 17)

    qtbot.mouseClick(screen.chip_explicar, QtCore.Qt.LeftButton)

    assert pedidos == [("bloqueo pesimista", "pantalla:tu")]
    assert screen.chip_explicar.isVisible() is False
    assert lab.hasSelectedText() is False
    assert screen.seleccion() == ("", "")


def test_click_without_selection_hides_explain(screen, qtbot):
    lab = select(screen, qtbot, "bloqueo pesimista", 4, 17)
    lab.setSelection(0, 0)

    screen.eventFilter(lab, release(lab))
    qtbot.wait(5)

    assert screen.chip_explicar.isVisible() is False


def test_starting_a_selection_elsewhere_clears_the_previous_one(screen, qtbot):
    primero = select(screen, qtbot, "bloqueo pesimista", 4, 17)
    otro = label_with(screen, "Postgres real")

    screen.eventFilter(otro, press(otro))

    assert primero.hasSelectedText() is False
    assert screen.chip_explicar.isVisible() is False


def test_thread_takes_the_mouse_once_there_is_text(qtbot):
    voz = overlay_ui.TranscriptPanel()
    qtbot.addWidget(voz)
    voz.show()
    assert voz.scroll.viewport() not in voz.interactive_widgets()

    voz.cerrar_intervencion("Hola")

    assert voz.scroll.viewport() in voz.interactive_widgets()
    qtbot.wait(5)


def test_new_meeting_forgets_the_selection(screen, qtbot):
    select(screen, qtbot, "bloqueo pesimista", 4, 17)

    screen.limpiar_hilo()

    assert screen.seleccion() == ("", "") and screen.chip_explicar.isVisible() is False


def test_explain_stays_inside_the_panel(screen, qtbot):
    lab = label_with(screen, "bloqueo pesimista")
    lab.setSelection(4, 17)
    screen.eventFilter(lab, release(lab, x=lab.width() - 1, y=lab.height() - 1))
    qtbot.wait(5)

    chip = screen.chip_explicar.geometry()
    assert screen.card.rect().contains(chip)


# ------------------------------------------------------------------ the ask box
def test_quoting_starts_the_question_with_the_fragment(qtbot):
    ask = overlay_ui.TranscriptPanel()
    qtbot.addWidget(ask)

    ask.citar("select_for_update")

    assert ask.entrada.toPlainText() == "«select_for_update» "
    assert ask.entrada.textCursor().position() == len("«select_for_update» ")
    qtbot.wait(5)


def test_quoting_never_overwrites_what_you_were_typing(qtbot):
    ask = overlay_ui.TranscriptPanel()
    qtbot.addWidget(ask)
    ask.entrada.setPlainText("mi pregunta a medias")

    ask.citar("otra cosa")

    assert ask.entrada.toPlainText() == "mi pregunta a medias"
    qtbot.wait(5)


def test_overlay_controls_keep_the_arrow_cursor(qtbot):
    ask = overlay_ui.TranscriptPanel()
    qtbot.addWidget(ask)

    assert ask.entrada.viewport().cursor().shape() == QtCore.Qt.ArrowCursor
    assert all(b.cursor().shape() == QtCore.Qt.ArrowCursor
               for b in ask.modo_chip.botones.values())
    assert ask.btn_enviar.cursor().shape() == QtCore.Qt.ArrowCursor
    qtbot.wait(5)
