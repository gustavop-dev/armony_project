"""Interview scenarios through CoachEngine: how many answers each one triggers.

The engine is driven through the same callbacks the two STT streams call
(interviewer = meeting loopback, tester = mic). No audio, network or LLM: the
answer requests are read from the engine queue, and the clock is fake.
"""
import pytest

import hilo
from engine import CoachEngine


class Session:
    def __init__(self):
        self.now = 0.0
        e = CoachEngine()
        e._running = True
        e._test_mode = False
        e._language = "es"
        e._turn_gap = 0.01
        e._clock = lambda: self.now
        self.engine = e
        self.no_answer = []
        e.noAnswer.connect(self.no_answer.append)

    def at(self, t):
        self.now = t
        return self

    def interviewer(self, text):
        self.engine._on_stt_final(text, 0)
        if self.engine._turn_parts:          # non-question turns close on a timer
            self.engine._flush_turn()
        return self

    def tester(self, text):
        self.engine._on_mic_final(text)
        return self

    def answers(self):
        items = []
        q = self.engine._queue
        while not q.empty():
            items.append(q.get_nowait())
        return [i["text"] for i in items if i["type"] == "respond"]


@pytest.fixture
def s():
    return Session()


def test_follow_up_while_tester_reads_does_not_open_a_second_answer(s):
    s.at(0).interviewer("¿Qué arquitectura usarías para los pedidos de Black Friday?")
    s.at(2).tester("Vale.")
    s.at(4).interviewer("Ah, pero ¿y si todo tiene que correr en AWS?")
    s.at(6).tester("Pues separaría la toma de pedidos con una cola en SQS.")
    s.at(12).interviewer("Perfecto.")
    assert s.answers() == ["¿Qué arquitectura usarías para los pedidos de Black Friday?"]
    assert "follow_up" in s.no_answer


def test_follow_up_while_tester_answers_is_context(s):
    s.at(0).interviewer("¿Qué base de datos usarías para el historial de pagos?")
    s.at(3).tester("Yo usaría PostgreSQL porque necesito transacciones.")
    s.at(4).interviewer("¿Y por qué no MongoDB?")      # mid-answer interjection
    assert len(s.answers()) == 1


def test_new_question_after_the_answer_gets_its_own_answer(s):
    s.at(0).interviewer("¿Qué base de datos usarías para el historial de pagos?")
    s.at(3).tester("Yo usaría PostgreSQL porque necesito transacciones.")
    s.at(3 + hilo.SILENCIO_FIN_RESPUESTA + 1).interviewer(
        "Perfecto. Otra cosa, ¿cómo monitorizarías los microservicios?")
    assert len(s.answers()) == 2


def test_unanswered_question_expires_and_unblocks_the_next(s):
    s.at(0).interviewer("¿Cómo escalarías las lecturas?")
    s.at(hilo.CADUCIDAD_PREGUNTA + 1).interviewer("¿Y cómo gestionarías los secretos?")
    assert len(s.answers()) == 2


def test_declined_question_does_not_block_the_next(s):
    s.at(0).interviewer("¿Me escuchas bien?")
    s.engine._cerrar_hilo()                  # the model answered NO_RESPONSE
    s.at(2).interviewer("¿Qué patrón usarías para coordinar pago y stock?")
    assert len(s.answers()) == 2


def test_speaker_echo_on_the_mic_is_not_taken_as_the_tester_answering(s):
    q = "¿Qué harías si llegan dos cobros iguales al mismo tiempo?"
    s.at(0).interviewer(q)
    s.at(0.8).tester("qué harías si llegan dos cobros iguales al mismo tiempo")
    assert s.engine._hilo.dijo_tester == []
    assert ("Yo", "qué harías si llegan dos cobros iguales al mismo tiempo") \
        not in s.engine._history


def test_tester_speech_becomes_context_but_never_an_answer(s):
    s.at(0).tester("Hola, ¿me oyes bien?")
    assert s.answers() == []
    assert ("Yo", "Hola, ¿me oyes bien?") in s.engine._history


def test_answer_now_always_answers_and_opens_a_new_thread(s):
    s.at(0).interviewer("¿Qué arquitectura usarías?")
    s.at(2).tester("Vale.")
    s.at(4).interviewer("Ah, pero ten en cuenta que es AWS.")
    s.engine.answer_now()
    texts = s.answers()
    assert len(texts) == 2 and texts[-1] == "Ah, pero ten en cuenta que es AWS."
    assert s.engine._hilo.partes == ["Ah, pero ten en cuenta que es AWS."]
