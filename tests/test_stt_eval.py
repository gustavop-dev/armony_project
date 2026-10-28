"""STT evaluation harness: normalization, scoring, replay and FLEURS loading.

No provider is contacted: a fake client stands in for StreamingSTT and the
FLEURS archive is a small tar.gz built under tmp_path and read via file://.
"""
import io
import shutil
import struct
import tarfile
import wave

import numpy as np
import pytest

from stt_eval import fleurs
from stt_eval.replay import (BLOCK, SAMPLE_RATE, build_session, play,
                             run_session)
from stt_eval.scoring import score_text
from stt_eval.textnorm import normalize


# -- textnorm ---------------------------------------------------------------
def test_normalize_drops_case_punctuation_and_inverted_marks():
    assert normalize("¿Cómo   estás? ¡Bien, gracias!") == "cómo estás bien gracias"


def test_normalize_splits_hyphens_and_can_strip_accents():
    assert normalize("Año-nuevo", strip_accents=True) == "ano nuevo"


# -- scoring ----------------------------------------------------------------
def test_score_text_perfect_match_ignores_formatting():
    sc = score_text("Hola, ¿qué tal?", "hola que tal", strip_accents=True)
    assert sc["wer"] == 0 and sc["cer"] == 0


def test_score_text_counts_substitution():
    sc = score_text("el gato duerme", "el pato duerme")
    assert sc["substitutions"] == 1
    assert sc["wer"] == pytest.approx(1 / 3)


def test_score_text_empty_hypothesis_is_all_deletions():
    sc = score_text("uno dos", "")
    assert sc["wer"] == 1.0 and sc["deletions"] == 2


def test_score_text_rejects_empty_reference():
    with pytest.raises(ValueError):
        score_text("¿?", "algo")


# -- replay -----------------------------------------------------------------
def test_build_session_places_clips_after_lead_and_gaps():
    a = np.ones(SAMPLE_RATE, dtype=np.float32)          # 1 s
    b = np.ones(SAMPLE_RATE // 2, dtype=np.float32)     # 0.5 s
    audio, spans = build_session([a, b], gap_s=2.0, lead_s=0.5, tail_s=4.0)
    assert [(s.start_s, s.end_s) for s in spans] == [(0.5, 1.5), (3.5, 4.0)]
    assert audio.size == int((0.5 + 1 + 2 + 0.5 + 4) * SAMPLE_RATE)


def test_play_feeds_everything_paced_to_block_end():
    now = [100.0]
    sleeps = []

    def sleep(d):
        sleeps.append(d)
        now[0] += d

    fed = []
    audio = np.zeros(BLOCK * 3 + 10, dtype=np.float32)
    t0 = play(audio, fed.append, clock=lambda: now[0], sleep=sleep)

    assert t0 == 100.0
    assert [c.size for c in fed] == [BLOCK, BLOCK, BLOCK, 10]
    assert now[0] == pytest.approx(100.0 + audio.size / SAMPLE_RATE)
    assert sleeps[0] == pytest.approx(BLOCK / SAMPLE_RATE)


class FakeSTT:
    """Emits each clip's reference as a final once its audio has been fed."""

    def __init__(self, on_partial, on_final, on_error, script):
        self._on_partial = on_partial
        self._on_final = on_final
        self._script = list(script)      # [(sample_offset, text)]
        self._fed = 0
        self.connected = False
        self.stopped = False

    def start(self):
        self.connected = True

    def stop(self):
        self.stopped = True

    def feed(self, block):
        self._fed += block.size
        self._on_partial("…")
        while self._script and self._fed >= self._script[0][0]:
            self._on_final(self._script.pop(0)[1], 80)


def _sample(name, text, seconds):
    return fleurs.Sample(name, name, text, "FEMALE",
                         np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32))


