"""llm.Coach: one append-only conversation per meeting on a single model.

The prompt cache only pays off if every request starts with the previous
request's input byte for byte; these tests pin that, plus the per-use effort
switch through configuration_update. A fake client records each request.
"""
import copy
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import llm
from llm import Coach


def _final(input_tokens=1000, cached=0):
    return SimpleNamespace(usage=SimpleNamespace(
        input_tokens=input_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached)))


class FakeStream(list):
    def get_final_response(self):
        return _final()


class FakeResponses:
    def __init__(self, reply="## Respuesta\nUsaría PostgreSQL.", fail=None):
        self.reply, self.fail = reply, fail or []
        self.stream_calls, self.create_calls = [], []

    @contextmanager
    def stream(self, **kw):
        self.stream_calls.append(copy.deepcopy(kw))
        if self.fail:
            raise self.fail.pop(0)
        yield FakeStream([SimpleNamespace(type="response.output_text.delta", delta=self.reply)])

    def create(self, **kw):
        self.create_calls.append(copy.deepcopy(kw))


def _coach(**kw):
    coach = Coach("sk-test", system_prompt="Eres mi coach.", tokens_voice=400,
                  tokens_vision=2500, cache_key="armony-test", **kw)
    coach.client = SimpleNamespace(responses=FakeResponses())
    return coach


def _calls(coach):
    return coach.client.responses.stream_calls


def test_every_request_extends_the_previous_one_byte_for_byte():
    c = _coach()
    c.anotar("Ellos", "Somos una pasarela de pagos.")
    c.anotar("Ellos", "¿Qué base de datos usarías?")
    c.stream_response("¿Qué base de datos usarías?")
    c.anotar("Yo", "Usaría PostgreSQL por las transacciones.")
    c.anotar("Ellos", "¿Y cómo evitarías cobros duplicados?")
    c.stream_response("¿Y cómo evitarías cobros duplicados?")
    c.stream_response("mira esto", images=["iVBOR"])

    inputs = [call["input"] for call in _calls(c)]
    for prev, cur in zip(inputs, inputs[1:]):
        assert cur[:len(prev)] == prev                 # prefix unchanged
        assert len(cur) > len(prev)
    # The previous answer is in the history the next request sees.
    assert {"role": "assistant", "content": "## Respuesta\nUsaría PostgreSQL."} in inputs[1]


def test_conversation_starts_with_one_developer_message_holding_the_rules():
    c = _coach()
    c.stream_response("¿Qué base de datos usarías?")
    first = _calls(c)[0]["input"][0]
    assert first["role"] == "developer"
    text = first["content"][0]["text"]
    assert text.startswith("Eres mi coach.")
    assert "FORMATO OBLIGATORIO" in text and "NO_RESPONSE" not in text
    assert "instructions" not in _calls(c)[0]          # breakpoint-friendly


def test_turn_carries_only_what_is_new_and_the_question():
    c = _coach()
    c.anotar("Ellos", "Contexto uno.")
    c.stream_response("¿Primera?")
    c.anotar("Yo", "Respuesta mía.")
    c.stream_response("¿Segunda?", allow_silence=True)
    turn = _calls(c)[1]["input"][-1]["content"][-1]["text"]
    assert "Yo: Respuesta mía." in turn and "Contexto uno." not in turn
    assert "¿Segunda?" in turn and "NO_RESPONSE" in turn


def test_request_settings_never_change_between_turns():
    c = _coach()
    c.stream_response("¿Voz?")
    c.stream_response("captura", images=["iVBOR"])
    c.stream_response("¿Voz otra vez?")
    for call in _calls(c):
        assert call["model"] == "gpt-6.1-sol"
        assert call["reasoning"] == {"effort": "low"}       # top-level fixed
        assert call["prompt_cache_key"] == "armony-test"
        assert call["prompt_cache_options"] == {"ttl": "30m"}


def test_effort_switches_through_configuration_update_items():
    c = _coach()
    c.stream_response("¿Voz?")
    c.stream_response("captura", images=["iVBOR"])
    c.stream_response("¿Voz otra vez?")
    updates = [it for it in _calls(c)[-1]["input"]
               if it.get("type") == "configuration_update"]
    assert [u["reasoning"]["effort"] for u in updates] == ["medium", "low"]
    assert not any(it.get("type") == "configuration_update"
                   for it in _calls(c)[0]["input"])


def test_screenshot_turn_has_images_and_more_room():
    c = _coach()
    c.stream_response("captura", images=["AAA", "BBB"])
    call = _calls(c)[0]
    content = call["input"][-1]["content"]
    assert [b["type"] for b in content] == ["input_image", "input_image", "input_text"]
    assert call["max_output_tokens"] == 2500 + llm._RESERVA_RAZONAMIENTO


def test_failed_request_keeps_its_lines_for_the_next_turn():
    c = _coach()
    c.client.responses.fail = [ValueError("bad request")]
    errors = []
    c.anotar("Ellos", "Línea que no puede perderse.")
    c.stream_response("¿Primera?", on_error=errors.append)
    assert errors and len(c._items) == 1                 # nothing appended
    c.stream_response("¿Segunda?")
    assert "Línea que no puede perderse." in _calls(c)[-1]["input"][-1]["content"][-1]["text"]


def test_transient_error_is_retried_without_duplicating_the_turn():
    c = _coach()
    c.client.responses.fail = [RuntimeError("503 overloaded")]
    llm.time.sleep, original = (lambda s: None), llm.time.sleep
    try:
        c.stream_response("¿Primera?")
    finally:
        llm.time.sleep = original
    assert len(_calls(c)) == 2
    assert _calls(c)[0]["input"] == _calls(c)[1]["input"]
    assert len(c._items) == 3                            # developer, user, assistant


def test_model_without_configuration_update_falls_back_to_top_level_effort():
    c = _coach()
    c.stream_response("¿Voz?")
    c.client.responses.fail = [ValueError("Unsupported item type configuration_update")]
    c.stream_response("captura", images=["iVBOR"])
    retry = _calls(c)[-1]
    assert retry["reasoning"] == {"effort": "medium"}
    assert not any(it.get("type") == "configuration_update" for it in retry["input"])


def test_warm_up_prewarms_the_developer_prefix():
    c = _coach(effort_voice="low")
    c.calentar()
    (call,) = c.client.responses.create_calls
    assert call["model"] == "gpt-6.1-sol"
    assert call["input"] == [c._items[0]]
    assert call["prompt_cache_options"] == {"ttl": "30m", "prewarm": True}
    assert call["reasoning"] == {"effort": "low"}       # sol rejects 'none'


def test_cache_usage_is_recorded():
    c = _coach()
    c.stream_response("¿Voz?")
    assert c.ultimo_uso == (1000, 0)


def test_very_long_conversation_is_trimmed_to_recent_turns(monkeypatch):
    monkeypatch.setattr(llm, "LIMITE_TOKENS", 50)
    monkeypatch.setattr(llm, "TURNOS_TRAS_RECORTE", 4)
    c = _coach()
    for i in range(6):
        c.anotar("Ellos", f"Frase número {i} " * 20)
        c.stream_response(f"¿Pregunta {i}?")
    assert len(c._items) <= 1 + 4 + 2
    assert c._items[0]["role"] == "developer"
