"""Tests for audio: the energy segmenter, WASAPI device picking and AudioEngine.

PyAudio/WASAPI and the clock are the only boundaries replaced. Capture loops
run in the test thread (``_capture`` called directly) with a fake stream that
yields scripted int16 blocks and then raises, which ends the loop.
"""
import threading
from types import SimpleNamespace

import numpy as np
import pytest

import audio

# ---------------------------------------------------------------------------
# Segmenter helpers. Blocks of 1600 samples = 0.1 s at 16 kHz.
# Parameters chosen so every threshold is an exact sample count:
#   silence_hang 0.5 s -> 8000 samples (5 blocks)
#   min_speech  0.25 s -> 4000 samples (3 speech blocks pass, 2 do not)
#   max_utt      1.0 s -> 16000 samples (10 blocks)
#   preroll     0.25 s -> 4000 samples
# ---------------------------------------------------------------------------
BLOCK = 1600
SEG_PARAMS = dict(speech_thresh=0.012, silence_hang=0.5, min_speech=0.25,
                  max_utt=1.0, preroll=0.25)


def speech(n=BLOCK):
    """Constant-amplitude block, RMS 0.5 (well above the threshold)."""
    return np.full(n, 0.5, dtype=np.float32)


def silence(n=BLOCK):
    return np.zeros(n, dtype=np.float32)


def feed(segmenter, *blocks):
    for block in blocks:
        segmenter.process(block)


def blocks(factory, count):
    return [factory() for _ in range(count)]


class UtteranceSink:
    def __init__(self):
        self.calls = []

    def __call__(self, utt, reason):
        self.calls.append((utt, reason))


@pytest.fixture
def sink():
    return UtteranceSink()


@pytest.fixture
def seg(sink):
    return audio._Segmenter(sink, **SEG_PARAMS)


# --- _Segmenter -------------------------------------------------------------

def test_segmenter_emits_after_silence_hang(seg, sink):
    feed(seg, *blocks(speech, 3), *blocks(silence, 5))

    assert [reason for _, reason in sink.calls] == ["silence"]


def test_segmenter_waits_for_full_silence_hang(seg, sink):
    feed(seg, *blocks(speech, 3), *blocks(silence, 4))

    assert sink.calls == []


def test_segmenter_utterance_contains_speech_plus_trailing_silence(seg, sink):
    # 3 x 1600 speech + 5 x 1600 silence = 12800 samples
    feed(seg, *blocks(speech, 3), *blocks(silence, 5))

    assert [utt.size for utt, _ in sink.calls] == [12800]


def test_segmenter_utterance_is_float32(seg, sink):
    feed(seg, *blocks(speech, 3), *blocks(silence, 5))

    assert sink.calls[0][0].dtype == np.float32


def test_segmenter_cuts_at_max_utt_with_maxlen_reason(seg, sink):
    feed(seg, *blocks(speech, 10))

    assert [(utt.size, reason) for utt, reason in sink.calls] == [(16000, "maxlen")]


def test_segmenter_does_not_cut_before_max_utt(seg, sink):
    feed(seg, *blocks(speech, 9))

    assert sink.calls == []


def test_segmenter_discards_utterance_shorter_than_min_speech(seg, sink):
    # 2 x 1600 = 3200 speech samples < 4000
    feed(seg, *blocks(speech, 2), *blocks(silence, 5))

    assert sink.calls == []


def test_segmenter_ignores_audio_below_threshold(seg, sink):
    quiet = np.full(BLOCK, 0.01, dtype=np.float32)  # RMS 0.01 < 0.012

    feed(seg, *[quiet] * 20)

    assert sink.calls == []


def test_segmenter_prepends_preroll_before_speech_onset(seg, sink):
    # Preroll keeps the last 4000 samples including the triggering block:
    # 2400 zeros of prior silence + 1600 speech. Total 4000 + 3200 + 8000.
    feed(seg, *blocks(silence, 3), *blocks(speech, 3), *blocks(silence, 5))

    assert int(np.flatnonzero(sink.calls[0][0])[0]) == 2400


def test_segmenter_preroll_counts_toward_utterance_length(seg, sink):
    feed(seg, *blocks(silence, 3), *blocks(speech, 3), *blocks(silence, 5))

    assert sink.calls[0][0].size == 15200


def test_segmenter_resets_after_emitting(seg, sink):
    utterance = [*blocks(speech, 3), *blocks(silence, 5)]

    feed(seg, *utterance, *utterance)

    assert [utt.size for utt, _ in sink.calls] == [12800, 12800]


