"""Convierte la respuesta del modelo en bloques que el panel sabe pintar.

El modelo contesta en markdown. Hasta ahora se pegaban todas las lineas con
espacios, lo que daba igual para una explicacion hablada pero destrozaba
cualquier codigo: sin saltos de linea ni indentacion no se entiende nada.

Aqui se distinguen tres cosas dentro de cada seccion '## Etiqueta':

    (TEXT, "parrafo")            texto corrido, con negritas y `codigo` en linea
    (CODE, "python", "…")        bloque cercado con ``` — se respeta tal cual
    (BULLETS, ["uno", "dos"])    lista

Se parsea en cada trozo que llega del streaming, asi que tiene que aguantar un
bloque de codigo a medias: si la valla no se ha cerrado todavia, se pinta lo que
haya llegado en vez de esperar (y de tragarselo si nunca cierra).
"""
import html
import re

TEXT, CODE, BULLETS = "text", "code", "bullets"

ETIQUETA_POR_DEFECTO = "Answer"

# ``` o ~~~, con lenguaje opcional detras
_VALLA = re.compile(r"^\s*(?:```+|~~~+)\s*([A-Za-z0-9_+#.\-]*)\s*$")
# '## Etiqueta' (y '###', que el modelo cuela a veces)
_ENCABEZADO = re.compile(r"^\s*#{2,}\s+(.+?)\s*#*\s*$")
# '- item', '* item', '1. item', '2) item'
_VINETA = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$")


def parse_answer(raw):
    """Devuelve [(etiqueta, [bloques])] listo para pintar."""
    secciones, bloques = [], []
    etiqueta = None
    parrafo, vinetas, codigo = [], [], None

    def cerrar_parrafo():
        if parrafo:
            bloques.append((TEXT, " ".join(parrafo).strip()))
            parrafo.clear()

    def cerrar_vinetas():
        if vinetas:
            bloques.append((BULLETS, list(vinetas)))
            vinetas.clear()

    def cerrar_seccion():
        nonlocal etiqueta
        cerrar_parrafo()
        cerrar_vinetas()
        if bloques:
            secciones.append((etiqueta or ETIQUETA_POR_DEFECTO, list(bloques)))
        bloques.clear()

    for linea in raw.splitlines():
        # Dentro de un bloque de codigo no se interpreta nada: ni '#' ni '-'.
        if codigo is not None:
            if _VALLA.match(linea):
                bloques.append((CODE, codigo["lang"], "\n".join(codigo["lineas"])))
                codigo = None
            else:
                codigo["lineas"].append(linea)
            continue

        valla = _VALLA.match(linea)
        if valla:
            cerrar_parrafo()
            cerrar_vinetas()
            codigo = {"lang": (valla.group(1) or "").lower(), "lineas": []}
            continue

        cabecera = _ENCABEZADO.match(linea)
        if cabecera:
            cerrar_seccion()
            etiqueta = cabecera.group(1)
            continue

        vineta = _VINETA.match(linea)
        if vineta:
            cerrar_parrafo()
            vinetas.append(vineta.group(1).strip())
            continue

        if not linea.strip():
            cerrar_parrafo()
            cerrar_vinetas()
            continue

        cerrar_vinetas()
        parrafo.append(linea.strip())

    if codigo is not None:
        # Valla sin cerrar: es lo normal mientras el codigo va llegando.
        bloques.append((CODE, codigo["lang"], "\n".join(codigo["lineas"])))
    cerrar_seccion()
    return secciones


def solo_texto(secciones):
    """Version plana de las secciones (compatibilidad con lo anterior)."""
    salida = []
    for etiqueta, bloques in secciones:
        trozos = []
        for bloque in bloques:
            if bloque[0] == TEXT:
                trozos.append(bloque[1])
            elif bloque[0] == BULLETS:
                trozos.extend(bloque[1])
            else:
                trozos.append(bloque[2])
        texto = " ".join(t for t in trozos if t).strip()
        if texto:
            salida.append((etiqueta, texto))
    return salida


def inline_html(texto, code_style=""):
    """Negritas, cursivas y `codigo` en linea, ya escapado para QLabel.

    El codigo en linea va primero: si no, un ** dentro de `a ** b` se
    interpretaria como negrita y se comeria los asteriscos del codigo.
    """
    t = html.escape(texto)
    t = re.sub(r"`([^`\n]+)`",
               lambda m: f'<span style="{code_style}">{m.group(1)}</span>', t)
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\*\w])\*([^*\n]+)\*(?![\*\w])", r"<i>\1</i>", t)
    return t
