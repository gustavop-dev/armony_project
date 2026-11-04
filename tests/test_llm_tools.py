"""llm.Coach reading a connected repo: the model asks for files, the coach
runs the tool locally, sends the result back and the turn keeps it."""
from types import SimpleNamespace

import pytest

import llm
from llm import Coach


class FakeTools:
    nombres = ["acme"]

    def __init__(self):
        self.calls = []

    def __bool__(self):
        return True

    def definiciones(self):
        return [{"type": "function", "name": "leer_archivos"}]

    def ejecutar(self, nombre, argumentos):
        self.calls.append((nombre, argumentos))
        return f"contenido de {argumentos}"


class Call:
    """A function_call output item as the SDK returns it."""

    def __init__(self, call_id="c1", name="leer_archivos", arguments='{"rutas": ["a.py"]}'):
        self.type = "function_call"
        self.call_id, self.name, self.arguments = call_id, name, arguments

    def model_dump(self, exclude_none=True):
        return {"type": "function_call", "call_id": self.call_id, "name": self.name,
                "arguments": self.arguments}


class Stream:
    def __init__(self, texts=(), output=()):
        self.texts, self.output = texts, list(output)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for t in self.texts:
            yield SimpleNamespace(type="response.output_text.delta", delta=t)

    def get_final_response(self):
        return SimpleNamespace(usage=None, output=self.output)


class FakeOpenAI:
    def __init__(self, *streams):
        self.streams = list(streams)
        self.calls = []
        self.responses = SimpleNamespace(stream=self._stream, create=self._create)

    def _stream(self, **kw):
        self.calls.append(kw)
        return self.streams.pop(0)

    def _create(self, **kw):
        self.calls.append(kw)


@pytest.fixture
def coach():
    c = Coach(api_key="k", system_prompt="SYS", model="m", tokens_voice=100,
              tokens_vision=900, herramientas=FakeTools())
    return c


def run(coach, latest="¿Por qué select_for_update?", **kw):
    out = {"deltas": [], "done": 0, "errors": []}
    coach.stream_response(latest=latest, on_delta=out["deltas"].append,
                          on_done=lambda: out.__setitem__("done", out["done"] + 1),
                          on_error=out["errors"].append, **kw)
    return out


def test_model_reads_a_file_then_answers(coach):
    reasoning = {"type": "reasoning", "id": "rs_1", "summary": []}
    coach.client = FakeOpenAI(Stream(output=[reasoning, Call()]),
                              Stream(texts=["## Respuesta\n", "Por el lock."]))

    out = run(coach)

    assert out == {"deltas": ["## Respuesta\n", "Por el lock."], "done": 1, "errors": []}
    assert coach.herramientas.calls == [("leer_archivos", '{"rutas": ["a.py"]}')]
    segunda = coach.client.calls[1]["input"]
    assert segunda[-3:] == [reasoning, Call().model_dump(),
                            {"type": "function_call_output", "call_id": "c1",
                             "output": 'contenido de {"rutas": ["a.py"]}'}]


def test_reading_stays_in_the_conversation(coach):
    coach.client = FakeOpenAI(Stream(output=[Call()]), Stream(texts=["ok"]),
                              Stream(texts=["siguiente"]))
    run(coach)

    run(coach, latest="¿Y el pago?")

    tipos = [it.get("type", it.get("role")) for it in coach._items]
    assert tipos == ["developer", "user", "function_call", "function_call_output",
                     "assistant", "user", "assistant"]
    # The next request repeats them byte for byte: the cache reuses them.
    assert coach.client.calls[2]["input"][:5] == coach._items[:5]


def test_tools_go_in_every_request_and_in_the_warm_up(coach):
    coach.client = FakeOpenAI(Stream(output=[Call()]), Stream(texts=["ok"]))
    run(coach)
    coach.calentar()

    assert all(c["tools"] == coach.herramientas.definiciones() for c in coach.client.calls)


def test_after_the_last_round_the_model_must_answer(coach, monkeypatch):
    monkeypatch.setattr(llm, "MAX_RONDAS_HERRAMIENTAS", 2)
    coach.client = FakeOpenAI(Stream(output=[Call("a")]), Stream(output=[Call("b")]),
                              Stream(texts=["con lo leído"]))

    out = run(coach)

    assert out["deltas"] == ["con lo leído"]
    assert [c.get("tool_choice") for c in coach.client.calls] == [None, None, "none"]


def test_without_tools_nothing_changes():
    c = Coach(api_key="k", system_prompt="SYS", model="m")
    c.client = FakeOpenAI(Stream(texts=["hola"]))

    run(c)

    assert "tools" not in c.client.calls[0]


def test_side_question_can_read_the_repo_too(coach):
    coach.client = FakeOpenAI(Stream(output=[Call()]), Stream(texts=["la línea 2"]))
    deltas = []

    coach.responder_aparte("¿qué hace post?", on_delta=deltas.append)

    assert deltas == ["la línea 2"]
    assert [it.get("type", it.get("role")) for it in coach._aparte] == [
        "user", "function_call", "function_call_output", "assistant"]


def test_trimming_drops_whole_readings(coach, monkeypatch):
    monkeypatch.setattr(llm, "LIMITE_TOKENS", 1)
    coach._items += [{"role": "user", "content": "x"},
                     {"type": "reasoning", "id": "rs"},
                     {"type": "function_call", "call_id": "c"},
                     {"type": "function_call_output", "call_id": "c", "output": "y"},
                     {"role": "assistant", "content": "z"}]

    coach._recortar_si_hace_falta()

    assert [it.get("type", it.get("role")) for it in coach._items] == [
        "developer", "user", "assistant"]


def test_sdk_only_fields_are_not_sent_back():
    """The SDK's parsed items carry fields the API rejects as input."""
    llamada = {"type": "function_call", "id": "fc_1", "call_id": "c", "name": "leer_archivos",
               "arguments": "{}", "parsed_arguments": {"x": 1}, "status": "completed"}
    mensaje = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "hola", "annotations": [],
                            "parsed": None, "logprobs": []}]}

    assert llm._como_dict(llamada) == {"type": "function_call", "id": "fc_1", "call_id": "c",
                                       "name": "leer_archivos", "arguments": "{}"}
    assert llm._como_dict(mensaje) == {"type": "message", "id": "msg_1", "role": "assistant",
                                       "content": [{"type": "output_text", "text": "hola",
                                                    "annotations": []}]}
    assert llm._como_dict({"type": "web_search_call", "id": "ws"}) is None