def test_segmenter_resets_after_discarding_short_utterance(seg, sink):
    feed(seg, *blocks(speech, 2), *blocks(silence, 5),
         *blocks(speech, 3), *blocks(silence, 5))

    assert [utt.size for utt, _ in sink.calls] == [12800]


def test_segmenter_starts_new_utterance_after_maxlen_cut(seg, sink):
    feed(seg, *blocks(speech, 10), *blocks(speech, 3), *blocks(silence, 5))

    assert [reason for _, reason in sink.calls] == ["maxlen", "silence"]


def test_segmenter_swallows_callback_exception():
    attempts = []

    def failing(utt, reason):
        attempts.append(reason)
        raise ValueError("consumer failed")

    seg = audio._Segmenter(failing, **SEG_PARAMS)
    utterance = [*blocks(speech, 3), *blocks(silence, 5)]

    feed(seg, *utterance, *utterance)

    assert attempts == ["silence", "silence"]


@pytest.mark.xfail(strict=True, reason="[KNOWN-301] preroll=0 keeps the whole "
                   "silence history ([-0:] slice) instead of no pre-roll")
def test_segmenter_without_preroll_starts_at_speech_onset(sink):
    seg = audio._Segmenter(sink, **{**SEG_PARAMS, "preroll": 0.0})

    feed(seg, *blocks(silence, 3), *blocks(speech, 3), *blocks(silence, 5))

    assert int(np.flatnonzero(sink.calls[0][0])[0]) == 0


@pytest.mark.xfail(strict=True, reason="[KNOWN-302] a block longer than the "
                   "pre-roll window loses its start: speech onset is cut")
def test_segmenter_keeps_whole_trigger_block_longer_than_preroll(sink):
    # preroll 0.05 s = 800 samples, trigger block 1600 samples of speech.
    seg = audio._Segmenter(sink, **{**SEG_PARAMS, "preroll": 0.05})

    feed(seg, *blocks(speech, 3), *blocks(silence, 5))

    assert int(np.count_nonzero(sink.calls[0][0])) == 4800


# ---------------------------------------------------------------------------
# Fake PyAudio (WASAPI boundary)
# ---------------------------------------------------------------------------
SPEAKERS = {"index": 2, "name": "Speakers (Realtek)", "defaultSampleRate": 48000.0,
            "maxInputChannels": 0, "isLoopbackDevice": False}
HEADPHONES = {"index": 3, "name": "Headphones (USB)", "defaultSampleRate": 48000.0,
              "maxInputChannels": 0, "isLoopbackDevice": False}
SPEAKERS_LB = {"index": 7, "name": "Speakers (Realtek) [Loopback]",
               "defaultSampleRate": 16000.0, "maxInputChannels": 1,
               "isLoopbackDevice": True}
HEADPHONES_LB = {"index": 9, "name": "Headphones (USB) [Loopback]",
                 "defaultSampleRate": 16000.0, "maxInputChannels": 1,
                 "isLoopbackDevice": True}
MIC = {"index": 1, "name": "Microphone (Realtek)", "defaultSampleRate": 16000.0,
       "maxInputChannels": 1}


class FakeStream:
    """Returns scripted chunks, then raises to end the capture loop."""

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.closed = False

    def read(self, frames, exception_on_overflow=True):
        if not self.chunks:
            raise OSError("stream ended")
        return self.chunks.pop(0)

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True


class BlockingStream(FakeStream):
    """Simulates a WASAPI loopback read stuck while nothing is playing."""

    def __init__(self, release):
        super().__init__()
        self.release = release

    def read(self, frames, exception_on_overflow=True):
        self.release.wait(timeout=10)
        raise OSError("released")


class FakePyAudio:
    def __init__(self, devices=(SPEAKERS, SPEAKERS_LB, MIC), default_output=2,
                 default_input=1, loopbacks=(SPEAKERS_LB,), streams=(),
                 default_input_error=None):
        self.devices = {d["index"]: d for d in devices}
        self.default_output = default_output
        self.default_input = default_input
        self.loopbacks = list(loopbacks)
        self.streams = list(streams)
        self.default_input_error = default_input_error
        self.opened = []
        self.terminated = 0

    def get_host_api_info_by_type(self, api):
        return {"defaultOutputDevice": self.default_output,
                "defaultInputDevice": self.default_input}

    def get_device_info_by_index(self, index):
        if index not in self.devices:
            raise OSError("Invalid device index")
        return self.devices[index]

    def get_loopback_device_info_generator(self):
        yield from self.loopbacks

    def get_default_input_device_info(self):
        if self.default_input_error is not None:
            raise self.default_input_error
        return self.devices[self.default_input]

    def open(self, **kwargs):
        self.opened.append(kwargs)
        stream = self.streams.pop(0) if self.streams else FakeStream()
        if isinstance(stream, Exception):
            raise stream
        return stream

    def terminate(self):
        self.terminated += 1


