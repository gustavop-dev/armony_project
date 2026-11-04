"""Convierte la respuesta del modelo en bloques que el panel sabe pintar.

El modelo contesta en markdown. Hasta ahora se pegaban todas las lineas con
espacios, lo que daba igual para una explicacion hablada pero destrozaba
cualquier codigo: sin saltos de linea ni indentacion no se entiende nada.

Dentro de cada seccion ('# Etiqueta' o '## Etiqueta') se distingue, como en
ChatGPT o Claude:

    (TEXT, "parrafo")                 texto corrido, con negritas y `codigo`
    (CODE, "python", "…")             bloque cercado con ``` — se respeta tal cual
    (LIST, [(nivel, "1.", "texto")])  lista, numerada o no ("•"), con sublistas
    (SUBHEAD, "titulo")               '### Subtitulo' dentro de la seccion
    (TABLE, [cabecera], [[fila]])     tabla '| a | b |'
    (QUOTE, "texto")                  cita '> ...'
    (RULE,)                           separador '---'

Se parsea en cada trozo que llega del streaming, asi que tiene que aguantar un
bloque de codigo a medias: si la valla no se ha cerrado todavia, se pinta lo que
haya llegado en vez de esperar (y de tragarselo si nunca cierra).
"""
import html
import re

TEXT, CODE, LIST = "text", "code", "list"
SUBHEAD, TABLE, QUOTE, RULE = "subhead", "table", "quote", "rule"

ETIQUETA_POR_DEFECTO = "Answer"

# ``` o ~~~ (tres o mas), con lenguaje opcional detras. Se cierra con la misma
# marca y al menos tan larga, como en CommonMark: asi un prompt cercado con
# cuatro acentos puede llevar dentro codigo con tres sin que se corte.
_VALLA = re.compile(r"^\s*(`{3,}|~{3,})\s*([A-Za-z0-9_+#.\-]*)\s*$")
# '# Etiqueta' y '## Etiqueta': secciones. '### Algo': subtitulo dentro.
_ENCABEZADO = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")
# '- item', '* item', '+ item', '1. item', '2) item', con su sangria
_VINETA = re.compile(r"^(\s*)([-*+•]|\d+[.)])\s+(.*)$")
_FILA = re.compile(r"^\s*\|.*\|\s*$")
_SEPARADOR_TABLA = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_CITA = re.compile(r"^\s*>\s?(.*)$")
_REGLA = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")


def _celdas(linea):
    return [c.strip() for c in linea.strip().strip("|").split("|")]


