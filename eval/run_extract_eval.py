"""
Run the locked extract cases against the real LLM and print a pass/fail table.
"expect" checks the raw LLM output; "expect_final" checks the request after normalize (code).
Usage: python eval/run_extract_eval.py                 (dev set)
       python eval/run_extract_eval.py EX-05 EX-13     (only some dev cases, to save API cost)
       python eval/run_extract_eval.py --holdout       (holdout set - run once per prompt version)
       python eval/run_extract_eval.py --holdout2      (fresh holdout round 2 - run once, on the final prompt)
       python eval/run_extract_eval.py --dates-final   (final date holdout - dates only, run once)
       python eval/run_extract_eval.py --budget        (budget direction set - all five directions)
"""
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from extract_node import extract_node  # noqa: E402
from normalize_node import normalize  # noqa: E402

DEV = pathlib.Path(__file__).with_name("extract_cases.json")
HOLDOUT = pathlib.Path(__file__).with_name("extract_holdout.json")
HOLDOUT2 = pathlib.Path(__file__).with_name("extract_holdout2.json")
DATES_FINAL = pathlib.Path(__file__).with_name("date_holdout_final.json")
BUDGET = pathlib.Path(__file__).with_name("budget_cases.json")


def _singular(word):
    word = word.strip().lower()
    for article in ("the ", "a ", "an "):
        if word.startswith(article):
            word = word[len(article):]
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def norm(field, value):
    if field == "interests":
        return sorted(value or [])
    if field == "place_types":
        words = [v["words"] if isinstance(v, dict) else v for v in (value or [])]
        return sorted(_singular(w) for w in words)
    if field == "must_visit":
        return sorted(v.lower() for v in (value or []))
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def compare(expect, got):
    wrong = []
    for f, exp in expect.items():
        if f.endswith("__includes"):
            base = f[: -len("__includes")]
            if not set(exp) <= set(got.get(base) or []):
                wrong.append((f, exp, got.get(base)))
        elif f == "must_visit":
            # A named place counts if the expected name is inside the extracted one
            # ("Mahakaleshwar temple" in "Mahakaleshwar temple darshan").
            got_names = [g.lower() for g in got.get(f) or []]
            if len(got_names) != len(exp) or not all(any(e.lower() in g for g in got_names) for e in exp):
                wrong.append((f, exp, got.get(f)))
        elif norm(f, got.get(f)) != norm(f, exp):
            wrong.append((f, exp, got.get(f)))
    return wrong


def main():
    args = sys.argv[1:]
    path = (BUDGET if "--budget" in args else DATES_FINAL if "--dates-final" in args
            else HOLDOUT2 if "--holdout2" in args
            else HOLDOUT if "--holdout" in args else DEV)
    data = json.loads(path.read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(data["today"])
    only = {a for a in args if not a.startswith("--")}
    print(f"Set: {path.name}\n")
    cases = [c for c in data["cases"] if not only or c["id"] in only]

    passed, failures = 0, []
    for case in cases:
        out = extract_node({"goal": case["goal"], "today": today})
        if "request" not in out:
            print(f"FAIL  {case['id']}  {case['goal']}\n        gave up: {out['errors'][0].message[:200]}")
            failures.append(case["id"])
            continue
        got = out["request"].model_dump(mode="json")
        # Score interests as the planner will see them: stated purposes plus those of each place type.
        got["interests"] = list(dict.fromkeys(
            (got.get("interests") or []) + [i for pt in got.get("place_types") or [] for i in pt["interests"]]))
        wrong = compare(case["expect"], got)
        notes = []
        if "expect_final" in case:
            final, notes = normalize(out["request"], case["goal"], today)
            wrong += [("final." + f, e, a) for f, e, a in compare(case["expect_final"],
                                                                 final.model_dump(mode="json"))]
        if "expect_status" in case and out["status"] != case["expect_status"]:
            wrong.append(("status", case["expect_status"], out["status"]))
        ok = not wrong
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['id']}  {case['goal']}")
        for field, exp, actual in wrong:
            print(f"        {field}: expected {exp!r}, got {actual!r}")
        if wrong and any(f.startswith("final.") or f in ("start", "end") for f, _, _ in wrong):
            print(f"        llm start: {got.get('start')}")
            print(f"        llm end:   {got.get('end')}")
            for event in out["trace"]:
                if event.event == "llm_self_check_retry":
                    print(f"        retry: {event.detail.get('problems')}")
            for note in notes:
                print(f"        note: {note}")
        if not ok:
            failures.append(case["id"])

    print(f"\n{passed}/{len(cases)} passed" + (f" | failed: {', '.join(failures)}" if failures else ""))


if __name__ == "__main__":
    main()
