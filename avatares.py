"""La mascota de Armony: un bichito tipo mochi con auriculares de reunion.

Una sola mascota para todos los agentes; cada uno la lleva de su color (como
el companero de Grok). Se dibuja con QPainter sobre un lienzo de 100x100, sin
imagenes: nitida a cualquier tamano. Cuerpo de judia con patitas, auriculares
de diadema con microfono (su trabajo es escuchar reuniones), ojos grandes con
brillo, mejillas y boquita.

Expresiones: ojos abiertos, cerrados (parpadeo), mirando arriba (pensando) y
felices (^ ^); la boca se abre al hablar. Avatar la anima segun la reunion:
  reposo     respira y parpadea.
  escuchando bota con la voz del entrevistador (el nivel de audio).
  pensando   mira arriba con tres puntitos: se esta preparando la respuesta.
  hablando   mueve la boca mientras se escribe la sugerencia.
  contento   ojos felices y un saltito al terminarla (dura un momento).
"""
import math
import random
import time

from PySide6 import QtCore, QtGui, QtWidgets

TINTA = QtGui.QColor("#1F2433")          # ojos y boca
MEJILLA = QtGui.QColor(255, 120, 150, 95)

# (id, nombre, hex)
COLORES = [
    ("pervinca", "Pervinca", "#6C8CFF"),
    ("coral", "Coral", "#FF7A6B"),
    ("menta", "Menta", "#38C9A0"),
    ("ambar", "Ámbar", "#FFB547"),
    ("lavanda", "Lavanda", "#A78BFA"),
    ("rosa", "Rosa", "#FF7EB6"),
    ("cielo", "Cielo", "#4CC3F5"),
    ("grafito", "Grafito", "#5B6478"),
]
HEX = {cid: h for cid, _, h in COLORES}
COLOR_POR_DEFECTO = "pervinca"

ABIERTOS, CERRADOS, PENSANDO, FELIZ = "abiertos", "cerrados", "pensando", "feliz"

# Estados del companero (Avatar vivo).
REPOSO, ESCUCHANDO, PENSANDO_E, HABLANDO, CONTENTO = (
    "reposo", "escuchando", "pensando", "hablando", "contento")
DURACION_CONTENTO = 1.6        # s que dura la alegria al terminar una respuesta

_OJOS = (38, 62)               # x de los ojos
_OJO_Y = 60


def _cuerpo():
    """Judia: mas estrecha arriba, panzona abajo."""
    c = QtGui.QPainterPath()
    c.moveTo(50, 24)
    c.cubicTo(74, 24, 86, 42, 86, 62)
    c.cubicTo(86, 82, 70, 92, 50, 92)
    c.cubicTo(30, 92, 14, 82, 14, 62)
    c.cubicTo(14, 42, 26, 24, 50, 24)
    return c


def _trazo(p, color, grosor):
    p.setPen(QtGui.QPen(color, grosor, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap,
                        QtCore.Qt.RoundJoin))
    p.setBrush(QtCore.Qt.NoBrush)


def _ojo(p, x, y, expresion):
    if expresion in (CERRADOS, FELIZ):
        # cerrados: arco hacia abajo; felices (^ ^): hacia arriba
        _trazo(p, TINTA, 3.2)
        c = QtGui.QPainterPath()
        if expresion == CERRADOS:
            c.moveTo(x - 5.5, y + 1); c.quadTo(x, y + 5.5, x + 5.5, y + 1)
        else:
            c.moveTo(x - 5.5, y + 2); c.quadTo(x, y - 6.5, x + 5.5, y + 2)
        p.drawPath(c)
        return
    ox, oy = (2.0, -3.5) if expresion == PENSANDO else (0.0, 0.0)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(TINTA)
    p.drawEllipse(QtCore.QPointF(x + ox, y + oy), 6.4, 8.0)
    p.setBrush(QtGui.QColor(255, 255, 255, 240))           # brillo grande
    p.drawEllipse(QtCore.QPointF(x + ox + 2.2, y + oy - 2.9), 2.3, 2.3)
    p.setBrush(QtGui.QColor(255, 255, 255, 160))           # y uno pequeno
    p.drawEllipse(QtCore.QPointF(x + ox - 2.0, y + oy + 3.2), 1.1, 1.1)


def _boca(p, abierta):
    if abierta:
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(TINTA)
        p.drawEllipse(QtCore.QPointF(50, 72), 5.2, 4.4)
        p.setBrush(QtGui.QColor(255, 120, 140, 230))       # lengua
        p.drawEllipse(QtCore.QPointF(50, 74.2), 3.1, 1.8)
        return
    _trazo(p, TINTA, 2.6)
    c = QtGui.QPainterPath()
    c.moveTo(46, 70); c.quadTo(50, 74, 54, 70)
    p.drawPath(c)


