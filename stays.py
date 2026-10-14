"""Node (find_stays_and_food): a place to stay each night, breakfast, lunch and an evening meal each day (a food
stop if the user asked for food, otherwise dinner), chosen in code from one OpenStreetMap query, and the day told as
a timed story: leave the hotel -> breakfast -> places -> lunch -> rest -> places -> evening meal -> night stay.

Rules agreed for the project:
  - the hotel for a night is near the NEXT day's places; last night's hotel is kept if it is close enough;
  - the hotel matches the price level being planned (OSM has no prices or ratings, so nothing more is claimed);
  - 'stay outside the centre' (a replanner option) picks a hotel 3-8 km away, assumed 25% cheaper;
  - no hotel on the last day;
  - visit lengths, travel times and meal times are assumptions (config.py); a place that would end the
    sightseeing after DAY_END moves to "if you have more time" (the least important first, never a must-visit).
"""

import config
import timeline as T
from scheduler import day_reason, food_wishes
from schemas import CostChoices, DayPlan, Itinerary, Place, Spot
from tools import osm
from tools.calls import ToolLog
from tools.geo import distance_km

def centre(places: list[Place]) -> tuple[float, float] | None:
    if not places:
        return None
    return sum(p.lat for p in places) / len(places), sum(p.lon for p in places) / len(places)

def _spot(o: osm.OsmPlace, near: tuple[float, float]) -> Spot:
    return Spot(name=o.name, kind=o.kind, lat=o.lat, lon=o.lon, stars=o.stars, url=o.url, distance_km=round(distance_km(near[0], near[1], o.lat, o.lon), 1))

def fits_tier(o: osm.OsmPlace, tier: str) -> bool:
    if o.kind not in config.LODGING_FOR_TIER[tier]:
        return False
    if o.kind == "hotel" and o.stars is not None:
        return o.stars >= 4 if tier == "luxury" else o.stars <= 3
    return tier != "luxury"  # a hotel without stars is not assumed to be a luxury hotel

def pick_hotel(spots: list[osm.OsmPlace], near: tuple[float, float], choices: CostChoices,
               keep: Spot | None) -> tuple[Spot | None, bool]:
    """Returns (hotel, matched the price level)."""
    lodging = [o for o in spots if o.kind in osm.LODGING]
    matching = [o for o in lodging if fits_tier(o, choices.hotel_tier)]
    pool, matched = (matching, True) if matching else (lodging, False)
    if not pool:
        return None, False

    def dist(o):
        return distance_km(near[0], near[1], o.lat, o.lon)

    if choices.hotel_outside_centre:
        ring = [o for o in pool if config.OUTSIDE_CENTRE_MIN_KM <= dist(o) <= config.OUTSIDE_CENTRE_MAX_KM]
        pool = ring or pool
    if keep is not None:
        same = next((o for o in pool if o.url == keep.url), None)
        if same and dist(same) <= (config.OUTSIDE_CENTRE_MAX_KM if choices.hotel_outside_centre
                                   else config.HOTEL_KEEP_KM):
            return _spot(same, near), matched  # close enough: no need to move
    return _spot(min(pool, key=dist), near), matched

def _nearest(spots: list[osm.OsmPlace], kinds: set[str], point: tuple[float, float], radius: float,
             used: dict[str, int]) -> tuple[Spot | None, int | None]:
    """The nearest spot of these kinds within the radius, preferring one not suggested on an earlier day.
    Returns (spot, the earlier day it was suggested on, if it had to be repeated)."""
    near = [o for o in spots if o.kind in kinds and distance_km(point[0], point[1], o.lat, o.lon) <= radius]
    if not near:
        return None, None
    fresh = [o for o in near if o.url not in used]
    best = min(fresh or near, key=lambda o: distance_km(point[0], point[1], o.lat, o.lon))
    return _spot(best, point), (None if fresh else used[best.url])