def pcm(value, frames=1024):
    """Mono int16 block with every sample equal to ``value``."""
    return np.full(frames, value, dtype=np.int16).tobytes()


def stereo_pcm(left, right, frames=1024):
    """Interleaved 2-channel int16 block."""
    data = np.empty(frames * 2, dtype=np.int16)
    data[0::2] = left
    data[1::2] = right
    return data.tobytes()


# --- device picking ---------------------------------------------------------

def test_pick_loopback_returns_default_output_already_loopback():
    p = FakePyAudio(default_output=9, devices=(HEADPHONES_LB,), loopbacks=())

    assert audio._pick_loopback_device(p) == HEADPHONES_LB


def test_pick_loopback_matches_default_output_by_name():
    p = FakePyAudio(default_output=2, loopbacks=(HEADPHONES_LB, SPEAKERS_LB))

    assert audio._pick_loopback_device(p) == SPEAKERS_LB


def test_pick_loopback_falls_back_to_first_loopback():
    p = FakePyAudio(default_output=2, loopbacks=(HEADPHONES_LB,))

    assert audio._pick_loopback_device(p) == HEADPHONES_LB


def test_pick_loopback_without_loopbacks_raises():
    p = FakePyAudio(default_output=2, loopbacks=())

    with pytest.raises(RuntimeError, match="loopback"):
        audio._pick_loopback_device(p)


def test_pick_input_returns_default_input():
    p = FakePyAudio()

    assert audio._pick_input_device(p) == MIC


def test_pick_input_falls_back_to_wasapi_default():
    p = FakePyAudio(default_input_error=OSError("no default input"))

    assert audio._pick_input_device(p) == MIC


# ---------------------------------------------------------------------------
# AudioEngine
# ---------------------------------------------------------------------------
class EngineSink:
    def __init__(self):
        self.sys_levels = []
        self.mic_levels = []
        self.utterances = []
        self.statuses = []
        self.pcm = []

    def utterance(self, audio_block, source, reason):
        self.utterances.append((source, reason, audio_block.size))


class Clock:
    """Fake monotonic clock: returns ``now`` and then advances by ``step``."""

    def __init__(self, now=100.0, step=0.0):
        self.now = now
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(audio, "time", SimpleNamespace(monotonic=fake))
    return fake


@pytest.fixture
def es():
    return EngineSink()


def make_engine(es, **kwargs):
    return audio.AudioEngine(es.sys_levels.append, es.mic_levels.append,
                             es.utterance, es.statuses.append, **kwargs)


def run_capture(engine, p, device, is_loopback):
    """Run one capture loop synchronously until the fake stream ends."""
    engine._p = p
    engine._running = True
    engine._capture(device, is_loopback)


# --- levels, gain, downmix --------------------------------------------------

@pytest.mark.parametrize("sample, level", [
    (0, 0),
    (1092, 9),      # 0.0333 * 300 = 9.99 -> 9
    (8192, 75),     # 0.25 * 300
    (16384, 100),   # 0.5 * 300 = 150 -> capped
])
def test_system_level_is_scaled_rms(clock, es, sample, level):
    engine = make_engine(es)
    p = FakePyAudio(streams=[FakeStream([pcm(sample)])])

    run_capture(engine, p, SPEAKERS_LB, True)

    assert es.sys_levels == [level]


def test_mic_level_is_scaled_rms(clock, es):
    engine = make_engine(es)
    p = FakePyAudio(streams=[FakeStream([pcm(8192)])])

    run_capture(engine, p, MIC, False)

    assert es.mic_levels == [75]


@pytest.mark.parametrize("gain, sample, level", [
    (2.0, 4096, 75),    # 0.125 * 2 = 0.25 -> 75
    (0.5, 16384, 75),   # 0.5 * 0.5 = 0.25 -> 75
])
def test_system_gain_applied_before_level(clock, es, gain, sample, level):
    engine = make_engine(es, gain_system=gain)
    p = FakePyAudio(streams=[FakeStream([pcm(sample)])])

    run_capture(engine, p, SPEAKERS_LB, True)

    assert es.sys_levels == [level]


def test_mic_gain_applied_before_level(clock, es):
    engine = make_engine(es, gain_mic=2.0)
    p = FakePyAudio(streams=[FakeStream([pcm(4096)])])

    run_capture(engine, p, MIC, False)

    assert es.mic_levels == [75]


