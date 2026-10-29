"""Tests for stt_stream.StreamingSTT: URL building, audio chunking, server
message handling, latency estimation and connection lifecycle.

The WebSocket is replaced with in-memory fakes; nothing connects to AssemblyAI.
"""
import json
import logging
import queue
import urllib.parse

import numpy as np
import pytest
import websocket

import stt_stream
from metrics import metricas
from stt_stream import CHUNK_SAMPLES, StreamingSTT


class Recorder:
    """Collects every callback StreamingSTT emits."""

    def __init__(self):
        self.partials, self.finals, self.status, self.errors = [], [], [], []

    def kwargs(self):
        return dict(on_partial=self.partials.append,
                    on_final=lambda t, ms: self.finals.append((t, ms)),
                    on_status=self.status.append,
                    on_error=self.errors.append)


class FakeWS:
    """Minimal websocket-client connection."""

    def __init__(self, incoming=(), on_send_binary=None):
        self.incoming = list(incoming)
        self.sent, self.sent_binary = [], []
        self.closed = 0
        self.timeout = "unset"
        self._on_send_binary = on_send_binary

    def recv(self):
        return self.incoming.pop(0) if self.incoming else ""

    def send(self, data):
        self.sent.append(data)

    def send_binary(self, data):
        self.sent_binary.append(data)
        if self._on_send_binary:
            self._on_send_binary()

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed += 1


@pytest.fixture
def rec():
    return Recorder()


@pytest.fixture
def stt(rec):
    return StreamingSTT(api_key="key-123", **rec.kwargs())


def _turn(text, end=False, formatted=False, words=None):
    return {"type": "Turn", "transcript": text, "end_of_turn": end,
            "turn_is_formatted": formatted, "words": words or []}


# ------------------------------------------------------------------- URL
@pytest.mark.parametrize("language, expected", [
    ("es", "es"), ("en", "en"), ("auto", None), (None, None), ("fr", None)])
def test_language_code_mapping(language, expected):
    assert stt_stream._language_codes(language) == expected


