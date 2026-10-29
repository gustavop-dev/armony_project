"""Tests for audio: WASAPI device picking and AudioEngine capture.

PyAudio/WASAPI and the clock are the only boundaries replaced; resampling runs
through the real soxr. Capture loops run in the test thread (``_capture``
called directly) with a fake stream that yields scripted int16 blocks and then
raises, which ends the loop.
"""
import threading
from types import SimpleNamespace

import numpy as np
import pytest
import soxr

import audio

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


def sine_int16(rate, reads, freq=440.0, amplitude=0.25, frames=1024):
    """Mono int16 sine spanning ``reads`` blocks of ``frames`` at ``rate``."""
    t = np.arange(reads * frames) / rate
    return np.round(amplitude * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)


def split_reads(samples, frames=1024):
    """Split an int16 signal into the byte blocks one stream.read() returns."""
    return [samples[i:i + frames].tobytes() for i in range(0, samples.size, frames)]


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
        self.statuses = []
        self.pcm = []
        self.mic_pcm = []


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


def make_engine(es, on_system_pcm=None, **kwargs):
    """Engine wired to ``es``; system PCM goes to ``es.pcm`` unless overridden.

    The mic is level-only unless the test passes ``on_mic_pcm``.
    """
    if on_system_pcm is None:
        on_system_pcm = es.pcm.append
    return audio.AudioEngine(es.sys_levels.append, es.mic_levels.append,
                             es.statuses.append, on_system_pcm, **kwargs)


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


# --- PCM forwarding at 16 kHz ----------------------------------------------
# One soxr.ResampleStream per capture holds back its filter delay (~35 ms of
# output) and may return an empty block for a read; only non-empty blocks are
# forwarded. Totals are therefore checked against the ideal length minus at
# most FILTER_DELAY output samples.
FILTER_DELAY = 1024     # 16 kHz samples (64 ms): generous bound on held-back audio


def forwarded(blocks):
    return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)


@pytest.mark.parametrize("rate", [32000, 44100, 48000])
def test_system_pcm_forwarded_at_16k(clock, es, rate):
    reads = 20
    engine = make_engine(es)
    device = {**SPEAKERS_LB, "defaultSampleRate": float(rate)}
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * reads)])

    run_capture(engine, p, device, True)

    expected = reads * 1024 * 16000 / rate
    assert expected - FILTER_DELAY <= forwarded(es.pcm).size <= expected


def test_system_pcm_blocks_are_non_empty_float32(clock, es):
    engine = make_engine(es)
    device = {**SPEAKERS_LB, "defaultSampleRate": 48000.0}
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * 20)])

    run_capture(engine, p, device, True)

    assert es.pcm and all(b.dtype == np.float32 and b.size > 0 for b in es.pcm)


def test_empty_resampler_output_is_not_forwarded(clock, es):
    # The first read only fills the resampler's filter delay: nothing to send.
    engine = make_engine(es)
    device = {**SPEAKERS_LB, "defaultSampleRate": 48000.0}
    p = FakePyAudio(streams=[FakeStream([pcm(8192)])])

    run_capture(engine, p, device, True)

    assert (es.sys_levels, es.pcm) == ([75], [])


def test_system_pcm_matches_one_shot_resampling(clock, es):
    # Many 1024-frame reads through one stream must equal resampling the whole
    # signal at once: no seams at read boundaries, no drift.
    rate = 48000
    samples = sine_int16(rate, reads=60)
    engine = make_engine(es)
    device = {**SPEAKERS_LB, "defaultSampleRate": float(rate)}
    p = FakePyAudio(streams=[FakeStream(split_reads(samples))])

    run_capture(engine, p, device, True)

    reference = soxr.resample(samples.astype(np.float32) / 32768.0, rate, 16000)
    got = forwarded(es.pcm)
    edge = 256
    assert got.size > reference.size - FILTER_DELAY
    assert np.max(np.abs(got[edge:-edge] - reference[edge:got.size - edge])) < 1e-3


def test_system_pcm_gain_applied_before_forwarding(clock, es):
    rate = 48000
    samples = sine_int16(rate, reads=20, amplitude=0.1)
    engine = make_engine(es, gain_system=2.0)
    device = {**SPEAKERS_LB, "defaultSampleRate": float(rate)}
    p = FakePyAudio(streams=[FakeStream(split_reads(samples))])

    run_capture(engine, p, device, True)

    peak = float(np.max(np.abs(forwarded(es.pcm))))
    assert peak == pytest.approx(0.2, abs=0.01)


def test_system_pcm_callback_exception_is_swallowed(clock, es):
    def failing(block):
        raise ValueError("stream consumer failed")

    engine = make_engine(es, on_system_pcm=failing)
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * 3)])

    run_capture(engine, p, SPEAKERS_LB, True)

    assert es.sys_levels == [75, 75, 75]


def test_loopback_audio_not_sent_to_mic_feed(clock, es):
    engine = make_engine(es, on_mic_pcm=es.mic_pcm.append)
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * 5)])

    run_capture(engine, p, SPEAKERS_LB, True)

    assert es.pcm and es.mic_pcm == []


# --- mic feed ----------------------------------------------------------------

@pytest.mark.parametrize("rate", [16000, 48000])
def test_mic_pcm_forwarded_at_16k_when_requested(clock, es, rate):
    reads = 20
    engine = make_engine(es, on_mic_pcm=es.mic_pcm.append)
    device = {**MIC, "defaultSampleRate": float(rate)}
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * reads)])

    run_capture(engine, p, device, False)

    expected = reads * 1024 * 16000 / rate
    assert expected - FILTER_DELAY <= forwarded(es.mic_pcm).size <= expected