def test_stereo_input_is_downmixed_to_mono(clock, es):
    # L = 0.25, R = 0 -> mono 0.125 -> 37.5 -> 37
    engine = make_engine(es)
    device = {**SPEAKERS_LB, "maxInputChannels": 2}
    p = FakePyAudio(streams=[FakeStream([stereo_pcm(8192, 0)])])

    run_capture(engine, p, device, True)

    assert es.sys_levels == [37]


# --- system audio routing ---------------------------------------------------

def test_system_pcm_forwarded_at_16k(clock, es):
    # 1024 frames at 32 kHz -> 512 samples at 16 kHz
    engine = make_engine(es, on_system_pcm=es.pcm.append)
    device = {**SPEAKERS_LB, "defaultSampleRate": 32000.0}
    p = FakePyAudio(streams=[FakeStream([pcm(8192)])])

    run_capture(engine, p, device, True)

    assert [(b.dtype, b.shape) for b in es.pcm] == [(np.float32, (512,))]


def test_system_pcm_callback_exception_is_swallowed(clock, es):
    def failing(block):
        raise ValueError("stream consumer failed")

    engine = make_engine(es, on_system_pcm=failing)
    p = FakePyAudio(streams=[FakeStream([pcm(8192), pcm(8192)])])

    run_capture(engine, p, SPEAKERS_LB, True)

    assert es.sys_levels == [75, 75]


def speech_then_silence():
    """8 loud blocks (8192 speech samples >= 6400) then 11 silent blocks
    (11264 >= 0.7 s * 16000 = 11200): one utterance of 19456 samples."""
    return [pcm(8192)] * 8 + [pcm(0)] * 11


def test_system_audio_segmented_into_utterance(clock, es):
    engine = make_engine(es)
    p = FakePyAudio(streams=[FakeStream(speech_then_silence())])

    run_capture(engine, p, SPEAKERS_LB, True)

    assert es.utterances == [("system", "silence", 19456)]


def test_system_segmentation_disabled_emits_nothing(clock, es):
    engine = make_engine(es, segment_system=False)
    p = FakePyAudio(streams=[FakeStream(speech_then_silence())])

    run_capture(engine, p, SPEAKERS_LB, True)

    assert es.utterances == []


def test_mic_not_segmented_by_default(clock, es):
    engine = make_engine(es)
    p = FakePyAudio(streams=[FakeStream(speech_then_silence())])

    run_capture(engine, p, MIC, False)

    assert es.utterances == []


# --- mic echo gate ----------------------------------------------------------

def run_system_then_mic(engine, clock, mic_time):
    """Loud system block at t=100.0 (echo window until 100.25), then the mic."""
    clock.now = 100.0
    run_capture(engine, FakePyAudio(streams=[FakeStream([pcm(8192)])]),
                SPEAKERS_LB, True)
    clock.now = mic_time
    run_capture(engine, FakePyAudio(streams=[FakeStream(speech_then_silence())]),
                MIC, False)


def test_mic_segmentation_suppressed_while_system_active(clock, es):
    engine = make_engine(es, capture_mic_utterances=True, segment_system=False)

    run_system_then_mic(engine, clock, mic_time=100.1)

    assert es.utterances == []


@pytest.mark.parametrize("mic_echo_gate, mic_time", [
    (True, 100.5),    # echo window already expired
    (False, 100.1),   # gate disabled
])
def test_mic_segmentation_runs_outside_echo_gate(clock, es, mic_echo_gate,
                                                  mic_time):
    engine = make_engine(es, capture_mic_utterances=True, segment_system=False,
                         mic_echo_gate=mic_echo_gate)

    run_system_then_mic(engine, clock, mic_time)

    assert es.utterances == [("mic", "silence", 19456)]


def test_mic_level_reported_while_echo_gated(clock, es):
    engine = make_engine(es, capture_mic_utterances=True, segment_system=False)

    run_system_then_mic(engine, clock, mic_time=100.1)

    assert len(es.mic_levels) == 19


# --- stream open / status ---------------------------------------------------

def test_capture_reports_listening_device(clock, es):
    engine = make_engine(es)

    run_capture(engine, FakePyAudio(), SPEAKERS_LB, True)

    assert es.statuses == ["Escuchando sistema: Speakers (Realtek) [Loopback] (16000 Hz)"]


def test_capture_reports_open_failure(clock, es):
    engine = make_engine(es)
    p = FakePyAudio(streams=[OSError("device busy")])

    run_capture(engine, p, MIC, False)

    assert es.statuses == ["No se pudo abrir microfono: device busy"]


def test_capture_closes_stream_when_loop_ends(clock, es):
    engine = make_engine(es)
    stream = FakeStream([pcm(0)])

    run_capture(engine, FakePyAudio(streams=[stream]), MIC, False)

    assert stream.closed is True


