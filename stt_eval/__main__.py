"""CLI: replay a dataset through the live STT path and write a JSON report.

    python -m stt_eval fleurs --limit 30

Sends real audio to the provider and is billed by connected time, so it shows
the estimated cost and asks before connecting (skip with --yes). The API key
comes from ASSEMBLYAI_API_KEY or, failing that, from the app's config.json
(source checkout first, then %APPDATA%\\Armony).
"""
import argparse
import json
import os
import subprocess
import sys
import time

from stt_eval import fleurs
from stt_eval.keys import read_key
from stt_eval.replay import run_session

# README: AssemblyAI streaming bills ~0.45 USD per connected hour.
USD_PER_HOUR = 0.45


def _git_rev():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m stt_eval")
    ap.add_argument("dataset", choices=["fleurs"])
    ap.add_argument("--lang", default="es_419", help="FLEURS language config")
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=30, help="number of clips")
    ap.add_argument("--gap", type=float, default=2.0,
                    help="seconds of silence between clips")
    ap.add_argument("--language", default="es", help="app language setting: es|en|auto")
    ap.add_argument("--model", default="universal-3-5-pro")
    ap.add_argument("--eot", type=float, default=0.4,
                    help="end_of_turn_confidence_threshold")
    ap.add_argument("--capture", choices=["none", "stateless", "stream"],
                    default="none",
                    help="simulate audio.py resampling from a 48 kHz device")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="playback speed; keep 1.0 against the real provider")
    ap.add_argument("--cache", default=".stt_eval_cache")
    ap.add_argument("--out", default=os.path.join("stt_eval", "runs"))
    ap.add_argument("--yes", action="store_true", help="do not ask before connecting")
    args = ap.parse_args(argv)

    samples = fleurs.load(args.cache, args.lang, args.split, args.limit)
    if not samples:
        print("No samples loaded.", file=sys.stderr)
        return 1
    seconds = sum(s.seconds for s in samples) + args.gap * (len(samples) - 1) + 4.5
    cost = seconds / 3600 * USD_PER_HOUR
    print(f"{len(samples)} clips, ~{seconds / 60:.1f} min of streaming, "
          f"~{cost:.3f} USD.")
    if not args.yes and input("Connect to AssemblyAI? [y/N] ").strip().lower() != "y":
        return 1

    key = read_key("assemblyai_api_key", "ASSEMBLYAI_API_KEY")
    if not key:
        print("No AssemblyAI API key (env ASSEMBLYAI_API_KEY or config.json).",
              file=sys.stderr)
        return 1

    from stt_stream import StreamingSTT

    def make_stt(on_partial, on_final, on_error):
        return StreamingSTT(api_key=key, on_partial=on_partial, on_final=on_final,
                            on_error=on_error, on_status=print,
                            language=args.language, model=args.model,
                            end_of_turn_threshold=args.eot)

    report = run_session(make_stt, samples, gap_s=args.gap, speed=args.speed,
                         capture=args.capture)
    report["run"] = {
        "dataset": f"fleurs/{args.lang}/{args.split}",
        "limit": args.limit,
        "gap_s": args.gap,
        "language": args.language,
        "model": args.model,
        "eot": args.eot,
        "speed": args.speed,
        "capture": args.capture,
        "git": _git_rev(),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{time.strftime('%Y%m%d-%H%M%S')}-fleurs-"
                                  f"{args.lang}-{args.limit}-{args.capture}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    lat = report["latency_ms"]["finalization"]
    print(f"WER {report['wer']:.2%} · CER {report['cer']:.2%} · "
          f"WER without accents {report['wer_no_accents']:.2%}")
    print(f"Finalization latency p50 {lat['p50']} ms · p95 {lat['p95']} ms · "
          f"clips without final {report['clips_without_final']}")
    print(f"Report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
