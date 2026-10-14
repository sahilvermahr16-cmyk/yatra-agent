"""Node 3: the planner (LLM) writes the visible plan before any tool runs; code checks it.

Manual check: python planner_node.py "3 days in Jodhpur, must see Mehrangarh Fort, love stepwells"
"""

import datetime as dt
import time
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError
from llm_setup import llm
from plan_checks import default_plan, format_plan, plan_problems, tidy, trip_facts
from prompts import PLANNER_PROMPT
from schemas import Plan, TraceEvent

structured_llm = llm.with_structured_output(Plan, method="function_calling")

RETRY_MESSAGE = ("Your plan has these problems:\n{problems}\n"
                 "Follow the rules: one step per wish, nothing the user did not ask for, the tools in the "
                 "required order. Return the complete plan again, corrected.")
PARSE_RETRY_MESSAGE = ("Your previous answer did not match the required output format:\n{error}\n"
                       "Return the complete plan again, with every field in the required type.")

def _ask(messages: list, trace: list) -> Plan | None:
    """One planner call with one retry on a format error. None if both fail."""
    for attempt in range(2):
        try:
            return structured_llm.invoke(messages)
        except (OutputParserException, ValidationError) as err:
            short = str(err).splitlines()[0][:300]
            trace.append(TraceEvent(node="planner", event="llm_parse_retry" if attempt == 0 else "llm_parse_failed",
                                    detail={"error": str(err)[:1000]}))
            messages = messages + [("user", PARSE_RETRY_MESSAGE.format(error=short))]
    return None

def make_plan(request, today: dt.date) -> tuple[Plan, list[TraceEvent], list[str]]:
    trace: list[TraceEvent] = []
    facts = trip_facts(request, today)
    messages = [("system", PLANNER_PROMPT.replace("{today_line}", today.isoformat())), ("user", facts)]
    start = time.perf_counter()
    plan = _ask(messages, trace)
    problems = plan_problems(plan, request, today) if plan else ["- the plan could not be read"]
    if plan and problems:  # self-correction: one retry with the list of problems
        trace.append(TraceEvent(node="planner", event="llm_self_check_retry", detail={"problems": problems}))
        retry = _ask(messages + [("assistant", plan.model_dump_json()),
                                 ("user", RETRY_MESSAGE.format(problems="\n".join(problems)))], trace)
        if retry:
            plan, problems = retry, plan_problems(retry, request, today)
    notes = []
    if problems:
        trace.append(TraceEvent(node="planner", event="planner_fallback", detail={"problems": problems}))
        notes.append("The planner's own plan did not pass the checks, so a default plan built by code was used.")
        plan = default_plan(request, today)
    plan = tidy(plan)
    ms = int((time.perf_counter() - start) * 1000)
    trace.append(TraceEvent(node="planner", event="plan", duration_ms=ms,
                            detail={"facts": facts, **plan.model_dump(mode="json")}))
    return plan, trace, notes

def planner_node(state: dict) -> dict:
    today = state.get("today") or dt.date.today()
    plan, trace, notes = make_plan(state["request"], today)
    return {"plan": plan, "trace": trace, "notes": notes}


if __name__ == "__main__":
    import sys

    from extract_node import extract_node
    from normalize_node import normalize

    today = dt.date.today()
    for goal in sys.argv[1:]:
        out = extract_node({"goal": goal, "today": today})
        print(f"\nGOAL: {goal}")
        if "request" not in out or out["status"] == "needs_city":
            print("  stopped:", out.get("notes"))
            continue
        request, _ = normalize(out["request"], goal, today)
        plan, trace, notes = make_plan(request, today)
        print(trip_facts(request, today))
        print(format_plan(plan))
        for e in trace:
            if e.event != "plan":
                print(f"  [{e.event}] {e.detail.get('problems', '')}")
        for n in notes:
            print("  note:", n)



