"""The blue second mouse: the hook swallows the physical mouse while it is on,
the blue cursor moves instead, and clicks/drags/wheel reach the overlay
through Qt (QTest), never the apps below. No hook is installed here: the hook
callback is called directly with synthetic MSLLHOOKSTRUCTs."""
import ctypes

import pytest
from PySide6 import QtCore, QtWidgets

import raton2


class Reloj:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def ventana(qtbot):
    w = QtWidgets.QWidget()
    w.setWindowFlags(QtCore.Qt.FramelessWindowHint)
    w.setGeometry(200, 200, 300, 200)
    boton = QtWidgets.QPushButton("ok", w)
    boton.setGeometry(50, 50, 100, 40)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.boton = boton
    return w


@pytest.fixture
def raton(qtbot, ventana, monkeypatch):
    monkeypatch.setattr(raton2, "posicion_real", lambda: (500, 400))
    rodadas = []
    reloj = Reloj()
    r = raton2.SegundoRaton(lambda: [ventana], al_rodar=lambda p, m: rodadas.append((p, m)),
                            reloj=reloj)
    qtbot.addWidget(r.cursor)
    r.rodadas, r.reloj = rodadas, reloj
    yield r
    r.desactivar()


def evento(x=0, y=0, data=0, flags=0):
    ms = raton2.MSLLHOOKSTRUCT()
    ms.pt.x, ms.pt.y, ms.mouseData, ms.flags = x, y, data, flags
    return ms


def hook(r, mensaje, ms):
    return r._on_mouse(0, mensaje, ctypes.addressof(ms))


def ir_a(r, qtbot, x, y):
    r.pos = QtCore.QPointF(x, y)
    r._colocar()


# ------------------------------------------------------------------ the hook
def test_off_it_lets_the_real_mouse_through(raton):
    assert hook(raton, raton2.WM_MOUSEMOVE, evento(510, 400)) != 1
    assert hook(raton, raton2.WM_LBUTTONDOWN, evento()) != 1


def test_on_it_swallows_moves_and_sends_the_delta(raton):
    raton.activar()

    assert hook(raton, raton2.WM_MOUSEMOVE, evento(512, 395)) == 1

    # Relative to where the real cursor froze, waiting for Qt to apply it.
    assert raton._mov == [12, -5] and raton._mov_pendiente is True


def test_on_it_swallows_clicks_and_the_wheel(raton):
    raton.activar()

    for mensaje in (raton2.WM_LBUTTONDOWN, raton2.WM_LBUTTONUP, raton2.WM_RBUTTONDOWN,
                    raton2.WM_MOUSEWHEEL, raton2.WM_XBUTTONDOWN):
        assert hook(raton, mensaje, evento(500, 400, data=120 << 16)) == 1


def test_injected_events_always_pass(raton):
    raton.activar()

    assert hook(raton, raton2.WM_MOUSEMOVE,
                evento(510, 400, flags=raton2.LLMHF_INJECTED)) != 1


def test_if_qt_stops_responding_the_real_mouse_comes_back(raton, monkeypatch):
    raton.activar()
    raton.reloj.t += raton2.LATIDO_MAX_S + 0.1      # no heartbeat for too long

    assert hook(raton, raton2.WM_MOUSEMOVE, evento(530, 400)) != 1
    assert raton._paso_libre is True

    monkeypatch.setattr(raton2, "posicion_real", lambda: (530, 400))
    raton.latir()                                   # Qt is back: re-anchor
    assert raton._paso_libre is False and raton._ancla == (530, 400)
    assert hook(raton, raton2.WM_MOUSEMOVE, evento(531, 400)) == 1


# ------------------------------------------------------------------ on Qt
def test_switching_on_shows_the_blue_cursor_where_the_real_one_is(raton):
    cambios = []
    raton.cambiado.connect(cambios.append)

    assert raton.alternar() is True

    assert raton.cursor.isVisible() and raton._ancla == (500, 400)
    assert raton.alternar() is False and not raton.cursor.isVisible()
    assert cambios == [True, False]


def test_moving_follows_the_delta_and_stays_on_screen(raton):
    raton.activar()
    ir_a(raton, None, 300, 300)

    raton._mover(10, -4)
    assert raton.pos == QtCore.QPointF(310, 296)
    assert raton.cursor.pos() == QtCore.QPoint(310, 296)

    raton._mover(-10 ** 6, -10 ** 6)
    limites = raton._limites()
    assert (raton.pos.x(), raton.pos.y()) == (limites.left(), limites.top())


