"""Code around the planner: the trip facts it reads, the checks its plan must pass, and the default plan
used when it cannot produce a valid one. No LLM here."""

import datetime as dt
import config
from schemas import Plan, PlanStep, TripRequest
from tools.destination import state_key

PLACE_TOOLS = ("locate_place", "find_places")
TAIL = ["build_itinerary", "find_stays_and_food", "estimate_costs", "check_budget"]
MAX_QUERY_WORDS = 5

def forecast_available(r: TripRequest, today: dt.date) -> bool:
    """Open-Meteo forecasts today + 15 days; the trip's first day must fall inside that window."""
    return r.start_date is not None and (r.start_date - today).days < config.FORECAST_MAX_DAYS

def purposes_needing_search(r: TripRequest) -> list[str]:
    """Purposes not already served by a kind of place the user named (code decides, not the LLM)."""
    served = {i for pt in r.place_types for i in pt.interests}
    return [i for i in r.interests if i != "popular" and i not in served]

def trip_facts(r: TripRequest, today: dt.date) -> str:
    """The planner's input: only facts, with every count and date difference already computed."""
    key = state_key(r.destination or "")
    in_list = key in config.INDIAN_STATES_AND_UTS and key not in config.CITY_LIKE_UTS
    starts_in = (r.start_date - today).days if r.start_date else None
    forecast = "a forecast IS available" if forecast_available(r, today) else "a forecast is NOT available"
    in_days = f"{starts_in} day{'' if starts_in == 1 else 's'}"
    dates = (f"{r.start_date:%d %b} – {r.end_date:%d %b %Y}, {r.days} days; the trip starts in {in_days}; "
             f"{forecast}") if r.start_date and r.end_date else f"{r.days} days; {forecast}"
    if r.budget_amount is None:
        guide = f" (Rs {r.total_budget:,.0f} is shown only as a rough guide)" if r.total_budget else ""
        budget = f"not given{guide}"
    else:
        budget = f"target Rs {r.total_budget:,.0f} for the whole group"
    if r.budget_ceiling:
        budget += f", must not cost more than Rs {r.budget_ceiling:,.0f}"
    if r.budget_floor:
        budget += f", should not cost less than Rs {r.budget_floor:,.0f}"
    kinds = "; ".join(f'"{pt.words}" ({", ".join(pt.interests) or "no category"})' for pt in r.place_types) or "none"
    needs = purposes_needing_search(r)
    served = [i for i in r.interests if i != "popular" and i not in needs]
    purposes = [f"{i} (needs its own search)" for i in needs] + [f"{i} (already served by a kind of place)"
                                                                 for i in served]
    return "\n".join([
        "Trip facts:",
        f'  Destination: "{r.destination}" ({"in" if in_list else "not in"} the list of Indian states)',
        f"  Dates: {dates}",
        f"  Travellers: {r.travellers}",
        f"  Budget: {budget}",
        f"  Style: {r.budget_style or 'not stated'}",
        f"  Must visit: {'; '.join(r.must_visit) or 'none'}",
        f"  Kinds of place: {kinds}",
        f"  Purposes: {'; '.join(purposes) or 'none'}",
    ])

