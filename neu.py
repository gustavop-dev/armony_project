"""Neumorfismo ("soft UI") para la ventana de configuracion.

Todo es del mismo material que el fondo; las piezas se separan por luz, no por
color ni por bordes:

  - en relieve: brillo blanco arriba a la izquierda y sombra azulada abajo a la
    derecha, como si salieran del fondo.
  - hundidas: las mismas dos luces por dentro (campos de texto, pistas, la
    opcion elegida).

Qt no tiene box-shadow ni sombras interiores, asi que se pintan aqui: cada forma
se renderiza una vez con desenfoque (QGraphicsBlurEffect) y se guarda en cache
por tamano, radio y modo. Un acento unico, pervinca, marca lo importante.
"""
import math

from PySide6 import QtCore, QtGui, QtWidgets

# --- tokens ------------------------------------------------------------------
BG = "#E6EBF5"            # el material: fondo y superficies
BG_HUNDIDO = "#E1E7F2"    # dentro de lo hundido, un punto mas oscuro
LUZ = QtGui.QColor(255, 255, 255, 235)
SOMBRA = QtGui.QColor(160, 174, 204, 150)
TEXTO = "#3B4563"
TITULO = "#2B3350"
APAGADO = "#8691AB"
TENUE = "#A7B0C6"
ACENTO = "#5B7CFA"
ACENTO_LT = "#8EA6FF"
PELIGRO = "#E0607A"
OK = "#3DBE8B"
AVISO = "#E9A23B"

SANS = "'Segoe UI Variable Text', 'Segoe UI', sans-serif"


def acento_degradado(rect):
    g = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0.0, QtGui.QColor(ACENTO_LT))
    g.setColorAt(1.0, QtGui.QColor(ACENTO))
    return g


# --- render de sombras con cache --------------------------------------------
_cache = {}


def _dpr():
    app = QtGui.QGuiApplication.instance()
    scr = app.primaryScreen() if app is not None else None
    return max(1.0, float(scr.devicePixelRatio())) if scr is not None else 1.0


def _desenfocar(img, radio):
    """Desenfoque gaussiano de una imagen (via QGraphicsBlurEffect)."""
    escena = QtWidgets.QGraphicsScene()
    item = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap.fromImage(img))
    efecto = QtWidgets.QGraphicsBlurEffect()
    efecto.setBlurRadius(radio)
    efecto.setBlurHints(QtWidgets.QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(efecto)
    escena.addItem(item)
    out = QtGui.QImage(img.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
    out.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(out)
    origen = QtCore.QRectF(0, 0, img.width(), img.height())
    escena.render(p, origen, origen)
    p.end()
    return out


def margen_relieve(prof):
    """Hueco que necesita una sombra en relieve para no cortarse: el
    desplazamiento mas el desenfoque."""
    return math.ceil(prof * 3)


def _forma(rect, radio):
    camino = QtGui.QPainterPath()
    camino.addRoundedRect(rect, radio, radio)
    return camino


def superficie(w, h, margen, radio, modo, prof, relleno=None):
    """QPixmap (con su devicePixelRatio) de una superficie neumorfica de w x h.

    El cuerpo ocupa el rectangulo menos 'margen' por cada lado; el margen es el
    hueco donde caen las sombras en relieve. modo: 'relieve' | 'hundido' | 'plano'.
    relleno: color del cuerpo, "acento" (degradado pervinca) o None (el material).
    """
    dpr = _dpr()
    clave = (w, h, margen, radio, modo, prof, dpr, relleno)
    if clave in _cache:
        return _cache[clave]
    W, H = max(1, round(w * dpr)), max(1, round(h * dpr))
    cuerpo = QtCore.QRectF(margen, margen, w - 2 * margen, h - 2 * margen)
    forma = _forma(cuerpo, radio)
    if relleno == "acento":
        fondo = QtGui.QBrush(acento_degradado(cuerpo))
    elif relleno:
        fondo = QtGui.QBrush(QtGui.QColor(relleno))
    else:
        fondo = QtGui.QBrush(QtGui.QColor(BG_HUNDIDO if modo == "hundido" else BG))

    def capa(pintar):
        img = QtGui.QImage(W, H, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(dpr, dpr)
        pintar(p)
        p.end()
        return img

    final = QtGui.QImage(W, H, QtGui.QImage.Format_ARGB32_Premultiplied)
    final.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(final)
    p.setRenderHint(QtGui.QPainter.Antialiasing)

    if modo == "relieve":
        for color, dx in ((SOMBRA, prof), (LUZ, -prof)):
            def pintar(q, color=color, dx=dx):
                q.setPen(QtCore.Qt.NoPen)
                q.setBrush(color)
                q.drawPath(forma.translated(dx, dx))
            p.drawImage(0, 0, _desenfocar(capa(pintar), prof * 1.9 * dpr))
        p.scale(dpr, dpr)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fondo)
        p.drawPath(forma)
    elif modo == "hundido":
        p.save()
        p.scale(dpr, dpr)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fondo)
        p.drawPath(forma)
        p.restore()
        # Marco alrededor del cuerpo, desplazado y desenfocado: dentro se ve
        # como la sombra que cae desde el borde.
        marco = QtGui.QPainterPath()
        marco.addRect(QtCore.QRectF(-3 * prof, -3 * prof, w + 6 * prof, h + 6 * prof))
        marco = marco.subtracted(forma)
        for color, dx in ((SOMBRA, prof * 0.6), (LUZ, -prof * 0.6)):
            def pintar(q, color=color, dx=dx):
                q.setPen(QtCore.Qt.NoPen)
                q.setBrush(color)
                q.drawPath(marco.translated(dx, dx))
            sombra = _desenfocar(capa(pintar), prof * 1.6 * dpr)
            p.save()
            p.scale(dpr, dpr)
            p.setClipPath(forma)
            p.scale(1 / dpr, 1 / dpr)
            p.drawImage(0, 0, sombra)
            p.restore()
    else:
        p.scale(dpr, dpr)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fondo)
        p.drawPath(forma)
    p.end()
    pm = QtGui.QPixmap.fromImage(final)
    pm.setDevicePixelRatio(dpr)
    _cache[clave] = pm
    return pm


