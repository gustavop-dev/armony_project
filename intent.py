"""Decide si una intervencion pide respuesta o solo esta dando contexto.

En una reunion la gente habla mucho mas de lo que pregunta: cuenta antecedentes,
enumera, divaga. Responder a cada frase llenaria el panel de ruido justo cuando
mas concentrado estas, asi que antes de molestar al modelo se mira si lo que
acaban de decir parece una pregunta o una peticion.

Esta es la PRIMERA de dos puertas. Se equivoca a proposito por exceso: al dejar
pasar de mas, el modelo tiene la ultima palabra y puede callarse. Si en cambio se
quedara corta, la pregunta se perderia en silencio, y eso si se nota. Por eso
ante la duda, pasa.

La red final es el atajo de responder ahora (Alt+5): si la transcripcion perdio
los signos de interrogacion y aqui no se vio la pregunta, se fuerza a mano.
"""
import re
import unicodedata

# Signos de interrogacion (incluida la apertura española) y su version ASCII.
_SIGNOS = ("?", "¿")

# Palabras interrogativas. Se comparan sin tildes, porque la transcripcion no
# siempre las pone y "como" / "cómo" tienen que valer igual.
# Ojo con "porque": va junto y siempre explica ("porque el cliente cambio..."),
# mientras que la pregunta "por que" va separada y ya la detecta el "que". Meter
# "porque" aqui convertia cada explicacion en una falsa pregunta.
_INTERROGATIVAS_ES = {
    "que", "cual", "cuales", "quien", "quienes", "como", "cuando", "donde",
    "adonde", "cuanto", "cuanta", "cuantos", "cuantas",
}
_INTERROGATIVAS_EN = {
    "what", "which", "who", "whom", "whose", "how", "when", "where", "why",
}

# Formulas de peticion: no llevan signos pero piden respuesta igual.
# ("cuentame un poco de ti" no es una pregunta y sin embargo hay que contestar)
_PETICIONES_ES = (
    "cuentame", "cuenteme", "dime", "digame", "explicame", "expliqueme",
    "explica", "hablame", "hableme", "describe", "describeme", "comparte",
    "muestrame", "ensename", "podrias", "podria", "puedes", "puede usted",
    "me gustaria saber", "me gustaria que", "quiero que", "quisiera saber",
    "necesito que", "necesitamos que", "te pido", "te importaria",
    "que opinas", "que piensas", "que te parece", "tu opinion", "tu punto de vista",
    "adelante", "tienes la palabra", "cedo la palabra", "es tu turno",
    "preguntarte", "preguntarle", "consultarte",
)
_PETICIONES_EN = (
    "tell me", "tell us", "explain", "describe", "walk me through", "walk us through",
    "could you", "can you", "would you", "will you", "do you", "did you", "have you",
    "are you", "i'd like to know", "i would like to know", "let us know", "let me know",
    "your thoughts", "your opinion", "go ahead", "your turn", "share with",
)


# Words that may stand before an interrogative that opens a clause or a question
# ("y cuando entregamos", "a que hora", "por que no", "so what's next"). Any other
# word before it means mid-sentence use ("no se que hacer", "lo que sea").
_ANTE_INTERROGATIVA = {
    "y", "e", "o", "pero", "entonces", "pues", "bueno", "vale", "oye",
    "ahora", "luego", "despues", "ya", "tambien", "now", "also", "just",
    "a", "de", "en", "con", "por", "para", "desde", "hasta",
    "and", "or", "but", "so", "then", "ok", "okay", "well", "hey",
    "to", "from", "with", "for", "in", "on", "at",
}
# Enclitic pronouns allowed after a request verb: "dimelo", "explicamelo".
_ENCLITICOS = r"(?:me|te|se|lo|la|le|nos|los|las|les)*"


def _patron_peticiones(peticiones):
    """Request phrases as whole words (so "dime" does not match "dimensiones")."""
    return re.compile(r"(?<![a-z0-9'])(?:" + "|".join(map(re.escape, peticiones))
                      + r")" + _ENCLITICOS + r"(?![a-z0-9])")


_PATRONES = {
    "es": _patron_peticiones(_PETICIONES_ES),
    "en": _patron_peticiones(_PETICIONES_EN),
    "auto": _patron_peticiones(_PETICIONES_ES + _PETICIONES_EN),
}


def _normaliza(texto):
    """Minusculas y sin tildes: la transcripcion no siempre acentua igual."""
    t = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def parece_pregunta(texto, idioma="es"):
    """True si la intervencion pide una respuesta.

    idioma: 'es' | 'en' | 'auto'. Con 'auto' se miran los dos vocabularios,
    que es lo correcto en reuniones donde se mezclan idiomas.
    """
    if not texto or not texto.strip():
        return False

    if any(s in texto for s in _SIGNOS):
        return True

    plano = _normaliza(texto)
    # Apostrophes split tokens: "what's" -> "what", "s".
    palabras = re.findall(r"[a-z0-9]+", plano)
    if not palabras:
        return False

    interrogativas = set()
    if idioma in ("es", "auto"):
        interrogativas |= _INTERROGATIVAS_ES
    if idioma in ("en", "auto"):
        interrogativas |= _INTERROGATIVAS_EN
    if idioma not in ("es", "en", "auto"):     # idioma desconocido: no filtrar
        return True

    if _PATRONES[idioma].search(plano):
        return True

    # Una interrogativa suelta a mitad de frase casi nunca es pregunta
    # ("no se que hacer", "lo que sea"), pero al principio de la frase o de una
    # subordinada si suele serlo ("como lo ves", "y cuando entregamos").
    for i, palabra in enumerate(palabras[:4]):
        if palabra in interrogativas and all(p in _ANTE_INTERROGATIVA
                                             for p in palabras[:i]):
            return True
    return False
