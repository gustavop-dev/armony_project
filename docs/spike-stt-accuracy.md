# Spike: live transcription accuracy and latency

Branch `perf/28102026-spike-stt-transcription`. Goal: measure, then improve, the
accuracy (WER/CER) and latency of the live meeting transcription path
(`audio.py` → `stt_stream.StreamingSTT` → AssemblyAI Universal Streaming).
Offline Whisper is out of scope; it is removed in
`refactor/28102026-remove-offline-whisper`.

## Harness (`stt_eval/`)

Replays dataset audio through `StreamingSTT.feed` at real-time pace, in ~21 ms
blocks (the cadence `AudioEngine` produces), with clips joined by silence into
one connection. Scores the finals against the references.

```powershell
python -m stt_eval fleurs --limit 30            # asks before connecting
python -m stt_eval fleurs --limit 30 --eot 0.6 --yes
```

- API key: `ASSEMBLYAI_API_KEY`, else the app's `config.json`.
- Datasets are cached in `.stt_eval_cache/`; JSON reports go to `stt_eval/runs/`
  (both git-ignored).
- Metrics:
  - `wer` / `cer`: corpus level, on the whole session after normalization
    (lowercase, no punctuation).
  - `wer_no_accents`: also ignores tilde errors.
  - `finalization_latency`: time from when the clip's last sample was sent to
    the final that closes the turn (end-of-turn detection + ASR + network).
  - `provider_estimate`: `StreamingSTT`'s own latency figure, for comparison.
  - Per-clip rows attribute each final by the amount of audio sent when it
    arrived; they are diagnostic, not the headline.
- Cost: AssemblyAI bills connected time (~0.45 USD/h). 30 FLEURS clips ≈ 7 min.

## Dataset plan

Use is internal and non-commercial, so NC licenses are acceptable.

