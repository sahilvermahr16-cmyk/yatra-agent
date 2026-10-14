"""Node 4: the executor runs the plan's data steps in order (resolve_destination, weather, locate_place,
find_places), records every call, and turns each failure or unmet wish into a note instead of a crash.
The last three steps (estimate_costs, build_itinerary, check_budget) belong to the nodes after it."""

import datetime as dt
from dataclasses import dataclass, field
import config
from plan_checks import TAIL, forecast_available, purposes_needing_search
from schemas import DestinationResult, Miss, Place, Plan, PlanStep, StepResult, TripRequest
from tools import places as places_tool
from tools import weather as weather_tool
from tools.calls import ToolLog
from tools.destination import resolve_destination
from tools.geo import distance_km

PRIORITY = ["must_visit", "place_type", "interest", "popular"]
SIGHT_WORD = {"history": "historic", "religious": "religious", "nature": "natural", "shopping": "shopping"}

def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in text.lower().split() if len(w) > 2}

def match_wishes(plan: Plan, request: TripRequest) -> dict[int, tuple[str, str]]:
    """For each place_type / interest step: the user's wish it serves and its category.
    Paired by shared words first ('stepwell' <-> 'stepwells'), then in order."""
    pairs: dict[int, tuple[str, str]] = {}
    pools = {
        "place_type": [(pt.words, pt.interests[0] if pt.interests else "popular") for pt in request.place_types],
        "interest": [(i, i) for i in purposes_needing_search(request)],
    }
    for serves, pool in pools.items():
        steps = [s for s in plan.steps if s.tool == "find_places" and s.serves == serves]
        free = list(pool)
        for s in steps:  # best word overlap first
            text = _words(f"{s.query or ''} {s.reason}")
            best = max(free, key=lambda w: len(text & _words(w[0])), default=None)
            if best and text & _words(best[0]):
                pairs[s.step] = best
                free.remove(best)
        for s in steps:  # the rest in order
            if s.step not in pairs and free:
                pairs[s.step] = free.pop(0)
    return pairs

def _place(page, city, serves, wish, category) -> Place:
    if serves == "popular":
        category = places_tool.category_of(page) or "popular"
    return Place(name=page.title, lat=page.lat, lon=page.lon, description=page.description, url=page.url,
                 distance_km=round(distance_km(city.lat, city.lon, page.lat, page.lon), 1),
                 serves=serves, wish=wish, category=category, indoor=places_tool.is_indoor(page),
                 entry_fee=config.DEFAULT_ENTRY_FEE, pageviews=page.views)

def _keep(found: dict[str, Place], place: Place) -> bool:
    """Add a place unless it is already there for a more important wish. True if it was added."""
    key = place.name.lower()
    old = found.get(key)
    if old and PRIORITY.index(old.serves) <= PRIORITY.index(place.serves):
        return False
    found[key] = place
    return True

@dataclass
class _Run:
    """What the executor knows while it works through the plan."""
    request: TripRequest
    today: dt.date
    log: ToolLog
    wishes: dict[int, tuple[str, str]]  # find_places step -> (the user's wish, its category)
    results: list[StepResult] = field(default_factory=list)
    misses: list[Miss] = field(default_factory=list)
    found: dict[str, Place] = field(default_factory=dict)
    prefer: dict[str, str] = field(default_factory=dict)  # kind of sight -> the must-visit place it comes from
    destination: DestinationResult | None = None
    weather: list | None = None

    @property
    def city(self):
        return self.destination.location if self.destination else None

    def done(self, step: PlanStep, ok: bool, summary: str) -> None:
        self.results.append(StepResult(step=step.step, tool=step.tool, ok=ok, summary=summary))

# One handler per data tool. Each records its own result; False means "stop: the trip cannot be planned".

def _resolve(run: _Run, step: PlanStep) -> bool:
    r = run.request
    run.destination = resolve_destination(r.destination, run.today, run.log)
    if run.destination.location is None:
        run.done(step, False, f"could not place '{r.destination}' on the map; stopping")
        return False
    d, loc = run.destination, run.destination.location
    run.done(step, True, f"{d.destination_type} -> base city {d.base_city} ({loc.lat:.3f}, {loc.lon:.3f})")
    return True

def _weather(run: _Run, step: PlanStep) -> bool:
    r, log = run.request, run.log
    days, ok = log.call("weather", weather_tool.forecast, run.city, r.start_date, r.end_date, run.today,
                        on_fail="continued without a forecast")
    if not ok:
        log.notes.append("The weather forecast could not be fetched, so the plan has no weather "
                         "adjustments. Please check the forecast before you go.")
        run.done(step, False, "forecast unavailable; continuing without weather")
        return True
    run.weather = days
    if len(days) < r.days:
        log.notes.append(f"The forecast covers {len(days)} of the {r.days} trip days "
                         f"(forecasts reach {config.FORECAST_MAX_DAYS} days ahead).")
    rainy = sum(d.rain_probability >= config.RAINY_DAY_PROBABILITY for d in days)
    run.done(step, True, f"{len(days)} day(s) of forecast, {rainy} likely rainy")
    return True

