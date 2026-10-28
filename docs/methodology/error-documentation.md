# Error documentation

Known defects and their resolution. IDs: `[KNOWN-NNN]` while open, renamed to `[ERR-NNN]` once fixed.
Every KNOWN entry with a test is pinned by a `pytest.mark.xfail(strict=True)` test asserting the correct behavior; when the fix lands, the xfail turns into an XPASS failure and must be removed together with the fix.

## Triage (2026-10-28)

All entries below were reproduced on 2026-10-28 (Windows, Python 3.11.9, PySide6 6.12, offscreen Qt for UI paths). Severity: **P1** data loss / app unusable, **P2** visible malfunction in normal use, **P3** limited or cosmetic, **P4** latent (not reachable today).

| Priority | IDs | Summary | Suggested fix branch |
|---|---|---|---|
| P1 | ~~KNOWN-204~~ ERR-204 | Settings → Save deletes contexts with an upper-case `.MD` extension | `fix/…-contexts-case-insensitive` |
| P1 | ~~KNOWN-205~~ ERR-205, ~~KNOWN-206~~ ERR-206 | Unreadable/BOM `config.json` → keys blanked and persisted; non-atomic save truncates the file | `fix/…-safe-config-io` |
| P1 | ~~KNOWN-201~~ ERR-201, ~~KNOWN-202~~ ERR-202 | Corrupt `config.json` aborts startup (`--noconsole`: no message) | `fix/…-safe-config-io` |
| P2 | KNOWN-501 | Every streamed suggestion is painted twice | `fix/…-answer-repaint-timer` |
| P2 | ~~KNOWN-203~~ ERR-203 | One non-UTF-8 context blocks Settings and leaves the meeting UI running without engine | `fix/…-safe-config-io` |
| P2 | KNOWN-003 | Engine init failure leaves the UI in running state | `fix/…-start-failure-state` |
| P2 | KNOWN-004 | 6 HTTP attempts / ~3.4 s per failed suggestion; 600 s read timeout | `fix/…-llm-client-timeouts` |
| P2 | KNOWN-005 | No logging; background-thread failures discarded | `feat/…-file-logging` |
| P2 | KNOWN-103 | Code spans in suggestions rendered with bold/italic (`__init__` → **init**) | `fix/…-inline-code-render` |
| P2 | KNOWN-402 | Touchpad: scroll down too fast, scroll up does nothing | `fix/…-wheel-accumulator` |
| P3 | KNOWN-002 | Session transcript misses Alt+5 pending turns (and all spoken turns offline) | `fix/…-start-failure-state` or own branch |
| P3 | KNOWN-101, KNOWN-102 | Question detector false positives (ES) / false negatives (EN contractions) without `?` | `fix/…-intent-tokenizer` |
| P3 | KNOWN-601 | `speech_threshold` slider shows/saves 0.013 for 0.012; max saves 0.101 | `fix/…-inline-code-render` (small UI batch) |
| P3 | KNOWN-401 | One Alt+digit press lost after an interrupted Alt combo | `fix/…-wheel-accumulator` (input batch) |
| P3 | KNOWN-503, KNOWN-504, KNOWN-502 | Top bar not draggable; copy-reset `RuntimeError`; caret not blinking | small UI batch |
| P3 | KNOWN-701 | Capture context can exceed 8000 chars by ≤ 79 | any engine branch |
| P4 | KNOWN-301, KNOWN-302 | Segmenter pre-roll edge cases; unreachable with fixed `preroll=0.3` | drop with offline removal |
| — | KNOWN-001 | Closed: not a defect on CPython 3.11 (measured) | — |

## Known issues — confirmed by tests

### [KNOWN-101] Interrogative or request token inside a statement is classified as a question
- **Where:** `intent.py:92-97` (any interrogative within the first 4 tokens → `True`) and `intent.py:85-86` (request phrases matched as substrings anywhere).
- **Reproduced (2026-10-28), phrases without `?`:**

  | Phrase | Result | Expected |
  |---|---|---|
  | `no sé qué hacer con el despliegue` | `True` | `False` |
  | `lo que sea que decidan está bien` | `True` | `False` |
  | `que el equipo lo revise mañana` | `True` | `False` |
  | `cuando terminemos lo subimos` | `True` | `False` |
  | `las dimensiones del cluster son grandes` (`dime` ⊂ `dimensiones`) | `True` | `False` |
  | `cómo lo harías tú` | `True` | `True` |