def _query(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_url_targets_streaming_endpoint(stt):
    assert stt._url().startswith("wss://streaming.assemblyai.com/v3/ws?")


def test_url_carries_audio_and_turn_parameters(stt):
    assert _query(stt._url()) == {
        "speech_model": "universal-3-5-pro", "sample_rate": "16000",
        "encoding": "pcm_s16le", "format_turns": "true",
        "end_of_turn_confidence_threshold": "0.4", "language_codes": "es"}


def test_url_omits_language_for_auto(rec):
    s = StreamingSTT(api_key="k", language="auto", **rec.kwargs())

    assert "language_codes" not in _query(s._url())


# ------------------------------------------------------------- audio feed
def test_chunk_is_fifty_ms_at_16khz():
    assert CHUNK_SAMPLES == 800


def test_feed_is_ignored_when_not_running(stt):
    stt.feed(np.zeros(1600, dtype=np.float32))

    assert stt._audio_q.qsize() == 0


def test_feed_emits_full_chunks_only(stt):
    stt._running = True

    stt.feed(np.zeros(1200, dtype=np.float32))

    assert (stt._audio_q.qsize(), stt._pending.size) == (1, 400)


def test_feed_converts_to_pcm16_bytes(stt):
    stt._running = True

    stt.feed(np.full(800, 0.5, dtype=np.float32))

    chunk = np.frombuffer(stt._audio_q.get_nowait(), dtype=np.int16)
    assert (chunk.size, int(chunk[0])) == (800, 16383)


def test_feed_clips_out_of_range_samples(stt):
    stt._running = True

    stt.feed(np.full(800, 2.0, dtype=np.float32))

    chunk = np.frombuffer(stt._audio_q.get_nowait(), dtype=np.int16)
    assert int(chunk[0]) == 32767


def test_feed_drops_oldest_chunk_when_queue_is_full(stt):
    stt._running = True
    stt._audio_q = queue.Queue(maxsize=1)

    stt.feed(np.concatenate([np.full(800, 0.1, dtype=np.float32),
                             np.full(800, 0.2, dtype=np.float32)]))

    chunk = np.frombuffer(stt._audio_q.get_nowait(), dtype=np.int16)
    assert (stt._audio_q.qsize(), int(chunk[0])) == (0, 6553)


# -------------------------------------------------------- server messages
def test_begin_reports_connected(stt, rec):
    stt._procesar({"type": "Begin"})

    assert rec.status == ["Transcripcion en vivo conectada."]


def test_partial_turn_is_forwarded(stt, rec):
    stt._procesar(_turn("hola que"))

    assert rec.partials == ["hola que"]


def test_repeated_partial_is_forwarded_once(stt, rec):
    stt._procesar(_turn("hola"))
    stt._procesar(_turn("hola"))

    assert rec.partials == ["hola"]


def test_partial_is_counted(stt):
    stt._procesar(_turn("hola"))

    assert metricas.resumen()["cuentas"] == {"parciales": 1}


def test_empty_partial_is_ignored(stt, rec):
    stt._procesar(_turn("   "))

    assert rec.partials == []


def test_unformatted_final_is_ignored(stt, rec):
    stt._procesar(_turn("hola que tal", end=True, formatted=False))

    assert rec.finals == []


def test_formatted_final_is_forwarded(stt, rec):
    stt._procesar(_turn(" ¿Hola, qué tal? ", end=True, formatted=True))

    assert rec.finals == [("¿Hola, qué tal?", 0)]


def test_final_resets_partial_dedup(stt, rec):
    stt._procesar(_turn("hola"))
    stt._procesar(_turn("Hola.", end=True, formatted=True))
    stt._procesar(_turn("hola"))

    assert rec.partials == ["hola", "hola"]


def test_empty_formatted_final_is_ignored(stt, rec):
    stt._procesar(_turn("", end=True, formatted=True))

    assert rec.finals == []


def test_termination_reports_status(stt, rec):
    stt._procesar({"type": "Termination"})

    assert rec.status == ["Sesion de transcripcion terminada."]


@pytest.mark.parametrize("msg", [
    {"type": "Error", "error_code": 1008, "error": "Unauthorized"},
    {"type": "Error", "error": "Invalid API key provided"},
])
def test_credential_error_stops_the_client(stt, rec, msg):
    stt._running = True

    stt._procesar(msg)

    assert stt._running is False


def test_credential_error_message_names_the_detail(stt, rec):
    stt._procesar({"type": "Error", "error_code": 1008, "error": "Unauthorized"})

    assert rec.errors[0].startswith("AssemblyAI rechazo la conexion: Unauthorized.")


def test_other_server_error_keeps_running(stt, rec):
    stt._running = True

    stt._procesar({"type": "Error", "error_code": 3005, "error": "too fast"})

    assert (stt._running, rec.errors) == (True, ["Transcripcion en vivo: too fast"])


def test_server_error_without_detail_uses_placeholder(stt, rec):
    stt._procesar({"type": "Error"})

    assert rec.errors == ["Transcripcion en vivo: error desconocido"]


# ---------------------------------------------------------------- latency
@pytest.fixture
def clock(monkeypatch):
    now = {"t": 100.0}
    monkeypatch.setattr(stt_stream.time, "monotonic", lambda: now["t"])
    return now


def test_latency_is_zero_without_words(stt):
    assert stt._latencia_ms({"words": []}) == 0


def test_latency_is_zero_without_word_end(stt):
    stt._t_ultimo_envio = 1.0

    assert stt._latencia_ms({"words": [{"text": "hola"}]}) == 0


def test_latency_is_zero_before_any_audio_sent(stt):
    assert stt._latencia_ms({"words": [{"end": 500}]}) == 0


def test_latency_adds_trailing_audio_to_time_since_last_send(stt, clock):
    stt._audio_ms = 1000.0
    stt._t_ultimo_envio = 99.875        # last chunk sent 125 ms ago (exact in binary)

    assert stt._latencia_ms({"words": [{"end": 800}]}) == 325


def test_latency_is_never_negative(stt, clock):
    stt._audio_ms = 100.0
    stt._t_ultimo_envio = 100.0

    assert stt._latencia_ms({"words": [{"end": 5000}]}) == 0


# -------------------------------------------------------------- lifecycle
def test_start_launches_a_single_reader_thread(stt, monkeypatch):
    monkeypatch.setattr(stt, "_run", lambda: None)

    stt.start()
    stt.start()

    assert len(stt._threads) == 1


def test_stop_sends_terminate_message(stt):
    ws = FakeWS()
    stt._ws, stt._running = ws, True

    stt.stop()

    assert (json.loads(ws.sent[0]), ws.closed) == ({"type": "Terminate"}, 1)


def test_stop_clears_state(stt):
    stt._ws, stt._running = FakeWS(), True
    stt._connected.set()

    stt.stop()

    assert (stt._running, stt.connected, stt._ws) == (False, False, None)


def test_stop_survives_send_failure(stt):
    ws = FakeWS()
    ws.send = lambda _d: (_ for _ in ()).throw(OSError("closed"))
    stt._ws, stt._running = ws, True

    stt.stop()

    assert ws.closed == 1


# --------------------------------------------------------- send loop
def test_send_loop_ships_queued_chunk(stt, clock):
    ws = FakeWS(on_send_binary=stt._connected.clear)
    stt._running = True
    stt._connected.set()
    stt._audio_q.put(b"\x01\x02")

    stt._enviar_audio(ws)

    assert (ws.sent_binary, stt._audio_ms, stt._t_ultimo_envio) == ([b"\x01\x02"], 50.0, 100.0)


def test_send_loop_stops_on_send_error(stt):
    ws = FakeWS()
    ws.send_binary = lambda _d: (_ for _ in ()).throw(OSError("broken pipe"))
    stt._running = True
    stt._connected.set()
    stt._audio_q.put(b"\x01")

    stt._enviar_audio(ws)

    assert stt._audio_ms == 0.0


# ---------------------------------------------------- connect and receive
@pytest.fixture
def fake_connect(monkeypatch):
    """Replace websocket.create_connection; records the call arguments."""
    calls = {}

    def install(ws):
        def create_connection(url, header=None, timeout=None):
            calls.update(url=url, header=header, timeout=timeout)
            return ws
        monkeypatch.setattr(stt_stream.websocket, "create_connection", create_connection)
        return calls
    return install


def test_connect_sends_api_key_header(stt, fake_connect):
    calls = fake_connect(FakeWS())
    stt._running = True

    stt._conectar_y_escuchar()

    assert (calls["header"], calls["timeout"]) == (["Authorization: key-123"], 10)


def test_connect_processes_text_messages_until_empty(stt, rec, fake_connect):
    fake_connect(FakeWS([json.dumps({"type": "Begin"}), b"\x00",
                         json.dumps(_turn("hola"))]))
    stt._running = True

    stt._conectar_y_escuchar()

    assert (rec.status, rec.partials) == (["Transcripcion en vivo conectada."], ["hola"])


def test_connect_closes_socket_on_exit(stt, fake_connect):
    ws = FakeWS()
    fake_connect(ws)
    stt._running = True

    stt._conectar_y_escuchar()

    assert (ws.closed, stt.connected, ws.timeout) == (1, False, None)


def test_connect_resets_audio_clock(stt, fake_connect):
    fake_connect(FakeWS())
    stt._running = True
    stt._audio_ms = 1234.0

    stt._conectar_y_escuchar()

    assert stt._audio_ms == 0.0


# ------------------------------------------------------- reconnect loop
def test_rejected_credentials_stop_without_retry(stt, rec, monkeypatch):
    def reject():
        raise websocket.WebSocketBadStatusException("Handshake status %d", 401)
    monkeypatch.setattr(stt, "_conectar_y_escuchar", reject)
    stt._running = True

    stt._run()

    assert (stt._running, rec.status) == (False, [])


def test_rejected_credentials_message_names_status_code(stt, rec, monkeypatch):
    def reject():
        raise websocket.WebSocketBadStatusException("Handshake status %d", 403)
    monkeypatch.setattr(stt, "_conectar_y_escuchar", reject)
    stt._running = True

    stt._run()

    assert "AssemblyAI rechazo la conexion (codigo 403)" in rec.errors[0]


def test_dropped_connection_schedules_reconnect(stt, rec, monkeypatch):
    def drop():
        raise ConnectionError("reset by peer")
    monkeypatch.setattr(stt, "_conectar_y_escuchar", drop)
    # Stop the loop as soon as the reconnect notice is emitted.
    stt._on_status = lambda m: (rec.status.append(m), setattr(stt, "_running", False))
    stt._running = True

    stt._run()

    assert (rec.errors, rec.status) == (["Transcripcion en vivo: reset by peer"],
                                        ["Reconectando la transcripcion en 1 s..."])


def test_reconnect_is_counted(stt, monkeypatch):
    monkeypatch.setattr(stt, "_conectar_y_escuchar",
                        lambda: (_ for _ in ()).throw(ConnectionError("x")))
    stt._on_status = lambda _m: setattr(stt, "_running", False)
    stt._running = True

    stt._run()

    assert metricas.resumen()["cuentas"]["reconexiones_stt"] == 1


def test_error_after_stop_is_not_reported(stt, rec, monkeypatch):
    def drop_after_stop():
        stt._running = False
        raise ConnectionError("closed by stop()")
    monkeypatch.setattr(stt, "_conectar_y_escuchar", drop_after_stop)
    stt._running = True

    stt._run()

    assert rec.errors == []


def test_server_error_status_is_reported_and_retried(stt, rec, monkeypatch):
    def fail():
        raise websocket.WebSocketBadStatusException("Handshake status %d", 500)
    monkeypatch.setattr(stt, "_conectar_y_escuchar", fail)
    stt._on_status = lambda m: (rec.status.append(m), setattr(stt, "_running", False))
    stt._running = True

    stt._run()

    assert rec.status == ["Reconectando la transcripcion en 1 s..."]


def test_reconnect_wait_backs_off(stt, rec, monkeypatch, clock):
    monkeypatch.setattr(stt_stream.time, "sleep",
                        lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(stt, "_conectar_y_escuchar",
                        lambda: (_ for _ in ()).throw(ConnectionError("x")))

    def on_status(m):
        rec.status.append(m)
        stt._running = len(rec.status) < 3
    stt._on_status = on_status
    stt._running = True

    stt._run()

    assert rec.status == ["Reconectando la transcripcion en 1 s...",
                          "Reconectando la transcripcion en 2 s...",
                          "Reconectando la transcripcion en 5 s..."]


def test_stop_survives_close_failure(stt):
    ws = FakeWS()
    ws.close = lambda: (_ for _ in ()).throw(OSError("already closed"))
    stt._ws, stt._running = ws, True

    stt.stop()

    assert stt._ws is None


def test_stop_joins_reader_thread(stt, monkeypatch):
    monkeypatch.setattr(stt, "_run", lambda: None)
    stt.start()

    stt.stop()

    assert stt._threads == []


def test_connect_survives_close_failure(stt, fake_connect):
    ws = FakeWS()
    ws.close = lambda: (_ for _ in ()).throw(OSError("already closed"))
    fake_connect(ws)
    stt._running = True

    stt._conectar_y_escuchar()

    assert stt.connected is False


# ------------------------------------------ logged failures (ERR-005)
def log_entries(caplog):
    return [(r.name, r.levelname, r.getMessage()) for r in caplog.records]


def test_send_failure_is_logged(stt, caplog):
    ws = FakeWS()
    ws.send_binary = lambda _d: (_ for _ in ()).throw(OSError("broken pipe"))
    stt._running = True
    stt._connected.set()
    stt._audio_q.put(b"\x01")

    stt._enviar_audio(ws)

    assert log_entries(caplog) == [
        ("armony.stt_stream", "WARNING",
         "Audio send failed after 0 ms of audio: OSError: broken pipe")]


def test_rejected_handshake_is_logged_with_status(stt, caplog, monkeypatch):
    def reject():
        raise websocket.WebSocketBadStatusException("Handshake status %d", 401)
    monkeypatch.setattr(stt, "_conectar_y_escuchar", reject)
    stt._running = True

    stt._run()

    assert log_entries(caplog) == [
        ("armony.stt_stream", "WARNING",
         "AssemblyAI handshake rejected: status=401 (WebSocketBadStatusException)")]


def test_dropped_connection_is_logged(stt, caplog, monkeypatch):
    def drop():
        raise ConnectionError("reset by peer")
    monkeypatch.setattr(stt, "_conectar_y_escuchar", drop)
    stt._on_status = lambda _m: setattr(stt, "_running", False)
    stt._running = True

    stt._run()

    assert log_entries(caplog) == [
        ("armony.stt_stream", "WARNING",
         "Transcription stream dropped: ConnectionError: reset by peer")]


def test_server_error_message_is_logged(stt, caplog):
    stt._procesar({"type": "Error", "error_code": 3005, "error": "too fast"})

    assert log_entries(caplog) == [
        ("armony.stt_stream", "WARNING", "AssemblyAI server error: code=3005 detail=too fast")]


def test_stop_close_failure_is_logged_at_debug(stt, caplog):
    caplog.set_level(logging.DEBUG, logger="armony")
    ws = FakeWS()
    ws.close = lambda: (_ for _ in ()).throw(OSError("already closed"))
    stt._ws, stt._running = ws, True

    stt.stop()

    assert log_entries(caplog) == [
        ("armony.stt_stream", "DEBUG", "Closing the WebSocket failed")]


def test_connect_close_failure_is_logged_at_debug(stt, fake_connect, caplog):
    caplog.set_level(logging.DEBUG, logger="armony")
    ws = FakeWS()
    ws.close = lambda: (_ for _ in ()).throw(OSError("already closed"))
    fake_connect(ws)
    stt._running = True

    stt._conectar_y_escuchar()

    assert log_entries(caplog) == [
        ("armony.stt_stream", "DEBUG", "Closing the WebSocket failed")]