def _nivel(sangria):
    return min(3, len(sangria.replace("\t", "    ")) // 2)


def parse_answer(raw):
    """Devuelve [(etiqueta, [bloques])] listo para pintar."""
    secciones, bloques = [], []
    etiqueta = None
    parrafo, lista, tabla, cita = [], [], [], []
    codigo = None

    def cerrar_parrafo():
        if parrafo:
            bloques.append((TEXT, " ".join(parrafo).strip()))
            parrafo.clear()

    def cerrar_lista():
        if lista:
            bloques.append((LIST, list(lista)))
            lista.clear()

    def cerrar_tabla():
        if not tabla:
            return
        if len(tabla) >= 2 and _SEPARADOR_TABLA.match(tabla[1]):
            filas = [_celdas(f) for f in tabla[2:]]
            bloques.append((TABLE, _celdas(tabla[0]), filas))
        else:                               # no era una tabla: texto
            parrafo.extend(f.strip() for f in tabla)
            cerrar_parrafo()
        tabla.clear()

    def cerrar_cita():
        if cita:
            bloques.append((QUOTE, " ".join(c for c in cita if c).strip()))
            cita.clear()

    def cerrar_bloques():
        cerrar_parrafo()
        cerrar_lista()
        cerrar_tabla()
        cerrar_cita()

    def cerrar_seccion():
        cerrar_bloques()
        if bloques:
            secciones.append((etiqueta or ETIQUETA_POR_DEFECTO, list(bloques)))
        bloques.clear()

    for linea in raw.splitlines():
        # Dentro de un bloque de codigo no se interpreta nada: ni '#' ni '-'.
        if codigo is not None:
            valla = _VALLA.match(linea)
            if (valla and not valla.group(2) and valla.group(1)[0] == codigo["marca"]
                    and len(valla.group(1)) >= codigo["largo"]):
                bloques.append((CODE, codigo["lang"], "\n".join(codigo["lineas"])))
                codigo = None
            else:
                codigo["lineas"].append(linea)
            continue

        valla = _VALLA.match(linea)
        if valla:
            cerrar_bloques()
            codigo = {"lang": (valla.group(2) or "").lower(), "lineas": [],
                      "marca": valla.group(1)[0], "largo": len(valla.group(1))}
            continue

        if tabla and not _FILA.match(linea):
            cerrar_tabla()
        if cita and not _CITA.match(linea):
            cerrar_cita()

        cabecera = _ENCABEZADO.match(linea)
        if cabecera:
            if len(cabecera.group(1)) <= 2:
                cerrar_seccion()
                etiqueta = cabecera.group(2)
            else:
                cerrar_bloques()
                bloques.append((SUBHEAD, cabecera.group(2)))
            continue

        if _FILA.match(linea):
            cerrar_parrafo()
            cerrar_lista()
            tabla.append(linea)
            continue

        if _CITA.match(linea):
            cerrar_parrafo()
            cerrar_lista()
            cita.append(_CITA.match(linea).group(1).strip())
            continue

        if _REGLA.match(linea):
            cerrar_bloques()
            bloques.append((RULE,))
            continue

        vineta = _VINETA.match(linea)
        if vineta:
            cerrar_parrafo()
            marca = vineta.group(2)
            marca = marca[:-1] + "." if marca[0].isdigit() else "•"
            lista.append((_nivel(vineta.group(1)), marca, vineta.group(3).strip()))
            continue

        if not linea.strip():
            cerrar_parrafo()
            cerrar_lista()
            continue

        if lista and linea[:1] in (" ", "\t"):
            # Continuacion sangrada del ultimo punto de la lista.
            nivel, marca, texto = lista[-1]
            lista[-1] = (nivel, marca, f"{texto} {linea.strip()}")
            continue

        cerrar_lista()
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
            elif bloque[0] == LIST:
                trozos.extend(t for _n, _m, t in bloque[1])
            elif bloque[0] in (SUBHEAD, QUOTE):
                trozos.append(bloque[1])
            elif bloque[0] == TABLE:
                trozos.extend(" ".join(f) for f in [bloque[1]] + bloque[2])
            elif bloque[0] == CODE:
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


# --- prompts y markdown dentro de un bloque ------------------------------------
# Un prompt para pegar va en un bloque de codigo (```markdown): se ve tal cual,
# con sus '#' y sus '-', pero coloreado como hacen ChatGPT o Claude: titulos,
# listas, negritas y codigo se distinguen de un vistazo. Y se parte por el ancho
# del panel en vez de obligar a desplazarse en horizontal.
LENGUAJES_PROSA = {"markdown", "md", "prompt", "text", "txt", "plaintext", "plain"}

COLORES_MD = {
    "h1": "#c3ceff",        # '# Titulo'
    "h": "#93a8ff",         # '## ...' y siguientes
    "marca": "#7c95ff",     # '-', '1.', '>'
    "negrita": "#ffffff",
    "codigo": "#89ddf0",    # `codigo` y lo que va dentro de ``` en el prompt
    "cursiva": "#d6dcf0",
    "cita": "#9aa3b8",
    "regla": "#5c6478",
    "texto": "#e6e9f2",
}


def _md_inline(texto):
    t = html.escape(texto)
    codigos = []

    def _guardar(m):
        codigos.append(f'<span style="color:{COLORES_MD["codigo"]};">`{m.group(1)}`</span>')
        return f"\x00{len(codigos) - 1}\x00"

    t = re.sub(r"`([^`\n]+)`", _guardar, t.replace("\x00", ""))
    t = re.sub(r"\*\*([^*\n]+)\*\*",
               rf'<b style="color:{COLORES_MD["negrita"]};">**\1**</b>', t)
    t = re.sub(r"(?<![\*\w])\*([^*\n]+)\*(?![\*\w])",
               rf'<i style="color:{COLORES_MD["cursiva"]};">*\1*</i>', t)
    t = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)",
               rf'<span style="color:{COLORES_MD["codigo"]};">[\1](\2)</span>', t)
    return re.sub(r"\x00(\d+)\x00", lambda m: codigos[int(m.group(1))], t)


def _sangria(linea):
    hueco = len(linea) - len(linea.lstrip(" \t"))
    return "&nbsp;" * len(linea[:hueco].replace("\t", "    ")), linea[hueco:]


def resaltar_markdown(texto):
    """El markdown de un bloque (un prompt) coloreado, sin tocar su texto."""
    salida, valla = [], None
    for linea in texto.split("\n"):
        hueco, resto = _sangria(linea)
        v = _VALLA.match(linea)
        if v and (valla is None or (v.group(1)[0] == valla[0] and len(v.group(1)) >= valla[1])):
            valla = None if valla is not None else (v.group(1)[0], len(v.group(1)))
            salida.append(f'<span style="color:{COLORES_MD["codigo"]};">'
                          f'{hueco}{html.escape(resto)}</span>')
            continue
        if valla is not None:                  # codigo dentro del prompt
            salida.append(f'<span style="color:{COLORES_MD["codigo"]};">'
                          f'{hueco}{html.escape(resto).replace(" ", "&nbsp;")}</span>')
            continue
        h = _ENCABEZADO.match(linea)
        if h:
            color = COLORES_MD["h1"] if len(h.group(1)) == 1 else COLORES_MD["h"]
            salida.append(f'<b style="color:{color};">{hueco}{html.escape(resto)}</b>')
            continue
        l = _VINETA.match(linea)
        if l:
            salida.append(f'{hueco}<b style="color:{COLORES_MD["marca"]};">'
                          f'{html.escape(l.group(2))}</b> {_md_inline(l.group(3))}')
            continue
        c = _CITA.match(linea)
        if c:
            salida.append(f'{hueco}<span style="color:{COLORES_MD["marca"]};">&gt;</span> '
                          f'<i style="color:{COLORES_MD["cita"]};">{_md_inline(c.group(1))}</i>')
            continue
        if _REGLA.match(linea):
            salida.append(f'<span style="color:{COLORES_MD["regla"]};">'
                          f'{html.escape(linea.strip())}</span>')
            continue
        salida.append(f"{hueco}{_md_inline(resto)}")
    while salida and not salida[-1].strip():
        salida.pop()
    return (f'<span style="color:{COLORES_MD["texto"]};">' + "<br>".join(salida)
            + "</span>")


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
