"""The answer being read never moves while new content arrives below it.

Drives the real TranscriptPanel offscreen with the same calls app.py makes when
the engine emits transcript, partial and response signals.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6 import QtCore          # noqa: E402
from PySide6.QtTest import QTest    # noqa: E402

from overlay_ui import TranscriptPanel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def panel(app):
    p = TranscriptPanel()
    p.resize(640, 420)
    p.show()
    QTest.qWait(50)
    yield p
    p.close()


def _settle():
    QTest.qWait(250)     # singleShot(0) restores + the 90 ms repaint batching


def _top_in_viewport(panel, widget):
    return widget.mapTo(panel.scroll.viewport(), QtCore.QPoint(0, 0)).y()


def _turn(panel, text):
    panel.set_question(text)
    panel.cerrar_intervencion(text)


def _answer(panel, chunks):
    panel.clear_answer()
    for c in chunks:
        panel.append_answer(c)
        QTest.qWait(30)
    panel.cerrar_respuesta()


def test_answer_stays_put_while_interviewer_keeps_talking(panel):
    for i in range(4):
        _turn(panel, f"Contexto previo número {i}: " + "bla " * 30)
    _settle()
    _turn(panel, "¿Qué harías si llegan dos cobros iguales al mismo tiempo?")
    _answer(panel, ["## Respuesta\n", "Usaría una clave de idempotencia ",
                    "guardada con una restricción única. " * 3])
    _settle()
    answer = panel._burbujas[-1]
    before = _top_in_viewport(panel, answer)
    assert 0 <= before < panel.scroll.viewport().height()

    # The interviewer adds something: live partials, then a closed turn.
    for partial in ("Ah, pero", "Ah, pero ten en cuenta", "Ah, pero ten en cuenta que es AWS"):
        panel.set_question(partial)
        QTest.qWait(40)
    panel.cerrar_intervencion("Ah, pero ten en cuenta que es AWS.")
    panel.set_hint("nota del sistema")
    _settle()

    assert _top_in_viewport(panel, answer) == before
    assert panel.nuevo_chip.isVisible()


def test_new_chip_goes_to_the_end_and_resumes_following(panel):
    for i in range(3):
        _turn(panel, f"Turno {i}: " + "texto " * 25)
    _answer(panel, ["## Respuesta\n", "contenido " * 40])
    _turn(panel, "Algo más que dijeron después " + "x " * 20)
    _settle()
    assert panel.nuevo_chip.isVisible()

    panel.nuevo_chip.click()
    _settle()
    sb = panel.scroll.verticalScrollBar()
    assert sb.value() == sb.maximum()
    assert not panel.nuevo_chip.isVisible()

    _turn(panel, "Y otra intervención más " + "y " * 20)
    _settle()
    assert sb.value() == sb.maximum()          # following again


def test_manual_scroll_releases_the_pin(panel):
    for i in range(3):
        _turn(panel, f"Turno {i}: " + "texto " * 25)
    _answer(panel, ["## Respuesta\n", "contenido " * 60])
    _settle()
    panel.scroll_zone("feed", 2)               # wheel up two notches
    _settle()
    value = panel.scroll.verticalScrollBar().value()
    _turn(panel, "Nueva intervención " + "z " * 20)
    _settle()
    assert panel.scroll.verticalScrollBar().value() == value   # stays where left


def test_revision_rewrites_the_same_card_in_place(panel):
    for i in range(3):
        _turn(panel, f"Turno {i}: " + "texto " * 25)
    _turn(panel, "¿Qué arquitectura usarías?")
    _answer(panel, ["## Respuesta\n", "Una cola entre la API y los workers. " * 4])
    _settle()
    card = panel._burbujas[-1]
    top = _top_in_viewport(panel, card)
    cards = sum(1 for b in panel._burbujas if b.quien == "tu")

    panel.revisar_respuesta()
    for chunk in ("## Respuesta\n", "Una cola duradera con reintentos. " * 3):
        panel.append_answer(chunk)
        QTest.qWait(30)
    panel.cerrar_respuesta()
    _settle()

    assert sum(1 for b in panel._burbujas if b.quien == "tu") == cards
    assert panel._burbujas[-1] is card and card.actualizada
    assert "duradera" in card._raw and "workers" not in card._raw
    assert _top_in_viewport(panel, card) == top


def test_one_answer_makes_one_card_even_when_done_follows_the_last_chunk(panel):
    # Regression: the 90 ms batched repaint fired after cerrar_respuesta and
    # opened a second card with the same answer.
    panel.clear_answer()
    panel.append_answer("## Respuesta\n")
    QTest.qWait(30)
    panel.append_answer("texto final")
    panel.cerrar_respuesta()
    _settle()
    cards = [b for b in panel._burbujas if b.quien == "tu"]
    assert len(cards) == 1
    assert cards[0]._raw == "## Respuesta\ntexto final"
