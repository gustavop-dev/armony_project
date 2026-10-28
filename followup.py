"""Arbitro de anadidos: decide que hacer cuando alguien sigue hablando despues
de haber hecho una pregunta.

El caso tipico: preguntan, el tester dice "vale", y al rato llega "ah, pero ten
en cuenta que...". Antes cada trozo era una pregunta nueva y salian tres
respuestas; ahora se trabaja SIEMPRE sobre la primera: el anadido la revisa o se
descarta. Solo una pregunta de verdad distinta abre otra respuesta.

Jev (TypeSafe) da los juicios -- que es el anadido, si cambia la respuesta, si
reacciona a lo que dijo el tester -- y la regla que decide es codigo fijo sobre
esas probabilidades. Las instrucciones van en ingles (el idioma fuerte de Jev);
la transcripcion va tal cual, en el idioma de la reunion.
"""
from dataclasses import dataclass

from typesafe_sdk import Choice, Noul

# Que hacer con la respuesta ya en marcha.
MANTENER = "keep"         # el anadido no la cambia: queda como contexto
REVISAR = "revise"        # reescribir la misma respuesta con el anadido
NUEVA = "new"             # pregunta distinta: otra respuesta
RETIRAR = "withdraw"      # retiraron la pregunta: la respuesta sobra

RELACIONES = {
    "filler_or_ack": (
        "Filler, backchannel or acknowledgement with no new content, e.g. "
        "'vale', 'ajá', 'claro', 'perfecto', 'genial, gracias', or telling the "
        "interviewee to take their time."),
    "extends_question": (
        "Adds a requirement, constraint, detail, scale, example or clarification "
        "to the SAME question, so what is being asked becomes more specific or "
        "larger."),
    "relaxes_or_answers": (
        "Loosens or removes a constraint of the SAME question, gives permission "
        "('no te preocupes, puedes usar X'), lowers the bar, or partly answers "
        "it themselves."),
    "new_question": (
        "Asks a DIFFERENT question, including a follow-up question about what "
        "the interviewee just answered ('¿y por qué no X?', '¿y si se cae?') or "
        "an explicit change of topic."),
    "withdraws_question": (
        "Withdraws or postpones the question so it no longer needs an answer "
        "('olvídalo', 'eso lo vemos luego', 'esa pregunta no aplica')."),
    "unrelated": (
        "Not about the question at all: audio or camera problems, logistics, "
        "small talk, talking to someone else."),
}


def construir_estado(pregunta, respuesta, dijo_tester, anadido):
    """Estado que ve Jev, con campos con nombre para citarlos en las preguntas."""
    return {
        "interviewer_question": pregunta,
        "suggested_answer": respuesta or "(still being generated)",
        "interviewee_said_since": list(dijo_tester) or ["(nothing)"],
        "follow_up": anadido,
    }


def preguntas():
    """Las tres preguntas van en UNA peticion: se evaluan en paralelo."""
    return {
        "relation": Choice(
            instructions=(
                "In a live technical interview, the interviewer asked "
                "`interviewer_question`. Then the interviewer said `follow_up`. "
                "`interviewee_said_since` is what the interviewee said in "
                "between. How does `follow_up` relate to `interviewer_question`?"),
            criteria=RELACIONES,
        ),
        "changes_answer": Noul(instructions=(
            "`suggested_answer` was prepared for `interviewer_question` before "
            "the interviewer said `follow_up`. Taking `follow_up` into account, "
            "should `suggested_answer` be rewritten because it is now wrong, "
            "incomplete, over-engineered, or no longer the best answer? Answer "
            "no if a good answer would keep essentially the same content.")),
        "reacts_to_interviewee": Noul(instructions=(
            "Is `follow_up` a reaction to something in `interviewee_said_since`, "
            "rather than a continuation of the interviewer's own question?")),
    }


@dataclass
class Juicio:
    relacion: str
    confianza: float
    probabilidades: dict
    cambia: float             # P(hay que reescribir la respuesta)
    reacciona_tester: float
    ms: float = 0.0           # latencia de la llamada


def juzgar(cliente, pregunta, respuesta, dijo_tester, anadido, clock=None):
    """Una llamada a Jev. ``cliente`` es un typesafe_sdk.TypeSafeClient."""
    import time
    clock = clock or time.monotonic
    t0 = clock()
    r = cliente.system_one(
        state=construir_estado(pregunta, respuesta, dijo_tester, anadido),
        questions=preguntas(),
    )
    a = r.answers
    return Juicio(
        relacion=a["relation"].choice,
        confianza=a["relation"].confidence,
        probabilidades=dict(a["relation"].probabilities),
        cambia=a["changes_answer"].noul,
        reacciona_tester=a["reacts_to_interviewee"].noul,
        ms=(clock() - t0) * 1000,
    )


@dataclass
class Umbrales:
    cambio: float = 0.6       # P(cambia) para reescribir
    confianza: float = 0.3    # por debajo, ante la duda no se toca nada


def decidir(juicio, umbrales=Umbrales()):
    """Regla fija. Ante la duda se mantiene: una revision de mas confunde mas
    al tester que un anadido que se queda como contexto."""
    if juicio is None or juicio.confianza < umbrales.confianza:
        return MANTENER
    if juicio.relacion == "new_question":
        return NUEVA
    if juicio.relacion == "withdraws_question":
        return RETIRAR
    if juicio.relacion in ("extends_question", "relaxes_or_answers") \
            and juicio.cambia >= umbrales.cambio:
        return REVISAR
    return MANTENER
