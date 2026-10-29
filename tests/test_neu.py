"""Neumorphic primitives: cached shadow rendering and the widgets built on it."""
import pytest
from PySide6 import QtGui, QtWidgets

import neu


@pytest.fixture(autouse=True)
def empty_cache():
    neu._cache.clear()


def _centro(pm):
    img = pm.toImage()
    return img.pixelColor(img.width() // 2, img.height() // 2)


@pytest.mark.parametrize("modo", ["relieve", "hundido", "plano"])
def test_surface_has_the_requested_logical_size(qapp, modo):
    pm = neu.superficie(120, 60, 12, 14, modo, 4)

    assert (pm.width() / pm.devicePixelRatio(), pm.height() / pm.devicePixelRatio()) == (120, 60)


def test_surface_is_rendered_once_per_shape(qapp):
    primera = neu.superficie(120, 60, 12, 14, "relieve", 4)

    assert neu.superficie(120, 60, 12, 14, "relieve", 4) is primera


@pytest.mark.parametrize("modo, color", [("relieve", neu.BG), ("plano", neu.BG)])
def test_body_is_the_material(qapp, modo, color):
    assert _centro(neu.superficie(120, 60, 12, 14, modo, 4)).name().upper() == color


def test_inset_body_is_a_shade_darker(qapp):
    centro = _centro(neu.superficie(120, 60, 2, 14, "hundido", 4))

    assert centro.lightness() <= QtGui.QColor(neu.BG).lightness()


def test_accent_fill_is_blue(qapp):
    centro = _centro(neu.superficie(120, 60, 12, 14, "relieve", 4, "acento"))

    assert centro.blue() > centro.red() + 60


def test_raised_shadow_leaves_room_for_its_blur():
    assert neu.margen_relieve(4) >= 4 * 3


def test_surface_layout_sits_inside_the_shadow_margin(qtbot):
    caja = neu.Surface("relieve", prof=5)
    qtbot.addWidget(caja)

    m = caja.contentsMargins()
    assert (m.left(), m.top()) == (neu.margen_relieve(5),) * 2


@pytest.mark.parametrize("variante", ["normal", "acento", "plano"])
def test_button_paints_in_every_state(qtbot, variante):
    b = neu.Button("Guardar", variante=variante)
    b.setCheckable(True)
    qtbot.addWidget(b)
    b.resize(b.sizeHint())

    normal = b.grab().isNull()
    b.setChecked(True)
    marcado = b.grab().isNull()

    assert (normal, marcado) == (False, False)


def test_round_button_is_square(qtbot):
    b = neu.Button(icono="x", redondo=30)
    qtbot.addWidget(b)

    assert b.width() == b.height() == 30 + 2 * b.margen


def test_field_wraps_the_editor_in_an_inset_surface(qtbot):
    editor = QtWidgets.QLineEdit("hola")
    caja = neu.campo(editor, ancho=200)
    qtbot.addWidget(caja)

    assert (caja.modo, editor.parentWidget() is caja, caja.width()) == ("hundido", True, 200)


def test_toggle_flips_on_click(qtbot):
    t = neu.Toggle(False)
    qtbot.addWidget(t)
    t.toggle()

    assert (t.isChecked(), t.grab().isNull()) == (True, False)
