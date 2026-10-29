"""Personajes de los agentes: minimalistas, de un color, con cara y vivos.

Se dibujan con QPainter sobre un lienzo de 100x100 (sin imagenes): se ven
nitidos a cualquier tamano y el color de cada agente es el del cuerpo. La cara
admite cuatro expresiones: ojos abiertos, cerrados (parpadeo), mirando arriba
(pensando) y felices (^ ^); y la boca se abre al hablar.

Avatar los anima segun lo que pasa en la reunion, como un companero:
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

TINTA = QtGui.QColor("#1F2433")          # ojos, boca, nariz
MEJILLA = QtGui.QColor(255, 120, 150, 90)

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

ABIERTOS, CERRADOS, PENSANDO, FELIZ = "abiertos", "cerrados", "pensando", "feliz"

# Estados del companero (Avatar vivo).
REPOSO, ESCUCHANDO, PENSANDO_E, HABLANDO, CONTENTO = (
    "reposo", "escuchando", "pensando", "hablando", "contento")
DURACION_CONTENTO = 1.6        # s que dura la alegria al terminar una respuesta

PERSONAJE_POR_DEFECTO = "gota"
COLOR_POR_DEFECTO = "pervinca"


def _p(*puntos):
    """Poligono cerrado como QPainterPath."""
    camino = QtGui.QPainterPath()
    camino.moveTo(*puntos[0])
    for x, y in puntos[1:]:
        camino.lineTo(x, y)
    camino.closeSubpath()
    return camino


def _elipse(x, y, w, h):
    camino = QtGui.QPainterPath()
    camino.addEllipse(QtCore.QRectF(x, y, w, h))
    return camino


def _redondeado(x, y, w, h, r):
    camino = QtGui.QPainterPath()
    camino.addRoundedRect(QtCore.QRectF(x, y, w, h), r, r)
    return camino


# ------------------------------------------------------------------ cuerpos
# Cada personaje: cuerpo (QPainterPath), donde van los ojos (x izq, x der, y,
# tamano), su boca y sus detalles. Todo en coordenadas de 0 a 100.
def _gota():
    return _redondeado(12, 16, 76, 72, 36)


def _gato():
    cabeza = _elipse(14, 30, 72, 60)
    return (cabeza.united(_p((18, 46), (22, 10), (46, 32)))
            .united(_p((82, 46), (78, 10), (54, 32))))


def _robot():
    cuerpo = _redondeado(16, 28, 68, 58, 16)
    antena = _redondeado(48, 12, 4, 18, 2).united(_elipse(43, 5, 14, 14))
    orejas = _redondeado(8, 48, 10, 18, 4).united(_redondeado(82, 48, 10, 18, 4))
    return cuerpo.united(antena).united(orejas)


def _fantasma():
    c = QtGui.QPainterPath()
    c.moveTo(16, 50)
    c.arcTo(QtCore.QRectF(16, 14, 68, 72), 180, -180)   # cupula
    c.lineTo(84, 86)
    for i, x in enumerate((73, 61, 50, 39, 27, 16)):
        c.quadTo(x + 5.5, 96 if i % 2 == 0 else 80, x, 86)
    c.closeSubpath()
    return c


def _buho():
    cuerpo = _elipse(16, 22, 68, 70)
    return (cuerpo.united(_p((20, 36), (22, 10), (40, 26)))
            .united(_p((80, 36), (78, 10), (60, 26))))


def _zorro():
    cara = QtGui.QPainterPath()
    cara.moveTo(12, 34)
    cara.quadTo(14, 66, 50, 90)
    cara.quadTo(86, 66, 88, 34)
    cara.quadTo(50, 22, 12, 34)
    return (cara.united(_p((14, 40), (20, 6), (44, 28)))
            .united(_p((86, 40), (80, 6), (56, 28))))


def _nube():
    return (_elipse(10, 42, 44, 44).united(_elipse(28, 22, 52, 52))
            .united(_elipse(54, 40, 38, 38)).united(_redondeado(18, 58, 66, 28, 14)))


def _oso():
    return (_elipse(18, 26, 64, 64).united(_elipse(14, 16, 26, 26))
            .united(_elipse(60, 16, 26, 26)))


# id -> (nombre, cuerpo, (ojo izq x, ojo der x, y, tamano), boca, mejillas)
PERSONAJES = {
    "gota": ("Gota", _gota, (38, 62, 50, 9), "sonrisa", True),
    "gato": ("Gato", _gato, (38, 62, 58, 8), "gato", True),
    "robot": ("Robot", _robot, (37, 63, 54, 9), "recta", False),
    "fantasma": ("Fantasma", _fantasma, (39, 61, 48, 10), "o", True),
    "buho": ("Búho", _buho, (37, 63, 50, 7), "pico", False),
    "zorro": ("Zorro", _zorro, (38, 62, 52, 8), "hocico", False),
    "nube": ("Nube", _nube, (42, 62, 58, 8), "sonrisa", True),
    "oso": ("Oso", _oso, (39, 61, 52, 8), "oso", False),
}


def _ojo(p, x, y, t, expresion):
    if expresion == FELIZ:
        # ^ ^ : arco hacia arriba
        p.setPen(QtGui.QPen(TINTA, t * 0.42, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.setBrush(QtCore.Qt.NoBrush)
        camino = QtGui.QPainterPath()
        camino.moveTo(x - t * 0.6, y + t * 0.2)
        camino.quadTo(x, y - t * 0.7, x + t * 0.6, y + t * 0.2)
        p.drawPath(camino)
        return
    if expresion == CERRADOS:
        p.setPen(QtGui.QPen(TINTA, t * 0.42, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.setBrush(QtCore.Qt.NoBrush)
        camino = QtGui.QPainterPath()
        camino.moveTo(x - t * 0.6, y)
        camino.quadTo(x, y + t * 0.55, x + t * 0.6, y)
        p.drawPath(camino)
        return
    dy = -t * 0.35 if expresion == PENSANDO else 0
    dx = t * 0.2 if expresion == PENSANDO else 0
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(TINTA)
    p.drawEllipse(QtCore.QPointF(x + dx, y + dy), t * 0.5, t * 0.62)
    p.setBrush(QtGui.QColor(255, 255, 255, 230))          # brillo
    p.drawEllipse(QtCore.QPointF(x + dx + t * 0.17, y + dy - t * 0.22), t * 0.17, t * 0.17)


def _boca(p, tipo, color):
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(TINTA, 2.6, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap,
                        QtCore.Qt.RoundJoin))
    c = QtGui.QPainterPath()
    if tipo == "sonrisa":
        c.moveTo(45, 62); c.quadTo(50, 67, 55, 62)
        p.drawPath(c)
    elif tipo == "gato":
        c.moveTo(43, 69); c.quadTo(46.5, 73, 50, 69); c.quadTo(53.5, 73, 57, 69)
        p.drawPath(c)
        p.setPen(QtCore.Qt.NoPen); p.setBrush(TINTA)
        p.drawPath(_p((47, 64), (53, 64), (50, 67.5)))
        p.setPen(QtGui.QPen(QtGui.QColor(31, 36, 51, 110), 1.6, QtCore.Qt.SolidLine,
                            QtCore.Qt.RoundCap))
        for y in (66, 71):
            p.drawLine(QtCore.QPointF(24, y - 2), QtCore.QPointF(36, y))
            p.drawLine(QtCore.QPointF(76, y - 2), QtCore.QPointF(64, y))
    elif tipo == "recta":
        p.drawLine(QtCore.QPointF(43, 70), QtCore.QPointF(57, 70))
    elif tipo == "o":
        p.setPen(QtCore.Qt.NoPen); p.setBrush(TINTA)
        p.drawEllipse(QtCore.QPointF(50, 64), 3.6, 4.6)
    elif tipo == "pico":
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor("#FFB547"))
        p.drawPath(_p((45, 60), (55, 60), (50, 69)))
    elif tipo == "hocico":
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(255, 255, 255, 215))
        hocico = QtGui.QPainterPath()
        hocico.moveTo(30, 62); hocico.quadTo(50, 54, 70, 62); hocico.quadTo(62, 80, 50, 86)
        hocico.quadTo(38, 80, 30, 62)
        p.drawPath(hocico)
        p.setBrush(TINTA)
        p.drawEllipse(QtCore.QPointF(50, 66), 4, 3)
    elif tipo == "oso":
        p.setPen(QtCore.Qt.NoPen); p.setBrush(color.lighter(135))
        p.drawEllipse(QtCore.QRectF(38, 58, 24, 18))
        p.setBrush(TINTA)
        p.drawEllipse(QtCore.QPointF(50, 63), 3.6, 2.8)
        p.setPen(QtGui.QPen(TINTA, 2.2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        c.moveTo(46, 69); c.quadTo(50, 72, 54, 69)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(c)


# Donde se abre la boca al hablar, segun el tipo de boca.
_BOCA_Y = {"sonrisa": 64, "gato": 71, "recta": 70, "o": 64, "pico": 64,
           "hocico": 75, "oso": 70}


def _boca_abierta(p, tipo, color):
    if tipo == "pico":
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#FFB547"))
        p.drawPath(_p((45, 58), (55, 58), (50, 63)))
        p.drawPath(_p((46, 66), (54, 66), (50, 71)))
        return
    if tipo == "hocico":
        _boca(p, "hocico", color)          # el hocico y la nariz se quedan
    elif tipo == "oso":
        _boca(p, "oso", color)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(TINTA)
    y = _BOCA_Y.get(tipo, 66)
    p.drawEllipse(QtCore.QPointF(50, y), 6.5, 5.5)
    p.setBrush(QtGui.QColor(255, 120, 140, 220))          # lengua
    p.drawEllipse(QtCore.QPointF(50, y + 2.6), 3.8, 2.2)


def _puntos(p, fase, color):
    """Tres puntitos de "estoy pensando", arriba a la derecha, del color del
    personaje (se ven tanto en la Home clara como en el overlay oscuro)."""
    p.setPen(QtCore.Qt.NoPen)
    for i, (x, y, r) in enumerate(((72, 12, 3.6), (81, 7, 4.0), (90, 3, 4.4))):
        a = 0.35 + 0.65 * max(0.0, math.sin((fase - i * 0.18) * math.tau))
        c = QtGui.QColor(color)
        c.setAlpha(int(255 * a))
        p.setBrush(c)
        p.drawEllipse(QtCore.QPointF(x, y), r, r)


def pintar(p, rect, personaje, color, expresion=ABIERTOS, boca_abierta=False,
           escala=1.0, dy=0.0, angulo=0.0, puntos=None):
    """Dibuja el personaje dentro de rect (cuadrado) con el color dado.

    Pose (para animarlo): escala y giro alrededor del centro, dy en unidades
    del lienzo (100 = alto entero), boca abierta y 'puntos' (fase 0..1 de los
    puntitos de pensar; None, sin puntitos)."""
    nombre_, cuerpo, ojos, boca, mejillas = PERSONAJES.get(personaje, PERSONAJES["gota"])
    color = QtGui.QColor(HEX.get(color, color))
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
    # cuerpo con un degradado suave: mas claro arriba, como si le diera la luz
    g = QtGui.QLinearGradient(0, 0, 0, 100)
    g.setColorAt(0, color.lighter(118))
    g.setColorAt(1, color.darker(108))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QBrush(g))
    p.drawPath(cuerpo())
    if personaje == "robot":
        p.setBrush(QtGui.QColor(255, 255, 255, 60))          # pantalla de la cara
        p.drawRoundedRect(QtCore.QRectF(24, 38, 52, 40), 10, 10)
    if personaje == "buho":
        p.setBrush(QtGui.QColor(255, 255, 255, 235))         # ojos grandes
        for x in (ojos[0], ojos[1]):
            p.drawEllipse(QtCore.QPointF(x, ojos[2]), 11, 11)
    if mejillas:
        p.setBrush(MEJILLA)
        y = ojos[2] + ojos[3] * 1.15
        p.drawEllipse(QtCore.QPointF(ojos[0] - 9, y), 5.5, 3.6)
        p.drawEllipse(QtCore.QPointF(ojos[1] + 9, y), 5.5, 3.6)
    if boca_abierta:
        _boca_abierta(p, boca, color)
    else:
        _boca(p, boca, color)
    for x in (ojos[0], ojos[1]):
        _ojo(p, x, ojos[2], ojos[3], expresion)
    p.restore()


def pixmap(personaje, color, px, expresion=ABIERTOS):
    """QPixmap del personaje a px logicos, nitido a la escala de la pantalla."""
    app = QtGui.QGuiApplication.instance()
    scr = app.primaryScreen() if app is not None else None
    dpr = max(1.0, float(scr.devicePixelRatio())) if scr is not None else 2.0
    pm = QtGui.QPixmap(max(1, round(px * dpr)), max(1, round(px * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    pintar(p, QtCore.QRectF(0, 0, px, px), personaje, color, expresion)
    p.end()
    return pm


def de_agente(agente):
    """(personaje, color) validos de un agente."""
    personaje = agente.get("personaje")
    color = agente.get("color")
    return (personaje if personaje in PERSONAJES else PERSONAJE_POR_DEFECTO,
            color if color in HEX else COLOR_POR_DEFECTO)


class Avatar(QtWidgets.QWidget):
    """El personaje como widget. Con 'vivo' respira, parpadea y reacciona a su
    estado (set_estado) y al nivel de audio (set_nivel); sin 'vivo' es una
    imagen fija con la expresion de set_expresion."""
    clicked = QtCore.Signal()
    _FPS_MS = 33               # ~30 fotogramas por segundo mientras se ve

    def __init__(self, personaje, color, lado=64, vivo=False, alegre_al_pasar=False):
        super().__init__()
        self.personaje, self.color = personaje, color
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
    def set_personaje(self, personaje, color):
        self.personaje, self.color = personaje, color
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
               self.personaje, self.color, **self.pose())
        p.end()

    def enterEvent(self, e):
        if self.alegre_al_pasar:
            self.set_estado(CONTENTO)
        super().enterEvent(e)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
