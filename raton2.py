"""El segundo raton: un cursor azul para usar el overlay sin tocar el real.

El overlay es invisible al compartir pantalla, pero el cursor del sistema no:
si lo llevas encima del overlay para hacer scroll, subrayar o redimensionar,
quien te ve compartiendo pantalla ve el puntero moviendose y seleccionando
sobre la nada. Con el segundo raton encendido (Bloq Mayus+Q):

- El cursor real se queda quieto donde estaba: un hook de bajo nivel
  (WH_MOUSE_LL) se traga los movimientos, clics y la rueda del raton fisico.
- Ese movimiento mueve un cursor azul dibujado en una ventana sin marco,
  transparente al raton y excluida de la captura, como el resto del overlay.
- Clics, arrastres (subrayar texto, mover un panel, redimensionarlo) y la
  rueda se inyectan en las ventanas del overlay con QTest, que los mete en la
  tuberia normal de Qt sin mover el cursor del sistema.

Fuera del overlay el cursor azul no hace nada (no hay clics "a ciegas" en
otras aplicaciones). Bloq Mayus+Q lo apaga y el raton fisico vuelve a mover el
cursor real, desde donde se quedo.

Seguridad: si el hilo de Qt deja de responder, el hook no puede quedarse con
el raton. Qt late cada 250 ms (latido); si pasa LATIDO_MAX_S sin latido, el
hook deja pasar todo y el raton real funciona aunque la app este colgada.
"""
import ctypes
import logging
import threading
import time
from ctypes import wintypes

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest   # inyecta raton en ventanas Qt (sin moverlo de verdad)

log = logging.getLogger("armony.raton2")

user32 = ctypes.windll.user32

WH_MOUSE_LL = 14
HC_ACTION = 0
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
WM_MOUSEHWHEEL = 0x020E
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
LLMHF_INJECTED = 0x01

BOTONES = {
    WM_LBUTTONDOWN: (1, True), WM_LBUTTONUP: (1, False),
    WM_RBUTTONDOWN: (2, True), WM_RBUTTONUP: (2, False),
    WM_MBUTTONDOWN: (4, True), WM_MBUTTONUP: (4, False),
}
_QT_BOTON = {1: QtCore.Qt.LeftButton, 2: QtCore.Qt.RightButton, 4: QtCore.Qt.MiddleButton}

# Sin latido de Qt durante esto, el raton real vuelve a funcionar.
LATIDO_MAX_S = 1.5
LATIDO_MS = 250

AZUL = "#0b5cff"            # azul fuerte, que se distingue sobre cualquier fondo


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE,
                                     wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]


def posicion_real():
    """Donde esta el cursor del sistema, en pixeles fisicos."""
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


class CursorAzul(QtWidgets.QWidget):
    """La flecha azul: una ventana diminuta, siempre encima, que no recibe
    raton ni foco. La punta de la flecha es su esquina superior izquierda."""

    LADO = 26

    def __init__(self):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
                            | QtCore.Qt.Tool | QtCore.Qt.WindowTransparentForInput
                            | QtCore.Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(self.LADO, self.LADO)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        flecha = QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in (
            (1.5, 1.5), (1.5, 19.5), (6.2, 15.4), (9.4, 22.6), (12.6, 21.2),
            (9.5, 14.2), (15.6, 14.2))])
        sombra = QtGui.QPolygonF([pt + QtCore.QPointF(1.2, 1.4) for pt in flecha])
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 90))
        p.drawPolygon(sombra)
        p.setBrush(QtGui.QColor(AZUL))
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.4))
        p.drawPolygon(flecha)


