"""CoachEngine behavior with synchronous audio, STT, clock and LLM boundaries."""
import importlib
import json
import queue
import sys
import threading
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

import config
import engine
from metrics import metricas


class ManualThread:
    """Capture scheduled work without starting a background thread."""

    def __init__(self, target, args=(), daemon=False):
        self.target, self.args, self.daemon = target, args, daemon
        self.started = False
        self.joined = []

    def start(self):
        self.started = True

    def join(self, timeout=None):
        self.joined.append(timeout)


class ManualTimer:
    """Expose timer expiry to the test thread."""

    def __init__(self, interval, function):
        self.interval, self.function = interval, function
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if self.started and not self.cancelled:
            self.function()


class FakeCoach:
    def __init__(self, chunks=(), **kwargs):
        self.chunks = chunks
        self.options = kwargs
        self.calls = []
        self.failure = None
        self.warmup_ms = 250

    def stream_response(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            kwargs["on_error"](self.failure)
            return
        for chunk in self.chunks:
            kwargs["on_delta"](chunk)
        kwargs["on_done"]()

    def calentar(self):
        return self.warmup_ms


class FakeDevice:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.started = False
        self.stopped = False
        self.frames = []

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def feed(self, pcm):
        self.frames.append(pcm)


class FakeTranscriber:
    def __init__(self, text="", **kwargs):
        self.text = text
        self.options = kwargs
        self.device = "cpu"
        self.samples = []

    def transcribe(self, samples):
        self.samples.append(samples)
        return self.text


def fail_load(**_kwargs):
    raise RuntimeError("load failed")


def run_items(subject, *items):
    """Exercise the real worker until its sentinel, without a worker thread."""
    work = queue.Queue()
    for item in items:
        work.put(item)
    work.put(None)
    subject._process_loop(work, threading.Event())


def utterance(source="system", reason="silence"):
    return {"type": "utterance", "audio": np.array([0.2, -0.1], np.float32),
            "source": source, "reason": reason}


@pytest.fixture
def subject(monkeypatch):
    monkeypatch.setattr(engine.threading, "Timer", ManualTimer)
    result = engine.CoachEngine()
    result._running = True
    result._stop_event = threading.Event()
    result._coach = FakeCoach()
    yield result
    result._cancel_turn_timer()


@pytest.fixture
def events(subject):
    recorded = []
    for name in ("sysLevel", "micLevel", "sttLatency", "e2eLatency", "transcript",
                 "partial", "noAnswer", "respStart", "respDelta", "respDone",
                 "status", "error"):
        getattr(subject, name).connect(
            lambda *args, signal=name: recorded.append((signal, *args)))
    return recorded


@pytest.fixture
def scheduled(monkeypatch):
    threads = []

    def create_thread(**kwargs):
        thread = ManualThread(**kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(engine.threading, "Thread", create_thread)
    return threads


@pytest.fixture
def cfg():
    return dict(config.DEFAULTS, anthropic_api_key="fake-anthropic",
                openai_api_key="fake-openai", assemblyai_api_key="fake-stt",
                anthropic_model_voice="voice", anthropic_model_vision="vision",
                anthropic_tokens_voice=100, anthropic_tokens_vision=300,
                openai_model_voice="o-voice", openai_model_vision="o-vision",
                system_prompt_es="Reglas", system_prompt_en="Rules",
                whisper_device="cpu")


@pytest.fixture
def dependencies(monkeypatch, scheduled):
    import audio
    import cuda_setup
    import llm
    import stt_stream

    stub = ModuleType("faster_whisper")
    stub.WhisperModel = fail_load
    monkeypatch.setitem(sys.modules, "faster_whisper", stub)
    monkeypatch.setattr(cuda_setup, "register_cuda_dlls", lambda: [])
    # Record both absent and previously imported modules for teardown restoration.
    monkeypatch.setitem(sys.modules, "transcribe", None)
    monkeypatch.delitem(sys.modules, "transcribe")
    transcribe = importlib.import_module("transcribe")
    monkeypatch.setattr(transcribe, "Transcriber", FakeTranscriber)
    monkeypatch.setattr(audio, "AudioEngine", FakeDevice)
    monkeypatch.setattr(stt_stream, "StreamingSTT", FakeDevice)
    monkeypatch.setattr(llm, "Coach", FakeCoach)
    return SimpleNamespace(transcribe=transcribe, llm=llm)


class TestHelpers:
    @pytest.mark.parametrize("text,limit,expected", [
        ("# Title\nHello  world\n```py\nprint(1)\n```\nBye", 240,
         "Hello world [código] Bye"),
        ("abcdefgh", 5, "abcde…"),
        ("abcde", 5, "abcde"),
        (None, 240, ""),
    ])
    def test_summary_removes_nonspoken_content(self, text, limit, expected):
        """Catch code or headings leaking into the spoken context summary."""
        assert engine._resumen(text, limit) == expected

    @pytest.mark.parametrize("options,expected", [
        ({"system_prompt_es": " ES ", "system_prompt_en": " EN "},
         "ES\n\n---\n\n(The same instructions in English; follow whichever matches "
         "the language being spoken.)\n\nEN"),
        ({"system_prompt_es": " ES ", "system_prompt": "old"}, "ES"),
        ({"system_prompt_en": " EN "}, "EN"),
        ({"system_prompt_es": " ", "system_prompt": "old"}, "old"),
        ({}, ""),
    ])
    def test_prompt_preserves_available_languages(self, options, expected):
        """Catch loss of a translated prompt or its legacy fallback."""
        assert engine._prompt_bilingue(options) == expected

    @pytest.mark.parametrize("samples,expected", [
        ([0.2, -0.4], [0.475, -0.95]),
        ([0.0, 0.00001], [0.0, 0.00001]),
        ([], []),
    ])
    def test_normalize_preserves_signal_shape(self, samples, expected):
        """Catch clipping, noise amplification or empty-array failures."""
        result = engine.CoachEngine._normalize(np.array(samples, np.float32))

        np.testing.assert_allclose(result, expected, rtol=1e-6)
        assert result.dtype == np.float32


class TestLifecycle:
    def test_start_discards_previous_session(self, subject, cfg, scheduled):
        """Catch old sentinel, transcript or partial turns surviving restart."""
        subject._running = False
        old_queue = subject._queue
        old_queue.put(None)
        subject._history.append(("Ellos", "old"))
        subject._registro.append(("Ellos", "old"))
        subject._turn_parts = ["old"]
        subject._last_heard = subject._last_question = "old"
        subject._heard_respondido = True
        subject._t_pregunta = 10

        subject.start(cfg, test_mode=True)

        assert subject._queue is not old_queue
        assert subject._queue.qsize() == 0
        assert (list(subject._history), subject._registro, subject._turn_parts) == ([], [], [])
        assert (subject._last_heard, subject._last_question, subject._heard_respondido,
                subject._t_pregunta) == ("", "", False, 0.0)
        assert (subject._running, subject._test_mode, subject._stop_event.is_set()) == (True, True, False)
        assert len(scheduled) == 1
        assert scheduled[0].args == (cfg,)
        assert scheduled[0].started is True

    def test_start_is_idempotent(self, subject, cfg, scheduled):
        """Catch repeated start replacing an active session queue."""
        original_queue = subject._queue
        subject._history.append(("Ellos", "keep"))

        subject.start(cfg)

        assert subject._queue is original_queue
        assert list(subject._history) == [("Ellos", "keep")]
        assert scheduled == []

    @pytest.mark.parametrize("provider,offline,expected", [
        ("anthropic", False, ["proveedor: anthropic", "transcripcion: universal-3-5-pro",
                              "voz: voice · capturas: vision"]),
        ("openai", False, ["proveedor: openai", "transcripcion: universal-3-5-pro",
                           "voz: o-voice · capturas: o-vision"]),
        ("anthropic", True, ["proveedor: anthropic", "transcripcion: whisper base (cpu)"]),
    ])
    def test_start_records_configuration(self, subject, cfg, scheduled, provider, offline, expected):
        """Catch metrics attributing a session to the wrong provider or STT."""
        subject._running = False
        cfg.update(llm_provider=provider, offline_mode=offline)

        subject.start(cfg)

        assert metricas.resumen()["notas"] == expected

    @pytest.mark.parametrize("offline,test_mode,status,capture_mic", [
        (False, False, "Escuchando la reunion. Habla y aparecera la sugerencia.", False),
        (False, True, "MODO PRUEBA: transcribe la reunion en vivo. No se llama a Claude.", False),
        (True, True, "MODO PRUEBA: transcribe reunion y microfono. No se llama a Claude.", True),
        (True, False, "Escuchando la reunion. Habla y aparecera la sugerencia.", True),
    ])
    def test_init_selects_capture_path(self, subject, cfg, dependencies, events,
                                      offline, test_mode, status, capture_mic):
        """Catch cloud/offline capture wiring or test mode starting the wrong path."""
        subject._offline, subject._test_mode = offline, test_mode

        subject._init_and_run(cfg)

        assert events[-1] == ("status", status)
        assert subject._audio.started is True
        assert subject._audio.options["capture_mic_utterances"] is capture_mic
        assert subject._audio.options["segment_system"] is offline
        assert subject._worker.args == (subject._queue, subject._stop_event)
        assert subject._worker.started is True

    def test_cloud_audio_reaches_stream(self, subject, cfg, dependencies, events):
        """Catch PCM or level callbacks disconnected from the live stream."""
        subject._init_and_run(cfg)
        events.clear()

        subject._audio.options["on_system_pcm"](b"pcm")
        subject._audio.options["on_sys_level"](42)
        subject._audio.options["on_mic_level"](17)
        subject._stt.options["on_status"]("connected")
        subject._stt.options["on_error"]("disconnected")
        subject._audio.options["on_status"]("audio ready")

        assert subject._stt.frames == [b"pcm"]
        assert events == [("sysLevel", 42), ("micLevel", 17),
                          ("status", "connected"), ("error", "disconnected"),
                          ("status", "audio ready")]

    def test_missing_stream_key_stops_initialization(self, subject, cfg, dependencies, events):
        """Catch starting audio without streaming credentials."""
        cfg["assemblyai_api_key"] = ""

        subject._init_and_run(cfg)

        assert subject._running is False
        assert subject._audio is None
        assert events == [("error", "Falta la API key de AssemblyAI. Ponla en Ajustes, "
                           "o activa el modo offline para transcribir con Whisper local.")]

    def test_whisper_load_failure_is_reported(self, subject, cfg, dependencies, events, monkeypatch):
        """Catch a failed local model leaving the session marked running."""
        subject._offline = True
        monkeypatch.setattr(dependencies.transcribe, "Transcriber", fail_load)

        subject._init_and_run(cfg)

        assert subject._running is False
        assert events[-1] == ("error", "No se pudo cargar Whisper: load failed")
        assert subject._audio is None

    def test_coach_load_failure_is_reported(self, subject, cfg, dependencies, events, monkeypatch):
        """Catch a failed model client silently starting an unusable worker."""
        monkeypatch.setattr(dependencies.llm, "Coach", fail_load)

        subject._init_and_run(cfg)

        assert subject._running is False
        assert subject._worker is None
        assert events[-1] == ("error", "No se pudo iniciar Claude: load failed")

    def test_coach_load_failure_closes_transcription_stream(self, subject, cfg, dependencies,
                                                            monkeypatch):
        """Catch a failed start leaving the per-second billed STT socket open."""
        import stt_stream
        created = []
        monkeypatch.setattr(stt_stream, "StreamingSTT",
                            lambda **kw: created.append(FakeDevice(**kw)) or created[-1])
        monkeypatch.setattr(dependencies.llm, "Coach", fail_load)

        subject._init_and_run(cfg)

        assert (created[0].started, created[0].stopped, subject._stt) == (True, True, None)

    def test_failed_start_reports_not_running(self, subject, cfg, dependencies, monkeypatch):
        """Catch the public running flag disagreeing with a failed start."""
        monkeypatch.setattr(dependencies.llm, "Coach", fail_load)

        subject._init_and_run(cfg)

        assert subject.running is False

    def test_coach_receives_bilingual_prompt(self, subject, cfg, dependencies):
        """Catch initialization dropping English rules or model token limits."""
        subject._init_and_run(cfg)

        assert subject._coach.options == {
            "api_key": "fake-anthropic", "provider": "anthropic",
            "system_prompt": "Reglas\n\n---\n\n(The same instructions in English; follow "
                             "whichever matches the language being spoken.)\n\nRules",
            "model_voice": "voice", "tokens_voice": 100,
            "model_vision": "vision", "tokens_vision": 300,
        }

    def test_warmup_reports_latency(self, subject, events):
        """Catch warmup latency disappearing from session metrics."""
        subject._calentar()

        assert events == [("status", "Modelo listo (0.2 s de calentamiento).")]
        assert metricas.resumen()["medidas"]["llm_calentamiento_ms"] == {
            "n": 1, "mediana": 250, "p90": 250, "min": 250, "max": 250}


class TestTurns:
    def test_partial_contains_closed_fragments(self, subject, events):
        """Catch partial text replacing preceding fragments of the same turn."""
        subject._turn_parts = ["Primera frase.", "Segunda frase."]

        subject._on_stt_partial("Continuación")

        assert events == [("partial", "Primera frase. Segunda frase. Continuación")]

    def test_question_flushes_without_timer(self, subject, events):
        """Catch a recognized question waiting for the silence timer."""
        subject._turn_parts = ["El informe está listo."]

        subject._on_stt_final("¿Lo revisas?", 150)

        assert subject._queue.get_nowait() == {
            "type": "respond", "text": "El informe está listo. ¿Lo revisas?", "auto": True}
        assert subject._turn_timer is None
        assert subject._registro == [("Ellos", "El informe está listo. ¿Lo revisas?")]
        assert metricas.resumen()["cuentas"] == {"intervenciones": 1, "con_pregunta": 1}
        assert events == [("sttLatency", 150),
                          ("partial", "El informe está listo. ¿Lo revisas?"),
                          ("transcript", "system", "El informe está listo. ¿Lo revisas?")]

    def test_statement_flushes_on_timer(self, subject, events):
        """Catch ordinary statements being sent to the LLM automatically."""
        subject._on_stt_final("El informe está listo.", 90)
        timer = subject._turn_timer

        timer.fire()

        assert timer.interval == 0.7
        assert subject._queue.qsize() == 0
        assert list(subject._history) == [("Ellos", "El informe está listo.")]
        assert subject._registro == [("Ellos", "El informe está listo.")]
        assert events[-1] == ("noAnswer", "no_question")
        assert metricas.resumen()["cuentas"] == {"intervenciones": 1, "solo_contexto": 1}

    def test_next_final_replaces_timer(self, subject):
        """Catch an earlier timer closing a turn during its next fragment."""
        subject._on_stt_final("Primera frase.", 80)
        previous = subject._turn_timer

        subject._on_stt_final("Segunda frase.", 90)
        previous.fire()

        assert previous.cancelled is True
        assert subject._turn_parts == ["Primera frase.", "Segunda frase."]
        assert subject._queue.qsize() == 0

    def test_test_mode_emits_transcript_only(self, subject, events):
        """Catch transcription test mode queueing a model request."""
        subject._test_mode = True

        subject._on_stt_final("¿Lo revisas?", 123)

        assert events == [("sttLatency", 123), ("transcript", "system", "¿Lo revisas?"),
                          ("status", "Transcrito en 123 ms (reunion).")]
        assert subject._queue.qsize() == 0
        assert subject._turn_parts == []

    def test_stopped_session_ignores_stt(self, subject, events):
        """Catch late stream callbacks changing a stopped session."""
        subject._running = False

        subject._on_stt_partial("late")
        subject._on_stt_final("¿Late?", 10)

        assert events == []
        assert subject._queue.qsize() == 0

    @pytest.mark.parametrize("running,parts", [(True, []), (False, ["¿Lo revisas?"])])
    def test_flush_without_active_turn_is_ignored(self, subject, events, running, parts):
        """Catch empty or stopped turns reaching history or model work."""
        subject._running, subject._turn_parts = running, parts

        subject._flush_turn()

        assert events == []
        assert list(subject._history) == []
        assert subject._queue.qsize() == 0

    def test_manual_answer_closes_pending_turn(self, subject, events):
        """Catch manual answering losing unfinished fragments or permitting silence."""
        subject._on_stt_final("Primera frase.", 20)
        timer = subject._turn_timer
        events.clear()

        subject.answer_now()

        assert subject._queue.get_nowait() == {
            "type": "respond", "text": "Primera frase.", "auto": False}
        assert timer.cancelled is True
        assert list(subject._history) == [("Ellos", "Primera frase.")]
        assert events == [("transcript", "system", "Primera frase.")]
        assert subject._last_heard == "Primera frase."

    @pytest.mark.xfail(strict=True, raises=AssertionError,
                       reason="[KNOWN-002] Manual pending turns are omitted from the session transcript")
    def test_manual_answer_records_pending_turn(self, subject):
        """Catch a manually closed turn disappearing from the saved transcript."""
        subject._turn_parts = ["Primera frase."]

        subject.answer_now()

        assert subject._registro == [("Ellos", "Primera frase.")]

    def test_manual_answer_uses_last_heard(self, subject):
        """Catch manual answering using an older answered question."""
        subject._last_heard = "La entrega es mañana."
        subject._last_question = "¿La entrega es hoy?"

        subject.answer_now()

        assert subject._queue.get_nowait() == {
            "type": "respond", "text": "La entrega es mañana.", "auto": False}
        assert list(subject._history) == []

    def test_manual_answer_without_speech_reports_status(self, subject, events):
        """Catch an empty manual answer request reaching the model."""
        subject.answer_now()

        assert events == [("status", "Aun no hay nada que responder.")]
        assert subject._queue.qsize() == 0


class TestCommands:
    @pytest.mark.parametrize("running,test_mode", [(False, False), (True, True)])
    @pytest.mark.parametrize("method", ["answer_now", "regenerate"])
    def test_inactive_commands_are_ignored(self, subject, running, test_mode, method):
        """Catch stopped or transcription-only sessions requesting completions."""
        subject._running, subject._test_mode = running, test_mode
        subject._last_heard = subject._last_question = "¿Lo revisas?"

        getattr(subject, method)()

        assert subject._queue.qsize() == 0

    def test_regenerate_preserves_note(self, subject):
        """Catch regeneration dropping the user's revision instruction."""
        subject._last_question = "¿Lo revisas?"

        subject.regenerate("Más corto")

        assert subject._queue.get_nowait() == {"type": "regen", "note": "Más corto"}

    def test_regenerate_without_question_reports_status(self, subject, events):
        """Catch regeneration issuing a request before any question exists."""
        subject.regenerate()

        assert events == [("status", "Aun no hay ninguna pregunta que responder.")]
        assert subject._queue.qsize() == 0

    def test_screenshot_request_owns_image_list(self, subject):
        """Catch the UI clearing images already queued for model work."""
        images = ["png-a", "png-b"]

        subject.request_screenshots(images)
        images.clear()

        assert subject._queue.get_nowait() == {"type": "screenshot", "images": ["png-a", "png-b"]}

    @pytest.mark.parametrize("running,images", [(False, ["png"]), (True, [])])
    def test_unavailable_screenshots_are_not_queued(self, subject, running, images):
        """Catch empty or stopped screenshot requests entering the worker."""
        subject._running = running

        subject.request_screenshots(images)

        assert subject._queue.qsize() == 0

    def test_utterance_drops_oldest_backlog(self, subject):
        """Catch stale audio displacing the latest three segments."""
        subject._queue.put({"type": "old"})
        subject._queue.put({"type": "second"})
        subject._queue.put({"type": "third"})

        subject._on_utterance(b"pcm", "mic", "maxlen")

        assert subject._queue.qsize() == 3
        assert subject._queue.get_nowait() == {"type": "second"}
        assert subject._queue.get_nowait() == {"type": "third"}
        assert subject._queue.get_nowait() == {
            "type": "utterance", "audio": b"pcm", "source": "mic", "reason": "maxlen"}


class TestWorker:
    @pytest.mark.parametrize("source,reason,text,history,responses", [
        ("mic", "silence", "¿Lo revisas?", [("Yo", "¿Lo revisas?")], 0),
        ("system", "silence", "¿Lo revisas?", [("Ellos", "¿Lo revisas?")], 1),
        ("system", "maxlen", "¿Lo revisas?", [("Ellos", "¿Lo revisas?")], 0),
        ("system", "silence", "El informe está listo.", [("Ellos", "El informe está listo.")], 0),
        ("system", "silence", "", [], 0),
    ])
    def test_utterance_response_routing(self, subject, source, reason, text, history, responses):
        """Catch microphone, empty or max-length segments triggering a response."""
        subject._transcriber = FakeTranscriber(text)

        run_items(subject, utterance(source, reason))

        assert list(subject._history) == history
        assert len(subject._coach.calls) == responses

    def test_offline_test_mode_only_transcribes(self, subject, events, monkeypatch):
        """Catch offline test mode retaining conversation or invoking the model."""
        subject._test_mode = True
        subject._transcriber = FakeTranscriber("¿Lo revisas?")
        monkeypatch.setattr(engine.time, "time", lambda: 10.0)

        run_items(subject, utterance("mic"))

        assert events == [("sttLatency", 0), ("transcript", "mic", "¿Lo revisas?"),
                          ("status", "Transcrito en 0 ms (mic, silence).")]
        assert list(subject._history) == []
        assert subject._coach.calls == []

    @pytest.mark.parametrize("normalize,expected", [(True, [0.95, -0.475]),
                                                    (False, [0.2, -0.1])])
    def test_worker_honors_normalization_setting(self, subject, normalize, expected):
        """Catch the offline worker ignoring automatic normalization settings."""
        subject._auto_normalize = normalize
        subject._transcriber = FakeTranscriber()

        run_items(subject, utterance())

        np.testing.assert_allclose(subject._transcriber.samples[0], expected, rtol=1e-6)

    @pytest.mark.parametrize("source,expected", [
        ("mic", [("Yo", "El informe está listo.")]),
        ("system", [("Ellos", "El informe está listo.")]),
    ])
    @pytest.mark.xfail(strict=True, raises=AssertionError,
                       reason="[KNOWN-002] Offline utterances are omitted from the session transcript")
    def test_offline_utterance_is_recorded(self, subject, source, expected):
        """Catch offline speech disappearing from the saved meeting transcript."""
        subject._transcriber = FakeTranscriber("El informe está listo.")

        run_items(subject, utterance(source))

        assert subject._registro == expected

    @pytest.mark.parametrize("item,latest,images,note,silence", [
        ({"type": "respond", "text": "¿Ahora?", "auto": True}, "¿Ahora?", None, "", True),
        ({"type": "respond", "text": "Ahora"}, "Ahora", None, "", False),
        ({"type": "regen", "note": "Shorter"}, "¿Antes?", None, "Shorter", False),
        ({"type": "screenshot", "images": ["png"]}, "Mira esto", ["png"], "", False),
    ])
    def test_worker_dispatches_model_request(self, subject, item, latest, images, note, silence):
        """Catch command dispatch dropping images, revision notes or silence policy."""
        subject._last_question, subject._last_heard = "¿Antes?", "Mira esto"

        run_items(subject, item)

        request = subject._coach.calls[0]
        assert (request["latest"], request["images"], request["note"],
                request["allow_silence"]) == (latest, images, note, silence)

    def test_worker_continues_after_item_error(self, subject, events):
        """Catch a malformed work item killing subsequent model requests."""
        run_items(subject, {"type": "utterance"}, {"type": "respond", "text": "Next"})

        assert events == [("error", "'audio'")]
        assert subject._coach.calls[0]["latest"] == "Next"

    def test_stop_event_prevents_consumption(self, subject):
        """Catch a retired worker consuming its old queue after stop."""
        subject._queue.put({"type": "respond", "text": "Old"})
        subject._stop_event.set()

        subject._process_loop(subject._queue, subject._stop_event)

        assert subject._queue.qsize() == 1
        assert subject._coach.calls == []


class TestStreaming:
    @pytest.mark.parametrize("chunks", [
        ["NO_RESPONSE"], ["  NO_", "RESP", "ONSE", " ignored"],
    ])
    def test_sentinel_suppresses_response(self, subject, events, chunks):
        """Catch split or whitespace-prefixed sentinel text flashing in the UI."""
        subject._coach.chunks = chunks

        subject._respond("A statement", permitir_silencio=True)

        assert events == [("status", "Sin pregunta todavia: guardado como contexto."),
                          ("noAnswer", "model_declined")]
        assert subject._registro == []
        assert list(subject._history) == []
        assert subject._coach.calls[0]["allow_silence"] is True

    def test_normal_stream_opens_once(self, subject, events):
        """Catch lost prefix chunks or duplicate response-start signals."""
        subject._coach.chunks = ["Hello ", "world!", " More."]

        subject._respond("Question")

        assert events == [("respStart",), ("respDelta", "Hello world!"),
                          ("respDelta", " More."), ("respDone",)]

    def test_short_response_opens_on_done(self, subject, events):
        """Catch a valid answer shorter than the sentinel being discarded."""
        subject._coach.chunks = ["Sí."]

        subject._respond("Question")

        assert events == [("respStart",), ("respDelta", "Sí."), ("respDone",)]

    @pytest.mark.parametrize("chunks", [[], ["   "]])
    def test_empty_response_does_not_open(self, subject, events, chunks):
        """Catch empty or whitespace model output creating a response bubble."""
        subject._coach.chunks = chunks

        subject._respond("Question")

        assert events == []
        assert subject._registro == []

    def test_response_persists_full_transcript(self, subject):
        """Catch code being removed from the full transcript instead of only context."""
        subject._coach.chunks = ["# Heading\nAnswer\n```py\nx = 1\n```"]

        subject._respond("Question")

        assert list(subject._history) == [("Yo (sugerido)", "Answer [código]")]
        assert subject._registro == [("Sugerido", "# Heading\nAnswer\n```py\nx = 1\n```")]

    def test_first_response_token_measures_e2e_once(self, subject, events, monkeypatch):
        """Catch per-chunk latency emission or failure to clear the question clock."""
        subject._t_pregunta = 10.0
        subject._coach.chunks = ["Hello world!", " Again."]
        monkeypatch.setattr(engine.time, "monotonic", lambda: 10.25)

        subject._respond("Question")

        assert events == [("e2eLatency", 250), ("respStart",),
                          ("respDelta", "Hello world!"), ("respDelta", " Again."), ("respDone",)]
        assert subject._t_pregunta == 0.0
        assert metricas.resumen()["medidas"]["extremo_a_extremo_ms"]["n"] == 1

    def test_model_error_reaches_ui(self, subject, events):
        """Catch an SDK failure being swallowed by response buffering."""
        subject._coach.failure = "provider unavailable"

        subject._respond("Question")

        assert events == [("error", "provider unavailable")]

    def test_answered_turn_is_not_reused_for_capture(self, subject):
        """Catch screenshots answering the same spoken question twice."""
        subject._last_heard = "¿Lo revisas?"
        subject._respond("¿Lo revisas?")

        subject._responder_capturas(["png"])

        assert subject._coach.calls[1]["latest"] == (
            "(no han dicho nada nuevo desde la ultima respuesta: lo que hay que resolver esta en las capturas)")
        assert subject._coach.calls[1]["images"] == ["png"]

    def test_capture_uses_unanswered_turn(self, subject):
        """Catch captures pairing with an older question instead of current speech."""
        subject._last_question, subject._last_heard = "Old question", "Mira esto"

        subject._responder_capturas(["png"])

        assert subject._coach.calls[0]["latest"] == "Mira esto"
        assert subject._coach.calls[0]["allow_silence"] is False


class TestContext:
    def test_context_excludes_latest_duplicate(self, subject):
        """Catch the current question being sent twice to the model."""
        subject._history.extend([("Yo", "Listo"), ("Ellos", "¿Ahora?")])

        result = subject._contexto(False, "¿Ahora?")

        assert result == "Yo: Listo"

    @pytest.mark.parametrize("capture,count", [(False, 36), (True, 80)])
    def test_context_keeps_recent_entry_limit(self, subject, capture, count):
        """Catch stale entries displacing the newest voice or screenshot context."""
        subject._history.extend([("Ellos", "old")] * 81)
        subject._history.extend([("Yo", "recent")] * count)

        result = subject._contexto(capture)

        assert result.splitlines() == ["Yo: recent"] * count
        assert "old" not in result

    def test_capture_discards_oldest_oversized_context(self, subject):
        """Catch screenshot context trimming recent speech before older entries."""
        subject._history.extend([("Ellos", "x" * 7990), ("Yo", "Recent")])

        result = subject._contexto(True)

        assert result == "Yo: Recent"

    @pytest.mark.xfail(strict=True, raises=AssertionError,
                       reason="[KNOWN-701] Capture context budget excludes newline separators")
    def test_capture_limit_includes_line_separators(self, subject):
        """Catch the serialized screenshot context exceeding its 8000-character cap."""
        subject._history.extend([("A", "x" * 3997), ("B", "y" * 3997)])

        result = subject._contexto(True)

        assert len(result) <= 8000


class TestPersistence:
    def test_stop_releases_resources_in_order(self, subject, tmp_path):
        """Catch audio or STT producing work after the worker has been retired."""
        calls = []
        subject._audio = SimpleNamespace(stop=lambda: calls.append("audio"))
        subject._turn_timer = SimpleNamespace(cancel=lambda: calls.append("timer"))
        subject._stt = SimpleNamespace(stop=lambda: calls.append("stt"))
        subject._worker = SimpleNamespace(join=lambda timeout: calls.append(("join", timeout)))
        subject._queue.put({"type": "stale"})
        subject._turn_parts = ["unfinished"]

        subject.stop()

        assert calls == ["audio", "timer", "stt", ("join", 3.0)]
        assert subject._running is False
        assert subject._stop_event.is_set() is True
        assert subject._queue.qsize() == 0
        assert subject._turn_parts == []
        assert (subject._audio, subject._stt, subject._worker) == (None, None, None)

    def test_stop_persists_session_metrics(self, subject, tmp_path):
        """Catch stop discarding the session metrics report."""
        metricas.contar("intervenciones", 2)

        subject.stop()

        reports = list((tmp_path / "metricas").glob("sesion-*.json"))
        assert len(reports) == 1
        assert json.loads(reports[0].read_text(encoding="utf-8"))["cuentas"] == {"intervenciones": 2}

    def test_stop_persists_transcript(self, subject, tmp_path, monkeypatch):
        """Catch missing speaker labels or stripped code in the saved Markdown."""
        subject._registro = [("Ellos", " Pregunta "), ("Sugerido", " ```py\nx = 1\n``` ")]
        formats = {"%Y%m%d-%H%M%S": "20261028-123000", "%d/%m/%Y %H:%M": "28/10/2026 12:30"}
        monkeypatch.setattr(engine.time, "strftime", lambda fmt: formats[fmt])

        subject.stop()

        assert (tmp_path / "sesiones" / "sesion-20261028-123000.md").read_text(encoding="utf-8") == (
            "# Reunion del 28/10/2026 12:30\n\n**Ellos:** Pregunta\n\n"
            "### Sugerido\n\n```py\nx = 1\n```\n\n")

    def test_stop_when_idle_writes_nothing(self, subject, tmp_path):
        """Catch repeated stop saving a spurious second session."""
        subject._running = False

        subject.stop()

        assert list(tmp_path.iterdir()) == []

    def test_empty_transcript_writes_nothing(self, subject, tmp_path):
        """Catch an empty meeting creating a transcript file."""
        result = subject._guardar_acta(str(tmp_path))

        assert result is None
        assert list(tmp_path.iterdir()) == []

    def test_transcript_io_error_is_nonfatal(self, subject, tmp_path):
        """Catch an unwritable transcript destination raising during shutdown."""
        subject._registro = [("Ellos", "Hello")]
        blocked = tmp_path / "blocked"
        blocked.write_text("file", encoding="utf-8")

        result = subject._guardar_acta(str(blocked))

        assert result is None
        assert blocked.read_text(encoding="utf-8") == "file"
