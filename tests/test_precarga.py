"""precarga.py: the meeting's coaches built the same way everywhere, and the
Home warming an agent's prompt cache before the meeting starts."""
import pytest

import agents
import llm
import precarga
import repos


class FakeCoach:
    made = []

    def __init__(self, **kw):
        self.options = kw
        self.warmed = 0
        FakeCoach.made.append(self)

    def calentar(self):
        self.warmed += 1
        return 10


@pytest.fixture
def cfg():
    return {"openai_api_key": "sk", "openai_model": "m", "openai_tokens_voice": 1000,
            "openai_tokens_vision": 4000, "openai_effort_voice": "low",
            "openai_effort_vision": "medium"}


@pytest.fixture(autouse=True)
def fake_coach(monkeypatch):
    FakeCoach.made = []
    monkeypatch.setattr(llm, "Coach", FakeCoach)


def test_coaches_share_the_agent_start_and_cache_key(cfg):
    agente = agents.preset("grok")

    voz, pantalla = precarga.crear_coaches(cfg, agente)

    for c in (voz, pantalla):
        assert c.options["system_prompt"] == agents.system_prompt(agente)
        assert c.options["cache_key"] == "armony-grok"
        assert "herramientas" not in c.options
    assert (voz.options["effort_voice"], pantalla.options["effort_voice"]) == ("low", "medium")


def test_only_the_screen_conversation_reads_repos(cfg):
    tools = object()

    voz, pantalla = precarga.crear_coaches(cfg, agents.preset("coach"), tools)

    assert "herramientas" not in voz.options
    assert pantalla.options["herramientas"] is tools


def test_prewarm_warms_both_conversations_once(cfg, precalentar_real):
    agente = agents.preset("coach")

    assert precalentar_real(cfg, agente, esperar=True) is True
    assert precalentar_real(cfg, agente, esperar=True) is False

    assert [c.warmed for c in FakeCoach.made] == [1, 1]


def test_prewarm_is_repeated_when_the_cache_would_expire(cfg, precalentar_real):
    agente = agents.preset("coach")
    ahora = [0.0]
    precalentar_real(cfg, agente, esperar=True, reloj=lambda: ahora[0])

    ahora[0] = precarga.VIGENCIA_S + 1

    assert precalentar_real(cfg, agente, esperar=True, reloj=lambda: ahora[0]) is True


def test_changed_knowledge_is_warmed_again(cfg, precalentar_real):
    agente = agents.preset("coach")
    precalentar_real(cfg, agente, esperar=True)

    agente["conocimiento"] = [{"id": "d", "name": "CV", "body": "Soy backend"}]

    assert precalentar_real(cfg, agente, esperar=True) is True


@pytest.mark.parametrize("cambio", [{"openai_api_key": ""}, {"test_mode": True}])
def test_no_prewarm_without_a_key_or_in_test_mode(cfg, precalentar_real, cambio):
    cfg.update(cambio)

    assert precalentar_real(cfg, agents.preset("coach"), esperar=True) is False
    assert FakeCoach.made == []


def test_failed_prewarm_can_be_retried(cfg, precalentar_real, monkeypatch):
    def roto(**kw):
        raise RuntimeError("sin red")
    monkeypatch.setattr(llm, "Coach", roto)
    agente = agents.preset("coach")
    precalentar_real(cfg, agente, esperar=True)

    monkeypatch.setattr(llm, "Coach", FakeCoach)

    assert precalentar_real(cfg, agente, esperar=True) is True


def test_agent_with_a_repo_warms_the_screen_conversation_with_its_tools(cfg, precalentar_real):
    repos.guardar("gus__acme__main", {"owner": "gus", "nombre": "acme", "rama": "main",
                                      "commit": "f" * 40}, [("a.py", "x")])
    agente = agents.preset("coach")
    agente["conocimiento"] = [{"id": "d", "name": "Repo", "body": "memoria",
                               "repo": {"id": "gus__acme__main"}}]

    precalentar_real(cfg, agente, esperar=True)

    assert FakeCoach.made[1].options["herramientas"].nombres == ["acme"]
