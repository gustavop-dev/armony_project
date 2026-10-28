"""Real-time replay of dataset clips through the streaming STT client.

Clips are joined into one session separated by silence, so the provider sees
one continuous connection (it bills connected time and closes turns on its
own), the same way it sees a meeting.

Finals are attributed to a clip by how much audio had been sent when they
arrived: a final belongs to the last clip that had started by then. That is
the provider's own frame of reference and does not depend on sleep accuracy.
Corpus WER is computed on the whole session (all references vs all finals),
so a final that lands on the wrong side of a boundary only blurs the per-clip
view, not the headline number.
"""
import bisect
import time
from dataclasses import dataclass

import numpy as np

from stt_eval.scoring import percentiles, score_text

SAMPLE_RATE = 16000
# audio.AudioEngine reads 1024 frames per block; from a 48 kHz device that is
# ~341 samples once resampled to 16 kHz (~21 ms). Same cadence here.
BLOCK = 341


@dataclass
class Span:
    start_s: float
    end_s: float


@dataclass
class Final:
    t: float                  # clock when it arrived
    audio_s: float            # seconds of session audio sent by then
    text: str
    provider_latency_ms: int  # StreamingSTT's own estimate


def build_session(clips, gap_s=2.0, lead_s=0.5, tail_s=4.0):
    """Concatenate float32 clips with silence. Returns (audio, spans)."""
    gap = np.zeros(int(gap_s * SAMPLE_RATE), dtype=np.float32)
    parts = [np.zeros(int(lead_s * SAMPLE_RATE), dtype=np.float32)]
    pos = parts[0].size
    spans = []
    for i, clip in enumerate(clips):
        if i:
            parts.append(gap)
            pos += gap.size
        parts.append(clip.astype(np.float32))
        spans.append(Span(pos / SAMPLE_RATE, (pos + clip.size) / SAMPLE_RATE))
        pos += clip.size
    # Trailing silence lets the provider close the last turn before we hang up.
    parts.append(np.zeros(int(tail_s * SAMPLE_RATE), dtype=np.float32))
    return np.concatenate(parts), spans


def play(audio, sink, speed=1.0, block=BLOCK, clock=time.monotonic,
         sleep=time.sleep):
    """Feed ``audio`` to ``sink`` in blocks paced like a capture device.

    A block is handed over when it would have finished recording, i.e. at
    t0 + (end of block) / rate / speed. Returns t0 on ``clock``.
    """
    t0 = clock()
    for i in range(0, audio.size, block):
        chunk = audio[i:i + block]
        delay = t0 + (i + chunk.size) / SAMPLE_RATE / speed - clock()
        if delay > 0:
            sleep(delay)
        sink(chunk)
    return t0


def run_session(make_stt, samples, gap_s=2.0, speed=1.0, connect_timeout=15.0,
                clock=time.monotonic):
    """Stream ``samples`` through a client built by ``make_stt`` and score it.

    make_stt(on_partial, on_final, on_error) must return an object with
    start(), stop(), feed(block_f32) and a ``connected`` property, i.e. a
    StreamingSTT or a test double.
    """
    finals, partials, errors = [], [], []
    sent = [0]                 # samples handed to the client so far
    stt = make_stt(
        on_partial=lambda text: partials.append((clock(), text)),
        on_final=lambda text, ms: finals.append(
            Final(clock(), sent[0] / SAMPLE_RATE, text, ms)),
        on_error=errors.append,
    )
    audio, spans = build_session([s.audio for s in samples], gap_s)
    ends = [round(sp.end_s * SAMPLE_RATE) for sp in spans]
    end_sent_at = []           # clock when each clip's last sample went out

    def sink(block):
        sent[0] += block.size
        while len(end_sent_at) < len(ends) and sent[0] >= ends[len(end_sent_at)]:
            end_sent_at.append(clock())
        stt.feed(block)

    t_start = clock()
    stt.start()
    try:
        while not stt.connected:
            if clock() - t_start > connect_timeout:
                raise RuntimeError(f"STT did not connect: {errors or 'timeout'}")
            time.sleep(0.02)
        connect_ms = (clock() - t_start) * 1000
        play(audio, sink, speed=speed, clock=clock)
    finally:
        stt.stop()

    report = summarize(samples, spans, finals, end_sent_at)
    report.update({
        "connect_ms": round(connect_ms, 1),
        "audio_seconds": round(audio.size / SAMPLE_RATE, 2),
        "speech_seconds": round(sum(s.seconds for s in samples), 2),
        "partials": len(partials),
        "errors": errors,
    })
    return report


def summarize(samples, spans, finals, end_sent_at):
    """end_sent_at[i]: clock when clip i's last sample was sent."""
    starts = [sp.start_s for sp in spans]
    owned = [[] for _ in samples]
    unassigned = []
    for f in finals:
        i = bisect.bisect_right(starts, f.audio_s) - 1
        (owned[i] if i >= 0 else unassigned).append(f)

    per_clip, fin_latency = [], []
    for i, (sample, span, mine) in enumerate(zip(samples, spans, owned)):
        hyp = " ".join(f.text for f in mine)
        after_end = [f for f in mine if f.audio_s >= span.end_s]
        # Time from the last spoken sample to the final that closes the turn:
        # end-of-turn detection plus transcription plus network.
        latency = None
        if after_end and i < len(end_sent_at):
            latency = round((after_end[0].t - end_sent_at[i]) * 1000, 1)
        if latency is not None:
            fin_latency.append(latency)
        sc = score_text(sample.reference, hyp)
        per_clip.append({
            "clip_id": sample.clip_id,
            "reference": sample.reference,
            "hypothesis": hyp,
            "wer": round(sc["wer"], 4),
            "cer": round(sc["cer"], 4),
            "finalization_latency_ms": latency,
        })

    session_ref = " ".join(s.reference for s in samples)
    session_hyp = " ".join(f.text for f in finals)
    strict = score_text(session_ref, session_hyp)
    lenient = score_text(session_ref, session_hyp, strip_accents=True)
    return {
        "clips": len(samples),
        "wer": round(strict["wer"], 4),
        "cer": round(strict["cer"], 4),
        "wer_no_accents": round(lenient["wer"], 4),
        "errors_breakdown": {k: strict[k] for k in
                             ("substitutions", "deletions", "insertions",
                              "hits", "ref_words")},
        "latency_ms": {
            "finalization": percentiles(fin_latency),
            "provider_estimate": percentiles([f.provider_latency_ms for f in finals]),
        },
        "clips_without_final": sum(1 for c in per_clip if not c["hypothesis"]),
        "unassigned_finals": [f.text for f in unassigned],
        "per_clip": per_clip,
    }
