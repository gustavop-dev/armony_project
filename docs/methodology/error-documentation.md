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
- **Where:** `config.py:167-169` (`open(..., encoding="utf-8")` + `except (json.JSONDecodeError, OSError)`)
- **Trigger:** `config.json` saved in a legacy code page (e.g. edited and saved as "ANSI"/cp1252) containing any non-ASCII character (`é`, `ñ` in prompts).
- **Reproduced (2026-10-28):** cp1252 file with `"Sé breve y en español"` → `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9`.
- **Root cause:** `UnicodeDecodeError` is a `ValueError`, not a `JSONDecodeError`/`OSError`, so it escapes the handler.
- **Impact:** `load_config` runs in `OverlayApp.__init__` (`app.py:28`) before any window exists; the exception aborts `main()`. Built with `--noconsole`, the exe exits with no visible error. Also raised from `start_meeting` (`app.py:169`), `open_settings` (`app.py:306`) and `_on_settings_saved` (`app.py:329`).
- **Proposed fix:** catch `(ValueError, OSError)` (covers `JSONDecodeError` and `UnicodeDecodeError`); combine with KNOWN-205/206 handling of unreadable files (keep a backup instead of overwriting).
- **Test:** `tests/test_config.py::test_load_config_with_non_utf8_file_falls_back_to_defaults`
### [KNOWN-202] Non-object JSON in `config.json` raises in `load_config`
- **Where:** `config.py:168` (`cfg.update(json.load(f))`)
- **Trigger:** syntactically valid JSON whose top level is not an object (`null`, a number, a string, a list).
- **Reproduced (2026-10-28):** `null` → `TypeError: 'NoneType' object is not iterable`; `[1, 2]` → `TypeError: cannot convert dictionary update sequence element #0`.
- **Root cause:** the result of `json.load` is passed to `dict.update` without a type check; the `TypeError`/`ValueError` is outside the caught set.
- **Impact:** same crash path as KNOWN-201 (startup abort). Lower likelihood: requires an external edit or tool writing the file.
- **Proposed fix:** `data = json.load(f)`; ignore (and back up) when `not isinstance(data, dict)`.
- **Test:** `tests/test_config.py::test_load_config_with_non_object_json_falls_back_to_defaults`
### [KNOWN-203] One non-UTF-8 context file breaks `list_contexts`
- **Where:** `contexts.py:64-67` (`open(..., encoding="utf-8")` + `except OSError`)
- **Trigger:** any `contexts/*.md` written outside the app in a legacy code page with non-ASCII text.
- **Reproduced (2026-10-28):** cp1252 `ctx-2.md` next to a valid `ctx-1.md` → `UnicodeDecodeError` from `list_contexts`, `active_count`, `active_text` and `SettingsWindow(...)` construction (`settings_window.py:354`).
- **Root cause:** `UnicodeDecodeError` is not an `OSError`; one bad file aborts the whole listing instead of being skipped.
- **Impact:**
  - Settings window cannot open (exception in the `settingsClicked` slot).
  - `start_meeting` sets `_running = True`, starts the top bar and timer (`app.py:185-190`) and then raises at `active_count` (`app.py:197`) before `engine.start` (`app.py:203`): the UI shows a running meeting with no engine (same end state as KNOWN-003).
  - In the engine thread, `active_text` (`engine.py:220`) raises inside the `try` and is reported as "No se pudo iniciar Claude".
- **Proposed fix:** catch `(OSError, UnicodeDecodeError)` per file and skip it (or read with `errors="replace"`); surface skipped files in the settings UI.
- **Test:** `tests/test_contexts.py` (KNOWN-203 xfail)
### [KNOWN-204] `write_all` deletes a context whose extension is upper-case (data loss)
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
- **Proposed fix:** build `vivos` and compare with `os.path.normcase` (or `.lower()`), or remember each context's original filename and write back to it.
- **Test:** `tests/test_contexts.py` (KNOWN-204 xfail)
### [KNOWN-205] UTF-8 BOM `config.json` is discarded and keys are lost on next save
- **Where:** `config.py:167` (`encoding="utf-8"` does not strip a BOM → `JSONDecodeError` → silently returns defaults)
- **Trigger:** `config.json` saved by an editor that writes a UTF-8 BOM.
- **Reproduced (2026-10-28):** BOM file with an encrypted `anthropic_api_key` and `language: en` → `load_config` returns `language: es` and an empty key; Settings → Save writes the empty key to disk.
- **Root cause:** decode/parse failures are swallowed and replaced by defaults with no backup and no user-visible warning; the next `save_config` overwrites the original file with those defaults.
- **Impact:** permanent loss of all stored API keys and settings. The same overwrite path applies to any unreadable file (empty file left by KNOWN-206, KNOWN-201/202 once they stop crashing).
- **Proposed fix:** read with `encoding="utf-8-sig"`; when a file exists but cannot be parsed, rename it to `config.json.bad-<timestamp>` before continuing with defaults and report it in the UI.
- **Test:** `tests/test_config.py::test_load_config_reads_utf8_file_with_bom`

