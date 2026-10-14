"""
End-to-end check of the whole agent on live APIs: does it cover what the assignment asks, and where does it fail?
Each case in e2e_cases.json is run once through the full graph, then checked twice:
  - against its own expectations (status, base city, notes, replanning, errors ...), and
  - against general rules every finished plan must follow (see general_checks).
Usage: python eval/run_e2e.py              (dev set, all cases; a few rupees of gpt-4o-mini)
       python eval/run_e2e.py E-04 E-05    (only some cases)
       python eval/run_e2e.py --holdout    (holdout set: run ONCE, after the dev fixes; never fixed against)
Writes eval/e2e_results.md (dev) or eval/e2e_holdout_results.md (holdout).
"""
import datetime as dt
import json
import pathlib
import sys
import time
import traceback
from itertools import pairwise

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from graph import build_graph  # noqa: E402
from tools.http import inject_failures  # noqa: E402

CASES = pathlib.Path(__file__).with_name("e2e_cases.json")
RESULTS = pathlib.Path(__file__).with_name("e2e_results.md")
HOLDOUT = pathlib.Path(__file__).with_name("e2e_holdout.json")
HOLDOUT_RESULTS = pathlib.Path(__file__).with_name("e2e_holdout_results.md")
TAIL = ["build_itinerary", "find_stays_and_food", "estimate_costs", "check_budget"]
SELF_CORRECTION = ("llm_self_check_retry", "llm_parse_retry", "planner_fallback", "replanner_fallback")


def minutes(t: dt.time) -> int:
    return t.hour * 60 + t.minute


def general_checks(s: dict) -> list[str]:
    """Rules every run must follow. Returns what is wrong."""
    wrong = []
    for e in s.get("errors", []):
        if not e.handled_by:
            wrong.append(f"error in {e.where} has no 'handled_by'")
    if not s.get("report_md") or not s.get("report_json"):
        wrong.append("no report was written")
    if s.get("status") != "done":
        if not s.get("notes"):
            wrong.append("stopped without a note saying why")
        return wrong

    r, plan, it = s["request"], s.get("plan"), s.get("itinerary")
    tools = [step.tool for step in plan.steps] if plan else []
    if tools[-len(TAIL):] != TAIL:
        wrong.append(f"plan does not end with {TAIL}")
    if it is None:
        return wrong + ["no itinerary"]
    if len(it.days) != r.days:
        wrong.append(f"{len(it.days)} days planned for a {r.days}-day trip")
    seen = set()
    for d in it.days:
        if not d.timeline:
            wrong.append(f"day {d.day} has no timeline")
            continue
        for a, b in pairwise(d.timeline):
            if minutes(b.start) < minutes(a.end):
                wrong.append(f"day {d.day}: '{b.title}' starts before '{a.title}' ends")
        visits = [i for i in d.timeline if i.kind == "visit"]
        if visits and minutes(visits[-1].end) > config.DAY_END and not any("long day" in n for n in d.day_notes):
            wrong.append(f"day {d.day}: sightseeing ends after {config.DAY_END // 60}:00 without a note")
        for p in d.places:
            if p.name in seen:
                wrong.append(f"{p.name} is planned twice")
            seen.add(p.name)
    v = s.get("verdict")
    if v and v.status != "within" and not any(n.startswith("Budget:") for n in s.get("notes", [])):
        wrong.append(f"budget is {v.status} but no budget note explains it")
    return wrong


def case_checks(s: dict, expect: dict) -> list[str]:
    wrong = []
    status = s.get("status")
    allowed = expect["status"] if isinstance(expect["status"], list) else [expect["status"]]
    if status not in allowed:
        wrong.append(f"status {status}, expected {' or '.join(allowed)}")
    d, r = s.get("destination"), s.get("request")
    if "base_city" in expect and (d is None or d.base_city not in expect["base_city"]):
        wrong.append(f"base city {d.base_city if d else None}, expected {expect['base_city']}")
    if "destination_type" in expect and (d is None or d.destination_type != expect["destination_type"]):
        wrong.append(f"destination type {d.destination_type if d else None}, expected {expect['destination_type']}")
    if "region" in expect and (d is None or d.location is None or expect["region"] not in (d.location.region or "")):
        wrong.append(f"region {d.location.region if d and d.location else None}, expected {expect['region']}")
    if "ceiling" in expect and (r is None or r.budget_ceiling != expect["ceiling"]):
        wrong.append(f"budget ceiling {r.budget_ceiling if r else None}, expected {expect['ceiling']}")
    if expect.get("no_ceiling") and r is not None and r.budget_ceiling is not None:
        wrong.append(f"budget ceiling {r.budget_ceiling}, expected none")
    if "replanned" in expect and bool(s.get("replan_count")) != expect["replanned"]:
        wrong.append(f"replan rounds {s.get('replan_count', 0)}, expected {'some' if expect['replanned'] else 'none'}")
    if "verdict" in expect and (s.get("verdict") is None or s["verdict"].status != expect["verdict"]):
        wrong.append(f"verdict {s['verdict'].status if s.get('verdict') else None}, expected {expect['verdict']}")
    notes = " ".join(s.get("notes", [])).lower()
    for text in expect.get("notes_include", []):
        if text.lower() not in notes:
            wrong.append(f"no note containing '{text}'")
    where = {e.where for e in s.get("errors", [])}
    for tool in expect.get("errors_where", []):
        if tool not in where:
            wrong.append(f"no handled error from {tool}")
    return wrong