def test_a_click_reaches_the_overlay_button_under_the_blue_cursor(raton, ventana, qtbot):
    """Even the first click on a window that never saw the mouse move."""
    raton.activar()
    clics = []
    ventana.boton.clicked.connect(lambda: clics.append(1))
    ir_a(raton, qtbot, 200 + 60, 200 + 60)

    raton._boton(1, True)
    qtbot.wait(5)
    raton._boton(1, False)
    qtbot.wait(5)                            # delivered by the event loop

    assert clics == [1]


def test_a_click_outside_the_overlay_does_nothing(raton, ventana):
    raton.activar()
    ir_a(raton, None, 5, 5)

    raton._boton(1, True)

    assert raton._presionado == {}


def test_a_drag_keeps_going_to_the_window_it_started_in(raton, ventana, qtbot):
    raton.activar()
    ir_a(raton, qtbot, 260, 260)
    raton._boton(1, True)

    ir_a(raton, qtbot, 5, 5)                 # dragged outside the window

    assert raton._destino() is ventana
    raton._boton(1, False)
    assert raton._presionado == {}


def test_switching_off_releases_a_pressed_button(raton, ventana, qtbot):
    raton.activar()
    ir_a(raton, qtbot, 260, 260)
    raton._boton(1, True)

    raton.desactivar()

    assert raton._presionado == {}


def test_wheel_goes_to_the_overlay_in_whole_notches(raton):
    raton.activar()
    ir_a(raton, None, 250, 250)

    raton._rueda(60)
    raton._rueda(60)
    raton._rueda(-120)

    assert raton.rodadas == [(QtCore.QPoint(250, 250), 1), (QtCore.QPoint(250, 250), -1)]


def test_nothing_reaches_qt_while_it_is_off(raton, ventana):
    raton._mover(10, 10)
    raton._boton(1, True)
    raton._rueda(120)

    assert raton._presionado == {} and raton.rodadas == []


def test_the_blue_cursor_never_takes_the_mouse_or_focus(raton):
    flags = raton.cursor.windowFlags()

    assert flags & QtCore.Qt.WindowTransparentForInput
    assert flags & QtCore.Qt.WindowDoesNotAcceptFocus
    assert raton.cursor.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)


# ------------------------------------------------------------------ coalescing
def test_many_hook_moves_become_one_pending_move(raton, qtbot):
    """A mouse gives hundreds of moves a second: they pile into one pending
    move, so Qt never falls behind (and a release never waits at the end of
    a long queue, which left the panel glued to the mouse)."""
    raton.activar()
    ir_a(raton, qtbot, 300, 300)
    llamadas = []
    original = raton._mover
    raton._mover = lambda dx, dy: (llamadas.append((dx, dy)), original(dx, dy))

    for _ in range(50):
        hook(raton, raton2.WM_MOUSEMOVE, evento(502, 401))
    qtbot.wait(10)

    assert llamadas == [(100, 50)]
    assert raton.pos == QtCore.QPointF(400, 350)


def test_a_click_first_applies_the_pending_move(raton, ventana, qtbot):
    raton.activar()
    ir_a(raton, qtbot, 150, 150)                  # outside the window
    raton._mov = [110, 110]                       # moved onto the button, not applied yet
    raton._mov_pendiente = True
    clics = []
    ventana.boton.clicked.connect(lambda: clics.append(1))

    raton._boton(1, True)
    qtbot.wait(5)
    raton._boton(1, False)
    qtbot.wait(5)

    assert clics == [1]


# ------------------------------------------------------------------ touchpad scroll
def test_touchpad_scroll_is_caught_under_the_frozen_real_cursor(raton, qtbot):
    """The touchpad gesture skips the hook and goes to the window under the
    real cursor: a tiny invisible window sits there while the blue mouse is on."""
    raton.activar()
    real = raton.pos.toPoint()                    # where the real cursor froze
    ir_a(raton, qtbot, 250, 250)

    assert raton.atrapa.isVisible()
    centro = raton.atrapa.geometry().center()
    assert abs(centro.x() - real.x()) <= 1 and abs(centro.y() - real.y()) <= 1

    from PySide6 import QtGui
    ev = QtGui.QWheelEvent(QtCore.QPointF(5, 5), QtCore.QPointF(5, 5), QtCore.QPoint(0, 0),
                           QtCore.QPoint(0, 120), QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
                           QtCore.Qt.NoScrollPhase, False)
    QtWidgets.QApplication.sendEvent(raton.atrapa, ev)

    assert raton.rodadas == [(QtCore.QPoint(250, 250), 1)]



def test_the_catcher_goes_away_with_the_blue_mouse(raton):
    raton.activar()
    raton.desactivar()

    assert not raton.atrapa.isVisible()


def test_the_catcher_is_hit_testable_but_never_takes_focus(raton):
    flags = raton.atrapa.windowFlags()

    assert not flags & QtCore.Qt.WindowTransparentForInput
    assert flags & QtCore.Qt.WindowDoesNotAcceptFocus
