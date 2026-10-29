"""llm.Coach: one model for every answer; only effort and length change per use."""
from contextlib import contextmanager
from types import SimpleNamespace

from llm import Coach


class FakeResponses:
    def __init__(self):
        self.stream_calls, self.create_calls = [], []

    @contextmanager
    def stream(self, **kw):
        self.stream_calls.append(kw)
        yield [SimpleNamespace(type="response.output_text.delta", delta="ok")]

    def create(self, **kw):
        self.create_calls.append(kw)


def _coach(**kw):
    coach = Coach("sk-test", system_prompt="sys", tokens_voice=400,
                  tokens_vision=2500, **kw)
    coach.client = SimpleNamespace(responses=FakeResponses())
    return coach


def test_voice_and_screenshot_use_the_same_model_with_different_effort():
    coach = _coach()
    coach.stream_response("ctx", "¿Qué base de datos usarías?")
    coach.stream_response("ctx", "mira esto", images=["iVBOR"])

    voice, shot = coach.client.responses.stream_calls
    assert voice["model"] == shot["model"] == "gpt-6.1-sol"
    assert voice["reasoning"] == {"effort": "low"}
    assert shot["reasoning"] == {"effort": "medium"}
    assert shot["max_output_tokens"] > voice["max_output_tokens"]


def test_warm_up_uses_voice_effort_not_none():
    # gpt-6.1-sol rejects effort 'none'; warming with it wasted a failed call.
    coach = _coach(effort_voice="low")
    coach.calentar()
    (call,) = coach.client.responses.create_calls
    assert call["model"] == "gpt-6.1-sol"
    assert call["reasoning"] == {"effort": "low"}
