"""WER/CER and latency summaries."""
import jiwer
import numpy as np

from stt_eval.textnorm import normalize


def score_text(reference, hypothesis, strip_accents=False):
    """Word and character error rates of one hypothesis against one reference."""
    ref = normalize(reference, strip_accents)
    hyp = normalize(hypothesis, strip_accents)
    if not ref:
        raise ValueError("empty reference")
    words = jiwer.process_words(ref, hyp)
    return {
        "wer": words.wer,
        "cer": jiwer.cer(ref, hyp),
        "substitutions": words.substitutions,
        "deletions": words.deletions,
        "insertions": words.insertions,
        "hits": words.hits,
        "ref_words": len(ref.split()),
    }


def percentiles(values, qs=(50, 90, 95)):
    if not values:
        return {f"p{q}": None for q in qs} | {"n": 0}
    arr = np.asarray(values, dtype=float)
    return {f"p{q}": round(float(np.percentile(arr, q)), 1) for q in qs} | {
        "n": len(values),
        "max": round(float(arr.max()), 1),
    }