def plan_problems(plan: Plan, r: TripRequest, today: dt.date) -> list[str]:
    """Everything wrong with a plan, as short lines the planner can act on. Empty = valid."""
    steps = plan.steps
    tools = [s.tool for s in steps]
    problems = []
    if not steps or tools[0] != "resolve_destination" or tools.count("resolve_destination") != 1:
        problems.append("- resolve_destination must be the first step, exactly once")

    if forecast_available(r, today) and tools.count("weather") != 1:
        problems.append("- a forecast is available, so the plan needs exactly one weather step")
    if not forecast_available(r, today) and "weather" in tools:
        problems.append("- a forecast is NOT available for these dates, so remove the weather step")

    def place_steps(serves):
        return [s for s in steps if s.tool in PLACE_TOOLS and s.serves == serves]

    located = [(s.query or "").lower() for s in place_steps("must_visit") if s.tool == "locate_place"]
    for place in r.must_visit:
        if not any(place.lower() in q or q and q in place.lower() for q in located):
            problems.append(f"- must visit '{place}' has no locate_place step")
    if len(place_steps("must_visit")) > len(r.must_visit):
        problems.append("- only the user's must-visit places get a locate_place step")
    for serves, wanted, label in (("place_type", len(r.place_types), "kind of place"),
                                  ("interest", len(purposes_needing_search(r)), "purpose that needs its own search")):
        got = [s for s in place_steps(serves) if s.tool == "find_places"]
        if len(got) != wanted:
            problems.append(f"- there are {wanted} {label} wish(es) but {len(got)} find_places step(s) for them")
    if len([s for s in place_steps("popular") if s.tool == "find_places"]) != 1:
        problems.append("- the plan needs exactly one find_places step that serves 'popular'")
    for s in steps:
        if s.tool in PLACE_TOOLS and not (s.query or "").strip():
            problems.append(f"- step {s.tool} needs a query")
        elif s.tool == "find_places" and len((s.query or "").split()) > MAX_QUERY_WORDS:
            problems.append(f"- find_places query '{s.query}' is too long: use 1-3 words")
        if s.tool in PLACE_TOOLS and s.serves is None:
            problems.append(f"- step {s.tool} '{s.query}' must say which wish it serves")

    if [t for t in tools if t in TAIL] != TAIL:
        problems.append("- build_itinerary, find_stays_and_food, estimate_costs and check_budget must each appear "
                        "once, in that order")
    elif (any(t in PLACE_TOOLS or t == "weather" for t in tools[tools.index("build_itinerary"):])
          or tools[-1] != "check_budget"):
        problems.append("- weather and place steps come before build_itinerary; check_budget is the last step")
    return problems

def tidy(plan: Plan) -> Plan:
    """Renumber steps and drop queries from tools that take none (harmless slips, not errors)."""
    steps = []
    for i, s in enumerate(plan.steps, start=1):
        keep = s.tool in PLACE_TOOLS
        steps.append(s.model_copy(update={"step": i, "query": s.query if keep else None,
                                          "serves": s.serves if keep else None}))
    return Plan(summary=plan.summary, steps=steps)

def default_plan(r: TripRequest, today: dt.date) -> Plan:
    """A valid plan built by code from the same rules, used when the planner's plan cannot be used."""
    steps = [PlanStep(step=1, tool="resolve_destination", reason=f"Find {r.destination} on the map.")]
    if forecast_available(r, today):
        steps.append(PlanStep(step=1, tool="weather", reason="The trip starts within the forecast range."))
    for place in r.must_visit:
        steps.append(PlanStep(step=1, tool="locate_place", query=place, serves="must_visit",
                              reason=f"You must see {place}."))
    for pt in r.place_types:
        query = " ".join(pt.words.split()[:MAX_QUERY_WORDS])
        steps.append(PlanStep(step=1, tool="find_places", query=query, serves="place_type",
                              reason=f"You want {pt.words}."))
    for i in purposes_needing_search(r):
        steps.append(PlanStep(step=1, tool="find_places", query=config.DEFAULT_SEARCH_PHRASES[i],
                              serves="interest", reason=f"You are interested in {i}."))
    steps.append(PlanStep(step=1, tool="find_places", query=config.DEFAULT_SEARCH_PHRASES["popular"],
                          serves="popular", reason="Fill the free time with the best-known sights."))
    steps += [PlanStep(step=1, tool="build_itinerary", reason="Put the places into days, most important first."),
              PlanStep(step=1, tool="find_stays_and_food",
                       reason="Find a place to stay and to eat near each day's plan."),
              PlanStep(step=1, tool="estimate_costs", reason="Price the stay, food, travel and tickets."),
              PlanStep(step=1, tool="check_budget", reason="Compare the cost with the budget.")]
    return tidy(Plan(summary=f"{r.days} days in {r.destination} (default plan).", steps=steps))

def format_plan(plan: Plan) -> str:
    lines = [f"PLAN: {plan.summary}"]
    for s in plan.steps:
        what = f' "{s.query}"' if s.query else ""
        why = f" [{s.serves}]" if s.serves else ""
        lines.append(f"  {s.step}. {s.tool}{what}{why} - {s.reason}")
    return "\n".join(lines)