- **Impact:** gate 1 is intentionally permissive; a false positive costs one LLM request with `allow_silence=True`, normally answered with `NO_RESPONSE` (gate 2) → extra latency/cost per statement and a "Not a question" pill. Only relevant when the transcript has no `?` (AssemblyAI `format_turns=true` usually adds it).
- **Proposed fix:** match request phrases on word boundaries (`\b`); treat `que`/`cuando`/`como` as interrogative only at token 0 or after a conjunction, or require accent-bearing forms when the transcript keeps accents.
- **Test:** `tests/test_intent.py` (KNOWN-101 xfail)
### [KNOWN-102] English contractions with ASCII apostrophe are not detected
- **Where:** `intent.py:74` (token regex `[a-z0-9']+` keeps `what's` as one token; `_INTERROGATIVAS_EN` contains `what`).
- **Reproduced (2026-10-28), phrases without `?`:** `what's your take on this`, `how's the migration going`, `where's the bottleneck in your design` → `False` (expected `True`); `what is your take on this` → `True`.
- **Impact:** false negative at gate 1: the turn is stored as context and no suggestion is requested; the user must press Alt+5. Only when the transcript lacks `?`.
- **Proposed fix:** split contractions (`re.findall(r"[a-z0-9]+", ...)` or strip `'s`/`'re`/`'d`) before the interrogative lookup.
- **Test:** `tests/test_intent.py` (KNOWN-102 xfail)
### [KNOWN-103] Bold/italic substitution runs inside inline code
- **Where:** `richtext.py:254-259` (`inline_html`); rendered through `overlay_ui.py:1446` (paragraphs) and `:1455` (bullets).
- **Reproduced (2026-10-28) in `TranscriptPanel`:** model text ``Override `__init__` and forward `**kwargs` `` renders the code span as `<b>init</b>`; ``Use `a * b * c` `` renders `a <i> b </i> c` inside the code span. With two `**` on a line (``\`x ** 2\` and **bold**``) the generated markup is unbalanced.
- **Root cause:** emphasis regexes run on the whole string after code spans are converted, without protecting their content.
- **Impact:** code identifiers in suggestions are displayed incorrectly (dunder methods, `**kwargs`, `*args`, arithmetic) — the case the vision model is prompted to produce.
- **Proposed fix:** tokenize code spans first (replace with placeholders), apply emphasis to the remaining text, then restore escaped code spans.
- **Test:** `tests/test_richtext.py` (KNOWN-103 xfail)
### [KNOWN-301] `preroll=0` keeps the whole silence history
- **Where:** `audio.py:74` (`_Segmenter.process`, slice `[-self.preroll_samples:]`)
- **Behavior:** with `preroll_samples == 0` the slice is `[-0:]`, which returns the full buffer; pre-roll grows during silence and is prepended to the utterance.
- **Repro:** `_Segmenter(preroll=0.0)` fed 3 silent + 3 speech + 5 silent blocks of 1600 samples → first speech sample at index 4800 and utterance cut as `maxlen` (expected index 0).
- **Reachability (2026-10-28):** not reachable. `preroll` is not a config key; `AudioEngine` constructs `_Segmenter` with the default `0.3` (`audio.py:150-155`). Offline mode only.
- **Impact:** none in the current app; latent if `preroll` is ever exposed.
- **Proposed fix:** `self._preroll = buf[-n:] if n else buf[:0]`. Drop if offline mode is removed (`refactor/28102026-remove-offline-whisper`).
- **Test:** `tests/test_audio.py::test_segmenter_without_preroll_starts_at_speech_onset`
### [KNOWN-302] Speech-onset block longer than the pre-roll window loses its start
- **Where:** `audio.py:74-77`
- **Behavior:** the block that triggers speech enters the buffer only through the pre-roll slice; if it is longer than the window its beginning is dropped, while `_speech_samples` counts the full block.
- **Repro:** `preroll=0.05` (800 samples), 3 speech blocks of 1600 + 5 silent → 4000 speech samples kept (expected 4800).
- **Reachability (2026-10-28):** not reachable. Blocks reaching the segmenter are `CHUNK=1024` device frames resampled to 16 kHz: 341 samples at 48 kHz, 372 at 44.1 kHz, 1024 at 16 kHz — always below the 4800-sample window of the fixed `preroll=0.3`.
- **Impact:** none in the current app.
- **Proposed fix:** append the trigger block to `_buf` separately from the pre-roll (`self._buf = [preroll_before_block, block]`). Drop if offline mode is removed.
- **Test:** `tests/test_audio.py::test_segmenter_keeps_whole_trigger_block_longer_than_preroll`
### [KNOWN-401] Digit held across an Alt+other-key combo stays in `_eaten`
- **Where:** `hotkeys.py:322` with `:332` / `:344` (`AltInterceptor._handle`): in passthrough mode (`self._passthrough`) the handler returns before the `_eaten` key-up check.
- **Trigger:** Alt held, a bound digit pressed (action fires), another key pressed while the digit is still down (e.g. Tab), then the digit released.
- **Reproduced (2026-10-28)** (`user32` faked): hook results for `Alt↓ 1↓ Tab↓ 1↑ Tab↑ Alt↑` = swallowed, swallowed, swallowed, passed, passed, passed; `_eaten = {VK_1}` afterwards. Next Alt+1: no action, `_eaten` cleared; following Alt+1 presses work.
- **Impact:** exactly one subsequent Alt+digit press of that digit is lost, then it self-recovers. The digit key-up leaks to the focused app (key-up without key-down; no visible effect observed).
- **Proposed fix:** run the `_eaten` key-up check before the `if self._passthrough: return False` branch.
- **Test:** `tests/test_hotkeys.py::test_alt_digit_triggers_after_hold_interrupted_by_other_key`
### [KNOWN-402] Negative partial wheel deltas round away from zero
- **Where:** `wheelscroll.py:144` (`muescas = delta // RUEDA_POR_MUESCA`, `RUEDA_POR_MUESCA = 120`)
- **Trigger:** wheel events with `|delta| < 120` or not a multiple of 120 — high-resolution wheels and precision touchpads. Standard notched wheels (±120) are unaffected.
- **Reproduced (2026-10-28):** 8 events of `|delta|` 30 or 60 → scrolling down = 8 notches, scrolling up = 0 notches; with `|delta| = 120` both directions = 8 notches.
- **Root cause:** Python floor division (`-60 // 120 == -1`, `60 // 120 == 0`).
- **Impact:** over the overlay answer, touchpad scrolling down jumps one notch per event (too fast) and scrolling up does nothing.
- **Proposed fix:** accumulate the remainder per direction (`self._acum += delta; n = int(self._acum / 120); self._acum -= n * 120`), which also fixes the "sub-notch movement is swallowed" behavior.
- **Test:** `tests/test_wheelscroll.py::test_wheel_partial_notch_down_mirrors_up`
### [KNOWN-601] `speech_threshold` slider cannot represent its default value
- **Where:** `settings_window.py:630-633` (`_number_control`: `steps = round((max-min)/step)`, `value = round((val-min)/step)`), field schema at `settings_window.py:272` (min 0.001, step 0.002, max 0.1).
- **Reproduced (2026-10-28) in `SettingsWindow`**, config `speech_threshold=0.012` (default):

  | Action | Label | Saved to `config.json` |
  |---|---|---|
  | open | `0.013` (slider 6/50) | — |
  | Save without touching | `0.013` | `0.012` |
  | slider +1 then -1, Save | `0.013` | `0.013` |
  | slider at max, Save | — | `0.101` (above declared max 0.1) |
- **Scope:** checked all 11 numeric fields in `_schema()`: only `speech_threshold` has an off-grid default or an off-grid max.
- **Root cause:** `(0.012 - 0.001) / 0.002 = 5.5` is not an integer; `(0.1 - 0.001) / 0.002 = 49.5` rounds up to 50.
- **Impact:** low. The displayed value differs from the stored one until the slider is touched; then the threshold becomes 0.013 (≈8% less sensitive voice detection / echo gate, `audio.py:271`).
- **Proposed fix:** `min=0.002` (grid 0.002…0.100 contains 0.012 and 0.1) or `step=0.001`.
- **Test:** `tests/test_settings_window.py::test_speech_threshold_displays_default_value`
### [KNOWN-501] Final answer is painted twice after `cerrar_respuesta`
- **Where:** `overlay_ui.py:1357-1382` (`append_answer` arms a 90 ms `QTimer.singleShot(_repintar)`; `cerrar_respuesta` repaints when `_repintado_pendiente` and sets `_burbuja_resp = None`, but cannot cancel the pending single-shot).
- **Trigger:** `respDone` delivered less than `INTERVALO_REPINTADO` (90 ms) after the last `respDelta`. The engine emits `respDone` from `on_done` immediately after the stream ends (`engine.py:590-609`), so this is the normal path; short answers (`< len(SENTINEL)`) emit `respStart`, one `respDelta` and `respDone` back to back (`engine.py:595-598`).
- **Reproduced (2026-10-28) through `OverlayApp` signal wiring** (`app.on_resp_done` → `panel.cerrar_respuesta`), `respDone` right after the last delta:

  | Stream shape | Suggestion bubbles |
  |---|---|
  | 1 delta (short answer) | 2 |
  | 2-12 deltas, 10 / 25 / 40 ms apart | 2 in 33/33 runs |
  | last delta followed by >= 90 ms of idle before `respDone` | 1 |
- **Root cause:** the throttle timer is a fire-and-forget `singleShot` on a bound method; when it fires after `cerrar_respuesta`, `_repintar` sees `_burbuja_resp is None` and creates a new bubble from the same `_raw`.
- **Impact:** every streamed suggestion appears twice in the thread; doubles render work per answer (`pintado_ms`).
- **Proposed fix:** use one `QTimer` instance (`setSingleShot(True)`) owned by the panel and `stop()` it in `cerrar_respuesta` / `clear_answer` / `limpiar_hilo`; or make `_repintar` a no-op when no answer is open.
- **Test:** `tests/test_overlay_ui_thread.py::test_cerrar_respuesta_does_not_duplicate_answer`
### [KNOWN-502] Question caret never blinks
- **Where:** `overlay_ui.py:1242` (`_animate` re-renders the caret only when `self._question_text`); `_question_text` is set to `""` at `overlay_ui.py:964` and never assigned again.
- **Reproduced (2026-10-28):** `set_state("listening"); set_question("Tell me about")`, 1.5 s → caret stays visible.
- **Root cause:** `set_question` stores the text elsewhere and does not update `_question_text`.
- **Impact:** cosmetic; the caret is static instead of blinking. No functional effect.
- **Proposed fix:** assign `self._question_text = texto` in `set_question` and clear it in `cerrar_intervencion` / `limpiar_hilo`.
- **Test:** `tests/test_overlay_ui_thread.py::test_caret_blinks_while_listening`
### [KNOWN-503] Drag mixin handlers are shadowed by `QWidget`
- **Where:** `overlay_ui.py:746`, `957`, `1488` — `class X(QtWidgets.QWidget, _Draggable)`; `_Draggable.mousePressEvent/mouseMoveEvent` (`overlay_ui.py:159-170`) are never reached.
- **Reproduced (2026-10-28):** MRO resolves `mousePressEvent` to `QWidget` for `TopBar`, `TranscriptPanel` and `CollapsedButton`; a press/move on an empty area of `TopBar` does not move it.
- **Effective behavior per window:**
  - `TranscriptPanel`: movable through its `DragBar` header (`overlay_ui.py:1070`), which implements its own handlers — works.
  - `TopBar`: not movable. In production its empty areas are also click-through (`interactive_widgets()` returns only `[self.btn_cfg]`, `overlay_ui.py:869-871`; `app._update_click_through`), so fixing the MRO alone does not make it draggable.
  - `CollapsedButton`: its whole surface is a `ClickFrame` child that consumes the press; not movable.
- **Root cause:** base-class order; the mixin must precede `QWidget` to override Qt's virtual handlers.
- **Impact:** low; the top bar and the collapsed button stay where `_place` puts them. Dead code in `_Draggable`.
- **Proposed fix:** decide whether those windows should be movable. If yes: `class TopBar(_Draggable, QtWidgets.QWidget)` plus an interactive drag zone (e.g. a grip) in `interactive_widgets()`. If no: remove `_Draggable` and its docstring claim.
- **Test:** `tests/test_overlay_ui_widgets.py::test_topbar_drag_from_empty_area_moves_window`
### [KNOWN-504] Copy-label reset fires on a destroyed `CodeBlock`
- **Where:** `overlay_ui.py:513` (`CodeBlock._copiar`: `QTimer.singleShot(1400, lambda: self.lbl_copy.setText(...))`)
- **Trigger:** Copy clicked, then the block is destroyed within 1.4 s (answer re-render while streaming, row pruning, `limpiar_hilo`).
- **Reproduced (2026-10-28):** `RuntimeError: Internal C++ object already deleted` raised from the event loop.
- **Root cause:** the lambda is not tied to the widget's lifetime (plain callable, no receiver object).
- **Impact:** low; PySide reports the exception and the app keeps running. With `--noconsole` nothing is visible.
- **Proposed fix:** `QtCore.QTimer.singleShot(1400, self.lbl_copy, lambda: ...)` (receiver overload, cancelled on destruction) or a child `QTimer`.
- **Test:** `tests/test_overlay_ui_widgets.py::test_code_block_destroyed_after_copy_raises_nothing`
### [KNOWN-002] Session transcript misses turns
- **Where:** `_registro` (the transcript saved to `sesiones/sesion-*.md` by `_guardar_acta`, `engine.py:672-695`) is appended only in `_flush_turn` (`engine.py:341`) and in `_respond.on_done` (`engine.py:608`).
  - `answer_now` with a pending turn (`engine.py:374-378`) appends to `_history` only.
  - Offline worker path (`engine.py:461-468`): mic (`"Yo"`) and system (`"Ellos"`) utterances append to `_history` only.
  - Cloud test mode returns before `_flush_turn` (`engine.py:305-308`): nothing is recorded (by design or not — undocumented).
- **Reproduced (2026-10-28):** the three xfail tests below fail as expected.
- **Impact:** in offline mode the saved transcript contains only `### Sugerido` blocks, none of the spoken turns; in cloud mode, turns forced with Alt+5 while someone is still speaking are missing.
- **Proposed fix:** a single `_record(speaker, text)` helper that appends to both `_history` and `_registro`, used at every turn-closing site. Note: if `refactor/28102026-remove-offline-whisper` removes offline mode, only the `answer_now` part remains.
- **Test:** `tests/test_engine.py::TestTurns::test_manual_answer_records_pending_turn`, `tests/test_engine.py::TestWorker::test_offline_utterance_is_recorded`
### [KNOWN-003] UI stays in running state when engine start-up fails
- **Where:** `app.py:185-190` set `_running = True`, start the top bar state and the 1 s timer before `engine.start` (`app.py:203`); `on_error` (`app.py:408-413`) only updates the badge and skip pill. Engine-side failures at `engine.py:187`, `195`, `237` set only the engine's `_running = False`.
- **Trigger:** any init failure reported through `error`: missing AssemblyAI key at engine level, Whisper load failure, `Coach` construction failure (invalid provider SDK, bad key format), contexts read failure (KNOWN-203).
- **Reproduced (2026-10-28) through `OverlayApp`:** after the error `_running=True`, timer active, badge `Error`. First Start press (Alt+4) calls `stop_meeting` (engine `stop` count 1, no start); only the second press calls `engine.start`.
- **Impact:** the UI shows a running meeting with an advancing timer and no audio/STT/LLM; the user must press Start twice to recover.
- **Proposed fix:** add an engine signal for init outcome (e.g. `started(bool)`) or treat errors received while the engine reports `not running` as a start failure: call `stop_meeting()` (UI-only reset) and keep the error visible.
- **Test:** `tests/test_app.py::TestMeeting::test_initialization_error_restores_idle`
### [KNOWN-701] Capture context budget ignores line separators
- **Where:** `engine.py:538-545` (`_contexto`, capture branch sums `len(linea)` but the result is joined with `"\n"`).
- **Repro:** two history lines of 4000 chars → 8001-char context (limit 8000).
- **Impact:** negligible: the overshoot is at most `lines - 1` characters (≤ 79 with `CONTEXTO_CAPTURA=80`) on an 8000-char budget.
- **Proposed fix:** `total + len(linea) + (1 if recortado else 0) > LIMITE_CHARS_CAPTURA`.
- **Test:** `tests/test_engine.py::TestContext::test_capture_limit_includes_line_separators`
## Design issues — confirmed by measurement

### [KNOWN-004] LLM clients keep SDK default retries and a 10-minute read timeout
- **Where:** `llm.py:79-84` (`anthropic.Anthropic(api_key=...)` / `OpenAI(api_key=...)` with defaults) plus the manual retry loop `llm.py:192-221`.
- **Measured (2026-10-28), anthropic 2.3.0 / openai 3.37.0:** defaults `max_retries=2`, `timeout=Timeout(connect=5.0, read=600, write=600, pool=600)` on both SDKs. Through `Coach.stream_response` with a mocked transport:

  | Server response | HTTP requests | Time until `on_error` |
  |---|---|---|
  | 503 | 6 | 3.1 s |
  | 529 overloaded | 6 | 3.4 s |
  | 401 | 1 | 0.0 s |
- **Root cause:** the SDK retries 2× with backoff inside each attempt; `_reintentable` (string matching on the error text) adds one more attempt → 2 × 3 requests.
- **Impact:** during an outage each suggestion takes ~3.4 s to fail instead of failing fast; a stalled stream can block the single worker thread for up to 600 s per attempt, queueing every later turn behind it.
- **Proposed fix:** construct clients with `max_retries=0` (keep the single manual retry before the first token) and a request timeout sized for live use (e.g. `connect=5`, `read=20`); classify retryable errors with the SDK exception types (`RateLimitError`, `APIConnectionError`, `InternalServerError`, `APIStatusError.status_code`) instead of message text.
- **Test:** none yet (needs a mocked-transport test in `tests/test_llm.py`).
### [KNOWN-005] No logging; failures in background threads are discarded
- **Where:** no module imports `logging`. Broad handlers that discard the exception with no signal/status: `audio.py:103-104` (`on_utterance` callback — offline utterance lost), `audio.py:278-280` (`on_system_pcm` → `StreamingSTT.feed` — cloud transcription stops silently), `engine.py:669-670` (metrics report and session transcript not written), `llm.py:255-256` (warm-up), `stt_stream.py:124-129, 230-231`, and 6 more `pass` branches in `audio.py`. Per module: `audio.py` 11, `engine.py` 8, `stt_stream.py` 7, `richtext.py` 3, `overlay.py` 3, `llm.py` 3, `hotkeys.py` 3, others ≤ 2.
- **Impact:** field failures leave no trace on disk; the packaged exe runs with `--noconsole`, so stderr is also lost. The defects in this file were found by tests, not from logs.
- **Proposed fix:** configure `logging` at startup with a `RotatingFileHandler` in `%APPDATA%\Armony\logs\armony.log` (never logging secrets); replace silent `pass` with `log.exception(...)` in the handlers above; install `sys.excepthook` / `threading.excepthook` and a Qt message handler.
- **Test:** none (design change).
## Test infrastructure notes
- `faster_whisper` is not installed in `.venv`; `tests/test_transcribe.py` injects a stub module. Offline mode cannot run from this venv as-is.
- `--cov=contexts` measures the `contexts/` data directory instead of `contexts.py`. Use `--cov=. --cov-report=term-missing` and read the module rows.

## Closed — not a defect

### [KNOWN-001] Unsynchronized iteration over session history — not a defect on CPython 3.11
- **Where:** `engine.py:531` (`list(self._history)` in the worker) vs `engine.py:340` (`append` from the turn timer / WebSocket thread).
- **Measured (2026-10-28), Python 3.11.9:** `list(deque)` concurrently with a thread appending to a `deque(maxlen=120)`: 1,217,810 reads in 4 s, 0 `RuntimeError`. A Python-level `for x in deque` under the same load: 106 `RuntimeError` in 4 s.
- **Conclusion:** `list(deque)` copies in C without releasing the GIL, so the code as written cannot raise. It would become a real race on a free-threaded (no-GIL) build or if the copy were rewritten as a Python loop. Keep `list(...)` (or add a lock) if this code changes.

## Resolved issues

### [ERR-204] `write_all` deletes a context whose extension is upper-case (data loss)
- **Where:** `contexts.py:60` (listing filter uses `fn.lower().endswith(".md")`) vs `contexts.py:87-97` (writes `<id>.md`, deletes every `.md` whose exact name is not in `vivos`).
- **Trigger:** a context file with a non-lower-case extension (`.MD`, `.Md`) placed in `contexts/` outside the app; the app itself always writes `.md`.
- **Reproduced (2026-10-28), user path:** open Settings, press Save without editing (`settings_window.py:941-947`):

  | Files before | Files after | UI status |
  |---|---|---|
  | `ctx-1.md` | `ctx-1.md` | "Todo guardado" |
  | `ctx-1.MD` | *(none)* | "Todo guardado" |
  | `ctx-1.Md`, `ctx-2.md` | `ctx-2.md` | "Todo guardado" |
  | `Notas.MD` | *(none)* | "Todo guardado" |
- **Root cause:** NTFS is case-insensitive: writing `ctx-1.md` overwrites `ctx-1.MD` in place and the directory entry keeps the original spelling `ctx-1.MD`; the delete pass compares names case-sensitively, so the just-written file is not in `vivos` and is removed.
- **Impact:** silent, permanent loss of the context content; no error is shown. On a case-sensitive file system the effect is a rename instead (no loss).
- **Resolution (2026-10-28):** `write_all` compares file names with `os.path.normcase` (`contexts.py:91-99`); a context listed from `ctx-1.MD` is rewritten in place and kept. Verified end-to-end through Settings → Save for `ctx-1.MD`, `ctx-1.Md`+`ctx-2.md`, `Notas.MD`.
- **Regression tests:** `tests/test_contexts.py::test_write_all_preserves_listed_uppercase_extension_context`, `::test_write_all_keeps_content_of_mixed_case_extension`, `::test_write_all_still_deletes_removed_mixed_case_context`

### [ERR-201] Non-UTF-8 `config.json` raises in `load_config`
- **Where:** `config.py:167-169` (`open(..., encoding="utf-8")` + `except (json.JSONDecodeError, OSError)`)
- **Trigger:** `config.json` saved in a legacy code page (e.g. edited and saved as "ANSI"/cp1252) containing any non-ASCII character (`é`, `ñ` in prompts).
- **Reproduced (2026-10-28):** cp1252 file with `"Sé breve y en español"` → `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9`.
- **Root cause:** `UnicodeDecodeError` is a `ValueError`, not a `JSONDecodeError`/`OSError`, so it escapes the handler.
- **Impact:** `load_config` runs in `OverlayApp.__init__` (`app.py:28`) before any window exists; the exception aborts `main()`. Built with `--noconsole`, the exe exits with no visible error. Also raised from `start_meeting` (`app.py:169`), `open_settings` (`app.py:306`) and `_on_settings_saved` (`app.py:329`).
- **Resolution (2026-10-28):** `config.read_user_text` decodes UTF-8 (BOM allowed), then cp1252, then latin-1, so legacy-encoded files load with their content; `load_config` catches `ValueError`/`OSError`. Verified: cp1252 config keeps the API key and `language`.
- **Regression tests:** `tests/test_config.py::test_load_config_reads_cp1252_file`, `::test_read_user_text_decoding_fallbacks`

### [ERR-202] Non-object JSON in `config.json` raises in `load_config`
- **Where:** `config.py:168` (`cfg.update(json.load(f))`)
- **Trigger:** syntactically valid JSON whose top level is not an object (`null`, a number, a string, a list).
- **Reproduced (2026-10-28):** `null` → `TypeError: 'NoneType' object is not iterable`; `[1, 2]` → `TypeError: cannot convert dictionary update sequence element #0`.
- **Root cause:** the result of `json.load` is passed to `dict.update` without a type check; the `TypeError`/`ValueError` is outside the caught set.
- **Impact:** same crash path as KNOWN-201 (startup abort). Lower likelihood: requires an external edit or tool writing the file.
- **Resolution (2026-10-28):** `load_config` applies the file only if the parsed value is a `dict`; otherwise the file is quarantined (see ERR-205) and defaults are used.
- **Regression tests:** `tests/test_config.py::test_load_config_with_non_object_json_falls_back_to_defaults`, `::test_unparseable_config_is_quarantined`

### [ERR-203] One non-UTF-8 context file breaks `list_contexts`
- **Where:** `contexts.py:64-67` (`open(..., encoding="utf-8")` + `except OSError`)
- **Trigger:** any `contexts/*.md` written outside the app in a legacy code page with non-ASCII text.
- **Reproduced (2026-10-28):** cp1252 `ctx-2.md` next to a valid `ctx-1.md` → `UnicodeDecodeError` from `list_contexts`, `active_count`, `active_text` and `SettingsWindow(...)` construction (`settings_window.py:354`).
- **Root cause:** `UnicodeDecodeError` is not an `OSError`; one bad file aborts the whole listing instead of being skipped.
- **Impact:**
  - Settings window cannot open (exception in the `settingsClicked` slot).
  - `start_meeting` sets `_running = True`, starts the top bar and timer (`app.py:185-190`) and then raises at `active_count` (`app.py:197`) before `engine.start` (`app.py:203`): the UI shows a running meeting with no engine (same end state as KNOWN-003).
  - In the engine thread, `active_text` (`engine.py:220`) raises inside the `try` and is reported as "No se pudo iniciar Claude".
- **Resolution (2026-10-28):** `list_contexts` reads through `config.read_user_text` (never raises on decoding), so legacy-encoded contexts are listed with their content and rewritten as UTF-8 on the next save. Skipping was rejected: a skipped file would be deleted by `write_all`. Verified: Settings opens, `active_count` = 2, both contexts survive Save.
- **Regression tests:** `tests/test_contexts.py::test_list_contexts_reads_cp1252_file`, `::test_write_all_rewrites_cp1252_context_as_utf8`, `::test_list_contexts_reads_utf8_bom_file`

### [ERR-205] UTF-8 BOM `config.json` is discarded and keys are lost on next save
- **Where:** `config.py:167` (`encoding="utf-8"` does not strip a BOM → `JSONDecodeError` → silently returns defaults)
- **Trigger:** `config.json` saved by an editor that writes a UTF-8 BOM.
- **Reproduced (2026-10-28):** BOM file with an encrypted `anthropic_api_key` and `language: en` → `load_config` returns `language: es` and an empty key; Settings → Save writes the empty key to disk.
- **Root cause:** decode/parse failures are swallowed and replaced by defaults with no backup and no user-visible warning; the next `save_config` overwrites the original file with those defaults.
- **Impact:** permanent loss of all stored API keys and settings. The same overwrite path applies to any unreadable file (empty file left by KNOWN-206, KNOWN-201/202 once they stop crashing).
- **Resolution (2026-10-28):** BOM is accepted (`utf-8-sig`). A file that still cannot be parsed is renamed to `config.json.bad-<YYYYmmdd-HHMMSS>` before defaults are used, so the next save cannot overwrite it. Follow-up (not done): the UI does not yet tell the user that a file was quarantined.
- **Regression tests:** `tests/test_config.py::test_load_config_reads_utf8_file_with_bom`, `::test_quarantined_config_keeps_original_bytes`, `::test_save_after_quarantine_does_not_touch_backup`, `::test_valid_config_is_not_quarantined`

### [ERR-206] `save_config` is not atomic
- **Where:** `config.py:199-203` (`open(CONFIG_PATH, "w")` truncates, then `json.dump` streams into it; only `OSError` is caught)
- **Trigger:** any exception during serialisation (non-JSON value) or process termination/power loss during the write.
- **Reproduced (2026-10-28):** existing `{"language": "en"}`; `save_config({"bad": object()})` → `TypeError` propagates and `config.json` is left truncated.
- **Impact:** an empty/partial `config.json`; on the next start KNOWN-205's path blanks every key. `SettingsWindow._save` catches the exception and shows "Error al guardar", but the file is already damaged.
- **Resolution (2026-10-28):** `save_config` serialises to a string first (returns `False` on `TypeError`/`ValueError`), writes `config.json.tmp`, `flush` + `os.fsync`, then `os.replace`; the temp file is removed on failure.
- **Regression tests:** `tests/test_config.py::test_failed_save_keeps_previous_config_file`, `::test_failed_save_returns_false`, `::test_save_leaves_no_temp_file`
