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


# --- coloreado del codigo ---------------------------------------------------
# Paleta propia, a juego con el overlay (fondos calidos y dorados) en vez de los
# azules de los temas habituales, que ahi dentro cantan.
COLORES = {
    "kw":   "#ffc857",      # palabras clave: def, class, for, return
    "kwc":  "#c58af9",      # True, False, None, and, or, not, in
    "def":  "#f7dd7f",      # nombres de funciones que se definen
    "cls":  "#7ee0c6",      # clases, excepciones y modulos importados
    "bi":   "#89ddf0",      # incorporados: len, sum, int, print
    "self": "#f08fb0",      # self y cls, que aparecen en casi todas las lineas
    "dec":  "#ffa96b",      # decoradores: @property
    "str":  "#b3e08a",      # cadenas
    "doc":  "#84a877",      # docstrings: son documentacion, no dato
    "esc":  "#ffd479",      # lo interpolado dentro de una cadena: f"{x}"
    "num":  "#f2a06a",      # numeros
    "com":  "#7f7a6c",      # comentarios: apagados, no compiten con el codigo
    "op":   "#e2d9c2",      # operadores: = + < ->
    "pun":  "#9b9384",      # signos: parentesis, comas, dos puntos
    "txt":  "#efe7d5",      # variables y todo lo demas
}

# En cursiva, como en cualquier editor: lo que no es codigo ejecutable.
CURSIVAS = {"com", "doc", "self"}

# Los numeros de linea: se tienen que ver sin robarle atencion al codigo.
COLOR_NUMERO = "#5c564a"


def _clase(tipo):
    """Traduce el tipo de token de Pygments a uno de nuestros colores.

    El orden importa: se mira de lo mas concreto a lo mas general, porque
    'Literal.String.Doc' tambien contiene 'String'.
    """
    t = str(tipo)
    if "Comment" in t:
        return "com"
    if "String.Doc" in t:
        return "doc"
    if "String.Interpol" in t or "String.Escape" in t or "String.Affix" in t:
        return "esc"
    if "String" in t:
        return "str"
    if "Number" in t:
        return "num"
    if "Name.Decorator" in t:
        return "dec"
    if "Keyword.Constant" in t or "Operator.Word" in t:
        return "kwc"
    if "Keyword" in t:
        return "kw"
    if "Name.Builtin.Pseudo" in t:      # self, cls
        return "self"
    if "Name.Function" in t:
        return "def"
    if "Name.Class" in t or "Name.Exception" in t or "Name.Namespace" in t:
        return "cls"
    if "Name.Builtin" in t:
        return "bi"
    if "Punctuation" in t:
        return "pun"
    if "Operator" in t:
        return "op"
    return "txt"


def resaltar(codigo, lenguaje="", numerar=False):
    """Devuelve el codigo como HTML coloreado, o None si no se puede.

    Sin colores el bloque se lee como un muro de texto, sobre todo cuando cada
    linea lleva su comentario: distinguir de un vistazo comentario de codigo es
    justo lo que hace que sirva.
    """
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_by_name, guess_lexer
    except ImportError:
        return None
    try:
        lexer = get_lexer_by_name(lenguaje) if lenguaje else guess_lexer(codigo)
    except Exception:
        try:
            lexer = guess_lexer(codigo)
        except Exception:
            return None
    try:
        # Se colorea linea a linea. Un token puede abarcar varias (una cadena de
        # tres comillas, por ejemplo), asi que se parte por los saltos.
        lineas = [[]]
        for tipo, valor in lex(codigo, lexer):
            if not valor:
                continue
            clase = _clase(tipo)
            estilo = f"color:{COLORES[clase]};"
            if clase in CURSIVAS:
                estilo += "font-style:italic;"
            for i, trozo in enumerate(valor.split("\n")):
                if i:
                    lineas.append([])
                if trozo:
                    escapado = html.escape(trozo).replace(" ", "&nbsp;")
                    lineas[-1].append(f'<span style="{estilo}">{escapado}</span>')
        while lineas and not lineas[-1]:      # el salto final sobra
            lineas.pop()
        if not lineas:
            return None
        if not numerar:
            return "<br>".join("".join(l) for l in lineas)
        return _con_numeros(lineas)
    except Exception:
        return None


def _con_numeros(lineas):
    """Antepone el numero de linea a cada linea, alineado a la derecha.

    Va como prefijo y no como tabla aunque una tabla alinearia mejor cuando una
    linea se parte por el ancho: medido, la tabla duplica lo que cuesta
    redimensionar el panel (38 -> 81 ms por paso de arrastre), y eso se nota
    todo el rato, mientras que una linea partida se ve de vez en cuando.
    """
    ancho = len(str(len(lineas)))
    salida = []
    for n, partes in enumerate(lineas, 1):
        numero = str(n).rjust(ancho).replace(" ", "&nbsp;")
        salida.append(f'<span style="color:{COLOR_NUMERO};">{numero}'
                      f'&nbsp;&nbsp;&nbsp;</span>{"".join(partes)}')
    return "<br>".join(salida)


def inline_html(texto, code_style=""):
    """Negritas, cursivas y `codigo` en linea, ya escapado para QLabel.

    El codigo en linea va primero: si no, un ** dentro de `a ** b` se
    interpretaria como negrita y se comeria los asteriscos del codigo.
    """
    t = html.escape(texto)
    # Code spans are swapped for \x00<n>\x00 placeholders while emphasis runs,
    # so `__init__` or `a * b * c` are never touched, but **use `x`** still
    # wraps the code span in bold.
    codigos = []

    def _guardar(m):
        codigos.append(f'<span style="{code_style}">{m.group(1)}</span>')
        return f"\x00{len(codigos) - 1}\x00"

    t = re.sub(r"`([^`\n]+)`", _guardar, t.replace("\x00", ""))
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\*\w])\*([^*\n]+)\*(?![\*\w])", r"<i>\1</i>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: codigos[int(m.group(1))], t)