| Stage | Dataset | Why | License / access |
|---|---|---|---|
| 1. Calm baseline | [FLEURS](https://huggingface.co/datasets/google/fleurs) `es_419` test | Clean read speech; any loss here is ours (capture, resampling, chunking) | CC BY 4.0, direct |
| 2. Spanish interviews | [COSER](https://corpusrural.es/) | 290 semi-directed interviews (~1 h each), interviewer/informant turns, full MP3 | CC BY-NC-ND 4.0, direct |
| 2b. Urban Spanish interviews | [ESLORA](https://eslora.usc.es/) | 60 h of sociolinguistic interviews, aligned transcripts | CC BY-NC 4.0, audio by request form |
| 3. Expert Q→A | [Earnings-21](https://github.com/revdotcom/speech-datasets) (Eval-10 first) | Analyst asks, executive answers; token timestamps + speakers; base for agent-vs-expert comparison | CC BY-SA 4.0, Git LFS |
| 3b. Expert dialogue | [Primock57](https://github.com/babylonhealth/primock57) | Mock GP consultations, per-speaker channels and TextGrids | CC BY 4.0, Git LFS |
| 4. Hard / spontaneous | [Spanish CallFriend](https://talkbank.org/ca/access/CallFriend/spa.html), [Bangor Miami](https://talkbank.org/biling/access/Bangor/Miami.html), [CIEMPIESS Light](https://huggingface.co/datasets/ciempiess/ciempiess_light) | Phone conversations (8 kHz), ES–EN code-switching, Mexican radio | TalkBank rules / CC BY-SA 4.0 |
| Meetings (EN) | [AMI](https://huggingface.co/datasets/edinburghcstr/ami) | Multi-party meetings, headset + far-field | CC BY 4.0 |

Notes:
- COSER speakers are elderly rural informants with dialectal speech. It is a
  hard WER set, but the informants are not domain experts.
- Earnings-21 is English. No free Spanish corpus of expert interviews was found.
  The Spanish Q→A set will likely be built in-house from interview templates.
- Unverified or limited: PRESEEA (only ~10 min of audio per interview is
  public), MIT Interview (academic email required), CORAAL (EN), NOTSOFAR-1
  (license unchecked, ~305 GB), MLC-SLM (registration, terms unpublished).

## Hypotheses to test (one experiment per commit, measured with the harness)

1. Stateless per-block `soxr.resample` in `audio.py` creates block-boundary
   artifacts → `soxr.ResampleStream`.
2. No domain vocabulary is sent → `keyterms_prompt` built from active contexts.
3. Turn-closing parameters: only `end_of_turn_confidence_threshold=0.4` is set.
4. On reconnect, queued audio is dropped silently, and `_audio_ms` resets while
   old audio is still queued. That skews `provider_estimate`.

## Workstream B: one answer per question (turn fragmentation)

Problem: a speaker asks, pauses, adds a clarification, pauses, adds more. Today
that produces three answers. Only the first has the full question; the other
two answer the fragments.

Cause in `engine.py`:
- `_on_stt_final` flushes the turn **immediately** when a final looks like a
  question (`intent.parece_pregunta`), without waiting `silence_hang`.
- Each later addition becomes a new turn and a new `respond` item.
- The worker answers items sequentially. A generation in flight cannot be
  cancelled, and the follow-ups go out with only the fragment as `latest`.

Direction:
1. Grace window after a question-like final. Partials from the same speaker
   inside it extend the turn instead of opening a new one. Also tune AssemblyAI
   turn parameters (`end_of_turn_confidence_threshold`,
   `min_end_of_turn_silence_when_confident`, `max_turn_silence`).
2. Speculative start with revision. Generate immediately to keep latency low.
   If more speech arrives while generating or shortly after, classify it:
   - filler: ignore
   - extension of the same question: cancel and regenerate with the merged
     question, or append a short addendum if most of the answer is already
     shown
   - new question: queue a new answer
3. UI: one answer card per question, updated in place.
4. Metrics: answers per question, and questions closed before the speaker
   finished. Test sets:
   - synthetic: references joined by 0.5–2 s pauses
   - real: analyst multi-part questions in Earnings-21

## Workstream C: meeting memory without resending everything

The LLM APIs are stateless: a chat like Claude Code also resends the whole
conversation on every turn. It stays fast and cheap through prompt caching,
which reuses an already-processed prefix, and through compaction (summarizing
old turns) when the conversation gets long.

Current state:
- `engine._contexto` sends only the last 36 history entries (~18 turns). Older
  content is dropped and nothing summarizes it.
- `llm._stream_anthropic` passes `system` as a plain string with no
  `cache_control`, so no prompt caching happens for Anthropic. That holds even
  though `engine._init_and_run` freezes the prompt "so as not to break the
  cache".
- The transcript is rebuilt inside one user message on every call. A sliding
  window changes the prefix, so it could not be cached even with
  `cache_control`.

Direction: a layered prompt with a stable, cacheable prefix.
1. System prompt + active contexts: fixed for the meeting, cached.
2. Meeting memory: a running summary of older turns (topics, decisions, what
   was already answered). A fast model refreshes it in the background, off the
   critical path. Cached.
3. Recent transcript verbatim, append-only, so the cached prefix keeps growing
   (incremental cache hits).
4. The current question, with an explicit instruction to answer that question
   and use the rest as background.

## Results

| Date | Dataset | Config | WER | WER no accents | CER | Final. latency p50 / p95 | Notes |
|---|---|---|---|---|---|---|---|
| 2026-10-28 | FLEURS es_419 test, 30 clips (760 words) | direct 16 kHz, eot 0.4 | 1.97% | 1.84% | 0.89% | n/a (measured from file end; fixed in 208896a) | provider estimate p50 263 / p95 352 ms |
| 2026-10-28 | same | `--capture stateless` (current audio.py), eot 0.4 | 2.11% | 1.97% | 0.98% | 696 / 1897 ms (n=24) | provider estimate p50 293 / p95 365 ms |
| 2026-10-28 | same | `--capture stream` (ResampleStream), eot 0.4 | 2.11% | 1.97% | 0.87% | 657 / 1878 ms (n=23) | provider estimate p50 275 / p95 373 ms |

Reading:
- Hypothesis 1: per-read resampling degrades the signal (~22 dB aligned SNR,
  0.1% drift), but on clean read speech it costs at most one word in 760.
  Errors are 15–16 across all three runs, which is within run-to-run noise.
  Still worth fixing (cheap, removes drift), but it is not where accuracy is
  lost.
- Remaining errors: rare proper nouns (Carpanedo, Jakar/Bumthang, pohutukawa),
  plus number formatting ("dos" vs "2") counted as substitutions by the
  normalizer.
- Finalization latency (last voiced sample → closing final) has a median of
  ~0.65–0.7 s and a p95 of ~1.9 s. This is mostly the provider's end-of-turn
  wait, the knob of workstream B. 6–7 clips have no value because the
  energy-based speech end landed after the final arrived.
