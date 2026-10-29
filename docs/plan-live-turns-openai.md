# Plan: stable answers, tester-aware turns and cached memory (OpenAI only)

Status: proposed, 2026-10-28. Follows from `docs/spike-stt-accuracy.md`
(workstreams B and C).

Goal: in a technical interview call, the tester gets **one** stable answer per
question that does not move while being read. The tester's own speech closes
the question. Only a real new question or a drill-down produces new content.
The model keeps the whole call in memory, at low cost and latency, through
prompt caching.

## Facts this plan relies on (checked 2026-10-28)

OpenAI models (developers.openai.com model pages):

| Model | Positioning | $/1M input · cached · output | `reasoning.effort` | Input |
|---|---|---|---|---|
| `gpt-6-luna` | most efficient, high-volume | 0.10 · 0.01 · 0.50 | none … max (default medium) | text, image |
| `gpt-6.1-terra` (released 2026-10-26) | fast, efficient, natural writing, visual reasoning | 1.00 · 0.05 · 5.00 | none … max (default medium) | text, image |
| `gpt-6.1-sol` | near-Astra, complex work | 2.00 · 0.10 · 10.00 | low … max (no `none`) | text, image |

The app today uses `gpt-5.6-terra` (voice) and `gpt-5.6-sol` (screenshots).

Prompt caching, Responses API, GPT-5.6 and later (OpenAI prompt-caching guide):
- Minimum prefix: **1024 visible input tokens**.
- Cached reads: 0.1× input (0.05× on GPT-6.1 Sol/Terra). Writes: 1.25×
  (`ttl: "30m"`, default) or 2.5× (`"12h"`).
- `prompt_cache_options`: `{mode: "implicit"|"explicit", ttl: "30m"|"12h",
  prewarm: true}`.
  - `prewarm` writes the cache without generating output.
- `prompt_cache_breakpoint: {mode: "explicit"}` goes inside a content block. Up
  to 4 cache writes per request.
- In implicit mode the breakpoint sits at the end of the latest eligible
  message. The end of the initial developer-message block is also a lookup
  boundary.
- Top-level `instructions` **cannot** hold a breakpoint. Reusable instructions
  belong in an `input_text` block of a developer message.
- Rules:
  - Append messages, never rewrite earlier turns.
  - Keep tools and schemas stable.
  - On GPT-6, change reasoning effort mid-conversation with a
    `configuration_update` item, not by changing the top-level field.
- `prompt_cache_key` is optional on GPT-5.6+. Useful for per-meeting cost
  accounting.
- Verify through `usage.input_tokens_details.cached_tokens` and
  `cache_write_tokens`.
- Caches are per model. Requests on a different model do not share the prefix.

Local facts:
- `openai` 3.37.0 installed.
- `llm.Coach._stream_openai` sends the whole prompt as one rebuilt user
  message with `instructions=`. Nothing is append-only, so nothing caches.
- `overlay_ui._AutoScroll` follows the feed tail while the reader is at the
  bottom. Every new bubble, including the interviewer's live partials, pushes
  the answer being read out of view.

## Phase 0: Foundations (OpenAI only, latest models)

0.1 **Branch.**
- Cut `feat/<date>-live-turns-openai` from the spike branch.
- Merge `refactor/28102026-remove-offline-whisper` into it.
- The product owner approves the merge; there is no remote.

0.2 **Remove the Claude integration (for now).**
- `llm.py`: drop the Anthropic backend and the `provider` switch. OpenAI
  Responses only.
- `config.py`: defaults `openai_model_voice = "gpt-6.1-terra"` and
  `openai_model_vision = "gpt-6.1-sol"` (final choice in 0.3). `llm_provider`
  is no longer read. **Stored `anthropic_*` keys are left untouched** in
  `config.json`, so restoring Claude later needs no re-entry.
- `settings_window.py`: remove the provider selector and the Claude fields.
  Update the `GPT` options to `gpt-6-luna`, `gpt-6.1-terra` and `gpt-6.1-sol`,
  plus `gpt-5.6-terra` as a fallback.
- `app.py`: the start check only requires the OpenAI and AssemblyAI keys.
- `requirements.txt`: drop `anthropic`. Docs: README and configuration
  reference.
- Tests: config defaults and migration (`llm_provider` ignored, anthropic keys
  preserved).

0.3 **Model (decided by the product owner, 2026-10-28): `gpt-6.1-sol` for
everything. Only the reasoning effort changes per use.**
- Config key `openai_model`. It is no longer in Settings. The old
  `openai_model_voice` / `openai_model_vision` keys are purged on load, so
  saved 5.x choices do not survive.