# OSM kinds to try for each meal, best first
BREAKFAST_KINDS = ({"cafe"}, {"restaurant"})
LUNCH_KINDS = ({"restaurant"}, {"food_court", "fast_food", "cafe"})
DINNER_KINDS = ({"restaurant"}, {"food_court", "fast_food"})
STREET_FOOD_KINDS = ({"fast_food", "food_court"},)

def _meal(spots: list[osm.OsmPlace], kinds: tuple[set[str], ...], point: T.Point, radius: float,
          used: dict[str, int], day: int) -> tuple[Spot | None, int | None]:
    """The nearest place to eat, trying the kinds in order; it is marked as used from this day on."""
    for k in kinds:
        spot, again = _nearest(spots, k, point, radius, used)
        if spot:
            used.setdefault(spot.url, day)
            return spot, again
    return None, None

def _kind(s: Spot) -> str:
    return s.kind.replace("_", " ")

def _day_story(day: DayPlan, spots: list[osm.OsmPlace], used: dict[str, int], want_food: bool, osm_ok: bool
               ) -> tuple[int, T.Point | None, int]:
    """Meals, notes and the timeline (without the start and the night) for the day's current places.
    Changes day and used. Returns (when sightseeing ends, where the day ends, when the day ends)."""
    day.day_notes, day.timeline = [], []
    day.breakfast = day.lunch = day.food_stop = day.dinner = None
    if not day.places:
        day.timeline = [T.item(config.DAY_START, config.DAY_END, "free", "Free day", "no more places were found")]
        return config.DAY_START, None, config.DAY_END
    tl, first, last = day.timeline, day.places[0], day.places[-1]
    t, pos = config.DAY_START, None

    # Breakfast near the first place
    day.breakfast, again = _meal(spots, BREAKFAST_KINDS, (first.lat, first.lon), config.BREAKFAST_RADIUS_KM, used, day.day)
    if day.breakfast:
        b = day.breakfast
        tl.append(T.item(t, t + config.BREAKFAST_MINUTES, "breakfast", f"Breakfast at {b.name}",
                         f"{_kind(b)}, {T.km(b.distance_km)}", b.url))
        pos = (b.lat, b.lon)
        if again:
            day.day_notes.append(f"Breakfast is at the same place as on day {again}: no other one was found nearby.")
    else:
        tl.append(T.item(t, t + config.BREAKFAST_MINUTES, "breakfast", "Breakfast near your stay"))
        if osm_ok:
            day.day_notes.append(f"No cafe or restaurant was found within {config.BREAKFAST_RADIUS_KM} km of "
                                 f"{first.name} on OpenStreetMap; have breakfast near your stay before leaving.")
    t += config.BREAKFAST_MINUTES

    def go(to: T.Point, name: str) -> None:
        nonlocal t, pos
        minutes = T.travel_minutes(pos, to)
        title = T.travel_title(pos, to) if pos else f"→ to {name}"
        tl.append(T.item(t, t + minutes, "travel", title))
        t, pos = t + minutes, to

    def lunch_and_rest() -> None:
        nonlocal t
        here = pos or (last.lat, last.lon)
        near = T.short(day.places[0].name)
        for p in day.places:
            if (p.lat, p.lon) == here:
                near = T.short(p.name)
        day.lunch, _ = _meal(spots, LUNCH_KINDS, here, config.MEAL_RADIUS_KM, used, day.day)
        if day.lunch:
            go((day.lunch.lat, day.lunch.lon), day.lunch.name)
            start = max(t, config.LUNCH_EARLIEST)
            tl.append(T.item(start, start + config.LUNCH_MINUTES, "lunch", f"Lunch at {day.lunch.name}",
                             f"{_kind(day.lunch)}, {T.km(day.lunch.distance_km)}", day.lunch.url))
        else:
            start = max(t, config.LUNCH_EARLIEST)
            tl.append(T.item(start, start + config.LUNCH_MINUTES, "lunch", f"Lunch near {near}",
                             "no restaurant found nearby on OpenStreetMap" if osm_ok else ""))
        t = start + config.LUNCH_MINUTES
        tl.append(T.item(t, t + config.REST_MINUTES, "rest", "Rest", "a break in the middle of the day"))
        t += config.REST_MINUTES

    # The places, with lunch and a rest in the middle of the day
    had_lunch, sights_end = False, t
    for p in day.places:
        visit = T.visit_minutes(p)
        arrive = t + T.travel_minutes(pos, (p.lat, p.lon))
        if not had_lunch and t >= config.LUNCH_EARLIEST and (
                t >= config.LUNCH_FROM or arrive + visit > config.LUNCH_BY):
            lunch_and_rest()
            had_lunch = True
        go((p.lat, p.lon), p.name)
        tl.append(T.item(t, t + visit, "visit", T.short(p.name), T.wish_label(p), p.url))
        t += visit
        sights_end = t
    if not had_lunch:
        lunch_and_rest()

    # The evening meal near the last place: the food stop the user asked for, otherwise dinner
    where = (last.lat, last.lon)
    if want_food:
        meal, again = _meal(spots, STREET_FOOD_KINDS, where, config.FOOD_STOP_RADIUS_KM, used, day.day)
        day.food_stop, kind, title = meal, "food", "Street food"
        if meal is None and osm_ok:
            day.day_notes.append(f"No food stall or eatery was found within {config.FOOD_STOP_RADIUS_KM} km of "
                                 f"{last.name} on OpenStreetMap.")
        elif again:
            day.day_notes.append(f"The food stop is the same as on day {again}: no other one was found nearby.")
    else:
        meal, _ = _meal(spots, DINNER_KINDS, where, config.MEAL_RADIUS_KM, used, day.day)
        day.dinner, kind, title = meal, "dinner", "Dinner"
    target = (meal.lat, meal.lon) if meal else None
    ride = T.travel_minutes(pos, target) if target else 0
    start = max(t + ride, config.DINNER_AT)
    if start - ride - t >= config.FREE_TIME_MIN_MINUTES:
        tl.append(T.item(t, start - ride, "free", "Free time", f"rest, or look around {T.short(last.name)}"))
        t = start - ride
    if target:
        go(target, meal.name)
        tl.append(T.item(start, start + config.DINNER_MINUTES, kind, f"{title} at {meal.name}",
                         f"{_kind(meal)}, {T.km(meal.distance_km)}", meal.url))
    else:
        tl.append(T.item(start, start + config.DINNER_MINUTES, kind, f"{title} near your stay"))
    return sights_end, pos, start + config.DINNER_MINUTES

