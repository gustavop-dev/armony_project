"""Tests for llm.Coach: turns, settings per use, streaming, retries and logging.

The OpenAI SDK client is replaced with an in-memory fake (or, for the HTTP
attempt test, a mock transport); no request leaves the process. The
append-only conversation and prompt-cache behaviour is covered in
test_llm_single_model.py.
"""
import logging
from types import SimpleNamespace

import pytest

import llm
from llm import Coach
from metrics import metricas


class _Stream:
    """Context manager that yields the given items, optionally failing."""

    def __init__(self, items, fail_after=None, error=None):
        self._items, self._fail_after, self._error = items, fail_after, error

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __iter__(self):
        for i, item in enumerate(self._items):
            if self._fail_after == i:
                raise self._error
            yield item
        if self._fail_after == len(self._items):
            raise self._error

    def get_final_response(self):
        return SimpleNamespace(usage=None)


class FakeOpenAI:
    def __init__(self, *streams):
        self._streams = list(streams)
        self.calls = []
        self.create_errors = []
        self.responses = SimpleNamespace(stream=self._stream,
                                         create=self._create)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return self._streams.pop(0)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.create_errors:
            raise self.create_errors.pop(0)


def _delta(text):
    return SimpleNamespace(type="response.output_text.delta", delta=text)


def _text_stream(*texts, **kw):
    return _Stream([_delta(t) for t in texts], **kw)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)


@pytest.fixture
def coach():
    c = Coach(api_key="test-key", system_prompt="SYS", model="test-model",
              tokens_voice=100, tokens_vision=900)
    c.client = FakeOpenAI(_text_stream("ok"))
    return c


def _run(coach, **kwargs):
    """Run stream_response and collect callbacks."""
    out = {"deltas": [], "done": 0, "errors": []}
    coach.stream_response(
        latest=kwargs.pop("latest", "¿Qué tal?"),
        on_delta=out["deltas"].append,
        on_done=lambda: out.__setitem__("done", out["done"] + 1),
        on_error=out["errors"].append,
        **kwargs)
    return out


def _turn_text(coach, call=-1):
    return coach.client.calls[call]["input"][-1]["content"][-1]["text"]


def _developer_text(coach):
    return coach.client.calls[-1]["input"][0]["content"][0]["text"]


# ------------------------------------------------------- settings per use
def test_voice_request_uses_voice_tokens_and_effort(coach):
    assert coach.ajustes(None) == (100, "low")


def test_screenshot_request_uses_vision_tokens_and_effort(coach):
    assert coach.ajustes(["png"]) == (900, "medium")


def test_vision_tokens_default_to_voice_tokens():
    c = Coach(api_key="k", tokens_voice=300)

    assert c.ajustes(["png"]) == (300, "medium")


def test_builds_openai_client():
    c = Coach(api_key="k")

    assert type(c.client).__module__.startswith("openai")


# ---------------------------------------------------------------- prompt
def test_developer_message_always_contains_injection_notice(coach):
    _run(coach)

    text = _developer_text(coach)
    assert text.startswith("SYS")
    assert "AVISO SOBRE LA TRANSCRIPCION" in text


def test_turn_without_new_lines_uses_placeholder(coach):
    _run(coach)

    assert "(nada nuevo)" in _turn_text(coach)


def test_turn_lists_what_was_heard_by_speaker(coach):
    coach.anotar("Ellos", "hola")
    coach.anotar("Yo", "buenas")

    _run(coach)

    assert "Ellos: hola\nYo: buenas" in _turn_text(coach)


def test_turn_quotes_latest(coach):
    _run(coach, latest="¿Y en AWS?")

    assert '"¿Y en AWS?"' in _turn_text(coach)


@pytest.mark.parametrize("allow_silence, expected", [(True, True), (False, False)])
def test_silence_clause_follows_allow_silence(coach, allow_silence, expected):
    _run(coach, allow_silence=allow_silence)

    assert ("NO_RESPONSE" in _turn_text(coach)) is expected


def test_turn_includes_user_note(coach):
    _run(coach, note="más corto")

    assert "más corto" in _turn_text(coach)