def test_mic_pcm_matches_one_shot_resampling(clock, es):
    rate = 48000
    samples = sine_int16(rate, reads=60, freq=300.0)
    engine = make_engine(es, on_mic_pcm=es.mic_pcm.append)
    device = {**MIC, "defaultSampleRate": float(rate)}
    p = FakePyAudio(streams=[FakeStream(split_reads(samples))])

    run_capture(engine, p, device, False)

    reference = soxr.resample(samples.astype(np.float32) / 32768.0, rate, 16000)
    got = forwarded(es.mic_pcm)
    edge = 256
    assert got.size > reference.size - FILTER_DELAY
    assert np.max(np.abs(got[edge:-edge] - reference[edge:got.size - edge])) < 1e-3


def test_mic_level_reported_while_forwarding(clock, es):
    engine = make_engine(es, on_mic_pcm=es.mic_pcm.append)
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * 3)])

    run_capture(engine, p, MIC, False)

    assert es.mic_levels == [75, 75, 75]


def test_mic_audio_not_sent_to_system_feed(clock, es):
    engine = make_engine(es, on_mic_pcm=es.mic_pcm.append)
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * 5)])

    run_capture(engine, p, MIC, False)

    assert es.mic_pcm and es.pcm == []


def test_mic_level_only_without_mic_feed(clock, es):
    engine = make_engine(es)
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * 5)])

    run_capture(engine, p, MIC, False)

    assert (es.mic_levels, es.pcm) == ([75] * 5, [])


def test_mic_pcm_callback_exception_is_swallowed(clock, es):
    engine = make_engine(es, on_mic_pcm=failing_pcm)
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * 3)])

    run_capture(engine, p, MIC, False)

    assert es.mic_levels == [75, 75, 75]


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


# --- logging of swallowed failures (ERR-005) ---------------------------------

def pcm_feed_log(feed):
    return (f"Live transcription feed failed ({feed}); further failures of this "
            "feed in this session are not logged")


def failing_pcm(block):
    raise ValueError("stream consumer failed")


def messages(caplog):
    return [record.getMessage() for record in caplog.records]


def test_system_pcm_failure_is_logged_once_per_session(clock, es, caplog):
    engine = make_engine(es, on_system_pcm=failing_pcm)
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * 3)])

    run_capture(engine, p, SPEAKERS_LB, True)

    assert messages(caplog).count(pcm_feed_log("sistema")) == 1


def test_mic_pcm_failure_is_logged_once_per_session(clock, es, caplog):
    # 48 kHz mic: several reads return resampled audio, each one fails.
    engine = make_engine(es, on_mic_pcm=failing_pcm)
    device = {**MIC, "defaultSampleRate": 48000.0}
    p = FakePyAudio(streams=[FakeStream([pcm(8192)] * 10)])

    run_capture(engine, p, device, False)

    assert [(r.getMessage(), r.levelname) for r in caplog.records] == [
        (pcm_feed_log("microfono"), "ERROR"),
        ("Capture read failed on microfono device; capture stopped", "WARNING")]


def test_a_failing_meeting_feed_does_not_hide_a_failing_mic_feed(clock, es, caplog):
    engine = make_engine(es, on_system_pcm=failing_pcm, on_mic_pcm=failing_pcm)
    run_capture(engine, FakePyAudio(streams=[FakeStream([pcm(8192)] * 3)]),
                SPEAKERS_LB, True)
    device = {**MIC, "defaultSampleRate": 48000.0}
    run_capture(engine, FakePyAudio(streams=[FakeStream([pcm(8192)] * 10)]),
                device, False)

    logged = messages(caplog)
    assert logged.count(pcm_feed_log("sistema")) == 1
    assert logged.count(pcm_feed_log("microfono")) == 1


def test_start_rearms_system_pcm_failure_log(clock, es, pyaudio_factory):
    pyaudio_factory.next = FakePyAudio(loopbacks=())
    engine = make_engine(es, on_system_pcm=failing_pcm)
    engine._pcm_error_logged = {"sistema", "microfono"}

    engine.start()
    engine.stop()

    assert engine._pcm_error_logged == set()


def test_capture_read_failure_is_logged(clock, es, caplog):
    engine = make_engine(es)

    run_capture(engine, FakePyAudio(streams=[FakeStream()]), SPEAKERS_LB, True)

    assert messages(caplog) == ["Capture read failed on sistema device; capture stopped"]


def test_default_output_check_failure_is_logged_once(clock, es, caplog):
    engine = make_engine(es)
    # Index 99 is unknown: both 2 s checks in this loop raise OSError.
    p, _ = reattach_setup(clock, default_output=99)

    run_capture(engine, p, SPEAKERS_LB, True)

    assert messages(caplog).count("Default output device check failed") == 1


def test_terminate_failure_is_logged(clock, es, pyaudio_factory, caplog):
    def broken_terminate():
        raise OSError("PortAudio not initialized")

    pyaudio_factory.next = FakePyAudio(loopbacks=())
    pyaudio_factory.next.terminate = broken_terminate
    engine = make_engine(es)
    engine.start()

    engine.stop()

    assert ("PortAudio terminate failed", "WARNING") in [
        (r.getMessage(), r.levelname) for r in caplog.records]
