"""The screen lane: screenshots and code solutions next to the spoken lane.

Jev is faked (followup.juzgar replaced) and arbitration runs inline. Work items
are read from each lane's queue; no thread, audio, network or LLM is used.
"""
import pytest

import followup
import hilo
from engine import CoachEngine


def _juicio(relacion="filler_or_ack", pantalla=0.0, cambia=0.0, p=0.95):
    return followup.Juicio(relacion, p, {relacion: p}, cambia, 0.0, ms=150,
                           pantalla=pantalla)


class FakeCoach:
    def __init__(self):
        self.cancelled = 0
        self.heard = []
        self.calls = []

    def cancelar(self):
        self.cancelled += 1

    def anotar(self, quien, texto):
        self.heard.append((quien, texto))

    def stream_response(self, **kw):
        self.calls.append(kw)
        kw["on_delta"]("## Solución\n```py\nprint(1)\n```")
        kw["on_done"]()


class Session:
    def __init__(self, monkeypatch, verdict=None):
        self.now = 0.0
        e = CoachEngine()
        e._running = True
        e._language = "es"
        e._clock = lambda: self.now
        e._arbitro = object()
        e._arbitrar_en_hilo = False
        e._coach = FakeCoach()
        e._coach_pantalla = FakeCoach()
        self.engine = e
        self.calls = []
        self.suggestions = []
        e.screenSuggest.connect(self.suggestions.append)
        self.verdict = verdict

        def fake_juzgar(cliente, pregunta, respuesta, dijo_tester, anadido, **kw):
            self.calls.append((pregunta, anadido, kw.get("solucion_pantalla")))
            return self.verdict

        monkeypatch.setattr(followup, "juzgar", fake_juzgar)

    def interviewer(self, text):
        self.engine._on_stt_final(text, 0)
        if self.engine._turn_parts:
            self.engine._flush_turn()
        return self

    @staticmethod
    def drain(q):
        items = []
        while not q.empty():
            items.append(q.get_nowait())
        return [(i["type"], i.get("text")) for i in items]

    def voice(self):
        return self.drain(self.engine._queue)

    def screen(self):
        return self.drain(self.engine._queue_pantalla)

    def solve_screen(self, text="## Solución\nUna función con un diccionario."):
        self.engine._solucion_pantalla = text
        return self


SOLUTION = "## Solución\n```py\ndef dos_suma(nums, objetivo): ...\n```"


def test_screenshots_go_to_the_screen_lane_and_answer_there(monkeypatch):
    s = Session(monkeypatch)
    s.engine.request_screenshots(["png"])
    assert s.voice() == [] and s.screen() == [("screenshot", None)]

    starts, deltas, dones = [], [], []
    s.engine.shotStart.connect(lambda: starts.append(1))
    s.engine.shotDelta.connect(deltas.append)
    s.engine.shotDone.connect(lambda: dones.append(1))
    voice_starts = []
    s.engine.respStart.connect(lambda: voice_starts.append(1))

    s.engine._responder_capturas(["png"])

    assert (len(starts), len(dones), voice_starts) == (1, 1, [])
    assert s.engine._coach_pantalla.calls[0]["images"] == ["png"]
    assert s.engine._coach.calls == []
    assert s.engine._solucion_pantalla.startswith("## Solución")
    assert s.engine._registro[-1][0] == "Sugerido (pantalla)"


def test_spoken_question_is_not_blocked_by_a_screen_answer(monkeypatch):
    s = Session(monkeypatch)
    s.engine._generando_pantalla = True           # long code answer in flight
    s.interviewer("¿Qué base de datos usarías?")
    assert s.voice() == [("respond", "¿Qué base de datos usarías?")]


def test_remark_about_the_solution_suggests_a_relaunch_instead_of_answering(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio(pantalla=0.92)).solve_screen(SOLUTION)

    s.interviewer("Hay un error, hazlo con un diccionario en vez de dos bucles.")

    assert s.suggestions == ["Hay un error, hazlo con un diccionario en vez de dos bucles."]
    assert s.voice() == [] and s.screen() == []          # nothing relaunches alone
    assert s.calls[0][2] == SOLUTION                      # Jev saw the solution


