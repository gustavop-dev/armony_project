"""Evaluate the follow-up arbiter (followup.py) on labeled Spanish snippets.

    python -m stt_eval.followup_eval              # all cases in followup_cases.json
    python -m stt_eval.followup_eval --repeat 3   # check answer stability

Each case is one interviewer question, the suggested answer, what the tester
said since, and the follow-up, with the expected relation and action. Reports
relation and action accuracy, the action confusion matrix, the costly errors
(revising on noise, missing a needed revision) and Jev latency.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import followup
from stt_eval.keys import read_key
from stt_eval.scoring import percentiles

CASES = os.path.join(os.path.dirname(__file__), "followup_cases.json")


def load_cases(path=CASES):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def judge_cases(client, cases, workers=6, judge=followup.juzgar):
    def one(case):
        try:
            j = judge(client, case["question"], case["suggested_answer"],
                      case["tester_said"], case["follow_up"])
            return case, j, None
        except Exception as e:      # a failed call is reported, not fatal
            return case, None, repr(e)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, cases))


def score(results, umbrales=followup.Umbrales()):
    rows, latencies, errors = [], [], []
    for case, j, err in results:
        if err:
            errors.append({"id": case["id"], "error": err})
        action = followup.decidir(j, case.get("state", "preguntada"), umbrales)
        if j is not None:
            latencies.append(j.ms)
        rows.append({
            "id": case["id"],
            "state": case.get("state", "preguntada"),
            "follow_up": case["follow_up"],
            "expected_relation": case["expected_relation"],
            "relation": j.relacion if j else None,
            "confidence": round(j.confianza, 3) if j else None,
            "changes": round(j.cambia, 3) if j else None,
            "reacts_to_tester": round(j.reacciona_tester, 3) if j else None,
            "expected_action": case["expected_action"],
            "action": action,
        })
    n = len(rows)
    confusion = Counter((r["expected_action"], r["action"]) for r in rows)
    return {
        "cases": n,
        "relation_accuracy": round(sum(r["relation"] == r["expected_relation"]
                                       for r in rows) / n, 3),
        "action_accuracy": round(sum(r["action"] == r["expected_action"]
                                     for r in rows) / n, 3),
        # The two errors that matter to the tester:
        "revised_on_noise": [r["id"] for r in rows
                             if r["action"] == followup.REVISAR
                             and r["expected_action"] != followup.REVISAR],
        "missed_revision": [r["id"] for r in rows
                            if r["expected_action"] == followup.REVISAR
                            and r["action"] != followup.REVISAR],
        "action_confusion": {f"{e}->{a}": c for (e, a), c in sorted(confusion.items())},
        "latency_ms": percentiles(latencies),
        "errors": errors,
        "rows": rows,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m stt_eval.followup_eval")
    ap.add_argument("--cases", default=CASES)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--model", default=None, help="pin a Jev version, e.g. jev-1.14.0")
    ap.add_argument("--out", default=os.path.join("stt_eval", "runs"))
    args = ap.parse_args(argv)

    key = read_key("typesafe_api_key", "TYPESAFE_API_KEY")
    if not key:
        print("No TypeSafe API key (env TYPESAFE_API_KEY or config.json).",
              file=sys.stderr)
        return 1
    from typesafe_sdk import TypeSafeClient

    cases = load_cases(args.cases)
    reports = []
    with TypeSafeClient(api_key=key, model=args.model, timeout=10.0) as client:
        for _ in range(args.repeat):
            reports.append(score(judge_cases(client, cases)))

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{time.strftime('%Y%m%d-%H%M%S')}-followup.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)

    for i, r in enumerate(reports, 1):
        lat = r["latency_ms"]
        print(f"[{i}] relation {r['relation_accuracy']:.0%} · action "
              f"{r['action_accuracy']:.0%} · revised on noise "
              f"{r['revised_on_noise']} · missed revision {r['missed_revision']} · "
              f"latency p50 {lat['p50']} p95 {lat['p95']} ms · errors {len(r['errors'])}")
    print(f"Report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
