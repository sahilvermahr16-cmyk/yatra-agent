"""Node 1: read the goal with the LLM. No tools, no defaults, no arithmetic."""

import datetime as dt
import re
import time
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError
from date_helpers import fix_kind_from_phrase, phrase_in_goal, ref_problems
from llm_setup import llm
from prompts import EXTRACT_PROMPT
from schemas import ErrorRecord, ExtractedGoal, TraceEvent, TripRequest

# Function calling followed the schema better than json_schema mode in eval/debug_variants.py
structured_llm = llm.with_structured_output(ExtractedGoal, method="function_calling")

RETRY_MESSAGE = (
    "Your output has these problems:\n{problems}\n"
    "Every date reference must copy the user's exact words as its phrase, and every number in it "
    "must come from those words. Every place_types entry needs at least one interest. "
    "A money figure is always copied into budget_phrase with the words attached to it, and "
    "budget_direction is decided by reading those words. Return the complete output again, corrected."
)

def budget_problems(extracted: ExtractedGoal, goal: str) -> list[str]:
    """Budget fields must rest on the user's own words around the figure and fit together.
    Code checks the evidence and the structure; what the words mean is the LLM's decision."""
    phrase = (extracted.budget_phrase or "").strip()
    direction, amount, top = extracted.budget_direction, extracted.budget_amount, extracted.budget_amount_max
    if amount is None:
        if direction != "not_stated":
            return [f"- budget_direction is '{direction}' but there is no money figure: copy the figure into "
                    "budget_phrase and budget_amount, or use not_stated"]
        return []
    if not phrase:
        return [f"- budget_amount is {amount:g} but budget_phrase is empty: copy the figure with the words "
                "attached to it, then decide budget_direction from those words"]
    if not phrase_in_goal(phrase, goal):
        return [f"- budget_phrase '{phrase}' does not appear in the goal: copy the user's exact words"]
    problems = []
    if any(c.isdigit() for c in goal) and not any(c.isdigit() for c in phrase):
        problems.append(f"- budget_phrase '{phrase}' does not contain the money figure: copy the figure as well")
    if direction == "range":
        if top is None:
            problems.append("- budget_direction is range but budget_amount_max is empty: a range needs its "
                            "lowest and highest numbers")
        elif top <= amount:
            problems.append("- budget_amount_max must be the larger number of the range")
        if len(re.findall(r"\d+(?:\.\d+)?", phrase)) < 2:
            problems.append(f"- '{phrase}' has only one number, so it is not a range")
    elif top is not None:
        problems.append("- budget_amount_max is only for a range; leave it null")
    return problems

def self_check_problems(extracted: ExtractedGoal, goal: str) -> list[str]:
    """Problems in the LLM's output that a second look could fix."""
    problems = []
    start = extracted.start
    if start:
        start, _ = fix_kind_from_phrase(start)
        problems += [f"- start: {p}" for p in ref_problems(start, goal)]
    if extracted.end:
        end, _ = fix_kind_from_phrase(extracted.end)
        problems += [f"- end: {p}" for p in ref_problems(end, goal, start=start)]
    for pt in extracted.place_types:
        if not pt.interests:
            problems.append(f"- place_types '{pt.words}' has no interests: why do people go there?")
    problems += budget_problems(extracted, goal)
    return problems

PARSE_RETRY_MESSAGE = (
    "Your previous answer did not match the required output format:\n{error}\n"
    "Return the complete output again, with every field in the required type."
)

def invoke_checked(messages: list, trace: list) -> ExtractedGoal:
    """Call the LLM; if its output does not fit the schema, retry once with the error.
    Raises the second error if the retry fails too."""
    start = time.perf_counter()
    try:
        return structured_llm.invoke(messages)
    except (OutputParserException, ValidationError) as err:
        short = str(err).splitlines()[0][:300]
        trace.append(TraceEvent(node="extract", event="llm_parse_retry", detail={"error": str(err)[:1000]},
                                duration_ms=int((time.perf_counter() - start) * 1000)))
        return structured_llm.invoke(messages + [("user", PARSE_RETRY_MESSAGE.format(error=short))])

def extract_node(state: dict) -> dict:
    today = state.get("today") or dt.date.today()
    # str.replace instead of str.format so braces elsewhere in the prompt are safe
    today_line = f"{today.isoformat()}. Current year: {today.year}."
    prompt = EXTRACT_PROMPT.replace("{today_line}", today_line)
    messages = [("system", prompt), ("user", state["goal"])]
    trace: list[TraceEvent] = []

    start = time.perf_counter()
    try:
        extracted = invoke_checked(messages, trace)
    except (OutputParserException, ValidationError) as err:
        return {
            "status": "gave_up",
            "trace": trace,
            "errors": [ErrorRecord(where="extract", error_type=type(err).__name__, message=str(err)[:500],
                                   handled_by="retried once with the error, then stopped")],
            "notes": ["The goal could not be read into a trip request. Please rephrase it and try again."],
        }
    ms = int((time.perf_counter() - start) * 1000)
    trace.append(TraceEvent(node="extract", event="llm_extract",
                            detail=extracted.model_dump(mode="json"), duration_ms=ms))

    # Self-correction: one retry when the output disagrees with the goal or with itself.
    problems = self_check_problems(extracted, state["goal"])
    if problems:
        feedback = RETRY_MESSAGE.format(problems="\n".join(problems))
        start = time.perf_counter()
        try:
            retried = invoke_checked(
                messages + [("assistant", extracted.model_dump_json()), ("user", feedback)], trace)
        except (OutputParserException, ValidationError):
            retried = extracted  # keep the first answer; normalize drops what is still wrong
        ms = int((time.perf_counter() - start) * 1000)
        left = self_check_problems(retried, state["goal"])
        trace.append(TraceEvent(node="extract", event="llm_self_check_retry",
                                detail={"problems": problems, "problems_after_retry": left,
                                        "start": retried.start.model_dump() if retried.start else None,
                                        "end": retried.end.model_dump() if retried.end else None},
                                duration_ms=ms))
        extracted = retried  # anything still wrong is dropped by normalize, with a note

    update = {
        "request": TripRequest(**extracted.model_dump()),
        "trace": trace,
        "status": "running",
    }
    if not extracted.destination:
        update["status"] = "needs_city"
        update["notes"] = ["No destination found in the goal. Please include a city or state."]
    return update