# --- widgets -------------------------------------------------------------------
class Surface(QtWidgets.QWidget):
    """Contenedor neumorfico. Su layout queda dentro del cuerpo: el margen de
    las sombras va en los contentsMargins del propio widget."""

    def __init__(self, modo="relieve", radio=18, prof=6, margen=None, relleno=None):
        super().__init__()
        self.modo, self.radio, self.prof = modo, radio, prof
        self.margen = (margen_relieve(prof) if modo == "relieve" else 2) if margen is None else margen
        self.relleno = relleno
        self.setContentsMargins(self.margen, self.margen, self.margen, self.margen)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)

    def set_modo(self, modo):
        if modo != self.modo:
            self.modo = modo
            self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, superficie(self.width(), self.height(), self.margen,
                                      self.radio, self.modo, self.prof, self.relleno))
        p.end()


class Button(QtWidgets.QPushButton):
    """Boton en relieve que se hunde al pulsarlo (o mientras esta marcado).

    variante: 'normal' | 'acento' (degradado pervinca, texto blanco) | 'plano'
    (sin sombra hasta que se marca: opciones de un segmentado). redondo: circulo
    del tamano dado, para iconos.
    """

    def __init__(self, texto="", icono=None, variante="normal", redondo=None,
                 radio=12, prof=4, color_icono=None):
        super().__init__(texto)
        self.variante, self.redondo, self.radio, self.prof = variante, redondo, radio, prof
        self._icono_nombre = icono
        self._color_icono = color_icono
        self.margen = margen_relieve(prof)
        f = self.font(); f.setPixelSize(13)
        f.setWeight(QtGui.QFont.DemiBold if variante == "acento" else QtGui.QFont.Medium)
        self.setFont(f)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        if redondo:
            lado = redondo + 2 * self.margen
            self.setFixedSize(lado, lado)

    def set_icono(self, nombre, color=None):
        self._icono_nombre, self._color_icono = nombre, color
        self.update()

    def sizeHint(self):
        if self.redondo:
            lado = self.redondo + 2 * self.margen
            return QtCore.QSize(lado, lado)
        fm = self.fontMetrics()
        ancho = fm.horizontalAdvance(self.text()) + 36 + 2 * self.margen
        if self._icono_nombre:
            ancho += 22
        return QtCore.QSize(ancho, 38 + 2 * self.margen)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _color_texto(self):
        if not self.isEnabled():
            return TENUE
        if self.variante == "acento":
            return "#FFFFFF"
        if self.variante == "peligro":
            return PELIGRO
        if self.isChecked() or self.isDown():
            return ACENTO
        return TEXTO

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        hundido = self.isDown() or (self.isCheckable() and self.isChecked()
                                    and self.variante != "plano")
        if self.variante == "plano":
            modo = "relieve" if self.isChecked() else None
        else:
            modo = "hundido" if hundido else "relieve"
        if not self.isEnabled() and self.variante != "plano":
            modo = "plano"
        radio = (self.redondo / 2) if self.redondo else self.radio
        if modo:
            relleno = "acento" if self.variante == "acento" and self.isEnabled() else None
            p.drawPixmap(0, 0, superficie(self.width(), self.height(), self.margen,
                                          radio, modo, self.prof, relleno))
        color = QtGui.QColor(self._color_texto())
        cuerpo = QtCore.QRect(self.margen, self.margen, self.width() - 2 * self.margen,
                              self.height() - 2 * self.margen)
        texto = self.text()
        icono = None
        if self._icono_nombre:
            import icons
            col_ic = self._color_icono if (self._color_icono and self.isEnabled()) else color.name()
            icono = icons.pixmap(self._icono_nombre, col_ic, 16)
        fm = self.fontMetrics()
        ancho = (fm.horizontalAdvance(texto) if texto else 0) + (16 if icono else 0) + (
            8 if icono and texto else 0)
        x = cuerpo.x() + (cuerpo.width() - ancho) / 2
        if icono:
            p.drawPixmap(QtCore.QPointF(x, cuerpo.center().y() - 7.5), icono)
            x += 24 if texto else 16
        if texto:
            p.setPen(color)
            p.setFont(self.font())
            p.drawText(QtCore.QRectF(x, cuerpo.y(), cuerpo.width(), cuerpo.height()),
                       QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, texto)
        p.end()


