"""Agent characters: every character and colour draws, faces validate."""
import pytest
from PySide6 import QtCore, QtGui

import avatares


@pytest.mark.parametrize("personaje", list(avatares.PERSONAJES))
@pytest.mark.parametrize("expresion", [avatares.ABIERTOS, avatares.CERRADOS, avatares.PENSANDO])
def test_every_character_draws_with_every_face(qapp, personaje, expresion):
    pm = avatares.pixmap(personaje, "coral", 48, expresion)
    img = pm.toImage()
    centro = img.pixelColor(img.width() // 2, int(img.height() * 0.8))

    assert pm.isNull() is False and centro.alpha() > 0          # there is a body


@pytest.mark.parametrize("cid, hexa", [(c, h) for c, _, h in avatares.COLORES])
def test_body_takes_the_chosen_colour(qapp, cid, hexa):
    img = avatares.pixmap("gota", cid, 60).toImage()
    pixel = img.pixelColor(img.width() // 2, int(img.height() * 0.3))
    objetivo = QtGui.QColor(hexa)

    assert abs(pixel.hue() - objetivo.hue()) <= 12 or objetivo.saturation() < 60


def test_pixmap_has_the_logical_size(qapp):
    pm = avatares.pixmap("robot", "menta", 26)

    assert round(pm.width() / pm.devicePixelRatio()) == 26


@pytest.mark.parametrize("agente, cara", [
    ({"personaje": "buho", "color": "menta"}, ("buho", "menta")),
    ({"personaje": "dragon", "color": "neon"}, ("gota", "pervinca")),
    ({}, ("gota", "pervinca")),
])
def test_unknown_faces_fall_back_to_the_default(agente, cara):
    assert avatares.de_agente(agente) == cara


def test_living_avatar_blinks_and_opens_again(qtbot):
    cara = avatares.Avatar("gato", "ambar", 64, vivo=True)
    qtbot.addWidget(cara)

    cara._parpadear()
    cerrado = cara.expresion
    qtbot.waitUntil(lambda: cara.expresion == avatares.ABIERTOS, timeout=1000)

    assert cerrado == avatares.CERRADOS


def test_thinking_face_does_not_blink(qtbot):
    cara = avatares.Avatar("gato", "ambar", 64, vivo=True)
    qtbot.addWidget(cara)
    cara.set_expresion(avatares.PENSANDO)

    cara._parpadear()

    assert cara.expresion == avatares.PENSANDO


def test_clicking_the_avatar_is_reported(qtbot):
    cara = avatares.Avatar("oso", "rosa", 64)
    qtbot.addWidget(cara)

    with qtbot.waitSignal(cara.clicked):
        qtbot.mouseClick(cara, QtCore.Qt.LeftButton)
