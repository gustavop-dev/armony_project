"""The ask box (overlay_ui.AskPanel) and the Manual | AI switch (ModoChip).

Offscreen Qt only; the box makes no Win32 calls itself (focus is app.py's job).
"""
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import overlay_ui


def flush_deletes():
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def bubbles(panel, who):
    flush_deletes()
    return [b for b in panel.findChildren(overlay_ui.Burbuja) if b.quien == who]


def labels(widget):
    flush_deletes()
    return [lab.text() for lab in widget.findChildren(QtWidgets.QLabel)]


@pytest.fixture
def ask(qtbot):
    panel = overlay_ui.AskPanel()
    qtbot.addWidget(panel)
    panel.resize(460, 220)
    yield panel
    # Pending single-shot scroll restores must run while the panel still lives.
    qtbot.wait(5)


# ------------------------------------------------------------------ the box
def test_box_is_titled_ask_without_agent_or_mascot(ask):
    assert ask.titulo.text() == "Ask"
    assert ask.agent_chip.isVisibleTo(ask) is False
    assert ask.compa.isVisibleTo(ask) is False
    assert ask.btn_close.isVisibleTo(ask) is True
    assert ask.modo_chip.isVisibleTo(ask) is True


def test_status_shows_only_once_something_was_asked(ask):
    assert ask.badge.isVisibleTo(ask) is False

    ask.set_status("Thinking…", "drafting")
    assert ask.badge.isVisibleTo(ask) is True

    ask.limpiar_hilo()
    assert ask.badge.isVisibleTo(ask) is False


def test_empty_box_explains_how_to_use_it(ask):
    assert overlay_ui.HINT_PREGUNTA in labels(ask)


def test_enter_sends_the_question_and_clears_the_field(ask, qtbot):
    enviadas = []
    ask.submitted.connect(enviadas.append)
    ask.entrada.setPlainText("  ¿Por qué un diccionario?  ")

    qtbot.keyClick(ask.entrada, QtCore.Qt.Key_Return)

    assert enviadas == ["¿Por qué un diccionario?"]
    assert ask.entrada.toPlainText() == ""


def test_shift_enter_adds_a_line_instead_of_sending(ask, qtbot):
    enviadas = []
    ask.submitted.connect(enviadas.append)
    ask.entrada.setPlainText("for x in xs:")
    ask.entrada.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    qtbot.keyClick(ask.entrada, QtCore.Qt.Key_Return, QtCore.Qt.ShiftModifier)

    assert enviadas == []
    assert ask.entrada.toPlainText() == "for x in xs:\n"


def test_blank_question_is_not_sent(ask, qtbot):
    enviadas = []
    ask.submitted.connect(enviadas.append)
    ask.entrada.setPlainText("   ")

    qtbot.mouseClick(ask.btn_enviar, QtCore.Qt.LeftButton)

    assert enviadas == []


def test_send_button_sends_too(ask, qtbot):
    enviadas = []
    ask.submitted.connect(enviadas.append)
    ask.entrada.setPlainText("hola")

    qtbot.mouseClick(ask.btn_enviar, QtCore.Qt.LeftButton)

    assert enviadas == ["hola"]


def test_escape_in_the_field_closes_the_box(ask, qtbot):
    cerrar = []
    ask.closeClicked.connect(lambda: cerrar.append(True))

    qtbot.keyClick(ask.entrada, QtCore.Qt.Key_Escape)

    assert cerrar == [True]


def test_question_and_answer_are_labelled_for_the_box(ask, qtbot):
    ask.add_question("¿Qué es un ledger?")
    ask.clear_answer()
    ask.append_answer("## Respuesta\nUn libro de asientos.")
    ask.cerrar_respuesta()

    pregunta, = bubbles(ask, "pregunta")
    respuesta, = bubbles(ask, "respuesta")
    assert "QUESTION" in labels(pregunta)
    assert "ANSWER" in labels(respuesta)
    assert any("Un libro de asientos." in t for t in labels(respuesta))
    assert bubbles(ask, "tu") == []


def test_clearing_keeps_the_hint_and_empties_the_field(ask):
    ask.add_question("una")
    ask.entrada.setPlainText("a medias")

    ask.limpiar_hilo()

    assert bubbles(ask, "pregunta") == []
    assert ask.entrada.toPlainText() == ""
    assert overlay_ui.HINT_PREGUNTA in labels(ask)


def test_field_and_send_button_take_clicks(ask):
    ask.show()
    zonas = ask.interactive_widgets()

    assert ask.entrada in zonas and ask.btn_enviar in zonas and ask.modo_chip in zonas


def test_box_fits_a_quarter_of_a_small_screen(ask):
    """1280x800 logical (the user's 150 % screen): a quarter is 200 px."""
    assert ask.minimumSizeHint().height() <= 200


def test_wheel_zones_are_named_after_the_box(ask):
    ask.show()
    for i in range(12):
        ask.add_question(f"pregunta larga {i} " + "palabra " * 30)
    QtWidgets.QApplication.processEvents()

    assert all(nombre.startswith("pregunta:") for _r, nombre in ask.wheel_zones())


# ------------------------------------------------------------------ Manual | AI
def test_switch_starts_in_manual(qtbot):
    chip = overlay_ui.ModoChip()
    qtbot.addWidget(chip)

    assert chip.modo == "manual" and chip.botones["manual"].isChecked()


def test_clicking_ai_announces_it_once(qtbot):
    chip = overlay_ui.ModoChip()
    qtbot.addWidget(chip)
    cambios = []
    chip.changed.connect(cambios.append)

    qtbot.mouseClick(chip.botones["ia"], QtCore.Qt.LeftButton)
    qtbot.mouseClick(chip.botones["ia"], QtCore.Qt.LeftButton)

    assert cambios == ["ia"] and chip.botones["ia"].isChecked()


def test_setting_the_mode_from_outside_is_silent(qtbot):
    chip = overlay_ui.ModoChip()
    qtbot.addWidget(chip)
    cambios = []
    chip.changed.connect(cambios.append)

    chip.set_modo("ia")
    chip.set_modo("magia")

    assert cambios == [] and chip.modo == "ia"
    assert chip.botones["ia"].isChecked()


def test_screen_panel_has_the_switch_and_the_spoken_one_does_not(qtbot):
    pantalla = overlay_ui.TranscriptPanel(modo="pantalla")
    voz = overlay_ui.TranscriptPanel()
    qtbot.addWidget(pantalla)
    qtbot.addWidget(voz)
    pantalla.show()
    voz.show()

    assert pantalla.modo_chip.isVisibleTo(pantalla) is True
    assert voz.modo_chip.isVisibleTo(voz) is False
    assert voz.modo_chip not in voz.interactive_widgets()
    assert pantalla.modo_chip in pantalla.interactive_widgets()
    qtbot.wait(5)            # let the hint's scroll restore run before teardown


def test_top_bar_shows_the_ask_shortcut(qtbot):
    barra = overlay_ui.TopBar()
    qtbot.addWidget(barra)

    textos = [lab.text() for lab in barra.btn_ask.findChildren(QtWidgets.QLabel)]
    assert "Ask" in textos and "E" in textos
