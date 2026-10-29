"""Question thread states (hilo.py): when an answer counts as given."""
import pytest

from hilo import (CADUCIDAD_PREGUNTA, PREGUNTADA, RESPONDIDA, RESPONDIENDO,
                  SILENCIO_FIN_RESPUESTA, HiloPregunta, decidir, es_acuse, es_eco)


@pytest.mark.parametrize("texto", ["Vale.", "ok", "Listo", "Sí, claro.", "Mm...",
                                   "Vale, déjame pensar.", "Perfecto, perfecto", ""])
def test_acknowledgements_are_not_answers(texto):
    assert es_acuse(texto)


@pytest.mark.parametrize("texto", ["Usaría una clave de idempotencia en Redis.",
                                   "Pues yo pondría una cola entre la API y los workers",
                                   "Vale, yo usaría PostgreSQL por las transacciones."])
def test_real_answers_are_not_acknowledgements(texto):
    assert not es_acuse(texto)


def test_question_stays_asked_while_tester_only_acknowledges():
    h = HiloPregunta("¿Qué base de datos usarías?", ahora=0)
    h.tester("Vale.", 1)
    h.tester("Déjame pensar.", 2)
    assert h.estado(3) == PREGUNTADA


def test_tester_answering_then_silence_closes_the_question():
    h = HiloPregunta("¿Qué base de datos usarías?", ahora=0)
    h.tester("Yo usaría PostgreSQL porque necesito transacciones.", 5)
    assert h.estado(5 + SILENCIO_FIN_RESPUESTA - 0.1) == RESPONDIENDO
    h.tester("Y además índices por fecha.", 7)
    assert h.estado(7 + SILENCIO_FIN_RESPUESTA - 0.1) == RESPONDIENDO
    assert h.estado(7 + SILENCIO_FIN_RESPUESTA) == RESPONDIDA


def test_interviewer_speaking_after_the_answer_closes_it():
    h = HiloPregunta("¿Qué base de datos usarías?", ahora=0)
    h.tester("Yo usaría PostgreSQL por las transacciones.", 5)
    h.entrevistador("Perfecto.", 6)
    assert h.estado(6) == RESPONDIDA


def test_unanswered_question_expires():
    h = HiloPregunta("¿Qué base de datos usarías?", ahora=0)
    assert h.estado(CADUCIDAD_PREGUNTA - 1) == PREGUNTADA
    assert h.estado(CADUCIDAD_PREGUNTA) == RESPONDIDA


def test_decidir_follow_up_while_reading_is_context():
    h = HiloPregunta("¿Qué arquitectura usarías?", ahora=0)
    h.tester("Vale.", 2)
    # "Ah, pero ten en cuenta que..." even phrased as a question.
    assert decidir(h, es_pregunta=True, ahora=4) == "contexto"


def test_decidir_follow_up_while_answering_is_context():
    h = HiloPregunta("¿Qué arquitectura usarías?", ahora=0)
    h.tester("Yo separaría la toma de pedidos con una cola.", 5)
    assert decidir(h, es_pregunta=True, ahora=6) == "contexto"


def test_decidir_new_question_after_answer_opens_a_new_thread():
    h = HiloPregunta("¿Qué arquitectura usarías?", ahora=0)
    h.tester("Yo separaría la toma de pedidos con una cola.", 5)
    assert decidir(h, es_pregunta=True, ahora=5 + SILENCIO_FIN_RESPUESTA) == "nueva"
    assert decidir(h, es_pregunta=False, ahora=20) == "contexto"


def test_echo_of_the_interviewer_is_detected():
    recientes = [(10.0, "¿Qué harías si llegan dos cobros iguales al mismo tiempo?")]
    assert es_eco("qué harías si llegan dos cobros iguales al mismo tiempo", recientes, 11.0)
    assert es_eco("llegan dos cobros iguales", recientes, 11.0)           # fragment


def test_tester_answer_is_not_echo():
    recientes = [(10.0, "¿Qué harías si llegan dos cobros iguales al mismo tiempo?")]
    assert not es_eco("Usaría una clave de idempotencia con una restricción única",
                      recientes, 12.0)
    assert not es_eco("vale", recientes, 10.5)                            # too short
    assert not es_eco("qué harías si llegan dos cobros iguales al mismo tiempo",
                      recientes, 30.0)                                     # too late


def test_decidir_without_thread():
    assert decidir(None, es_pregunta=True, ahora=0) == "nueva"
    assert decidir(None, es_pregunta=False, ahora=0) == "contexto"
