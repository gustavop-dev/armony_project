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

## Results

| Date | Dataset | Config | WER | WER no accents | CER | Final. latency p50 / p95 | Notes |
|---|---|---|---|---|---|---|---|
| | | | | | | | |