def _puntos(p, fase, color):
    """Tres puntitos de "estoy pensando", arriba a la derecha, de su color (se
    ven tanto en la Home clara como en el overlay oscuro)."""
    p.setPen(QtCore.Qt.NoPen)
    for i, (x, y, r) in enumerate(((74, 14, 3.6), (83, 8, 4.0), (92, 3, 4.4))):
        a = 0.35 + 0.65 * max(0.0, math.sin((fase - i * 0.18) * math.tau))
        c = QtGui.QColor(color)
        c.setAlpha(int(255 * a))
        p.setBrush(c)
        p.drawEllipse(QtCore.QPointF(x, y), r, r)


def pintar(p, rect, color, expresion=ABIERTOS, boca_abierta=False,
           escala=1.0, dy=0.0, angulo=0.0, puntos=None):
    """Dibuja la mascota dentro de rect (cuadrado) con el color dado.

    Pose (para animarla): escala y giro alrededor del centro, dy en unidades del
    lienzo (100 = alto entero), boca abierta y 'puntos' (fase 0..1 de los
    puntitos de pensar; None, sin puntitos)."""
    color = QtGui.QColor(HEX.get(color, color))
    oscuro = color.darker(170)              # auriculares: el mismo tono, hondo
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    lado = min(rect.width(), rect.height())
    p.translate(rect.x() + (rect.width() - lado) / 2, rect.y() + (rect.height() - lado) / 2)
    p.scale(lado / 100, lado / 100)
    if puntos is not None:
        _puntos(p, puntos, color)
    p.translate(50, 50 + dy)
    p.rotate(angulo)
    p.scale(escala, escala)
    p.translate(-50, -50)

    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(color.darker(125))                           # patitas
    p.drawEllipse(QtCore.QPointF(37, 91), 7.5, 4.2)
    p.drawEllipse(QtCore.QPointF(63, 91), 7.5, 4.2)
    g = QtGui.QLinearGradient(0, 24, 0, 92)                 # luz desde arriba
    g.setColorAt(0, color.lighter(122))
    g.setColorAt(1, color.darker(106))
    p.setBrush(QtGui.QBrush(g))
    p.drawPath(_cuerpo())
    p.setBrush(QtGui.QColor(255, 255, 255, 70))             # brillo
    p.drawEllipse(QtCore.QRectF(26, 34, 18, 10))

    _trazo(p, oscuro, 5.5)                                  # diadema
    diadema = QtGui.QPainterPath()
    diadema.moveTo(16, 56); diadema.cubicTo(14, 12, 86, 12, 84, 56)
    p.drawPath(diadema)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(oscuro)                                      # orejeras
    p.drawRoundedRect(QtCore.QRectF(6, 48, 15, 22), 7, 7)
    p.drawRoundedRect(QtCore.QRectF(79, 48, 15, 22), 7, 7)
    p.setBrush(color.lighter(135))
    p.drawRoundedRect(QtCore.QRectF(9, 53, 6, 12), 3, 3)
    p.drawRoundedRect(QtCore.QRectF(85, 53, 6, 12), 3, 3)
    _trazo(p, oscuro, 2.6)                                  # microfono
    brazo = QtGui.QPainterPath()
    brazo.moveTo(84, 66); brazo.quadTo(80, 82, 64, 80)
    p.drawPath(brazo)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(oscuro)
    p.drawEllipse(QtCore.QPointF(62, 80), 3.4, 3.0)

    p.setBrush(MEJILLA)
    p.drawEllipse(QtCore.QPointF(29, 71), 6, 3.8)
    p.drawEllipse(QtCore.QPointF(71, 71), 6, 3.8)
    _boca(p, boca_abierta)
    for x in _OJOS:
        _ojo(p, x, _OJO_Y, expresion)
    p.restore()