def test_run_session_scores_and_attributes_finals_per_clip():
    samples = [_sample("a.wav", "Hola, ¿qué tal?", 1.0),
               _sample("b.wav", "Todo bien.", 0.5)]
    _, spans = build_session([s.audio for s in samples], gap_s=1.0)
    # Clip a is transcribed perfectly; clip b loses a word.
    script = [(int((spans[0].end_s + 0.3) * SAMPLE_RATE), "Hola, qué tal."),
              (int((spans[1].end_s + 0.3) * SAMPLE_RATE), "Todo.")]
    made = []

    def make_stt(**callbacks):
        made.append(FakeSTT(script=script, **callbacks))
        return made[0]

    report = run_session(make_stt, samples, gap_s=1.0, speed=100.0)

    assert made[0].stopped
    assert [c["hypothesis"] for c in report["per_clip"]] == ["Hola, qué tal.", "Todo."]
    assert report["per_clip"][0]["wer"] == 0
    assert report["per_clip"][1]["wer"] == 0.5
    assert report["errors_breakdown"]["deletions"] == 1
    assert report["wer"] == pytest.approx(1 / 5)
    assert report["clips_without_final"] == 0
    assert report["latency_ms"]["finalization"]["n"] == 2
    assert report["latency_ms"]["provider_estimate"]["p50"] == 80


def test_run_session_reports_clip_without_final():
    samples = [_sample("a.wav", "uno", 0.5), _sample("b.wav", "dos", 0.5)]
    _, spans = build_session([s.audio for s in samples], gap_s=1.0)
    script = [(int((spans[0].end_s + 0.2) * SAMPLE_RATE), "uno")]

    report = run_session(lambda **cb: FakeSTT(script=script, **cb),
                         samples, gap_s=1.0, speed=100.0)

    assert report["clips_without_final"] == 1
    assert report["per_clip"][1]["finalization_latency_ms"] is None
    assert report["wer"] == 0.5


def test_run_session_fails_when_client_never_connects():
    class Dead(FakeSTT):
        def start(self):
            pass

    with pytest.raises(RuntimeError, match="did not connect"):
        run_session(lambda **cb: Dead(script=[], **cb),
                    [_sample("a.wav", "uno", 0.1)], connect_timeout=0.05)


# -- fleurs -----------------------------------------------------------------
def _wav_bytes(seconds):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(np.zeros(int(seconds * SAMPLE_RATE), np.int16).tobytes())
    return buf.getvalue()


@pytest.fixture
def fake_fleurs(tmp_path):
    """data/es_419/{test.tsv, audio/test.tar.gz} with 3 clips, 2 of one sentence."""
    root = tmp_path / "remote" / "es_419"
    (root / "audio").mkdir(parents=True)
    rows = [("10", "x1.wav", "Primera frase."),
            ("10", "x2.wav", "Primera frase."),
            ("11", "x3.wav", "Segunda frase.")]
    with open(root / "test.tsv", "w", encoding="utf-8") as f:
        for sid, name, raw in rows:
            f.write(f"{sid}\t{name}\t{raw}\t{raw.lower()}\tchars\t16000\tMALE\n")
    with tarfile.open(root / "audio" / "test.tar.gz", "w:gz") as tar:
        for _, name, _ in rows:
            data = _wav_bytes(0.25)
            info = tarfile.TarInfo(f"test/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return (tmp_path / "remote").as_uri(), root


def test_fleurs_load_keeps_one_reading_per_sentence(tmp_path, fake_fleurs):
    base_url, _ = fake_fleurs
    samples = fleurs.load(str(tmp_path / "cache"), limit=2, base_url=base_url)

    assert [s.clip_id for s in samples] == ["x1.wav", "x3.wav"]
    assert samples[1].reference == "Segunda frase."
    assert samples[0].seconds == pytest.approx(0.25)


def test_read_wav_supports_ieee_float(tmp_path):
    # FLEURS ships format 3 (32-bit float), which the stdlib wave module rejects.
    pcm = np.array([0.0, 0.5, -0.25], dtype="<f4").tobytes()
    fmt = struct.pack("<HHIIHH", 3, 1, SAMPLE_RATE, SAMPLE_RATE * 4, 4, 32)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(pcm)) + pcm)
    path = tmp_path / "f.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)

    assert fleurs.read_wav(str(path)).tolist() == [0.0, 0.5, -0.25]


def test_fleurs_load_reuses_cache_without_the_archive(tmp_path, fake_fleurs):
    base_url, remote = fake_fleurs
    cache = str(tmp_path / "cache")
    first = fleurs.load(cache, limit=2, base_url=base_url)
    shutil.rmtree(remote)

    again = fleurs.load(cache, limit=2, base_url=base_url)

    assert [s.clip_id for s in again] == [s.clip_id for s in first]
