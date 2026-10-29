"""Text normalization applied to references and hypotheses before scoring.

Providers format turns (case, punctuation, inverted marks); references come in
their own style. Scoring compares words, so both sides are reduced to
lowercase tokens without punctuation. ``strip_accents`` gives a lenient
variant that ignores tilde errors (e.g. "como" vs "cómo").
"""
import re
import unicodedata

_NON_WORD = re.compile(r"[^\w\s']", re.UNICODE)


def normalize(text, strip_accents=False):
    t = unicodedata.normalize("NFC", text or "").lower()
    t = t.replace("-", " ")
    t = _NON_WORD.sub(" ", t)
    t = t.replace("_", " ")
    if strip_accents:
        t = "".join(c for c in unicodedata.normalize("NFD", t)
                    if not unicodedata.combining(c))
    return " ".join(t.split())
