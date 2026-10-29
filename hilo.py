"""Estado de la pregunta en curso: cuando una respuesta ya esta "contestada".

En una entrevista el patron es: preguntan, el tester lee la sugerencia y
contesta en voz alta, y al rato el entrevistador anade algo ("ah, pero...",
"vale, ¿y si...?"). Antes cada trozo era una pregunta nueva y salian varias
respuestas, cada una empujando a la anterior mientras el tester la leia.

Ahora hay un hilo por pregunta, y lo que diga el entrevistador despues se
juzga segun en que punto esta ese hilo:

    preguntada   -> hay sugerencia en pantalla y el tester la esta leyendo
    respondiendo -> el tester esta contestando en voz alta (se oye por su micro)
    respondida   -> el tester termino: la pregunta esta saldada

Mientras esta preguntada o respondiendo, lo que anada el entrevistador es
contexto y no genera nada en pantalla. Una vez respondida, una pregunta de
verdad abre otro hilo (ya hay que contestar otra cosa). La decision fina de
que es cada anadido la tomara Jev (followup.py); esto es la base que decide
cuando no hay que molestar al tester.

Sin Qt y sin reloj propio: el tiempo entra como argumento, asi se prueba solo.
"""
import re
import unicodedata

PREGUNTADA = "preguntada"
RESPONDIENDO = "respondiendo"
RESPONDIDA = "respondida"

# Lo que dice el tester sin estar contestando todavia: confirmar que oyo,
# ganar tiempo. Con esto solo, la pregunta sigue abierta.
_ACUSES = {
    "vale", "ok", "okay", "listo", "si", "claro", "perfecto", "genial", "bien",
    "aja", "mm", "mmm", "eh", "este", "bueno", "entiendo", "entendido", "ya",
    "vale vale", "de acuerdo", "a ver", "dejame pensar", "un segundo",
    "un momento", "yeah", "yes", "sure", "right", "got it", "let me think",
}
MIN_PALABRAS_RESPUESTA = 4

# Cuanto silencio del tester, despues de contestar, cierra la pregunta.
SILENCIO_FIN_RESPUESTA = 2.5      # s
# Si el tester nunca contesta en voz alta (lee en silencio, se le corta el
# micro...), la pregunta no puede quedarse abierta para siempre bloqueando la
# siguiente.
CADUCIDAD_PREGUNTA = 45.0         # s


def _normal(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def es_acuse(texto):
    """True si el tester solo confirma o gana tiempo, sin contestar aun."""
    t = _normal(texto)
    if not t or t in _ACUSES:
        return True
    palabras = t.split()
    # Primero se quitan las frases hechas enteras ("dejame pensar"), luego las
    # palabras sueltas; lo que queda es lo que de verdad dijo.
    resto = f" {t} "
    for frase in sorted((a for a in _ACUSES if " " in a), key=len, reverse=True):
        resto = resto.replace(f" {frase} ", " ")
    resto = [p for p in resto.split() if p not in _ACUSES]
    if not resto:
        return True
    return len(palabras) < MIN_PALABRAS_RESPUESTA and len(resto) <= 1


class HiloPregunta:
    """Una pregunta del entrevistador y lo que paso despues."""

    def __init__(self, pregunta, ahora):
        self.partes = [pregunta]          # la pregunta y sus anadidos
        self.abierto_en = ahora
        self.dijo_tester = []             # todo lo que dijo el tester desde entonces
        self.respuesta = ""               # la sugerencia que se le dio (para Jev)
        self.revisiones = 0               # se reescribe como mucho una vez
        self._empezo_a_responder = None
        self._ultimo_tester = None
        self._interrumpio_entrevistador = False

    # -- eventos ---------------------------------------------------------------
    def tester(self, texto, ahora):
        """Final del micro del tester."""
        self.dijo_tester.append(texto)
        if not es_acuse(texto) and self._empezo_a_responder is None:
            self._empezo_a_responder = ahora
        if self._empezo_a_responder is not None:
            self._ultimo_tester = ahora

    def entrevistador(self, texto, ahora):
        """Final del entrevistador mientras este hilo esta abierto."""
        if self._empezo_a_responder is not None:
            # Habla el entrevistador despues de que el tester contesto: lo que
            # sea que diga, la respuesta ya se dio.
            self._interrumpio_entrevistador = True
        self.partes.append(texto)

    # -- estado ----------------------------------------------------------------
    def estado(self, ahora):
        if self._empezo_a_responder is None:
            if ahora - self.abierto_en >= CADUCIDAD_PREGUNTA:
                return RESPONDIDA
            return PREGUNTADA
        if self._interrumpio_entrevistador:
            return RESPONDIDA
        if ahora - self._ultimo_tester >= SILENCIO_FIN_RESPUESTA:
            return RESPONDIDA
        return RESPONDIENDO


def es_eco(texto_micro, recientes, ahora, ventana=4.0, umbral=0.75):
    """True si lo que oyo el micro es el entrevistador saliendo por los altavoces.

    recientes: [(instante, texto)] de lo ultimo que dijo el entrevistador. Con
    auriculares no pasa; con altavoces el micro repite casi palabra por palabra
    lo que acaba de decir el otro, y eso no es el tester contestando.
    """
    from difflib import SequenceMatcher
    m = _normal(texto_micro)
    if len(m.split()) < 3:
        return False                  # "vale", "si": iguales por casualidad
    for t, texto in recientes:
        if ahora - t > ventana:
            continue
        otro = _normal(texto)
        if m in otro or SequenceMatcher(None, m, otro).ratio() >= umbral:
            return True
    return False


def decidir(hilo, es_pregunta, ahora):
    """Que hacer con un final del entrevistador.

    Devuelve "nueva" (abrir hilo y responder) o "contexto" (guardar sin tocar
    la pantalla). Se decide con el estado de ANTES de anotar el final: la
    misma frase no puede cerrar la pregunta y a la vez juzgarse con ella.
    """
    if hilo is None:
        return "nueva" if es_pregunta else "contexto"
    if hilo.estado(ahora) == RESPONDIDA and es_pregunta:
        return "nueva"
    return "contexto"