- Voice: `openai_effort_voice = "low"`. Screenshots:
  `openai_effort_vision = "medium"`. Both are selectable in Settings
  (low / medium / high). `gpt-6.1-sol` does not accept `none`.
- One model means one prompt cache for the whole meeting (phase 4). In phase
  4 the per-use effort switch must go through `configuration_update` items so
  the cached prefix survives.

0.4 **Spoken-question latency with the real prompt** (2026-10-28,
`python -m stt_eval.voice_latency`; 12 Spanish technical questions in
`stt_eval/voice_questions.json`; warm connection; configs interleaved):

| Config | First word p50 (max) | Full answer p50 | Length p50 |
|---|---|---|---|
| `gpt-6.1-terra` effort none | 0.94 s (1.17) | 2.35 s | ~453 chars |
| `gpt-6.1-terra` effort low | 0.91 s (1.69) | 2.64 s | ~444 chars |
| `gpt-6.1-sol` effort low | 1.05 s (1.53) | 4.04 s | ~585 chars |

Reading:
- What the tester waits for is the first word: sol is ~0.1–0.15 s slower at
  the median.
- The full answer takes ~1.4 s longer on sol, mostly because it is ~30%
  longer. Both stream at ~150–200 chars/s, an order of magnitude faster than
  anyone reads aloud (~15–20 chars/s). The tail is never what the tester waits
  on.
- Sol's answers are more senior on the same questions. Duplicate card charge:
  a DB unique constraint plus passing the idempotency key to the processor,
  vs. a generic "unique identifier". Monolith split: sol also covers data
  ownership.
- One run of 12 questions: a direction, not a benchmark.

Acceptance:
- Tests are green.
- The app starts and answers with OpenAI only.
- No Anthropic import remains.

## Phase 1: Pin the answer (the text no longer "runs away")

- Extract the scroll decision into a pure class (`FeedAnchor`) that Qt
  drives, so it can be unit-tested.
- On answer start, scroll so the top of the answer card is visible, then
  **stop following the tail**.
  - Content arriving below the pinned answer (interviewer bubbles, partials,
    new cards) does not move the viewport and raises a "nuevo ↓" chip.
  - Clicking the chip or scrolling to the bottom resumes following.
- An in-place revision (phase 3) re-renders the same card and keeps its top
  fixed. A small "actualizada" tag marks it.
- Tests:
  - unit tests of `FeedAnchor` decisions
  - offscreen Qt smoke test: emit a sequence of engine signals and assert that
    the answer card's top y-position does not change while pinned

Acceptance: in the scripted sequence (answer, interviewer follow-up partials,
second card), the pinned answer never moves.

Status (2026-10-28): **done**.
- `feedanchor.FeedAnchor` holds the decision and `overlay_ui._AutoScroll`
  applies it.
- A new answer anchors with its question above it if that fits in 40% of the
  viewport. The content gets a minimum height so a short answer can sit at
  the top, ChatGPT-style.
- `NewBelowChip` ("nuevo ↓") lives in the footer and is added to the
  interactive zones while visible.
- Tests:
  - `tests/test_feedanchor.py`: 10 unit tests
  - `tests/test_feed_pinning_qt.py`: 3 offscreen tests with the real panel.
    With the anchor disabled the first one fails: the answer moved 96 px up as
    soon as the interviewer kept talking.

## Phase 2: The tester's mic and the question's state

- Audio and STT:
  - `audio.AudioEngine` feeds the mic as 16 kHz PCM too.
  - The engine opens a **second `StreamingSTT`** for the mic, in the same
    language. Assumes headphones; adds roughly 0.45 USD/h.
  - Setting "Escuchar mi micrófono" (default on).
  - Echo guard: if a mic final closely matches a loopback final within 2 s,
    show a one-time "usa auriculares" warning.
- Thread model in the engine:
  - `QuestionThread`: id, question parts, card id, answer text, tester
    utterances, timestamps, state.
  - States:
    - `ASKED`: answer generating or shown
    - `ANSWERING`: tester final with substantive content, e.g. ≥ 4 words that
      are not just an acknowledgement
    - `ANSWERED`: tester silent ≥ N s after answering, or the interviewer
      acknowledges or moves on
    - `CLOSED`: a new thread opens
  - Tester finals enter history as "Yo".
  - Interim rule until phase 3: while a thread is `ANSWERING` or `ANSWERED`,
    interviewer finals **never** auto-generate. Only "Answer now" does.
