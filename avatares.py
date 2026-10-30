"""La mascota de Armony: una figura plana de un color, solo con ojos.

Minimalista a proposito: un circulo, un cuadrado o un triangulo (esquinas
suaves), lisos, sin sombras ni boca, y dos ojos blancos en forma de pildora que
miran hacia la derecha. Cada agente elige su forma y su color. Se dibuja con
QPainter sobre un lienzo de 100x100: nitida a cualquier tamano.

Toda la expresion esta en los ojos: abiertos, cerrados (parpadeo), pensando
(suben y miran mas a la derecha, con tres puntitos) y felices (arcos); al
hablar laten. Avatar la anima segun la reunion:
  reposo     respira y parpadea.
  escuchando bota con la voz del entrevistador (el nivel de audio).
  pensando   mira arriba con tres puntitos: se esta preparando la respuesta.
  hablando   los ojos laten mientras se escribe la sugerencia.
  contento   ojos felices y un saltito al terminarla (dura un momento).
"""
import math
import random
import time

from PySide6 import QtCore, QtGui, QtWidgets

OJO = QtGui.QColor("#FFFFFF")

# (id, nombre, hex): colores planos y vivos.
COLORES = [
    ("negro", "Negro", "#141414"),
    ("turquesa", "Turquesa", "#12B5A5"),
    ("morado", "Morado", "#8B5CF6"),
    ("azul", "Azul", "#2F7BFF"),
    ("naranja", "Naranja", "#FF6A1A"),
    ("ambar", "Ámbar", "#FFAE1A"),
    ("rosa", "Rosa", "#FF3D9A"),
    ("gris", "Gris", "#6B6E76"),
    ("marron", "Marrón", "#9A5B34"),
]
HEX = {cid: h for cid, _, h in COLORES}
COLOR_POR_DEFECTO = "azul"
# Colores de versiones anteriores -> el mas parecido de ahora.
_ANTIGUOS = {"pervinca": "azul", "coral": "naranja", "menta": "turquesa",
             "lavanda": "morado", "cielo": "azul", "grafito": "gris"}

FORMAS = [("circulo", "Círculo"), ("cuadrado", "Cuadrado"), ("triangulo", "Triángulo")]
FORMA_POR_DEFECTO = "circulo"

ABIERTOS, CERRADOS, PENSANDO, FELIZ = "abiertos", "cerrados", "pensando", "feliz"

# Estados del companero (Avatar vivo).
REPOSO, ESCUCHANDO, PENSANDO_E, HABLANDO, CONTENTO = (
    "reposo", "escuchando", "pensando", "hablando", "contento")
DURACION_CONTENTO = 1.6        # s que dura la alegria al terminar una respuesta


def _triangulo():
    """Triangulo con las esquinas redondeadas (apoyado en su base)."""
    puntos = [QtCore.QPointF(50, 10), QtCore.QPointF(92, 86), QtCore.QPointF(8, 86)]
    r = 12.0
    c = QtGui.QPainterPath()
    for i, v in enumerate(puntos):
        antes, despues = puntos[i - 1], puntos[(i + 1) % 3]

        def hacia(a, b, d):
            dx, dy = b.x() - a.x(), b.y() - a.y()
            n = math.hypot(dx, dy)
            return QtCore.QPointF(a.x() + dx / n * d, a.y() + dy / n * d)
        entra, sale = hacia(v, antes, r), hacia(v, despues, r)
        if i == 0:
            c.moveTo(entra)
        else:
            c.lineTo(entra)
        c.quadTo(v, sale)
    c.closeSubpath()
    return c


def _forma(forma):
    c = QtGui.QPainterPath()
    if forma == "cuadrado":
        c.addRoundedRect(QtCore.QRectF(11, 11, 78, 78), 20, 20)
    elif forma == "triangulo":
        c = _triangulo()
    else:
        c.addEllipse(QtCore.QRectF(8, 8, 84, 84))
    return c


# Donde van los ojos en cada forma (x izquierdo, x derecho, y centro, ancho,
# alto): a la derecha del centro y un poco arriba, "mirando" hacia alli.
_OJOS = {
    "circulo": (56, 76, 42, 10.5, 21),
    "cuadrado": (56, 76, 43, 10.5, 21),
    "triangulo": (51, 68, 60, 9, 18),
}