def test_turn_counts_screenshots(coach):
    _run(coach, images=["a", "b"])

    assert "2 captura(s)" in _turn_text(coach)


# -------------------------------------------------------- retry predicate
@pytest.mark.parametrize("error, expected", [
    (Exception("Error code: 429 - rate limit"), True),
    (Exception("503 Service Unavailable"), True),
    (TimeoutError("timed out"), True),
    (ConnectionError("reset"), True),
    (Exception("overloaded_error"), True),
    (Exception("401 invalid x-api-key"), False),
    (Exception("model not found"), False),
])
def test_retryable_error_detection(error, expected):
    assert llm._reintentable(error) is expected


# -------------------------------------------------------------- streaming
def test_forwards_only_text_delta_events(coach):
    coach.client = FakeOpenAI(_Stream([
        SimpleNamespace(type="response.created"), _delta("Ho"), _delta("la"),
        SimpleNamespace(type="response.completed")]))

    out = _run(coach)

    assert (out["deltas"], out["done"]) == (["Ho", "la"], 1)


def test_reserves_reasoning_tokens(coach):
    _run(coach)

    assert coach.client.calls[0]["max_output_tokens"] == 100 + llm._RESERVA_RAZONAMIENTO


def test_image_is_data_url(coach):
    _run(coach, images=["AAA"])

    image = coach.client.calls[0]["input"][-1]["content"][0]
    assert image == {"type": "input_image", "image_url": "data:image/png;base64,AAA"}


# ----------------------------------------------------------------- retries
def test_retryable_error_before_first_token_is_retried(coach):
    coach.client = FakeOpenAI(
        _Stream([], fail_after=0, error=Exception("429 rate limit")),
        _text_stream("ok"))

    out = _run(coach)

    assert (out["deltas"], out["errors"]) == (["ok"], [])


def test_retry_is_counted_in_metrics(coach):
    coach.client = FakeOpenAI(
        _Stream([], fail_after=0, error=Exception("429 rate limit")),
        _text_stream("ok"))

    _run(coach)

    assert metricas.resumen()["cuentas"]["reintentos_llm"] == 1


def test_error_after_first_token_is_not_retried(coach):
    coach.client = FakeOpenAI(
        _text_stream("par", fail_after=1, error=Exception("503 overloaded")),
        _text_stream("never"))

    out = _run(coach)

    assert (out["deltas"], out["errors"], out["done"]) == (["par"], ["503 overloaded"], 0)
    # What was shown stays in the conversation.
    assert coach._items[-1] == {"role": "assistant", "content": "par"}


def test_non_retryable_error_is_reported_without_retry(coach):
    coach.client = FakeOpenAI(
        _Stream([], fail_after=0, error=Exception("401 invalid x-api-key")),
        _text_stream("never"))

    out = _run(coach)

    assert (len(coach.client.calls), out["errors"]) == (1, ["401 invalid x-api-key"])


def test_second_retryable_failure_is_reported(coach):
    coach.client = FakeOpenAI(
        _Stream([], fail_after=0, error=Exception("429 rate limit")),
        _Stream([], fail_after=0, error=Exception("429 rate limit again")))

    out = _run(coach)

    assert out["errors"] == ["429 rate limit again"]


# ----------------------------------------------------------------- warm-up
def test_warmup_returns_elapsed_ms(coach, monkeypatch):
    ticks = iter([10.0, 10.25])
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(ticks))

    assert coach.calentar() == pytest.approx(250.0)


def test_warmup_failure_returns_none(coach):
    coach.client.create_errors = [ConnectionError("down"), ConnectionError("down")]

    assert coach.calentar() is None


def test_warmup_without_prewarm_falls_back_to_a_minimal_request(coach):
    coach.client.create_errors = [Exception("prewarm not supported")]

    coach.calentar()

    first, second = coach.client.calls
    assert first["prompt_cache_options"]["prewarm"] is True
    assert "prewarm" not in second["prompt_cache_options"]
    assert second["max_output_tokens"] == 16


# ------------------------------------------- client limits (ERR-004)
def test_sdk_client_does_not_retry_on_its_own():
    c = Coach(api_key="k")

    assert c.client.max_retries == 0


