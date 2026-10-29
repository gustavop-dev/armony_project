"""Agent modes in the engine: notetaker, answer on demand, automatic; screenshot
permission; meeting notes generated on stop."""
import pytest

import agents
import engine
import notas
import sesiones
from engine import CoachEngine


class FakeCoach:
    def cancelar(self):
        pass

    def anotar(self, quien, texto):
        pass


class InlineThread:
    def __init__(self, target=None, daemon=None, name=None, args=()):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def _engine(modo="automatico", capturas=True, notas_=True):
    e = CoachEngine()
    e._running = True
    e._language = "es"
    e._clock = lambda: 0.0
    e._coach = FakeCoach()
    e._coach_pantalla = FakeCoach()
    e._permisos({"modo": modo, "capturas": capturas, "notas": notas_})
    return e


def _queued(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait()["type"])
    return out


def _ask(e, texto="¿Qué base de datos usarías?"):
    e._on_stt_final(texto, 0)
    if e._turn_parts:
        e._flush_turn()


def test_automatic_agent_answers_on_its_own():
    e = _engine("automatico")

    _ask(e)

    assert _queued(e._queue) == ["respond"]


def test_manual_agent_waits_to_be_asked():
    e = _engine("manual")
    motivos = []
    e.noAnswer.connect(motivos.append)

    _ask(e)

    assert (_queued(e._queue), motivos) == ([], ["manual"])


def test_manual_agent_answers_when_asked():
    e = _engine("manual")
    _ask(e)

    e.answer_now()

    assert _queued(e._queue) == ["respond"]


def test_notetaker_never_answers():
    e = _engine("notetaker")
    motivos = []
    e.noAnswer.connect(motivos.append)

    _ask(e)
    e.answer_now()

    assert (_queued(e._queue), motivos) == ([], [])


def test_screenshots_are_refused_without_permission():
    e = _engine(capturas=False)

    e.request_screenshots(["png"])

    assert (e.permite_capturas, _queued(e._queue_pantalla)) == (False, [])


def test_notetaker_never_uses_screenshots():
    e = _engine("notetaker", capturas=True)

    assert e.permite_capturas is False


def test_switching_agent_brings_its_permissions(monkeypatch):
    monkeypatch.setattr(engine.threading, "Thread", InlineThread)
    lista = agents.list_agents()
    lista[2]["modo"] = "notetaker"
    agents.write_all(lista)
    e = _engine("automatico")
    e._coach.system_prompt, e._coach.reglas = "otro", "otras"
    e._coach.cambiar_instrucciones = lambda *a: None
    e._coach_pantalla.cambiar_instrucciones = lambda *a: None
    e._calentar = lambda: None

    e.set_agent("grok")

    assert (e.modo, e.permite_capturas) == ("notetaker", False)


# ------------------------------------------------------------------ notes on stop
@pytest.fixture
def notes_engine(monkeypatch):
    monkeypatch.setattr(engine.threading, "Thread", InlineThread)
    pedidas = []
    monkeypatch.setattr(notas, "generar", lambda key, model, registro: (
        pedidas.append((key, model, list(registro))) or "## Resumen\nSe habló de pagos."))
    e = _engine("automatico", notas_=True)
    e._agente = ("coach", "Coach")
    e._clave_notas = ("sk-test", "gpt-6.1-sol")
    e._registro = [("Ellos", "¿Pagos duplicados?"), ("Sugerido", "Idempotencia"),
                   ("Yo", "Usaría una clave de idempotencia")]
    e.pedidas = pedidas
    return e


def test_notes_are_saved_next_to_the_meeting(notes_engine):
    listas = []
    notes_engine.notesReady.connect(lambda sid, ok: listas.append((sid, ok)))

    notes_engine.stop()

    (s,) = sesiones.listar()
    assert listas == [(s["id"], True)]
    assert sesiones.leer_notas(s["id"]) == "## Resumen\nSe habló de pagos."


def test_notes_are_asked_with_the_spoken_lines(notes_engine):
    notes_engine.stop()

    ((clave, modelo, registro),) = notes_engine.pedidas
    assert (clave, modelo) == ("sk-test", "gpt-6.1-sol")
    assert notas.transcripcion(registro) == (
        "Ellos: ¿Pagos duplicados?\nYo: Usaría una clave de idempotencia")


def test_agent_without_notes_saves_only_the_transcript(notes_engine):
    notes_engine._notas = False

    notes_engine.stop()

    assert notes_engine.pedidas == [] and len(sesiones.listar()) == 1


def test_short_meeting_gets_no_notes(notes_engine):
    notes_engine._registro = [("Ellos", "hola")]

    notes_engine.stop()

    assert notes_engine.pedidas == []


def test_failed_notes_are_reported(notes_engine, monkeypatch):
    def falla(*a):
        raise RuntimeError("sin red")
    monkeypatch.setattr(notas, "generar", falla)
    listas = []
    notes_engine.notesReady.connect(lambda sid, ok: listas.append(ok))

    notes_engine.stop()

    assert listas == [False]