def _ojo(p, x, y, w, h, expresion, latido):
    if expresion == FELIZ:
        # arquitos (∩): finos y separados, que no se junten en una "w"
        p.setPen(QtGui.QPen(OJO, w * 0.5, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.setBrush(QtCore.Qt.NoBrush)
        c = QtGui.QPainterPath()
        c.moveTo(x - w * 0.55, y + h * 0.1)
        c.quadTo(x, y - h * 0.5, x + w * 0.55, y + h * 0.1)
        p.drawPath(c)
        return
    if expresion == CERRADOS:
        h = w * 0.55
    elif expresion == PENSANDO:
        x, y = x + w * 0.35, y - h * 0.28
    h *= latido
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(OJO)
    p.drawRoundedRect(QtCore.QRectF(x - w / 2, y - h / 2, w, h), w / 2, w / 2)


def _puntos(p, fase, color):
    """Tres puntitos de "estoy pensando", arriba a la derecha, de su color."""
    p.setPen(QtCore.Qt.NoPen)
    for i, (x, y, r) in enumerate(((78, 8, 3.4), (87, 4, 3.8), (96, 1, 4.2))):
        a = 0.35 + 0.65 * max(0.0, math.sin((fase - i * 0.18) * math.tau))
        c = QtGui.QColor(color)
        c.setAlpha(int(255 * a))
        p.setBrush(c)
        p.drawEllipse(QtCore.QPointF(x, y), r, r)


def pintar(p, rect, color, forma=FORMA_POR_DEFECTO, expresion=ABIERTOS, latido=1.0,
           escala=1.0, dy=0.0, angulo=0.0, puntos=None):
    """Dibuja la mascota dentro de rect (cuadrado): la forma lisa de su color y
    sus dos ojos. Pose (para animarla): escala y giro alrededor del centro, dy en
    unidades del lienzo (100 = alto entero), latido de los ojos (1 = normal) y
    'puntos' (fase 0..1 de los puntitos de pensar; None, sin puntitos)."""
    color = QtGui.QColor(HEX.get(_ANTIGUOS.get(color, color), color))
    forma = forma if forma in _OJOS else FORMA_POR_DEFECTO
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
    # Los colores oscuros llevan un contorno tenue: si no, sobre el vidrio
    # oscuro del overlay el negro desaparece. Sobre la Home clara no se nota.
    if color.lightness() < 60:
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 46), 2.2))
    else:
        p.setPen(QtCore.Qt.NoPen)
    p.setBrush(color)
    p.drawPath(_forma(forma))
    xi, xd, y, w, h = _OJOS[forma]
    for x in (xi, xd):
        _ojo(p, x, y, w, h, expresion, latido)
    p.restore()


def pixmap(color, px, expresion=ABIERTOS, forma=FORMA_POR_DEFECTO):
    """QPixmap de la mascota a px logicos, nitido a la escala de la pantalla."""
    app = QtGui.QGuiApplication.instance()
    scr = app.primaryScreen() if app is not None else None
    dpr = max(1.0, float(scr.devicePixelRatio())) if scr is not None else 2.0
    pm = QtGui.QPixmap(max(1, round(px * dpr)), max(1, round(px * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    pintar(p, QtCore.QRectF(0, 0, px, px), color, forma, expresion)
    p.end()
    return pm


def de_agente(agente):
    """(forma, color) validos de un agente (los colores antiguos se traducen)."""
    forma = agente.get("forma")
    color = _ANTIGUOS.get(agente.get("color"), agente.get("color"))
    return (forma if forma in _OJOS else FORMA_POR_DEFECTO,
            color if color in HEX else COLOR_POR_DEFECTO)


class Avatar(QtWidgets.QWidget):
    """La mascota como widget. Con 'vivo' respira, parpadea y reacciona a su
    estado (set_estado) y al nivel de audio (set_nivel); sin 'vivo' es una
    imagen fija con la expresion de set_expresion."""
    clicked = QtCore.Signal()
    _FPS_MS = 33               # ~30 fotogramas por segundo mientras se ve

    def __init__(self, color, lado=64, vivo=False, alegre_al_pasar=False, forma=FORMA_POR_DEFECTO):
        super().__init__()
        self.color = color
        self.forma = forma
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
    def set_color(self, color, forma=None):
        self.color = color
        if forma is not None:
            self.forma = forma
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
        pose = dict(expresion=CERRADOS if parpadea else ABIERTOS, latido=1.0,
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
            # Sin boca: "habla" con los ojos, que laten al ritmo de la frase.
            pose.update(latido=0.78 + 0.22 * abs(math.cos(t * 7)),
                        dy=-1.5 * abs(math.sin(t * 7)))
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
               self.color, forma=self.forma, **self.pose())
        p.end()

    def enterEvent(self, e):
        if self.alegre_al_pasar:
            self.set_estado(CONTENTO)
        super().enterEvent(e)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