- Fix the immediate flush: a question-like final no longer bypasses the turn
  gap when a thread is open.
- Scenario harness: `stt_eval/scenarios/*.json` hold timelines of interviewer
  and tester finals. They replay through `CoachEngine` with a fake STT and a
  fake LLM.
  - Metrics: answer cards per question, revisions, generations started.
  - Scenarios:
    - ask → vale → "ah, pero" → tester answers → ok
    - ask → tester answers → "¿y esta parte?"
    - ask → retract
    - two questions back to back
    - and so on

Acceptance: every non-"new question" scenario produces exactly 1 card.

Status (2026-10-28): **done**, with the interim rule.
- `hilo.py` holds the thread states, the acknowledgement filter and echo
  detection, all pure.
  - States: `preguntada` / `respondiendo` / `respondida`.
  - Acknowledgement filter: "vale", "déjame pensar"… don't count as answering.
  - Echo detection: a mic final ≈ a recent interviewer final means the
    speakers leak into the mic. A one-time warning is shown and the text is
    dropped.
- `engine` opens a second `StreamingSTT` for the mic (`listen_mic`, default
  on). Tester finals go to history as "Yo" and to the thread.
- An interviewer final while the thread is `preguntada` / `respondiendo` is
  context: `noAnswer("follow_up")`, and the footer pill says "Added to the
  current question — Alt+5 for a new answer". A question once it is
  `respondida` opens a new thread.
- A thread whose answer never reached the screen (model declined, error,
  empty answer) is closed so it cannot block the next question. Alt+5 always
  opens a new thread.
- Since `audio.py` was being touched, capture now resamples with one
  `soxr.ResampleStream` per stream (hypothesis 1 fix).
- Tests:
  - `tests/test_hilo.py`: 21
  - `tests/test_engine_turns.py`: 8 interview scenarios through
    `CoachEngine`. With the old "every question gets an answer" rule, the two
    follow-up scenarios produce 2 answers instead of 1.
- Not verified here: a live meeting with real mic audio. The mic stream is the
  same `StreamingSTT` class measured on FLEURS.

## Phase 3: Jev arbiter, gated by state

- Add a `drills_into_part` relation: go deeper into one specific part of the
  question or of the tester's answer.
- Extend `followup_cases.json` with ~20 cases where the tester already
  answered. If the product owner allows it, add real follow-ups from session
  records in `%APPDATA%\Armony\sesiones`.
- Policy by state (thresholds re-tuned on the extended set):

| Thread state | Revise in place | New card | Everything else |
|---|---|---|---|
| `ASKED` (tester reading) | extends/relaxes, P(change) ≥ 0.85 and confidence ≥ 0.6 | `new_question` / `drills_into_part`, confidence ≥ 0.6 | context only |
| `ANSWERING` / `ANSWERED` | never | `new_question` / `drills_into_part`, confidence ≥ 0.6 | context only |

  `withdraws_question` dims the card.
- Jev runs off the UI thread with a 1.0 s timeout. A timeout or error means
  context only.
- Cancellable generation: closing the Responses stream when a revision
  supersedes it while it is still generating.
- Revision: appended as a new turn of the same conversation (phase 4). It is
  rendered into the same card.

Acceptance:
- Arbiter eval ≥ 95% action accuracy with 0 revisions on noise, on the extended
  set.
- Scenario harness: at most 1 card per question except in new-question
  scenarios.

## Phase 4: Meeting memory with prompt caching

- The conversation is an **append-only** Responses `input` list owned by the
  engine:
  1. A developer message: the coach prompt plus the active contexts as one
     `input_text` block. Frozen for the meeting. It must be byte-stable: no
     timestamps, and contexts in sorted order.
  2. As the meeting runs, append user messages with labelled transcript chunks
     ("Ellos: …" / "Yo: …"). Chunks are appended only when a request is made,
     so the item list grows monotonically.
  3. Per answer: a user message "Pregunta a responder ahora: …" (answer this;
     the rest is background), then the assistant output item exactly as
     returned.
  4. Per revision: a user message "Han añadido: … Reescribe tu respuesta
     anterior" and the new assistant output.
- Cache settings:
  - `prompt_cache_options: {mode: "implicit", ttl: "30m"}`
  - one `prewarm: true` request at meeting start, after contexts load
  - `prompt_cache_key = "armony:<session-id>"`
  - Effort changes go through `configuration_update` items, never top-level.
