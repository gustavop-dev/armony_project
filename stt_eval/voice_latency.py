"""Latency of spoken-question answers per model/effort, with the app's real prompt.

    python -m stt_eval.voice_latency                       # default configs
    python -m stt_eval.voice_latency --configs gpt-6.1-sol:low gpt-6.1-terra:none

Each question goes through llm.Coach.stream_response exactly as the engine
sends it (coach prompt from config.DEFAULTS, a line of meeting context, the
question). Configurations are interleaved per question so network drift does
not favour one of them. Reports time to first token, time to the full answer
and length, and saves every answer for a side-by-side quality read.
"""
import argparse
import json
import os
import statistics as st
import sys
import time

import config
from engine import _prompt_bilingue
from llm import Coach
from stt_eval.keys import read_key

QUESTIONS = os.path.join(os.path.dirname(__file__), "voice_questions.json")
DEFAULT_CONFIGS = ["gpt-6.1-terra:none", "gpt-6.1-terra:low", "gpt-6.1-sol:low"]


def ask(coach, context, question, clock=time.monotonic):
    out, first, errors = [], [], []
    t0 = clock()

    def delta(text):
        if not first:
            first.append(clock() - t0)
        out.append(text)

    coach.stream_response(context, question, on_delta=delta, on_error=errors.append)
    return {
        "ttft_s": round(first[0], 3) if first else None,
        "total_s": round(clock() - t0, 3),
        "answer": "".join(out),
        "error": errors[0] if errors else None,
    }


def summarize(rows):
    ok = [r for r in rows if not r["error"] and r["ttft_s"] is not None]
    if not ok:
        return {"n": 0, "errors": len(rows)}
    ttft = [r["ttft_s"] for r in ok]
    total = [r["total_s"] for r in ok]
    return {
        "n": len(ok),
        "errors": len(rows) - len(ok),
        "ttft_p50": round(st.median(ttft), 2),
        "ttft_max": round(max(ttft), 2),
        "total_p50": round(st.median(total), 2),
        "chars_p50": int(st.median(len(r["answer"]) for r in ok)),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m stt_eval.voice_latency")
    ap.add_argument("--configs", nargs="+", default=DEFAULT_CONFIGS,
                    help="model:effort pairs")
    ap.add_argument("--questions", default=QUESTIONS)
    ap.add_argument("--out", default=os.path.join("stt_eval", "runs"))
    args = ap.parse_args(argv)

    key = read_key("openai_api_key", "OPENAI_API_KEY")
    if not key:
        print("No OpenAI API key (env OPENAI_API_KEY or config.json).", file=sys.stderr)
        return 1
    with open(args.questions, encoding="utf-8") as f:
        questions = json.load(f)

    cfg = dict(config.DEFAULTS)
    prompt = _prompt_bilingue(cfg)
    coaches = {}
    for spec in args.configs:
        model, effort = spec.split(":")
        coaches[spec] = Coach(key, system_prompt=prompt, model=model,
                              tokens_voice=cfg["openai_tokens_voice"],
                              effort_voice=effort)
        coaches[spec].calentar()        # as the app does at meeting start

    rows = {spec: [] for spec in coaches}
    for i, q in enumerate(questions):
        order = list(coaches)
        order = order[i % len(order):] + order[:i % len(order)]   # rotate
        for spec in order:
            r = ask(coaches[spec], q["context"], q["question"])
            r["id"] = q["id"]
            rows[spec].append(r)

    report = {spec: {"summary": summarize(rs), "rows": rs} for spec, rs in rows.items()}
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{time.strftime('%Y%m%d-%H%M%S')}-voice-latency.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    for spec, r in report.items():
        s = r["summary"]
        print(f"{spec:22s} first word p50 {s.get('ttft_p50')} s (max {s.get('ttft_max')}) · "
              f"full answer p50 {s.get('total_p50')} s · ~{s.get('chars_p50')} chars · "
              f"errors {s.get('errors')}")
    print(f"Report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
