"""The Armony mascot: a flat shape with eyes, in every shape, colour and face,
and it comes alive."""
import pytest
from PySide6 import QtCore, QtGui

import avatares


@pytest.mark.parametrize("forma", [f for f, _ in avatares.FORMAS])
@pytest.mark.parametrize("expresion", [avatares.ABIERTOS, avatares.CERRADOS,
                                       avatares.PENSANDO, avatares.FELIZ])
def test_mascot_draws_every_shape_with_every_face(qapp, forma, expresion):
    img = avatares.pixmap("naranja", 48, expresion, forma=forma).toImage()

    assert img.pixelColor(img.width() // 2, int(img.height() * 0.8)).alpha() > 0


def test_eyes_are_white_and_look_right(qapp):
    img = avatares.pixmap("negro", 100).toImage()
    w, h = img.width(), img.height()

    derecha = img.pixelColor(int(w * 0.56), int(h * 0.42))
    izquierda = img.pixelColor(int(w * 0.30), int(h * 0.42))

    assert derecha.lightness() > 200 and izquierda.lightness() < 60


@pytest.mark.parametrize("cid, hexa", [(c, h) for c, _, h in avatares.COLORES])
def test_body_takes_the_chosen_colour(qapp, cid, hexa):
    img = avatares.pixmap(cid, 60).toImage()
    pixel = img.pixelColor(img.width() // 2, int(img.height() * 0.85))
    objetivo = QtGui.QColor(hexa)

    assert abs(pixel.hue() - objetivo.hue()) <= 12 or objetivo.saturation() < 60


def test_pixmap_has_the_logical_size(qapp):
    pm = avatares.pixmap("menta", 26)

    assert round(pm.width() / pm.devicePixelRatio()) == 26


@pytest.mark.parametrize("agente, cara", [
    ({"forma": "triangulo", "color": "rosa"}, ("triangulo", "rosa")),
    ({"forma": "estrella", "color": "neon"}, ("circulo", "azul")),
    ({"color": "menta"}, ("circulo", "turquesa")),            # old colours translate
    ({}, ("circulo", "azul")),
])
def test_faces_are_validated(agente, cara):
    assert avatares.de_agente(agente) == cara


def _vivo(estado=avatares.REPOSO):
    cara = avatares.Avatar("ambar", 64, vivo=True)
    cara._proximo_parpadeo = 99            # no blinking unless a test wants it
    cara.set_estado(estado)
    return cara


def test_living_avatar_blinks_and_opens_again(qtbot):
    cara = _vivo()
    qtbot.addWidget(cara)
    cara._proximo_parpadeo = 0.5

    cara.avanzar(0.6)
    cerrado = cara.pose()["expresion"]
    cara.avanzar(0.2)

    assert (cerrado, cara.pose()["expresion"]) == (avatares.CERRADOS, avatares.ABIERTOS)


def test_resting_avatar_breathes(qtbot):
    cara = _vivo()
    qtbot.addWidget(cara)

    escalas = set()
    for _ in range(6):
        cara.avanzar(0.25)
        escalas.add(round(cara.pose()["escala"], 3))

    assert len(escalas) > 1


def test_listening_avatar_bounces_with_the_voice(qtbot):
    cara = _vivo(avatares.ESCUCHANDO)
    qtbot.addWidget(cara)
    cara._t = 0.2

    quieto = cara.pose()["dy"]
    cara.set_nivel(80)
    con_voz = cara.pose()["dy"]

    assert quieto == 0 and con_voz < -2


def test_thinking_avatar_looks_up_with_dots(qtbot):
    cara = _vivo(avatares.PENSANDO_E)
    qtbot.addWidget(cara)

    pose = cara.pose()

    assert (pose["expresion"], pose["puntos"] is not None) == (avatares.PENSANDO, True)


def test_talking_avatar_pulses_its_eyes(qtbot):
    cara = _vivo(avatares.HABLANDO)
    qtbot.addWidget(cara)

    latidos = set()
    for _ in range(8):
        cara.avanzar(0.05)
        latidos.add(round(cara.pose()["latido"], 2))

    assert len(latidos) > 2 and max(latidos) <= 1.0


def test_joy_is_brief_and_returns_to_the_state(qtbot):
    cara = _vivo(avatares.ESCUCHANDO)
    qtbot.addWidget(cara)

    cara.set_estado(avatares.CONTENTO)
    feliz = cara.pose()["expresion"]
    cara.avanzar(avatares.DURACION_CONTENTO + 0.1)

    assert (feliz, cara.contento, cara.estado) == (avatares.FELIZ, False, avatares.ESCUCHANDO)


def test_hover_makes_the_home_avatar_happy(qtbot):
    cara = avatares.Avatar("rosa", 64, vivo=True, alegre_al_pasar=True)
    qtbot.addWidget(cara)

    cara.enterEvent(None)

    assert cara.contento is True


def test_animation_only_runs_while_visible(qtbot):
    cara = _vivo()
    qtbot.addWidget(cara)

    cara.show()
    visible = cara._reloj.isActive()
    cara.hide()

    assert (visible, cara._reloj.isActive()) == (True, False)


@pytest.mark.parametrize("estado", [avatares.ESCUCHANDO, avatares.PENSANDO_E, avatares.HABLANDO,
                                    avatares.CONTENTO])
def test_every_pose_draws(qtbot, estado):
    cara = _vivo(estado)
    qtbot.addWidget(cara)
    cara.nivel = 70

    assert cara.grab().isNull() is False


def test_clicking_the_avatar_is_reported(qtbot):
    cara = avatares.Avatar("rosa", 64)
    qtbot.addWidget(cara)

    with qtbot.waitSignal(cara.clicked):
        qtbot.mouseClick(cara, QtCore.Qt.LeftButton)