class Toggle(QtWidgets.QAbstractButton):
    """Interruptor: pista hundida y perilla en relieve; encendido, pista pervinca."""

    def __init__(self, checked=False, small=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self._w, self._h = (40, 22) if small else (48, 26)
        self._m = 4
        self.setFixedSize(self._w + 2 * self._m, self._h + 2 * self._m)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        m, w, h = self._m, self._w, self._h
        pista = QtCore.QRectF(m, m, w, h)
        if self.isChecked():
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QBrush(acento_degradado(pista)))
            p.drawRoundedRect(pista, h / 2, h / 2)
        else:
            p.drawPixmap(0, 0, superficie(self.width(), self.height(), m, h / 2,
                                          "hundido", 3))
        k = h - 6
        x = (m + w - k - 3) if self.isChecked() else (m + 3)
        perilla = QtCore.QRectF(x, m + 3, k, k)
        # sombra suave de la perilla
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(120, 135, 170, 60))
        p.drawEllipse(perilla.translated(1, 1.5))
        p.setBrush(QtGui.QColor("#FFFFFF" if self.isChecked() else "#F4F7FC"))
        p.drawEllipse(perilla)
        p.end()


def qss_campo(mono=False):
    """Campos de texto y combos: fondo transparente, van dentro de un Surface hundido."""
    fam = "'Cascadia Mono', 'Consolas', monospace" if mono else SANS
    return (f"QLineEdit, QPlainTextEdit, QComboBox {{ background: transparent; border: none; "
            f"color: {TEXTO}; font-family: {fam}; font-size: 13px; "
            f"selection-background-color: rgba(91,124,250,0.30); selection-color: {TITULO}; }}"
            f"QPlainTextEdit {{ padding: 6px 4px; }}"
            f"QLineEdit {{ padding: 8px 6px; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 8px; margin: 6px 2px; }}"
            f"QScrollBar::handle:vertical {{ background: rgba(91,124,250,0.35); "
            f"border-radius: 3px; min-height: 30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: rgba(91,124,250,0.6); }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}")


def campo(widget, ancho=None, radio=12, alto_min=None):
    """Envuelve un campo (QLineEdit, QComboBox, QPlainTextEdit) en una
    superficie hundida. Devuelve el contenedor."""
    caja = Surface("hundido", radio=radio, prof=4, margen=2)
    lay = QtWidgets.QHBoxLayout(caja)
    lay.setContentsMargins(10, 2, 8, 2)
    lay.addWidget(widget)
    if ancho:
        caja.setFixedWidth(ancho)
    if alto_min:
        caja.setMinimumHeight(alto_min)
    return caja