def _locate(run: _Run, step: PlanStep) -> bool:
    name, city, log = step.query, run.city, run.log
    page, ok = log.call("places", places_tool.locate, name, city, on_fail=f"'{name}' could not be looked up")
    if not ok:
        run.misses.append(Miss(serves="must_visit", wish=name, reason="the place search failed"))
        run.done(step, False, f"lookup of {name} failed")
        return True
    if page is None:
        run.misses.append(Miss(serves="must_visit", wish=name, reason="it could not be found on Wikipedia"))
        run.done(step, False, f"{name} not found")
        return True
    place = _place(page, city, "must_visit", name, "popular")
    if place.distance_km > config.MUST_VISIT_RADIUS_KM:
        near, _ = log.call("places", places_tool.city_of, page, on_fail=f"the note for {name} names no nearby city")
        run.misses.append(Miss(serves="must_visit", wish=name, near_city=near,
                               reason=f"it is {place.distance_km:.0f} km from {city.name}"))
        run.done(step, False, f"{page.title} is {place.distance_km:.0f} km away "
                              f"(limit {config.MUST_VISIT_RADIUS_KM} km)")
        return True
    _keep(run.found, place)
    kind = places_tool.category_of(page)
    if kind:
        run.prefer.setdefault(kind, name)
    run.done(step, True, f"{page.title} found, {place.distance_km:.1f} km from {city.name}")
    return True

def _find(run: _Run, step: PlanStep) -> bool:
    city, log = run.city, run.log
    serves = step.serves or "popular"
    if serves == "popular":  # enough well-known sights to fill every day if nothing else is found
        wish, category = "best-known sights", "popular"
        pages, ok = log.call("places", places_tool.popular, step.query, city,
                             run.request.days * config.PLACES_PER_DAY, set(run.prefer),
                             on_fail=f"search for '{step.query}' skipped")
        for kind, source in run.prefer.items():
            log.notes.append(f"Because you chose {source}, other {SIGHT_WORD.get(kind, kind)} sights were "
                             "preferred among the popular ones.")
    else:
        wish, category = run.wishes.get(step.step, ("best-known sights", "popular"))
        pages, ok = log.call("places", places_tool.find, step.query, city,
                             on_fail=f"search for '{step.query}' skipped")
    if not ok:
        run.misses.append(Miss(serves=serves, wish=wish, reason="the place search failed"))
        run.done(step, False, f"search '{step.query}' failed")
        return True
    added = [p.name for p in (_place(pg, city, serves, wish, category) for pg in pages) if _keep(run.found, p)]
    if not pages:
        run.misses.append(Miss(serves=serves, wish=wish, reason=f"no matching places were found on Wikipedia "
                                                                 f"within {config.SEARCH_RADIUS_KM} km of {city.name}"))
    shown = f" ({', '.join(added[:3])}{'...' if len(added) > 3 else ''})" if added else ""
    run.done(step, bool(pages), f"'{step.query}': {len(pages)} found, {len(added)} new{shown}")
    return True

HANDLERS = {"resolve_destination": _resolve, "weather": _weather, "locate_place": _locate, "find_places": _find}

def _forecast_note(plan: Plan, request: TripRequest, today: dt.date) -> str | None:
    """The planner leaves out the weather step for dates beyond the forecast; say so instead of staying silent."""
    if "weather" in [s.tool for s in plan.steps] or forecast_available(request, today):
        return None
    days_away = (request.start_date - today).days if request.start_date else None
    when = f"Your trip starts in {days_away} days; w" if days_away is not None else "W"
    return (f"{when}eather forecasts reach only {config.FORECAST_MAX_DAYS} days ahead, so this plan does not "
            "account for the weather. Check the forecast a few days before you go.")

def execute(plan: Plan, request: TripRequest, today: dt.date) -> dict:
    """Run the data steps in the plan's order; the tail steps belong to the nodes after this one."""
    run = _Run(request=request, today=today, log=ToolLog("executor"), wishes=match_wishes(plan, request))
    for step in plan.steps:
        if step.tool not in TAIL and not HANDLERS[step.tool](run, step):
            break
    note = _forecast_note(plan, request, today)
    if note:
        run.log.notes.append(note)

    log, d = run.log, run.destination
    status = "running"
    if d is None or d.location is None:
        status = "gave_up" if any(e.where in ("geocode", "wikivoyage") for e in log.errors) else "needs_city"
    ordered = sorted(run.found.values(), key=lambda p: PRIORITY.index(p.serves))
    return {"destination": d, "location": d.location if d else None, "weather": run.weather, "places": ordered,
            "misses": run.misses, "step_results": run.results, "trace": log.trace, "errors": log.errors,
            "notes": log.notes, "status": status}

def executor_node(state: dict) -> dict:
    today = state.get("today") or dt.date.today()
    return execute(state["plan"], state["request"], today)