def test_tester_relaunches_with_the_suggestion(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio(pantalla=0.92)).solve_screen(SOLUTION)
    s.interviewer("Hay un error en el bucle.")
    s.interviewer("¿Y qué cambiarías para que acepte negativos?")

    s.engine.relaunch_screen()

    assert s.screen() == [("screen_revise",
                           "Hay un error en el bucle. ¿Y qué cambiarías para que "
                           "acepte negativos?")]
    assert s.suggestions[-1] == ""                       # suggestion withdrawn


def test_relaunch_rewrites_the_screen_solution_in_place(monkeypatch):
    s = Session(monkeypatch)
    s.solve_screen(SOLUTION)
    revises, starts = [], []
    s.engine.shotRevise.connect(lambda: revises.append(1))
    s.engine.shotStart.connect(lambda: starts.append(1))

    s.engine._respond("Hay un error en el bucle.", revision=True, carril="pantalla")

    assert (len(revises), starts) == (1, [])
    assert s.engine._coach_pantalla.calls[0]["revision"] is True
    assert s.engine._registro[-1][0] == "Sugerido (pantalla) (revisada)"


def test_relaunch_cancels_a_screen_answer_still_being_generated(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio(pantalla=0.92)).solve_screen(SOLUTION)
    s.interviewer("Hay un error en el bucle.")
    s.engine._generando_pantalla = True

    s.engine.relaunch_screen()

    assert s.engine._coach_pantalla.cancelled == 1


def test_relaunch_without_a_suggestion_does_nothing(monkeypatch):
    s = Session(monkeypatch).solve_screen(SOLUTION)
    statuses = []
    s.engine.status.connect(statuses.append)

    s.engine.relaunch_screen()

    assert s.screen() == []
    assert statuses == ["No hay nada que actualizar en la pantalla."]


def test_new_screenshots_withdraw_a_pending_suggestion(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio(pantalla=0.92)).solve_screen(SOLUTION)
    s.interviewer("Hay un error en el bucle.")

    s.engine.request_screenshots(["png"])

    assert s.suggestions[-1] == "" and s.engine._sugerencia_pantalla == ""


def test_spoken_question_with_a_solution_on_screen_still_gets_a_spoken_answer(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio("new_question", pantalla=0.1)).solve_screen(SOLUTION)

    s.interviewer("¿Has trabajado con Kubernetes?")

    assert s.voice() == [("respond", "¿Has trabajado con Kubernetes?")]
    assert s.suggestions == []


def test_without_a_solution_on_screen_jev_is_not_asked_about_the_screen(monkeypatch):
    s = Session(monkeypatch, verdict=_juicio(pantalla=0.99))
    s.interviewer("¿Qué arquitectura usarías?")
    s.now = 2
    s.interviewer("Ah, pero en AWS.")

    assert all(call[2] in (None, "") for call in s.calls)
    assert s.suggestions == []


def test_jev_failure_with_a_solution_on_screen_falls_back_to_spoken_rules(monkeypatch):
    s = Session(monkeypatch, verdict=None).solve_screen(SOLUTION)

    def boom(*_a, **_k):
        raise TimeoutError("slow")
    monkeypatch.setattr(followup, "juzgar", boom)
    s.interviewer("¿Y cómo lo desplegarías?")

    assert s.voice() == [("respond", "¿Y cómo lo desplegarías?")]
    assert s.suggestions == []


def test_heard_speech_reaches_both_conversations(monkeypatch):
    s = Session(monkeypatch)
    s.engine._on_mic_final("Usaría un diccionario para guardar los vistos.")

    expected = [("Yo", "Usaría un diccionario para guardar los vistos.")]
    assert s.engine._coach.heard == expected
    assert s.engine._coach_pantalla.heard == expected
