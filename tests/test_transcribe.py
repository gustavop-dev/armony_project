"""Tests for transcribe.Transcriber with faster_whisper.WhisperModel replaced.

faster_whisper may not be installed in the test venv, so a stub module is put
in sys.modules and ``transcribe`` is imported fresh for every test. The CUDA
DLL registration that runs at import time is replaced with a recorder.
"""
import importlib
import sys
import types

import numpy as np
import pytest

import cuda_setup


class FakeWhisperModel:
    """Records constructor and transcribe() calls; can refuse some devices."""

    failing_devices = ()
    created = []
    segments = []
    transcribe_calls = []

    def __init__(self, size, device, compute_type):
        FakeWhisperModel.created.append((size, device, compute_type))
        if device in FakeWhisperModel.failing_devices:
            raise RuntimeError(f"{device} not available")

    def transcribe(self, audio, **kwargs):
        FakeWhisperModel.transcribe_calls.append((audio, kwargs))
        segments = (types.SimpleNamespace(text=t) for t in FakeWhisperModel.segments)
        return segments, types.SimpleNamespace(language="es")


@pytest.fixture
def registrations(monkeypatch):
    calls = []
    monkeypatch.setattr(cuda_setup, "register_cuda_dlls",
                        lambda: calls.append("registered") or [])
    return calls


@pytest.fixture
def transcribe_mod(monkeypatch, registrations):
    monkeypatch.setattr(FakeWhisperModel, "failing_devices", ())
    monkeypatch.setattr(FakeWhisperModel, "created", [])
    monkeypatch.setattr(FakeWhisperModel, "segments", [])
    monkeypatch.setattr(FakeWhisperModel, "transcribe_calls", [])
    stub = types.ModuleType("faster_whisper")
    stub.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", stub)
    monkeypatch.delitem(sys.modules, "transcribe", raising=False)
    module = importlib.import_module("transcribe")
    monkeypatch.setitem(sys.modules, "transcribe", module)
    monkeypatch.setattr(module, "WhisperModel", FakeWhisperModel)
    return module


def test_import_registers_cuda_dlls(transcribe_mod, registrations):
    assert registrations == ["registered"]


def test_auto_device_prefers_cuda_float16(transcribe_mod):
    transcribe_mod.Transcriber(size="base", device="auto")

    assert FakeWhisperModel.created == [("base", "cuda", "float16")]


def test_auto_device_selects_cuda_when_available(transcribe_mod):
    t = transcribe_mod.Transcriber(device="auto")

    assert t.device == "cuda"


def test_auto_device_falls_back_to_cpu_int8(transcribe_mod):
    FakeWhisperModel.failing_devices = ("cuda",)

    transcribe_mod.Transcriber(size="base", device="auto")

    assert FakeWhisperModel.created == [("base", "cuda", "float16"),
                                        ("base", "cpu", "int8")]


def test_auto_device_fallback_selects_cpu(transcribe_mod):
    FakeWhisperModel.failing_devices = ("cuda",)

    t = transcribe_mod.Transcriber(device="auto")

    assert t.device == "cpu"


@pytest.mark.parametrize("device, expected", [
    ("cpu", [("small", "cpu", "int8")]),
    ("cuda", [("small", "cuda", "float16")]),
])
def test_explicit_device_loads_single_model(transcribe_mod, device, expected):
    transcribe_mod.Transcriber(size="small", device=device)

    assert FakeWhisperModel.created == expected


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_explicit_device_is_reported(transcribe_mod, device):
    t = transcribe_mod.Transcriber(device=device)

    assert t.device == device


def test_explicit_cuda_failure_propagates(transcribe_mod):
    FakeWhisperModel.failing_devices = ("cuda",)

    with pytest.raises(RuntimeError, match="cuda not available"):
        transcribe_mod.Transcriber(device="cuda")


@pytest.mark.parametrize("language, expected", [
    ("auto", None),
    ("es", "es"),
    ("en", "en"),
])
def test_language_passed_to_model(transcribe_mod, language, expected):
    t = transcribe_mod.Transcriber(device="cpu", language=language)

    t.transcribe(np.zeros(16000, dtype=np.float32))

    assert FakeWhisperModel.transcribe_calls[0][1]["language"] == expected


def test_transcribe_uses_greedy_decoding_without_vad(transcribe_mod):
    t = transcribe_mod.Transcriber(device="cpu", language="es")

    t.transcribe(np.zeros(16000, dtype=np.float32))

    assert FakeWhisperModel.transcribe_calls[0][1] == {
        "language": "es", "beam_size": 1, "vad_filter": False}


def test_transcribe_passes_audio_unchanged(transcribe_mod):
    t = transcribe_mod.Transcriber(device="cpu")
    audio = np.zeros(16000, dtype=np.float32)

    t.transcribe(audio)

    assert FakeWhisperModel.transcribe_calls[0][0] is audio


def test_transcribe_joins_stripped_segments(transcribe_mod):
    FakeWhisperModel.segments = [" Hola, ", "  que tal?", " Bien. "]
    t = transcribe_mod.Transcriber(device="cpu")

    text = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert text == "Hola, que tal? Bien."


def test_transcribe_without_segments_returns_empty(transcribe_mod):
    t = transcribe_mod.Transcriber(device="cpu")

    text = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert text == ""
