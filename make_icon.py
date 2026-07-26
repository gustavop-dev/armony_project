"""Genera el icono de la app: 'Ar.' sobre fondo blanco.

Se dibuja con Qt en varios tamaños y se empaquetan en un .ico. Windows elige el
tamaño segun donde lo muestre (16 px en la barra de tareas, 256 en el escritorio),
y un icono dibujado a cada tamaño se ve nitido; uno reescalado, borroso.

    python make_icon.py        -> assets/armony.ico
"""
import os
import struct
import sys

from PySide6 import QtCore, QtGui, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(HERE, "assets", "armony.ico")

TAMANOS = (16, 24, 32, 48, 64, 128, 256)
FONDO = "#ffffff"
TINTA = "#1b1811"      # el gris casi negro del panel
PUNTO = "#f2c94c"      # el dorado de la marca, solo para el punto


def dibujar(px):
    pm = QtGui.QPixmap(px, px)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing)

    # Fondo blanco con esquinas redondeadas (a 16 px casi no se nota, pero a 256
    # evita el cuadrado duro que desentona en el escritorio).
    radio = max(2, round(px * 0.18))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(FONDO))
    p.drawRoundedRect(QtCore.QRectF(0, 0, px, px), radio, radio)

    familia = "Segoe UI"
    f = QtGui.QFont(familia)
    # Letras grandes a proposito: el tamaño que manda es el de 16 px de la barra
    # de tareas, y ahi todo margen de mas se come la legibilidad.
    f.setPixelSize(max(9, round(px * 0.62)))
    f.setWeight(QtGui.QFont.Black)
    f.setLetterSpacing(QtGui.QFont.PercentageSpacing, 96)
    p.setFont(f)

    # 'Ar' y '.' se pintan por separado para que el punto vaya en dorado; se
    # miden juntos para poder centrar el conjunto.
    fm = QtGui.QFontMetrics(f)
    ancho_ar = fm.horizontalAdvance("Ar")
    ancho_punto = fm.horizontalAdvance(".")
    x = (px - (ancho_ar + ancho_punto)) / 2
    y = (px + fm.capHeight()) / 2

    p.setPen(QtGui.QColor(TINTA))
    p.drawText(QtCore.QPointF(x, y), "Ar")
    p.setPen(QtGui.QColor(PUNTO))
    p.drawText(QtCore.QPointF(x + ancho_ar, y), ".")
    p.end()
    return pm


def png_bytes(pm):
    ba = QtCore.QByteArray()
    buf = QtCore.QBuffer(ba)
    buf.open(QtCore.QIODevice.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(ba.data())


def escribir_ico(imagenes, ruta):
    """Empaqueta PNGs en un .ico (el formato admite PNG dentro desde Vista)."""
    n = len(imagenes)
    cabecera = struct.pack("<HHH", 0, 1, n)      # reservado, tipo 1 = icono, cuantos
    entradas, datos = b"", b""
    offset = 6 + 16 * n
    for px, png in imagenes:
        entradas += struct.pack("<BBBBHHII",
                                0 if px >= 256 else px,   # 0 significa 256
                                0 if px >= 256 else px,
                                0, 0, 1, 32, len(png), offset)
        datos += png
        offset += len(png)
    with open(ruta, "wb") as f:
        f.write(cabecera + entradas + datos)


def _tira_de_prueba(imagenes):
    """Todos los tamaños juntos y a escala real, para ver si el chico se lee."""
    tira = QtGui.QPixmap(sum(px + 12 for px, _ in imagenes), 300)
    tira.fill(QtGui.QColor("#3a3a3a"))         # gris: el blanco tiene que recortarse
    p = QtGui.QPainter(tira)
    x = 6
    for px, png in imagenes:
        pm = QtGui.QPixmap()
        pm.loadFromData(png, "PNG")
        p.drawPixmap(x, 20, pm)
        p.setPen(QtGui.QColor("#dddddd"))
        p.drawText(x, 290, f"{px}px")
        x += px + 12
    p.end()
    ruta = os.path.join(HERE, "assets", "armony-tamanos.png")
    tira.save(ruta)
    print(f"vista previa de tamaños: {ruta}")


def main():
    app = QtWidgets.QApplication(sys.argv)     # necesario para dibujar texto
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    imagenes = []
    for px in TAMANOS:
        pm = dibujar(px)
        imagenes.append((px, png_bytes(pm)))
        if px == 256:                          # vista previa suelta, para mirarla
            pm.save(os.path.join(HERE, "assets", "armony-256.png"))
    _tira_de_prueba(imagenes)
    escribir_ico(imagenes, SALIDA)
    print(f"icono escrito: {SALIDA} ({os.path.getsize(SALIDA)} bytes, "
          f"tamaños {', '.join(str(t) for t in TAMANOS)})")


if __name__ == "__main__":
    main()