- **The prompt cache is per model.** A cached prefix is the model's internal
  state over those tokens, computed with that model's weights, so another
  model cannot read it. OpenAI's guide lists `model` among the settings that
  shape the cached prefix: "A different model can use different weights and
  caching behavior".
  - Switching model mid-session keeps the *conversation* (the same `input`
    list is sent), but the first request on the other model reprocesses the
    whole prefix. After that it has its own cache.
  - Returning to the first model hits its cache if it is still alive.
  - This is what ChatGPT does when you switch models in a chat: the history
    carries over, the cache does not.
- **Effort changes do keep the cache** if they are made with a
  `configuration_update` item and the top-level `reasoning.effort` stays
  unchanged (GPT-6+).
- Design with two models:
  - Voice (`gpt-6.1-terra`) owns the hot cache: every spoken answer reads it.
  - A screenshot sends the same conversation to `gpt-6.1-sol`. The first one
    in a while pays a cold prefill (~10–15K tokens at $2/M ≈ $0.02–0.03 and
    some extra latency). Later screenshots within the TTL read sol's own
    cache.
  - The screenshot result is appended to the shared conversation, so the voice
    model sees it on its next turn.
  - Optional optimisation: start a `prewarm` request on sol the moment a
    screenshot hotkey is pressed, in parallel with the capture.
- Size:
  - A 1-hour meeting is ~10–15K tokens, so no compaction is needed.
  - Guard: past ~200K tokens, start a new conversation seeded with a summary,
    which accepts one cold prefix.
- Metrics:
  - per call: `cached_tokens`, `cache_write_tokens`, TTFT, logged through
    `metrics.py`
  - per session: cache hit share

Acceptance:
- From the 2nd answer on, ≥ 80% of input tokens are cached.
- TTFT p50 is lower than in the no-cache baseline from 0.3.
- Answers reference earlier parts of the call (spot-checked on a scripted
  60-minute transcript).

Status (2026-10-28): **done**.
- `llm.Coach` owns one append-only Responses conversation per meeting:
  - A single developer message at the start: coach prompt, contexts and the
    answering rules that used to be resent inside every question.
  - Then, per answer: a user turn with only what is new
    (`Coach.anotar('Ellos'|'Yo', text)` buffers it) plus the question.
  - Then the assistant answer as given.
- The effort switch voice ↔ screenshot is a `configuration_update` item. The
  top-level `reasoning.effort` never changes.
- Every request uses `prompt_cache_options: {ttl: "30m"}` and a per-meeting
  `prompt_cache_key`. `calentar()` prewarms the developer prefix.
- Error handling:
  - A failed request appends nothing, and its transcript lines ride on the
    next turn.
  - A partial answer that was shown is kept.
  - If the model rejected `configuration_update`, the coach would fall back to
    top-level effort.
- The engine no longer builds a sliding context window, and "Yo (sugerido)"
  summaries are gone: the conversation already holds the answers.
- Live check (`gpt-6.1-sol`, 6 questions with a screenshot in the middle):
  - Prewarm accepted. The developer prefix is ~1.6K tokens, above the 1,024
    minimum.
  - **88–93% of input tokens cached on every turn, from the first question
    on**: 12,687 of 13,972 overall.
  - `configuration_update` accepted. The voice turn after the screenshot was
    still 93% cached.
  - First word on voice turns 1.0–1.8 s. The screenshot turn (effort medium,
    image) 6.5 s.
- Tests: `tests/test_llm_single_model.py`, 12 tests covering:
  - the byte-for-byte prefix invariant
  - fixed request settings
  - configuration_update switching
  - failure and retry handling
  - prewarm
  - trimming

## Order and size

| Phase | Size | Depends on |
|---|---|---|
| 0 Foundations | M | — |
| 1 Pin the answer | S | — (can run in parallel with 0) |
| 2 Mic + thread states | L | 0 |
| 3 Arbiter by state | M | 2 |
| 4 Cached memory | M | 0 (conversation shape also serves 3's revisions) |

Suggested sequence: 0 → 1 → 2 → 4 → 3. Phase 4 lands before 3 because the
in-place revision is easiest to build as one more turn of the cached
conversation.

## Risks

- Spanish quality and latency of `gpt-6-luna` / `gpt-6.1-terra` are untested
  here. Phase 0.3 decides with data.
- The `openai` SDK may not type `prompt_cache_options` yet. Fall back to
  `extra_body`, checked in 0.3.
- Echo without headphones: the mic transcribes the interviewer. Mitigated by
  the warning; a full echo canceller is out of scope.
- STT cost doubles with the mic stream (~0.90 USD/h total).
- Jev and the arbiter cases are Spanish-authored by us. Real session data is
  needed before trusting the thresholds.