# --- default output change (re-attach) --------------------------------------

def reattach_setup(clock, default_output):
    """Capture starts on the speakers loopback; the clock advances 1.5 s per
    call, so the second loop iteration runs the 2 s default-output check."""
    clock.now, clock.step = 0.0, 1.5
    first = FakeStream([pcm(0)] * 3)
    second = FakeStream([pcm(0)])
    p = FakePyAudio(devices=(SPEAKERS, HEADPHONES, SPEAKERS_LB, HEADPHONES_LB),
                    default_output=default_output,
                    loopbacks=(SPEAKERS_LB, HEADPHONES_LB),
                    streams=[first, second])
    return p, first


def test_default_output_change_reopens_new_loopback(clock, es):
    engine = make_engine(es)
    p, _ = reattach_setup(clock, default_output=3)

    run_capture(engine, p, SPEAKERS_LB, True)

    assert [kw["input_device_index"] for kw in p.opened] == [7, 9]


def test_default_output_change_closes_old_stream(clock, es):
    engine = make_engine(es)
    p, first = reattach_setup(clock, default_output=3)

    run_capture(engine, p, SPEAKERS_LB, True)

    assert first.closed is True


def test_default_output_change_reports_status(clock, es):
    engine = make_engine(es)
    p, _ = reattach_setup(clock, default_output=3)

    run_capture(engine, p, SPEAKERS_LB, True)

    assert ("Salida de audio cambiada a Headphones (USB) [Loopback]: reenganchando."
            in es.statuses)


def test_unchanged_default_output_keeps_stream(clock, es):
    engine = make_engine(es)
    p, _ = reattach_setup(clock, default_output=2)

    run_capture(engine, p, SPEAKERS_LB, True)

    assert [kw["input_device_index"] for kw in p.opened] == [7]


def test_default_output_not_checked_within_two_seconds(clock, es):
    engine = make_engine(es)
    p, _ = reattach_setup(clock, default_output=3)
    clock.step = 0.0

    run_capture(engine, p, SPEAKERS_LB, True)

    assert [kw["input_device_index"] for kw in p.opened] == [7]


# --- start / stop -----------------------------------------------------------

@pytest.fixture
def pyaudio_factory(monkeypatch):
    """Replace pyaudio.PyAudio; tests set ``factory.next`` before start()."""
    factory = SimpleNamespace(next=FakePyAudio(), created=[])

    def create():
        factory.created.append(factory.next)
        return factory.next

    monkeypatch.setattr(audio.pyaudio, "PyAudio", create)
    return factory


@pytest.fixture
def release():
    """Event that unblocks BlockingStream reads at teardown."""
    event = threading.Event()
    yield event
    event.set()


def test_start_reports_missing_loopback(clock, es, pyaudio_factory):
    pyaudio_factory.next = FakePyAudio(loopbacks=())
    engine = make_engine(es)

    engine.start()
    engine.stop()

    assert ("Loopback no disponible: No se encontro un dispositivo de loopback WASAPI."
            in es.statuses)


def test_start_reports_missing_microphone(clock, es, pyaudio_factory):
    pyaudio_factory.next = FakePyAudio(default_input=5,
                                       default_input_error=OSError("no input"))
    engine = make_engine(es)

    engine.start()
    engine.stop()

    assert "Microfono no disponible: Invalid device index" in es.statuses


def test_start_while_running_does_not_create_new_pyaudio(clock, es, pyaudio_factory):
    engine = make_engine(es)

    engine.start()
    engine.start()
    engine.stop()

    assert len(pyaudio_factory.created) == 1


def test_stop_terminates_pyaudio_after_threads_exit(clock, es, pyaudio_factory):
    engine = make_engine(es)
    engine.start()

    engine.stop()

    assert pyaudio_factory.next.terminated == 1


def test_stop_skips_terminate_while_thread_blocked(clock, es, pyaudio_factory,
                                                   release):
    pyaudio_factory.next = FakePyAudio(loopbacks=(),
                                       streams=[BlockingStream(release)])
    engine = make_engine(es)
    engine.start()

    engine.stop()

    assert pyaudio_factory.next.terminated == 0


def test_stop_warns_while_thread_blocked(clock, es, pyaudio_factory, release):
    pyaudio_factory.next = FakePyAudio(loopbacks=(),
                                       streams=[BlockingStream(release)])
    engine = make_engine(es)
    engine.start()

    engine.stop()

    assert ("Aviso: un hilo de audio no respondio; no se libero PortAudio."
            in es.statuses)
