"""Node 2: complete the request in code - dates, defaults, nights and total budget. No LLM."""

import datetime as dt
import time
import config
from date_helpers import check_date_refs, resolve_date_ref
from schemas import TraceEvent, TripRequest

BUDGET_MEANING = {"at_most": "a maximum", "about": "an estimate", "at_least": "a minimum"}

def budget_bounds(direction: str, low: float, high: float) -> tuple[float, float | None, float | None]:
    """(target, ceiling, floor) in rupees for the whole group and trip. None = no bound on that side.
    Whether a plan above or below these is acceptable is decided later by the planner."""
    if direction == "at_most":
        return low, low, None
    if direction == "at_least":
        return low, None, low
    if direction == "range":
        return (low + high) / 2, high, low
    return low, round(low * (1 + config.BUDGET_FLEX)), None  # about

def normalize(req: TripRequest, goal: str, today: dt.date) -> tuple[TripRequest, list[str]]:
    r = req.model_copy(deep=True)
    notes: list[str] = []
    tomorrow = today + dt.timedelta(days=config.DEFAULT_START_OFFSET_DAYS)

    # The LLM only says how each date was named; code checks it against the goal and counts.
    start_ref, end_ref, date_notes = check_date_refs(r.start, r.end, goal)
    notes += date_notes

    r.start_date = r.end_date = None
    if start_ref:
        r.start_date, note = resolve_date_ref(start_ref, today)
        if note:
            notes.append(note)
    if end_ref:
        r.end_date, note = resolve_date_ref(end_ref, today, after=r.start_date)
        if note:
            notes.append(note)
    if start_ref and start_ref.kind == "weekend" and r.start_date and not end_ref and not r.days:
        r.end_date = r.start_date + dt.timedelta(days=1)  # Saturday + Sunday

    if r.start_date and r.start_date < today:
        notes.append(f"Start date {r.start_date} is in the past, so the trip starts tomorrow ({tomorrow}).")
        r.start_date = tomorrow
    if r.end_date and (r.end_date < today or (r.start_date and r.end_date < r.start_date)):
        notes.append(f"End date {r.end_date} is before the start date, so it was ignored.")
        r.end_date = None

    if r.start_date and r.end_date:
        span = (r.end_date - r.start_date).days + 1
        if r.days and r.days != span:
            notes.append(f"You said {r.days} days but the dates cover {span} days; the dates were used.")
        r.days = span
    elif r.end_date:  # only an end date
        if r.days:
            r.start_date = max(r.end_date - dt.timedelta(days=r.days - 1), tomorrow)
        else:
            r.start_date = tomorrow
            notes.append(f"Start date not given, so the trip starts tomorrow ({tomorrow}).")
        r.days = (r.end_date - r.start_date).days + 1
    else:
        if not r.days:
            r.days = config.DEFAULT_DAYS
            notes.append(f"Trip length not given, so {r.days} days were assumed.")
        if not r.start_date:
            r.start_date = tomorrow
            notes.append(f"Start date not given, so the trip starts tomorrow ({tomorrow}).")

    if r.days > config.MAX_DAYS:
        notes.append(f"Trips are limited to {config.MAX_DAYS} days; {r.days} days were shortened.")
        r.days = config.MAX_DAYS
    r.end_date = r.start_date + dt.timedelta(days=r.days - 1)
    r.nights = r.days - 1

    if r.travellers is None:
        r.travellers = config.DEFAULT_TRAVELLERS
        if r.budget_is_per_person:
            notes.append(f"The budget is per person but the group size was not given, "
                         f"so {r.travellers} traveller was assumed.")
        else:
            notes.append(f"Group size not given, so {r.travellers} traveller was assumed.")

    # Budget: the LLM said which way the figure limits the cost; code turns that into rupee bounds.
    if r.budget_amount is None:
        # Our own guess is a guide for the report, never a limit: the plan is not cut to fit it.
        r.total_budget = config.DEFAULT_BUDGET_PER_PERSON_PER_DAY * r.travellers * r.days
        r.budget_ceiling = r.budget_floor = None
        notes.append(f"Budget not given, so Rs {config.DEFAULT_BUDGET_PER_PERSON_PER_DAY} per person per day "
                     f"(Rs {r.total_budget:,.0f} in total) is shown as a rough guide; the plan is not cut to fit it.")
    else:
        scale = (r.travellers if r.budget_is_per_person else 1) * (r.days if r.budget_is_per_day else 1)
        direction = r.budget_direction
        low = r.budget_amount * scale
        high = (r.budget_amount_max or 0) * scale if direction == "range" else low
        if direction == "range" and high <= low:
            direction = "about"
            notes.append(f"Only one budget figure was found in '{r.budget_phrase}', so Rs {low:,.0f} "
                         "was treated as an estimate.")
        if direction == "not_stated":
            direction = config.PLAIN_BUDGET_DIRECTION
            reason = (f"the words '{r.budget_phrase}' did not say whether it can be exceeded"
                      if r.budget_phrase else "no word said whether it can be exceeded")
            notes.append(f"Budget of Rs {low:,.0f} was treated as {BUDGET_MEANING[direction]}, because {reason}.")
        r.total_budget, r.budget_ceiling, r.budget_floor = budget_bounds(direction, low, high)

    # Purposes stated directly plus the purposes of every kind of place, in order, without repeats.
    combined = list(r.interests) + [i for pt in r.place_types for i in pt.interests]
    r.interests = list(dict.fromkeys(combined))
    if not r.interests:
        r.interests = list(config.DEFAULT_INTERESTS)
        notes.append("No interests given, so popular sights were planned.")

    seen = set()
    r.must_visit = [p for p in r.must_visit if not (p.lower() in seen or seen.add(p.lower()))]

    return r, notes

def normalize_node(state: dict) -> dict:
    start = time.perf_counter()
    today = state.get("today") or dt.date.today()
    request, notes = normalize(state["request"], state["goal"], today)
    ms = int((time.perf_counter() - start) * 1000)
    return {
        "request": request,
        "notes": notes,
        "trace": [TraceEvent(node="normalize", event="normalize",
                             detail={"days": request.days, "nights": request.nights,
                                     "start_date": str(request.start_date),
                                     "travellers": request.travellers,
                                     "total_budget": request.total_budget,
                                     "notes_added": len(notes)},
                             duration_ms=ms)],
    }