def _least_important(places: list[Place]) -> Place | None:
    """The place to give up when a day is too long: popular sights first, then interests, then kinds of place;
    within a group the least read on Wikipedia. Never a must-visit place."""
    for serves in config.DROP_ORDER:
        group = [p for p in places if p.serves == serves]
        if group:
            return min(reversed(group), key=lambda p: p.pageviews or 0)
    return None

def fit_day(day: DayPlan, spots: list[osm.OsmPlace], used: dict[str, int], want_food: bool, osm_ok: bool
            ) -> tuple[DayPlan, list[Place], T.Point | None, int]:
    """Build the day's story; while sightseeing would end after DAY_END, give up the least important place.
    Returns (the day, places given up, where the day ends, when it ends)."""
    dropped: list[Place] = []
    while True:
        trial, trial_used = day.model_copy(deep=True), dict(used)
        trial.places = [p for p in trial.places if p not in dropped]
        sights_end, pos, end = _day_story(trial, spots, trial_used, want_food, osm_ok)
        drop = _least_important(trial.places) if sights_end > config.DAY_END else None
        if drop is None:
            break
        dropped.append(drop)
    used.clear()
    used.update(trial_used)
    late = [f"{p.name} did not fit in the day (sightseeing would end after {T.clock(config.DAY_END):%H:%M}), so it "
            "is listed under 'If you have more time'." for p in dropped]
    if sights_end > config.DAY_END:
        late.append(f"This is a long day: sightseeing ends around {T.clock(sights_end):%H:%M}.")
    trial.day_notes = late + trial.day_notes
    if dropped:
        trial.reason = day_reason(trial.places, trial.weather)
    return trial, dropped, pos, end

