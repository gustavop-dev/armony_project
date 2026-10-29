"""Tu tono, sacado de tus chats de WhatsApp.

WhatsApp exporta cada chat como texto (en el movil, "Exportar chat": un .txt en
Android o un .zip con _chat.txt en iPhone). Aqui se lee ese export, se separan
los mensajes por autor y, de los TUYOS, se pide al modelo una guia de tu tono y
tu estilo en markdown: la pestana "Tono" de cada agente.

Privacidad: los mensajes de los demas nunca salen del equipo. De los tuyos se
quitan enlaces, correos y telefonos, se descartan los avisos del sistema y los
adjuntos, y se manda como mucho MAX_CARACTERES (los mas recientes).
"""
import io
import logging
import re
import zipfile
from collections import Counter

log = logging.getLogger("armony.estilo")

# Lo que se le manda al modelo como mucho: ~5K tokens, de sobra para ver como
# escribes, y acotado para el coste y para no mandar mas de lo necesario.
MAX_CARACTERES = 20_000
MIN_MENSAJES = 20            # por debajo no hay de donde sacar un estilo

# Una linea que empieza un mensaje. Android: "29/10/26, 16:18 - Ana: hola"
# (tambien "4:18 p. m." o "PM"); iPhone: "[29/10/26, 16:18:05] Ana: hola".
_FECHA = r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]\.?\s?m\.?)?"
_LINEA = re.compile(
    r"^‎?(?:\[(?P<f1>" + _FECHA + r")\]\s*|(?P<f2>" + _FECHA + r")\s*[-–]\s*)"
    r"(?P<autor>[^:]{1,60}?):\s(?P<texto>.*)$", re.I)
_INICIO = re.compile(r"^‎?\[?" + _FECHA, re.I)

# Adjuntos y avisos que no dicen nada de como escribes.
_RUIDO = re.compile(
    r"^‎?(<?(multimedia omitido|media omitted|archivo adjunto|attached)|"
    r"(imagen|image|video|vídeo|audio|sticker|gif|documento|document|stickers?)\s+(omitid[oa]|omitted)|"
    r"se eliminó este mensaje|this message was deleted|eliminaste este mensaje|"
    r"you deleted this message|null|<se editó este mensaje>|<this message was edited>|"
    r"llamada de (voz|video) perdida|missed (voice|video) call)", re.I)

_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_TELEFONO = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def leer_export(ruta):
    """Texto del chat exportado: un .txt o el .zip de WhatsApp (con su .txt)."""
    if ruta.lower().endswith(".zip"):
        with zipfile.ZipFile(ruta) as z:
            txt = next((n for n in z.namelist() if n.lower().endswith(".txt")), None)
            if txt is None:
                raise ValueError("El .zip no trae el chat (.txt)")
            datos = z.read(txt)
    else:
        with open(ruta, "rb") as f:
            datos = f.read()
    for codificacion in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return datos.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return datos.decode("latin-1")


def parsear(texto):
    """[(autor, mensaje)] en orden. Las lineas sin fecha continuan el mensaje
    anterior (mensajes de varias lineas); los avisos del sistema se descartan."""
    mensajes = []
    for linea in io.StringIO(texto):
        linea = linea.rstrip("\r\n")
        m = _LINEA.match(linea)
        if m:
            mensajes.append([m.group("autor").strip(), m.group("texto")])
        elif _INICIO.match(linea):
            continue                   # aviso del sistema ("Ana se unió...")
        elif mensajes and linea.strip():
            mensajes[-1][1] += "\n" + linea
    return [(a, t.strip()) for a, t in mensajes if t.strip() and not _RUIDO.match(t.strip())]


def autores(mensajes):
    """{autor: cuantos mensajes}, del que mas escribe al que menos."""
    return dict(Counter(a for a, _ in mensajes).most_common())


def limpiar(texto):
    texto = _URL.sub("[enlace]", texto)
    texto = _EMAIL.sub("[correo]", texto)
    return _TELEFONO.sub("[teléfono]", texto)


def muestra(mensajes, autor, max_caracteres=MAX_CARACTERES):
    """Los mensajes de 'autor', limpios, los mas recientes que quepan."""
    suyos = [limpiar(t) for a, t in mensajes if a == autor]
    elegidos, total = [], 0
    for t in reversed(suyos):
        if total + len(t) + 1 > max_caracteres:
            break
        elegidos.append(t)
        total += len(t) + 1
    return list(reversed(elegidos))


PROMPT_TONO = (
    "Vas a describir el tono y el estilo con los que escribe una persona, a partir "
    "de sus propios mensajes de WhatsApp. Esa descripcion la usara un asistente "
    "que le sugiere QUE DECIR EN VOZ ALTA en reuniones y entrevistas de trabajo, "
    "asi que tiene que sonar a ella hablando.\n\n"
    "Escribe en markdown, en el idioma en que escribe la persona, con estas "
    "secciones:\n"
    "## Registro — formal o cercano, tuteo o usted, como saluda y como se despide.\n"
    "## Frases — largo tipico, como encadena las ideas, si va al grano o da rodeos.\n"
    "## Vocabulario — palabras y expresiones que usa mucho, muletillas, regionalismos.\n"
    "## Humor y emocion — si bromea, ironia, entusiasmo, como suaviza o enfatiza.\n"
    "## Como explica — ejemplos, comparaciones, preguntas de vuelta.\n"
    "## Para una reunion — como adaptar este estilo a una conversacion de trabajo "
    "hablada: que conservar (expresiones, ritmo, cercania) y que dejar fuera "
    "(abreviaturas de chat, emojis, groserias, faltas).\n"
    "## Ejemplos — 4 o 5 frases cortas inventadas, en su estilo, que podria decir "
    "en una reunion.\n\n"
    "Reglas: describe el estilo, no el contenido. No copies datos personales, "
    "nombres, lugares ni nada privado de los mensajes; las citas literales, solo "
    "de expresiones sueltas. Se concreto: mejor 'dice «la verdad es que» para "
    "empezar a opinar' que 'usa expresiones coloquiales'.")


def entrada_modelo(mensajes_propios):
    """Lo que se manda al modelo: las instrucciones y los mensajes, uno por linea."""
    cuerpo = "\n".join(f"- {t}" for t in mensajes_propios)
    return [
        {"role": "developer", "content": [{"type": "input_text", "text": PROMPT_TONO}]},
        {"role": "user", "content": [{"type": "input_text",
                                      "text": f"Mis mensajes ({len(mensajes_propios)}):\n{cuerpo}"}]},
    ]


def generar_tono(api_key, model, mensajes_propios, effort="medium"):
    """Guia de tono en markdown (llamada a OpenAI; tarda unos segundos)."""
    import openai
    cliente = openai.OpenAI(api_key=api_key, max_retries=1,
                            timeout=openai.Timeout(120, connect=10))
    respuesta = cliente.responses.create(
        model=model, input=entrada_modelo(mensajes_propios),
        reasoning={"effort": effort}, max_output_tokens=4000)
    texto = (getattr(respuesta, "output_text", "") or "").strip()
    if not texto:
        raise RuntimeError("el modelo no devolvió texto")
    return texto