### [KNOWN-206] `save_config` is not atomic
- **Where:** `config.py:199-203` (`open(CONFIG_PATH, "w")` truncates, then `json.dump` streams into it; only `OSError` is caught)
- **Trigger:** any exception during serialisation (non-JSON value) or process termination/power loss during the write.
- **Reproduced (2026-10-28):** existing `{"language": "en"}`; `save_config({"bad": object()})` → `TypeError` propagates and `config.json` is left truncated.
- **Impact:** an empty/partial `config.json`; on the next start KNOWN-205's path blanks every key. `SettingsWindow._save` catches the exception and shows "Error al guardar", but the file is already damaged.
- **Proposed fix:** serialise to a string first, write to `config.json.tmp`, `flush` + `os.fsync`, then `os.replace` onto `config.json`.
- **Test:** `tests/test_config.py::test_failed_save_keeps_previous_config_file`

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

### [KNOWN-401] Digit held across an Alt+other-key combo stays in `_eaten`
- **Where:** `hotkeys.py:322` with `:332` / `:344` (`AltInterceptor._handle`)
- **Behavior:** in passthrough mode the handler returns before the `_eaten` key-up check, so the digit's key-up leaks to the focused app and the digit stays in `_eaten`; the next Alt+digit is swallowed without dispatching.
- **Repro:** Alt↓, 1↓ (action), Tab↓ (passthrough), 1↑, Tab↑, Alt↑, Alt↓, 1↓ → action called once (expected twice).
- **Test:** `tests/test_hotkeys.py::test_alt_digit_triggers_after_hold_interrupted_by_other_key`

### [KNOWN-402] Negative partial wheel deltas round away from zero
- **Where:** `wheelscroll.py:144` (`delta // RUEDA_POR_MUESCA`)
- **Behavior:** floor division: `+60 → 0` notches but `-60 → -1`; `+180 → 1` but `-180 → -2`. High-resolution wheels/touchpads scroll down on every small step and never scroll up on small steps.
- **Test:** `tests/test_wheelscroll.py::test_wheel_partial_notch_down_mirrors_up`

### [KNOWN-601] `speech_threshold` slider cannot represent its default value
- **Where:** `settings_window.py:630-633` (`_number_control`), field schema at `settings_window.py:272` (min 0.001, step 0.002, max 0.1)
- **Behavior:** slider positions are `0.001 + k*0.002`; `0.012` maps to `round(5.5) = 6` → displays and, after any slider move, saves `0.013`. The top position yields `0.101` (`round(49.5) = 50`), above the declared max.
- **Repro:** config `speech_threshold=0.012` (default) → label `0.013` (expected `0.012`).
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
- **Where:** `engine.py:541` (`_contexto`, capture branch)
- **Behavior:** the 8000-char budget sums line lengths but not the `\n` joiners, so the joined context can exceed `LIMITE_CHARS_CAPTURA`.
- **Repro:** two history lines of 4000 chars each → 8001-char context (expected <= 8000).
- **Test:** `tests/test_engine.py::TestContext::test_capture_limit_includes_line_separators`

## Suspected issues — from code review, not yet covered by tests

### [KNOWN-001] Unsynchronized iteration over session history
- **Status:** not deterministically testable; needs a lock or a snapshot under lock.
- **Where:** `engine.py:531` (`list(self._history)` in the worker) vs `engine.py:340` (`append` from the turn timer / WebSocket thread).
- **Risk:** `RuntimeError: deque mutated during iteration`, swallowed at `engine.py:496`; the suggestion for that turn is dropped.

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