def _pt(x) -> T.Point | None:
    return (x.lat, x.lon) if x is not None else None

def _bookends(day: DayPlan, i: int, days: list[DayPlan], end_of_day: tuple[T.Point | None, int],
              arrival: T.Point | None, city: str) -> None:
    """The start of the day (arrive / leave / check out, bags) and its end (night, or collect the bags).
    The start is worked back from breakfast at DAY_START, so the middle of the day does not move."""
    prev = days[i - 1].stay if i else None
    stay, last_day = day.stay, i == len(days) - 1
    first = _pt(day.breakfast) or (_pt(day.places[0]) if day.places else None)
    moving = stay is not None and (i == 0 or prev is None or prev.url != stay.url)  # bags go to a new hotel today
    steps: list[tuple[int, str, str, str, str | None]] = []  # (minutes, kind, title, detail, url)
    here: T.Point | None = None

    def ride(to: T.Point | None) -> None:
        nonlocal here
        if here and to:
            steps.append((T.travel_minutes(here, to), "travel", T.travel_title(here, to), "", None))
        here = to or here

    if i == 0:
        steps.append((0, "start", f"Arrive in {city}" if city else "Arrive", "", None))
        here = arrival
    elif prev is None:
        steps.append((0, "start", "Start the day", "", None))
    elif last_day:
        steps.append((0, "start", f"Check out of {prev.name}", "leave the bags at the desk", prev.url))
        here = _pt(prev)
    elif moving:
        steps.append((0, "start", f"Check out of {prev.name}", "take the bags along", prev.url))
        here = _pt(prev)
    else:
        steps.append((0, "start", f"Leave {prev.name}", "", prev.url))
        here = _pt(prev)
    if moving:
        ride(_pt(stay))
        steps.append((config.BAG_MINUTES, "bags", f"Drop the bags at {stay.name}", "check-in is later", stay.url))
    ride(first)
    t = config.DAY_START - sum(m for m, *_ in steps)
    head = []
    for minutes, kind, title, detail, url in steps:
        head.append(T.item(t, t + minutes, kind, title, detail, url))
        t += minutes
    day.timeline[:0] = head

    here, t = end_of_day
    tail = []

    def ride_back(to: T.Point) -> None:
        nonlocal here, t
        if here:
            minutes = T.travel_minutes(here, to)
            tail.append(T.item(t, t + minutes, "travel", T.travel_title(here, to)))
            t += minutes
        here = to

    if stay:
        ride_back(_pt(stay))
        verb = "Check in at" if moving else "Night at"
        tail.append(T.item(t, t, "stay", f"{verb} {stay.name}", f"{_kind(stay)}, near tomorrow's places", stay.url))
    elif last_day and prev:
        ride_back(_pt(prev))
        tail.append(T.item(t, t + config.BAG_MINUTES, "bags", f"Collect the bags from {prev.name}", "", prev.url))
        t += config.BAG_MINUTES
        tail.append(T.item(t, t, "end", "End of the trip"))
    elif last_day:
        tail.append(T.item(t, t, "end", "End of the trip"))
    else:
        tail.append(T.item(t, t, "stay", "Night at your stay"))
    day.timeline += tail

