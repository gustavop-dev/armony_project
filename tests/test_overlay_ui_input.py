"""The question field at the bottom of the spoken panel (Caps+E) and the
Manual | AI switch next to it. Offscreen Qt; focus handling is app.py's."""
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import overlay_ui


@pytest.fixture
def voz(qtbot):
    panel = overlay_ui.TranscriptPanel()
    qtbot.addWidget(panel)
    panel.resize(460, 600)
    yield panel
    qtbot.wait(5)


def test_spoken_panel_has_the_field_and_the_switch(voz):
    assert voz.entrada.placeholderText() == overlay_ui.HINT_PREGUNTA
    assert voz.modo_chip.isVisibleTo(voz)
    assert voz.modo_chip.parentWidget() is voz.entrada.parentWidget()   # same row


def test_big_panel_has_no_field_but_has_the_switch(qtbot):
    pantalla = overlay_ui.TranscriptPanel(modo="pantalla")
    qtbot.addWidget(pantalla)

    assert getattr(pantalla, "entrada", None) is None
    assert pantalla.modo_chip.isVisibleTo(pantalla)
    qtbot.wait(5)


def test_enter_sends_and_clears(voz, qtbot):
    enviadas = []
    voz.submitted.connect(enviadas.append)
    voz.entrada.setPlainText("  ¿Y si lo hago recursivo?  ")

    qtbot.keyClick(voz.entrada, QtCore.Qt.Key_Return)

    assert enviadas == ["¿Y si lo hago recursivo?"] and voz.entrada.toPlainText() == ""


def test_shift_enter_adds_a_line(voz, qtbot):
    enviadas = []
    voz.submitted.connect(enviadas.append)
    voz.entrada.setPlainText("for x in xs:")
    voz.entrada.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    qtbot.keyClick(voz.entrada, QtCore.Qt.Key_Return, QtCore.Qt.ShiftModifier)

    assert enviadas == [] and voz.entrada.toPlainText() == "for x in xs:\n"


def test_blank_question_is_not_sent(voz, qtbot):
    enviadas = []
    voz.submitted.connect(enviadas.append)
    voz.entrada.setPlainText("   ")

    qtbot.mouseClick(voz.btn_enviar, QtCore.Qt.LeftButton)

    assert enviadas == []


def test_escape_leaves_the_field(voz, qtbot):
    salidas = []
    voz.entradaSalir.connect(lambda: salidas.append(1))

    qtbot.keyClick(voz.entrada, QtCore.Qt.Key_Escape)

    assert salidas == [1]


def test_clicking_the_field_asks_for_the_keyboard(voz, qtbot):
    pulsadas = []
    voz.entradaPulsada.connect(lambda: pulsadas.append(1))

    qtbot.mousePress(voz.entrada.viewport(), QtCore.Qt.LeftButton)

    assert pulsadas == [1]


def test_field_send_button_and_switch_take_clicks(voz):
    voz.show()

    zonas = voz.interactive_widgets()

    assert voz.entrada in zonas and voz.btn_enviar in zonas and voz.modo_chip in zonas


def test_spoken_header_fits_its_column(voz):
    """The switch lives by the field: the header with the agent and the status
    has to fit the 460 px column."""
    assert voz.minimumSizeHint().width() <= 460


def test_typed_question_and_its_answer_on_the_big_panel(qtbot):
    pantalla = overlay_ui.TranscriptPanel(modo="pantalla")
    qtbot.addWidget(pantalla)

    pantalla.add_question("¿Qué es un ledger?")
    pantalla.clear_answer("respuesta")
    pantalla.append_answer("## Respuesta\nUn libro de asientos.")
    pantalla.cerrar_respuesta()

    assert [b.quien for b in pantalla._burbujas] == ["pregunta", "respuesta"]
    etiquetas = [lab.text() for lab in pantalla._burbujas[1].findChildren(QtWidgets.QLabel)]
    assert "ANSWER" in etiquetas
    qtbot.wait(5)


def test_prominent_update_chip(qtbot):
    chip = overlay_ui.SuggestionChip(vistoso=True)
    qtbot.addWidget(chip)
    chip.resize(400, 34)

    chip.mostrar("hazlo sin librerías")

    assert chip.isVisibleTo(chip.parentWidget() or chip) or chip.texto
    assert chip.text().startswith("↻ Update the solution with: «")
    assert "qlineargradient" in chip.styleSheet()


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

    assert cambios == ["ia"]


def test_setting_the_mode_from_outside_is_silent(qtbot):
    chip = overlay_ui.ModoChip()
    qtbot.addWidget(chip)
    cambios = []
    chip.changed.connect(cambios.append)

    chip.set_modo("ia")
    chip.set_modo("magia")

    assert cambios == [] and chip.modo == "ia"


def test_top_bar_lists_every_shortcut(qtbot):
    barra = overlay_ui.TopBar()
    qtbot.addWidget(barra)

    textos = [lab.text() for lab in barra.findChildren(QtWidgets.QLabel)]
    for rotulo, tecla in (("Answer", "A"), ("Solve", "R"), ("Shot", "S"), ("Ask", "E"),
                          ("Mouse", "Q"), ("Hide", "W")):
        assert rotulo in textos and tecla in textos


def test_mouse_pill_lights_up_while_the_blue_mouse_is_on(qtbot):
    barra = overlay_ui.TopBar()
    qtbot.addWidget(barra)

    barra.set_raton(True)
    assert "#6fa0ff" in barra._lbl_mouse.styleSheet()
    barra.set_raton(False)
    assert "#6fa0ff" not in barra._lbl_mouse.styleSheet()
