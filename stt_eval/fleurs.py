"""FLEURS loader (google/fleurs on Hugging Face, CC BY 4.0).

Clean read speech, one sentence per clip, 16 kHz mono WAV. Used as the "calm"
baseline: if the live path loses accuracy here, the problem is ours (capture,
resampling, chunking), not the conversation.

The test audio ships as one large tar.gz (~580 MB for es_419). It is read as a
stream and only the first ``limit`` clips that match the TSV are extracted, so
a small run never downloads the whole archive.
"""
import csv
import os
import struct
import tarfile
import urllib.request
from dataclasses import dataclass

import numpy as np

BASE_URL = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
SAMPLE_RATE = 16000


@dataclass
class Sample:
    clip_id: str          # wav file name
    sentence_id: str      # same sentence is read by several speakers
    reference: str        # raw transcription (case and punctuation kept)
    gender: str
    audio: np.ndarray     # float32 mono 16 kHz

    @property
    def seconds(self):
        return self.audio.size / SAMPLE_RATE


def _download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, dest)


def read_tsv(path):
    """Rows keyed by wav name: (sentence_id, raw transcription, gender)."""
    rows = {}
    with open(path, encoding="utf-8", newline="") as f:
        for rec in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(rec) < 7:
                continue
            sentence_id, wav_name, raw = rec[0], rec[1], rec[2]
            rows[wav_name] = (sentence_id, raw, rec[6])
    return rows


def read_wav(path):
    """Mono 16 kHz WAV as float32. FLEURS ships IEEE float (format 3), which
    the stdlib ``wave`` module rejects, so the RIFF chunks are read here."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a WAV file")
    fmt = pcm = None
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            tag, channels, rate = struct.unpack_from("<HHI", body)
            bits = struct.unpack_from("<H", body, 14)[0]
            if tag == 0xFFFE:                      # WAVE_FORMAT_EXTENSIBLE
                tag = struct.unpack_from("<H", body, 24)[0]
            fmt = (tag, channels, rate, bits)
        elif cid == b"data":
            pcm = body
        pos += 8 + size + (size & 1)
    if fmt is None or pcm is None:
        raise ValueError(f"{path}: missing fmt or data chunk")
    tag, channels, rate, bits = fmt
    if rate != SAMPLE_RATE or channels != 1:
        raise ValueError(f"{path}: expected 16 kHz mono, got {rate} Hz x{channels}")
    if tag == 3 and bits == 32:
        return np.frombuffer(pcm, dtype="<f4").astype(np.float32)
    if tag == 1 and bits == 16:
        return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    raise ValueError(f"{path}: unsupported WAV format tag={tag} bits={bits}")


def load(cache_dir, lang="es_419", split="test", limit=30,
         unique_sentences=True, base_url=BASE_URL):
    """Return up to ``limit`` samples, in archive order, caching what it reads.

    unique_sentences: keep one reading per sentence, so a run of N clips
    covers N different sentences instead of the same one in several voices.
    """
    root = os.path.join(cache_dir, "fleurs", lang, split)
    wav_dir = os.path.join(root, "wav")
    tsv_path = os.path.join(root, f"{split}.tsv")
    if not os.path.exists(tsv_path):
        _download(f"{base_url}/{lang}/{split}.tsv", tsv_path)
    rows = read_tsv(tsv_path)

    # The archive order is fixed, so the selection is reproducible. It is kept
    # in a manifest to rebuild it from the cache without touching the network.
    manifest = os.path.join(root, f"manifest-{limit}-{int(unique_sentences)}.txt")
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as f:
            chosen = [line.strip() for line in f if line.strip()]
    else:
        chosen = _extract(f"{base_url}/{lang}/audio/{split}.tar.gz", rows,
                          wav_dir, limit, unique_sentences)
        with open(manifest, "w", encoding="utf-8") as f:
            f.write("\n".join(chosen) + "\n")

    samples = []
    for name in chosen:
        sentence_id, raw, gender = rows[name]
        samples.append(Sample(name, sentence_id, raw, gender,
                              read_wav(os.path.join(wav_dir, name))))
    return samples


def _extract(url, rows, wav_dir, limit, unique_sentences):
    os.makedirs(wav_dir, exist_ok=True)
    chosen, seen = [], set()
    with urllib.request.urlopen(url) as resp, \
            tarfile.open(fileobj=resp, mode="r|gz") as tar:
        for member in tar:
            if len(chosen) >= limit:
                break
            name = os.path.basename(member.name)
            if not member.isfile() or name not in rows:
                continue
            sentence_id = rows[name][0]
            if unique_sentences and sentence_id in seen:
                continue
            data = tar.extractfile(member).read()
            with open(os.path.join(wav_dir, name), "wb") as f:
                f.write(data)
            seen.add(sentence_id)
            chosen.append(name)
    return chosen
