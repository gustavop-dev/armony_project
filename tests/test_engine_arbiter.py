"""Engine + Jev arbiter: what a follow-up does depending on the question state.

Jev is faked (followup.juzgar is replaced) and arbitration runs inline, so each
scenario is deterministic. Answer requests are read from the engine queue.
"""
import pytest

import followup
import hilo
from engine import CoachEngine


def _juicio(relacion, cambia=0.0, p=0.95):
    return followup.Juicio(relacion, p, {relacion: p}, cambia, 0.0, ms=150)


class FakeCoach:
    def __init__(self):
        self.cancelled = 0
        self.notes = []

    def cancelar(self):
        self.cancelled += 1

    def anotar(self, quien, texto):
        self.notes.append((quien, texto))


class Session:
    def __init__(self, monkeypatch, verdict=None, error=None):
        self.now = 0.0
        e = CoachEngine()
        e._running = True
        e._language = "es"
        e._turn_gap = 0.01
        e._clock = lambda: self.now
        e._arbitro = object()            # "Jev is configured"
        e._arbitrar_en_hilo = False
        e._coach = FakeCoach()
        self.engine = e
        self.calls = []

        def fake_juzgar(cliente, pregunta, respuesta, dijo_tester, anadido):
            self.calls.append((pregunta, respuesta, list(dijo_tester), anadido))
            if error:
                raise error
            return verdict

        monkeypatch.setattr(followup, "juzgar", fake_juzgar)

    def at(self, t):
        self.now = t
        return self

    def interviewer(self, text):
        self.engine._on_stt_final(text, 0)
        if self.engine._turn_parts:
            self.engine._flush_turn()
        return self

    def tester(self, text):
        self.engine._on_mic_final(text)
        return self

    def answered(self, text):
        self.engine._hilo.respuesta = text
        return self

    def queued(self):
        items = []
        while not self.engine._queue.empty():
            items.append(self.engine._queue.get_nowait())
        return [(i["type"], i.get("text")) for i in items]


Q = "¿Qué arquitectura usarías para los pedidos de Black Friday?"
ADD = "Ah, pero ten en cuenta que no podemos perder ningún pedido."


def test_change_while_reading_rewrites_the_same_answer_once(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio("extends_question", cambia=0.9))
    s.at(0).interviewer(Q).answered("Una cola entre la API y los workers.")
    s.at(2).tester("Vale.")
    s.at(4).interviewer(ADD)
    s.at(6).interviewer("Y además que escale solo, ¿vale?")
    assert s.queued() == [("respond", Q), ("revise", ADD)]
    # Jev saw the question, the suggestion and what the tester said.
    assert s.calls[0] == (Q, "Una cola entre la API y los workers.", ["Vale."], ADD)


def test_change_while_answering_never_rewrites(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio("extends_question", cambia=0.99))
    s.at(0).interviewer(Q)
    s.at(3).tester("Yo separaría la toma de pedidos con una cola.")
    s.at(4).interviewer(ADD)
    assert s.queued() == [("respond", Q)]


def test_drill_down_after_the_answer_opens_a_new_answer(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio("drills_into_part"))
    s.at(0).interviewer(Q)
    s.at(3).tester("Yo separaría la toma de pedidos con una cola.")
    drill = "Bueno, y esa parte de la cola, ¿cómo la harías?"
    s.at(3 + hilo.SILENCIO_FIN_RESPUESTA + 1).interviewer(drill)
    assert s.queued() == [("respond", Q), ("respond", drill)]
    assert s.engine._hilo.partes == [drill]


def test_noise_is_context_in_every_state(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio("filler_or_ack"))
    s.at(0).interviewer(Q)
    s.at(1).interviewer("Perfecto, perfecto.")
    s.at(3).tester("Yo separaría la toma de pedidos con una cola.")
    s.at(10).interviewer("Genial, gracias.")
    assert s.queued() == [("respond", Q)]


def test_revision_cancels_an_answer_still_being_generated(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio("relaxes_or_answers", cambia=0.9))
    s.at(0).interviewer(Q)
    s.engine._generando = True
    s.at(1).interviewer("No te compliques, son cincuenta usuarios.")
    assert s.engine._coach.cancelled == 1
    assert ("revise", "No te compliques, son cincuenta usuarios.") in s.queued()


@pytest.mark.parametrize("after,expected", [
    (2, [("respond", Q)]),                                   # still reading: context
    (3 + hilo.SILENCIO_FIN_RESPUESTA + 1,
     [("respond", Q), ("respond", "¿Y cómo lo monitorizarías?")]),   # answered: new
])
def test_jev_failure_falls_back_to_the_fixed_rule(monkeypatch, after, expected):
    s = Session(monkeypatch, error=TimeoutError("jev slow"))
    s.at(0).interviewer(Q)
    s.at(1).tester("Yo separaría la toma de pedidos con una cola.") if after > 2 else None
    s.at(after).interviewer("¿Y cómo lo monitorizarías?")
    assert s.queued() == expected


def test_without_jev_the_engine_uses_the_fixed_rule(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio("extends_question", cambia=0.99))
    s.engine._arbitro = None
    s.at(0).interviewer(Q)
    s.at(2).interviewer("Ah, pero ¿y si todo es en AWS?")
    assert s.queued() == [("respond", Q)]
    assert s.calls == []
