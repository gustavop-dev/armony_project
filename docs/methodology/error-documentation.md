# Error documentation

Known defects and their resolution. IDs: `[KNOWN-NNN]` while open, renamed to `[ERR-NNN]` once fixed.
Every KNOWN entry with a test is pinned by a `pytest.mark.xfail(strict=True)` test asserting the correct behavior; when the fix lands, the xfail turns into an XPASS failure and must be removed together with the fix.

## Known issues — confirmed by tests

### [KNOWN-101] Mid-sentence interrogative is classified as a question
- **Where:** `intent.py:92-97` (`parece_pregunta`)
- **Behavior:** any interrogative word within the first 4 tokens returns `True`, contradicting the module comment that a mid-sentence interrogative is not a question.
- **Repro:** `parece_pregunta("no se que hacer", "es")` → `True` (expected `False`); same for `"lo que sea"`.
- **Test:** `tests/test_intent.py`

### [KNOWN-102] English contractions with ASCII apostrophe are not detected
- **Where:** `intent.py:74` (token regex `[a-z0-9']+`)
- **Behavior:** `what's` is tokenized as one word and never matches `what`; the typographic apostrophe (`’`) works.
- **Repro:** `parece_pregunta("what's the plan", "en")` → `False` (expected `True`); also `how's`, `where's`.
- **Test:** `tests/test_intent.py`

### [KNOWN-103] Bold/italic substitution runs inside inline code
- **Where:** `richtext.py:254-259` (`inline_html`)
- **Behavior:** emphasis regexes are applied to inline code spans, altering code text and producing unbalanced markup.
- **Repro:** ``inline_html("`__init__`")`` → `<span style=""><b>init</b></span>` (expected `<span style="">__init__</span>`); ``inline_html("`x ** 2` and **bold**")`` → broken nesting.
- **Test:** `tests/test_richtext.py`

### [KNOWN-201] Non-UTF-8 `config.json` raises in `load_config`
- **Where:** `config.py:168`
- **Behavior:** `UnicodeDecodeError` is not caught (only `JSONDecodeError`/`OSError`), so startup fails instead of falling back to defaults.
- **Repro:** file bytes `{"language": "espa\xf1ol"}` → `UnicodeDecodeError`.
- **Test:** `tests/test_config.py`

### [KNOWN-202] Non-object JSON in `config.json` raises in `load_config`
- **Where:** `config.py:167` (`cfg.update(json.load(f))`)
- **Repro:** file content `null`, `42`, `"text"` or `[1, 2]` → `TypeError`/`ValueError` (expected: defaults).
- **Test:** `tests/test_config.py`

### [KNOWN-203] One non-UTF-8 context file breaks `list_contexts`
- **Where:** `contexts.py:66`
- **Behavior:** `UnicodeDecodeError` propagates (only `OSError` is caught), so `active_text`/`active_count` fail and no context is loaded.
- **Repro:** `ctx-1.md` with bytes `espa\xf1ol` next to a valid `ctx-2.md` → exception (expected `["ctx-2"]`).
- **Test:** `tests/test_contexts.py`

### [KNOWN-204] `write_all` deletes a context whose extension is upper-case (data loss)
- **Where:** `contexts.py:97`
- **Behavior:** `list_contexts` accepts `*.MD` case-insensitively; `write_all` writes `<id>.md` (same file on NTFS) and then deletes every name not in its case-sensitive keep set, removing the file it just wrote.
- **Repro:** create `ctx-1.MD`; `write_all(list_contexts())` → directory empty (expected 1 file). Reproduced on Windows.
- **Test:** `tests/test_contexts.py`

### [KNOWN-301] `preroll=0` keeps the whole silence history
- **Where:** `audio.py:74` (`_Segmenter.process`, slice `[-self.preroll_samples:]`)
- **Behavior:** with `preroll_samples == 0` the slice is `[-0:]`, which returns the full buffer; pre-roll grows during silence and is prepended to the utterance.
- **Repro:** `_Segmenter(preroll=0.0)` fed 3 silent + 3 speech + 5 silent blocks of 1600 samples (test params) → first speech sample at index 4800 and utterance cut as `maxlen` (expected index 0). Not reachable with the default `preroll=0.3`.
- **Test:** `tests/test_audio.py`

### [KNOWN-302] Speech-onset block longer than the pre-roll window loses its start
- **Where:** `audio.py:74-77`
- **Behavior:** the block that triggers speech enters the buffer only through the pre-roll slice; if it is longer than the window its beginning is dropped, while `_speech_samples` counts the full block.
- **Repro:** `preroll=0.05` (800 samples), 3 speech blocks of 1600 + 5 silent → 4000 speech samples kept (expected 4800). Not reachable with the engine's ~341-sample blocks and default `preroll=0.3`.
- **Test:** `tests/test_audio.py`

## Suspected issues — from code review, not yet covered by tests

### [KNOWN-001] Unsynchronized iteration over session history
- **Where:** `engine.py:531` (`list(self._history)` in the worker) vs `engine.py:340` (`append` from the turn timer / WebSocket thread).
- **Risk:** `RuntimeError: deque mutated during iteration`, swallowed at `engine.py:496`; the suggestion for that turn is dropped.

### [KNOWN-002] Session transcript misses turns
- **Where:** `engine.py:374-378` (`answer_now` with a pending turn) and `engine.py:461-468` (offline path) append to `_history` but not to `_registro`.
- **Effect:** the saved `sesiones/*.md` file omits those turns.

### [KNOWN-003] UI stays in running state when engine start-up fails
- **Where:** `engine.py:187/195/237` set `_running = False` on init failure; `app.py:185` keeps `OverlayApp._running = True` and `on_error` does not reset it.

### [KNOWN-004] Anthropic client uses SDK default retries and timeout
- **Where:** `llm.py:84` (`anthropic.Anthropic(api_key=...)`), plus the manual retry at `llm.py:192-217`.
- **Effect:** SDK default `max_retries=2` (408/409/429/5xx/connection) and 10-minute timeout, stacked with the manual retry: up to 6 attempts per suggestion. Retry classification uses error-string matching instead of typed exceptions.

### [KNOWN-005] No logging
- **Where:** 44 broad `except` blocks across the codebase; no `logging` usage.
- **Effect:** runtime failures leave no trace on disk.

## Test infrastructure notes
- `faster_whisper` is not installed in `.venv`; `tests/test_transcribe.py` injects a stub module. Offline mode cannot run from this venv as-is.
- `--cov=contexts` measures the `contexts/` data directory instead of `contexts.py`. Use `--cov=. --cov-report=term-missing` and read the module rows.

## Resolved issues
None yet.