def pixmap(color, px, expresion=ABIERTOS):
    """QPixmap de la mascota a px logicos, nitido a la escala de la pantalla."""
    app = QtGui.QGuiApplication.instance()
    scr = app.primaryScreen() if app is not None else None
    dpr = max(1.0, float(scr.devicePixelRatio())) if scr is not None else 2.0
    pm = QtGui.QPixmap(max(1, round(px * dpr)), max(1, round(px * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    pintar(p, QtCore.QRectF(0, 0, px, px), color, expresion)
    p.end()
    return pm


def de_agente(agente):
    """El color valido de un agente."""
    color = agente.get("color")
    return color if color in HEX else COLOR_POR_DEFECTO


class Avatar(QtWidgets.QWidget):
    """La mascota como widget. Con 'vivo' respira, parpadea y reacciona a su
    estado (set_estado) y al nivel de audio (set_nivel); sin 'vivo' es una
    imagen fija con la expresion de set_expresion."""
    clicked = QtCore.Signal()
    _FPS_MS = 33               # ~30 fotogramas por segundo mientras se ve

    def __init__(self, color, lado=64, vivo=False, alegre_al_pasar=False):
        super().__init__()
        self.color = color
        self.expresion = ABIERTOS
        self.vivo = vivo
        self.alegre_al_pasar = alegre_al_pasar
        self.estado = REPOSO          # el que manda (escuchando, pensando...)
        self._contento_hasta = 0.0    # alegria pasajera, encima del estado
        self.nivel = 0.0
        self._t = 0.0
        self._parpadeo_hasta = 0.0
        self._proximo_parpadeo = random.uniform(1.5, 4.0)
        self.setFixedSize(lado, lado)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self._reloj = QtCore.QTimer(self)
        self._reloj.setInterval(self._FPS_MS)
        self._reloj.timeout.connect(self._tick)
        self._ultimo = None

    # ---------------------------------------------------------- estado
    def set_color(self, color):
        self.color = color
        self.update()

    def set_expresion(self, expresion):
        if expresion != self.expresion:
            self.expresion = expresion
            self.update()

    def set_estado(self, estado):
        """reposo | escuchando | pensando | hablando | contento (pasajero)."""
        if estado == CONTENTO:
            self._contento_hasta = self._t + DURACION_CONTENTO
        else:
            self.estado = estado
        self.update()

    def set_nivel(self, nivel):
        """Nivel de audio 0..100: sube de golpe y baja suave."""
        self.nivel = max(float(nivel), self.nivel * 0.8)

    @property
    def contento(self):
        return self._t < self._contento_hasta

    # ---------------------------------------------------------- animacion
    def showEvent(self, e):
        if self.vivo:
            self._ultimo = time.monotonic()
            self._reloj.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._reloj.stop()
        super().hideEvent(e)

    def _tick(self):
        ahora = time.monotonic()
        self.avanzar(min(0.1, ahora - (self._ultimo or ahora)))
        self._ultimo = ahora
        self.update()

    def avanzar(self, dt):
        """Mueve el reloj de la animacion dt segundos (los tests lo llaman)."""
        self._t += dt
        self.nivel *= 0.9
        if self._t >= self._proximo_parpadeo:
            self._parpadeo_hasta = self._t + 0.13
            self._proximo_parpadeo = self._t + random.uniform(2.5, 5.5)

    def pose(self):
        """Lo que se dibuja ahora: dict con los argumentos de pintar()."""
        t = self._t
        parpadea = self._t < self._parpadeo_hasta
        pose = dict(expresion=CERRADOS if parpadea else ABIERTOS, boca_abierta=False,
                    escala=1.0 + 0.025 * math.sin(t * 2.2), dy=0.0, angulo=0.0, puntos=None)
        if not self.vivo:
            pose.update(expresion=self.expresion, escala=1.0)
            return pose
        if self.contento:
            hecho = DURACION_CONTENTO - (self._contento_hasta - t)
            pose.update(expresion=FELIZ,
                        dy=-7 * abs(math.sin(hecho * 7)) if hecho < 0.6 else 0.0)
        elif self.estado == PENSANDO_E:
            pose.update(expresion=PENSANDO, puntos=(t * 1.4) % 1, angulo=-4, escala=1.0)
        elif self.estado == HABLANDO:
            pose.update(boca_abierta=int(t * 7) % 2 == 0, dy=-1.5 * abs(math.sin(t * 7)))
        elif self.estado == ESCUCHANDO:
            fuerza = min(1.0, self.nivel / 60)
            pose.update(dy=-8 * fuerza * abs(math.sin(t * 9)),
                        angulo=3 * fuerza * math.sin(t * 3))
        return pose

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        # Margen para el bote y los puntitos, que se salen del cuerpo.
        m = self.width() * (0.08 if self.vivo else 0.0)
        pintar(p, QtCore.QRectF(self.rect()).adjusted(m, m, -m, -m),
               self.color, **self.pose())
        p.end()

    def enterEvent(self, e):
        if self.alegre_al_pasar:
            self.set_estado(CONTENTO)
        super().enterEvent(e)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