class AtrapaRueda(QtWidgets.QWidget):
    """Ventanita invisible bajo el cursor real (quieto) mientras el raton azul
    esta encendido. El gesto de scroll del panel tactil no pasa por el hook:
    Windows lo entrega a la ventana que hay bajo el cursor real. Asi esa
    ventana es esta, y el scroll se lleva al panel que hay bajo el azul.
    Pixeles casi transparentes (alfa 1): invisibles, pero Windows los cuenta
    para el raton (con alfa 0 la ventana dejaria pasar todo)."""

    LADO = 64

    def __init__(self, al_rodar):
        super().__init__()
        self._al_rodar = al_rodar
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
                            | QtCore.Qt.Tool | QtCore.Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(self.LADO, self.LADO)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 1))

    def colocar(self, centro):
        self.move(centro.x() - self.LADO // 2, centro.y() - self.LADO // 2)

    def wheelEvent(self, e):
        delta = e.angleDelta().y() or e.angleDelta().x()
        if delta:
            self._al_rodar(delta)
        e.accept()


class _Puente(QtCore.QObject):
    """Del hilo del hook al de Qt, siempre en cola."""
    movido = QtCore.Signal()
    boton = QtCore.Signal(int, bool)
    rueda = QtCore.Signal(int)

    def __init__(self, raton):
        super().__init__()
        self.movido.connect(raton._mover_pendiente, QtCore.Qt.QueuedConnection)
        self.boton.connect(raton._boton, QtCore.Qt.QueuedConnection)
        self.rueda.connect(raton._rueda, QtCore.Qt.QueuedConnection)


class SegundoRaton(QtCore.QObject):
    """El cursor azul y el hook que le da el movimiento del raton fisico.

    ventanas(): las ventanas del overlay que puede tocar (QWidget de nivel
    superior), en orden de arriba a abajo. al_rodar(pos, muescas): la rueda
    sobre el overlay (pos en coordenadas logicas de pantalla).
    """
    cambiado = QtCore.Signal(bool)

    def __init__(self, ventanas, al_rodar=None, reloj=time.monotonic):
        super().__init__()
        self._ventanas = ventanas
        self._al_rodar = al_rodar
        self._reloj = reloj
        self.cursor = CursorAzul()
        self.atrapa = AtrapaRueda(self._rueda)
        self.pos = QtCore.QPointF()
        # Movimiento acumulado por el hook y aun no aplicado. Se junta: un raton
        # da cientos de movimientos por segundo y, uno a uno, Qt se quedaba
        # atras (con mucho texto o redimensionando) y hasta el soltar llegaba
        # tarde, al final de la cola: el panel seguia "pegado" al raton.
        self._mov_lock = threading.Lock()
        self._mov = [0, 0]
        self._mov_pendiente = False
        self.activo = False                  # lo lee el hook (bool: atomico)
        self._ancla = (0, 0)                 # donde se quedo el cursor real
        self._latido = reloj()
        self._paso_libre = False             # el hook dejo pasar por falta de latido
        self._presionado = {}                # boton -> ventana que recibio el press
        self._resto_rueda = 0
        self._puente = _Puente(self)
        self._proc = HOOKPROC(self._on_mouse)   # referencia viva o crash
        self._hook = None
        self._hilo = None
        self._tid = 0
        self._listo = threading.Event()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(LATIDO_MS)
        self._timer.timeout.connect(self.latir)

    # -- ciclo de vida ------------------------------------------------------
    def instalar(self):
        if self._hilo and self._hilo.is_alive():
            return bool(self._hook)
        self._listo.clear()
        self._hilo = threading.Thread(target=self._run, name="raton2-hook", daemon=True)
        self._hilo.start()
        self._listo.wait(5.0)
        self._timer.start()
        return bool(self._hook)

    def _run(self):
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        self._listo.set()
        if not self._hook:
            log.warning("SetWindowsHookExW(WH_MOUSE_LL) failed; no second mouse")
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
        finally:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def desinstalar(self):
        self.desactivar()
        self._timer.stop()
        if self._hilo and self._hilo.is_alive() and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._hilo.join(2.0)
        self._hilo = None
        self._hook = None

    # -- encender / apagar --------------------------------------------------
    def activar(self):
        if self.activo:
            return
        self._ancla = posicion_real()
        self.pos = QtCore.QPointF(QtGui.QCursor.pos())
        self._latido = self._reloj()
        self._colocar()
        self.atrapa.colocar(self.pos.toPoint())
        self.atrapa.show()
        self.cursor.show()
        self.cursor.raise_()
        self.activo = True
        self.cambiado.emit(True)

    def desactivar(self):
        if not self.activo:
            return
        self.activo = False
        for boton in list(self._presionado):      # nada se queda pulsado
            self._boton(boton, False)
        self.cursor.hide()
        self.atrapa.hide()
        with self._mov_lock:
            self._mov = [0, 0]
            self._mov_pendiente = False
        self.cambiado.emit(False)

    def alternar(self):
        if self.activo:
            self.desactivar()
        else:
            self.activar()
        return self.activo

    def latir(self):
        """Qt sigue vivo. Si el hook tuvo que soltar el raton (Qt no
        respondia), el cursor real se movio: se ancla de nuevo donde este."""
        self._latido = self._reloj()
        if self._paso_libre:
            self._paso_libre = False
            self._ancla = posicion_real()

    # -- hook (hilo propio: nada lento aqui) --------------------------------
    def _on_mouse(self, nCode, wParam, lParam):
        try:
            if nCode == HC_ACTION and self.activo:
                if self._reloj() - self._latido > LATIDO_MAX_S:
                    self._paso_libre = True          # Qt no responde: raton real
                else:
                    ms = MSLLHOOKSTRUCT.from_address(lParam)
                    if not ms.flags & LLMHF_INJECTED and self._tragar(wParam, ms):
                        return 1
        except Exception:
            pass                                      # ante la duda, dejar pasar
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _tragar(self, wParam, ms):
        """Pasa el evento al cursor azul. True: el sistema no lo ve."""
        if wParam == WM_MOUSEMOVE:
            dx, dy = ms.pt.x - self._ancla[0], ms.pt.y - self._ancla[1]
            if dx or dy:
                with self._mov_lock:
                    self._mov[0] += dx
                    self._mov[1] += dy
                    avisar = not self._mov_pendiente
                    self._mov_pendiente = True
                if avisar:                       # uno en cola como mucho
                    self._puente.movido.emit()
            return True
        if wParam in BOTONES:
            boton, abajo = BOTONES[wParam]
            self._puente.boton.emit(boton, abajo)
            return True
        if wParam == WM_MOUSEWHEEL:
            delta = ctypes.c_short((ms.mouseData >> 16) & 0xFFFF).value
            self._puente.rueda.emit(delta)
            return True
        return wParam in (WM_XBUTTONDOWN, WM_XBUTTONUP, WM_MOUSEHWHEEL)

    # -- en el hilo de Qt ---------------------------------------------------
    def _limites(self):
        rect = QtCore.QRect()
        for pantalla in QtGui.QGuiApplication.screens():
            rect = rect.united(pantalla.geometry())
        return rect

    def _mover_pendiente(self):
        """Aplica de una vez todo lo que se movio desde la ultima vez."""
        with self._mov_lock:
            dx, dy = self._mov
            self._mov = [0, 0]
            self._mov_pendiente = False
        if dx or dy:
            self._mover(dx, dy)

    def _mover(self, dx, dy):
        if not self.activo:
            return
        pantalla = QtGui.QGuiApplication.screenAt(self.pos.toPoint())
        dpr = pantalla.devicePixelRatio() if pantalla is not None else 1.0
        lim = self._limites()
        x = min(max(self.pos.x() + dx / dpr, lim.left()), lim.right())
        y = min(max(self.pos.y() + dy / dpr, lim.top()), lim.bottom())
        self.pos = QtCore.QPointF(x, y)
        self._colocar()
        ventana = self._destino()
        if ventana is not None:
            self._inyectar("mover", ventana)

    def _colocar(self):
        self.cursor.move(self.pos.toPoint())

    def _destino(self, boton=None):
        """La ventana del overlay bajo el cursor azul (o la que recibio el
        press de ese boton, que sigue recibiendo hasta soltarlo)."""
        if boton is not None and boton in self._presionado:
            return self._presionado[boton]
        sueltos = [b for b in self._presionado]
        if sueltos:                                    # arrastrando: la del press
            return self._presionado[sueltos[0]]
        punto = self.pos.toPoint()
        emergente = QtWidgets.QApplication.activePopupWidget()
        candidatas = ([emergente] if emergente is not None else []) + list(self._ventanas())
        for w in candidatas:
            if w is not None and w.isVisible() and w.frameGeometry().contains(punto):
                return w
        return None

    def _local(self, ventana):
        return ventana.mapFromGlobal(self.pos.toPoint())

    def _inyectar(self, accion, ventana, boton=None):
        handle = ventana.windowHandle()
        if handle is None:
            return
        local = self._local(ventana)
        mods = QtGui.QGuiApplication.queryKeyboardModifiers()
        try:
            if accion == "mover":
                QTest.mouseMove(handle, local)
            elif accion == "pulsar":
                QTest.mousePress(handle, _QT_BOTON[boton], mods, local)
            elif accion == "soltar":
                QTest.mouseRelease(handle, _QT_BOTON[boton], mods, local)
        except Exception:
            log.debug("Second-mouse event not delivered", exc_info=True)

    def _boton(self, boton, abajo):
        if abajo:
            if not self.activo:
                return
            self._mover_pendiente()            # el clic, donde esta el raton ya
            ventana = self._destino()
            if ventana is None:
                return                           # fuera del overlay: nada
            self._presionado[boton] = ventana
            # Primero un movimiento ahi mismo, como haria un raton de verdad: sin
            # el, Qt pierde la primera pulsacion en una ventana que aun no ha
            # visto el raton encima.
            self._inyectar("mover", ventana)
            self._inyectar("pulsar", ventana, boton)
            return
        self._mover_pendiente()                # soltar donde se solto
        ventana = self._presionado.pop(boton, None)
        if ventana is not None and ventana.isVisible():
            self._inyectar("soltar", ventana, boton)

    def _rueda(self, delta):
        if not self.activo or self._al_rodar is None:
            return
        if self._resto_rueda and (self._resto_rueda > 0) != (delta > 0):
            self._resto_rueda = 0
        total = self._resto_rueda + delta
        muescas = int(total / 120)
        self._resto_rueda = total - muescas * 120
        if muescas:
            self._al_rodar(self.pos.toPoint(), muescas)