def test_sdk_client_timeout_is_sized_for_live_use():
    c = Coach(api_key="k")

    assert (c.client.timeout.connect, c.client.timeout.read) == (5.0, 30.0)


def _status_error(status):
    return type("APIStatusError", (Exception,), {"status_code": status})("x")


class APIConnectionError(Exception):
    pass


class APITimeoutError(APIConnectionError):
    pass


@pytest.mark.parametrize("error, expected", [
    (_status_error(429), True),
    (_status_error(408), True),
    (_status_error(529), True),
    (_status_error(500), True),
    (_status_error(400), False),
    (_status_error(401), False),
    (_status_error(404), False),
    (APIConnectionError("reset"), True),
    (APITimeoutError("read timeout"), True),
])
def test_retry_classification_uses_status_and_type(error, expected):
    assert llm._reintentable(error) is expected


def _mocked_openai(status):
    """A Coach whose real SDK client talks to an in-memory transport."""
    import httpx2
    hits = []

    def handler(request):
        hits.append(request.url.path)
        return httpx2.Response(status, json={"error": {"message": "x", "type": "error"}})
    c = Coach(api_key="test-key", tokens_voice=100)
    c.client = c.client.with_options(
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    return c, hits


@pytest.mark.parametrize("status, expected_requests", [(503, 2), (529, 2), (401, 1)])
def test_failed_suggestion_http_attempts(status, expected_requests):
    c, hits = _mocked_openai(status)

    out = _run(c)

    assert (len(hits), len(out["errors"])) == (expected_requests, 1)


# ------------------------------------------- logged failures (ERR-005)
def _api_error(status, message):
    """SDK-shaped error: class name APIStatusError with a status_code."""
    return type("APIStatusError", (Exception,), {"status_code": status})(message)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(llm.time, "monotonic", lambda: 10.0)


def _log_entries(caplog):
    return [(r.name, r.levelname, r.getMessage()) for r in caplog.records]


def test_final_error_is_logged_with_status_code(coach, frozen_clock, caplog):
    coach.client = FakeOpenAI(
        _Stream([], fail_after=0, error=_api_error(401, "invalid api key")))

    _run(coach)

    assert _log_entries(caplog) == [
        ("armony.llm", "ERROR",
         "LLM request failed after 1 attempt(s), 0 ms (model=test-model, "
         "text received=False): APIStatusError status=401: invalid api key")]


def test_retry_is_logged_at_info(coach, caplog):
    caplog.set_level(logging.INFO, logger="armony")
    coach.client = FakeOpenAI(
        _Stream([], fail_after=0, error=_api_error(529, "overloaded")),
        _text_stream("ok"))

    _run(coach)

    assert _log_entries(caplog) == [
        ("armony.llm", "INFO",
         "LLM request failed, retrying once: APIStatusError status=529: overloaded")]


def test_warmup_failure_is_logged(coach, caplog):
    coach.client.create_errors = [ConnectionError("down"), ConnectionError("down")]

    coach.calentar()

    assert _log_entries(caplog) == [
        ("armony.llm", "WARNING", "LLM warm-up failed: ConnectionError status=None: down")]


def test_error_log_does_not_contain_api_key(caplog):
    secret = "sk-test-SECRET-0123456789"
    c = Coach(api_key=secret)
    c.client = FakeOpenAI(_Stream([], fail_after=0, error=_api_error(
        401, f"Incorrect API key provided: {secret}")))

    _run(c)

    assert secret not in caplog.text


# ------------------------------------------------------- agents
def test_agent_rules_replace_the_default_rules():
    c = Coach(api_key="k", system_prompt="SYS", reglas="MIS REGLAS")

    assert c._items[0]["content"][0]["text"] == "SYS\n\nMIS REGLAS"


def test_switching_instructions_keeps_the_conversation(coach):
    coach.client = FakeOpenAI(_text_stream("uno"), _text_stream("dos"))
    _run(coach)
    turnos = len(coach._items)

    coach.cambiar_instrucciones("OTRO", "OTRAS REGLAS")
    _run(coach)

    assert _developer_text(coach) == "OTRO\n\nOTRAS REGLAS"
    assert len(coach._items) == turnos + 2       # history kept, new turn added