def summary(s: dict) -> str:
    d, c, v = s.get("destination"), s.get("cost"), s.get("verdict")
    parts = []
    if d and d.base_city:
        parts.append(d.base_city)
    it = s.get("itinerary")
    if it:
        parts.append(f"{sum(len(day.places) for day in it.days)} places")
    if c:
        limit = f" / limit Rs {v.ceiling:,.0f}" if v and v.ceiling else ""
        parts.append(f"Rs {c.total:,.0f}{limit}")
    if s.get("replan_count"):
        parts.append(f"{s['replan_count']} replan round(s)")
    fixes = [e.event for e in s.get("trace", []) if e.event in SELF_CORRECTION]
    if fixes:
        parts.append(f"self-corrections: {', '.join(fixes)}")
    if s.get("errors"):
        parts.append("handled: " + ", ".join(f"{e.where} ({e.error_type}: {e.message})" for e in s["errors"]))
    return "; ".join(parts)


def run_case(case: dict) -> dict:
    injected = set()
    for name in filter(None, (case.get("inject") or "").split(",")):
        injected |= config.INJECTABLE_FAILURES[name.strip()]
    inject_failures(injected)
    start = time.perf_counter()
    try:
        state = build_graph().invoke({"goal": case["goal"], "today": dt.date.today(), "replan_count": 0})
        wrong = case_checks(state, case["expect"]) + general_checks(state)
        info = summary(state)
        status = state.get("status")
    except Exception as err:  # a crash is a failure of the agent, recorded rather than stopping the run
        wrong, info, status = [f"crashed: {type(err).__name__}: {err}"], traceback.format_exc(limit=3), "crash"
    finally:
        inject_failures(set())
    return {"id": case["id"], "about": case["about"], "goal": case["goal"], "inject": case.get("inject", ""),
            "status": status, "wrong": wrong, "info": info, "seconds": round(time.perf_counter() - start)}


def write_results(results: list[dict], path: pathlib.Path, title: str) -> None:
    passed = sum(not r["wrong"] for r in results)
    lines = [f"# yatra-agent — {title}", "",
             f"Run on {dt.datetime.now():%Y-%m-%d %H:%M}, live APIs, gpt-4o-mini. "
             f"**{passed}/{len(results)} cases passed.**", "",
             "Every case is checked against its own expectation and against general rules: errors carry "
             "'handled_by', a report is written, the plan ends with the fixed tail, the right number of days, every "
             "day has a timeline with no overlaps, sightseeing ends by 19:00 (or a note says the day is long), no "
             "place twice, and a budget outside the limit is explained.", "",
             "| Case | What it tests | Result | Status | Details |", "|---|---|---|---|---|"]
    for r in results:
        result = "PASS" if not r["wrong"] else "FAIL: " + "; ".join(r["wrong"])
        about = r["about"] + (f" (`--inject-failure {r['inject']}`)" if r["inject"] else "")
        info = r["info"].replace("\n", " ").replace("|", "/") if r["status"] != "crash" else "see console"
        result = result.replace("|", "/")
        lines.append(f"| {r['id']} | {about} | {result} | {r['status']} | {info} ({r['seconds']} s) |")
    lines += ["", "## Goals", ""] + [f"- **{r['id']}**: {r['goal']}" for r in results] + [""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = sys.argv[1:]
    holdout = "--holdout" in args
    source, target = (HOLDOUT, HOLDOUT_RESULTS) if holdout else (CASES, RESULTS)
    only = {a for a in args if not a.startswith("--")}
    cases = [c for c in json.loads(source.read_text(encoding="utf-8"))["cases"] if not only or c["id"] in only]
    print(f"Set: {source.name}\n")
    results = []
    for case in cases:
        print(f"{case['id']}  {case['goal']}" + (f"  [{case['inject']}]" if case.get("inject") else ""), flush=True)
        r = run_case(case)
        results.append(r)
        print(f"      {'PASS' if not r['wrong'] else 'FAIL'}  status={r['status']}  {r['seconds']} s")
        for w in r["wrong"]:
            print(f"      - {w}")
        if r["status"] == "crash":
            print(r["info"])
        else:
            print(f"      {r['info']}")
    write_results(results, target, "end-to-end HOLDOUT results" if holdout else "end-to-end results (dev set)")
    passed = sum(not r["wrong"] for r in results)
    failed = [r["id"] for r in results if r["wrong"]]
    print(f"\n{passed}/{len(results)} passed" + (f" | failed: {', '.join(failed)}" if failed else ""))
    print(f"Saved {target}")


if __name__ == "__main__":
    main()
