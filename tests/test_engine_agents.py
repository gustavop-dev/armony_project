"""Switching agents in the middle of a meeting."""
import agents
import engine
from engine import CoachEngine


class FakeCoach:
    def __init__(self, system_prompt, reglas):
        self.system_prompt, self.reglas = system_prompt, reglas
        self.cambios = []

    def cambiar_instrucciones(self, system_prompt, reglas):
        self.cambios.append((system_prompt, reglas))
        self.system_prompt, self.reglas = system_prompt, reglas


class NoThread:
    started = []

    def __init__(self, target=None, daemon=None, **_kw):
        self.target = target

    def start(self):
        NoThread.started.append(self.target)


def _engine(monkeypatch):
    monkeypatch.setattr(engine.threading, "Thread", NoThread)
    NoThread.started = []
    e = CoachEngine()
    e._running = True
    coach = agents.get("coach")
    prompt = agents.system_prompt(coach)
    e._coach = FakeCoach(prompt, coach["reglas"])
    e._coach_pantalla = FakeCoach(prompt, coach["reglas"])
    return e


def test_switch_changes_both_conversations(monkeypatch):
    lista = agents.list_agents()
    lista[2]["conocimiento"] = [{"id": "doc-1", "name": "CV", "body": "Producto X"}]
    agents.write_all(lista)
    e = _engine(monkeypatch)

    nombre = e.set_agent("grok")

    grok = agents.get("grok")
    esperado = (agents.system_prompt(grok), grok["reglas"])
    assert "Producto X" in esperado[0]
    assert nombre == "Grok"
    assert e._coach.cambios == [esperado] and e._coach_pantalla.cambios == [esperado]


def test_switch_warms_the_new_prompt(monkeypatch):
    e = _engine(monkeypatch)

    e.set_agent("grok")

    assert NoThread.started == [e._calentar]


def test_choosing_the_same_agent_keeps_the_cache(monkeypatch):
    e = _engine(monkeypatch)

    nombre = e.set_agent("coach")

    assert (nombre, e._coach.cambios, NoThread.started) == ("Coach", [], [])


def test_without_a_meeting_the_choice_waits_for_the_next(monkeypatch):
    e = _engine(monkeypatch)
    e._running = False

    assert e.set_agent("grok") is None
    assert e._coach.cambios == []


def test_test_mode_has_no_agent_to_switch(monkeypatch):
    e = _engine(monkeypatch)
    e._test_mode = True

    assert e.set_agent("grok") is None


def test_switch_is_noted_in_the_transcript(monkeypatch):
    e = _engine(monkeypatch)

    e.set_agent("grok")

    assert e._registro[-1] == ("Agente", "desde aquí responde Grok")