def assign(it: Itinerary, spots: list[osm.OsmPlace], choices: CostChoices, want_food: bool, osm_ok: bool = True,
           arrival: T.Point | None = None, city: str = "") -> tuple[Itinerary, list[str]]:
    """Fill meals, stays and the timeline for every day. Pure code over the OSM places already fetched.
    osm_ok=False: OpenStreetMap could not be reached, so the days are timed without naming stays or meals.
    arrival: where the traveller reaches the city (its centre); city: its name, for 'Arrive in ...'."""
    it = it.model_copy(deep=True)
    notes, keep, unmatched = [], None, False
    used: dict[str, int] = {}  # OSM url -> the day it was first suggested on
    ends: list[tuple[T.Point | None, int]] = []
    for i, day in enumerate(it.days):
        it.days[i], dropped, pos, end = fit_day(day, spots, used, want_food, osm_ok)
        it.unused += dropped
        ends.append((pos, end))

    for i, day in enumerate(it.days):
        if i == len(it.days) - 1:
            day.stay = None  # the last day ends the trip
            continue
        target = centre(it.days[i + 1].places) or centre(day.places)
        if target is None:
            day.stay = keep
            continue
        day.stay, matched = pick_hotel(spots, target, choices, keep)
        unmatched |= day.stay is not None and not matched
        if day.stay is None and osm_ok:
            day.day_notes.append("No place to stay was found on OpenStreetMap near tomorrow's places.")
        keep = day.stay

    for i, day in enumerate(it.days):  # the start and the end of each day's story
        _bookends(day, i, it.days, ends[i], arrival, city)

    if unmatched:
        notes.append(f"No {choices.hotel_tier}-level stay was found on OpenStreetMap near the plan, so the nearest "
                     "available one is shown; its price is still assumed at the planned level.")
    if osm_ok and len(it.days) > 1 and all(d.stay is None for d in it.days[:-1]):
        notes.append("No places to stay were found on OpenStreetMap near the plan.")
    return it, notes

def arrival_of(state: dict) -> tuple[T.Point | None, str]:
    """The city centre and name, where day 1 starts."""
    d = state.get("destination")
    if d is None or d.location is None:
        return None, ""
    return (d.location.lat, d.location.lon), d.base_city or d.location.name

def stays_node(state: dict) -> dict:
    r, it = state["request"], state["itinerary"]
    arrival, city = arrival_of(state)
    log = ToolLog("find_stays_and_food")
    days_with_places = [d for d in it.days if d.places]
    centres = [centre(d.places) for d in days_with_places]
    points = [(p.lat, p.lon) for d in days_with_places for p in d.places]
    wishes = food_wishes(r)
    if not centres:
        it, _ = assign(it, [], CostChoices(hotel_tier=config.DEFAULT_STYLE, food_tier=config.DEFAULT_STYLE),
                       bool(wishes), osm_ok=False,
                       arrival=arrival, city=city)
        return {"osm_spots": [], "osm_ok": False, "itinerary": it, "trace": log.trace}
    found, ok = log.call("osm", osm.fetch, centres, points, on_fail="planned without stays and meals")
    spots, server = found if ok else ([], None)
    choices = state.get("cost_choices") or CostChoices(hotel_tier=r.budget_style or config.DEFAULT_STYLE,
                                                       food_tier=r.budget_style or config.DEFAULT_STYLE)
    notes = []
    if not ok:
        notes.append("Places to stay and eat could not be fetched from OpenStreetMap, so the plan names none; "
                     "costs still include the assumed hotel and food prices.")
        it, _ = assign(it, [], choices, bool(wishes), osm_ok=False,
                       arrival=arrival, city=city)  # the days are still timed
        return {"osm_spots": [], "osm_ok": False, "itinerary": it, "trace": log.trace, "errors": log.errors,
                "notes": notes}
    it, notes = assign(it, spots, choices, bool(wishes), arrival=arrival, city=city)
    if wishes:
        stops = [d.food_stop for d in it.days if d.food_stop]
        missed = [m.wish for m in state.get("misses", []) if m.wish in wishes]
        for wish in sorted(wishes):
            if stops and wish in missed:
                notes.append(f"Wikipedia had no places for '{wish}', so food spots from OpenStreetMap were added "
                             "to the days instead.")
            elif not stops and wish in missed:
                notes.append(f"No places for '{wish}' were found near {state['destination'].base_city} on "
                             "Wikipedia or OpenStreetMap; that time is filled with popular sights.")
    log.trace[-1].detail["found"] = {k: sum(o.kind == k for o in spots) for k in sorted(osm.LODGING | osm.FOOD)}
    log.trace[-1].detail["server"] = server
    return {"osm_spots": spots, "osm_ok": True, "itinerary": it, "trace": log.trace, "notes": notes}
