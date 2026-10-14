"""Node 5 (build_itinerary): turn the places found into days. Pure code, no LLM.

Rules agreed for the project:
  1. choose in priority order: every must-visit place, then the best place of each kind of place,
     then of each purpose, then the rest of those, then the best-known sights;
  2. group nearby places on the same day (less travelling);
  3. give rainy days the group with the most indoor places;
  4. every wish that could not be met becomes an honest note.
"""

import datetime as dt
import config
from schemas import DayPlan, DayWeather, Itinerary, Miss, Place, TripRequest
from tools.geo import distance_km

WISH_LABEL = {"must_visit": "must visit", "place_type": "you wanted {wish}", "interest": "for your interest in {wish}",
              "popular": "popular sight"}

def _dist(a: Place, b: Place) -> float:
    return distance_km(a.lat, a.lon, b.lat, b.lon)

def select_places(places: list[Place], capacity: int) -> tuple[list[Place], list[Place], list[str]]:
    """Choose what fits, most important first. Returns (selected, unused, notes)."""
    notes = []
    must = [p for p in places if p.serves == "must_visit"]
    if len(must) > capacity:
        left = must[capacity:]
        notes.append(f"Not all must-visit places fit in the trip ({capacity} places in total); "
                     f"left out: {', '.join(p.name for p in left)}.")
        selected = must[:capacity]
        return selected, [p for p in places if p not in selected], notes

    selected = list(must)
    groups: dict[tuple[str, str], list[Place]] = {}
    for p in places:
        if p.serves in ("place_type", "interest"):
            groups.setdefault((p.serves, p.wish), []).append(p)
    ordered_keys = sorted(groups, key=lambda k: 0 if k[0] == "place_type" else 1)
    for key in ordered_keys:  # at least one place for every wish that found something
        if len(selected) < capacity:
            selected.append(groups[key][0])
    rest = []  # the other matches of each wish, taken in turns, then the best-known sights
    depth = max((len(g) for g in groups.values()), default=0)
    for i in range(1, depth):
        rest += [groups[k][i] for k in ordered_keys if i < len(groups[k])]
    rest += [p for p in places if p.serves == "popular"]
    for p in rest:
        if len(selected) >= capacity:
            break
        selected.append(p)
    return selected, [p for p in places if p not in selected], notes

def day_sizes(count: int, days: int) -> list[int]:
    """Spread places evenly: 7 places over 3 days -> [3, 2, 2]."""
    base, extra = divmod(count, days)
    return [base + (1 if i < extra else 0) for i in range(days)]

def group_by_distance(selected: list[Place], days: int) -> list[list[Place]]:
    """Each day starts from the most important place left and adds its nearest neighbours,
    visiting them in a short chain (nearest next)."""
    remaining = list(selected)
    groups = []
    for size in day_sizes(len(selected), days):
        if not remaining or size == 0:
            groups.append([])
            continue
        group = [remaining.pop(0)]
        while len(group) < size and remaining:
            nearest = min(remaining, key=lambda p: _dist(group[-1], p))
            remaining.remove(nearest)
            group.append(nearest)
        groups.append(group)
    return groups

def assign_days(groups: list[list[Place]], weather_by_date: dict[dt.date, DayWeather],
                dates: list[dt.date]) -> list[list[Place]]:
    """Rainy dates get the groups with the most indoor places; dry dates keep the priority order."""
    rainy = [d for d in dates if (w := weather_by_date.get(d)) and w.rain_probability >= config.RAINY_DAY_PROBABILITY]
    if not rainy:
        return groups
    by_indoor = sorted(range(len(groups)), key=lambda i: -sum(p.indoor for p in groups[i]))
    rainy_sorted = sorted(rainy, key=lambda d: -weather_by_date[d].rain_probability)
    chosen = dict(zip(rainy_sorted, by_indoor, strict=False))  # date -> group index (more groups than rainy days)
    left = [i for i in range(len(groups)) if i not in chosen.values()]
    return [groups[chosen[d]] if d in chosen else groups[left.pop(0)] for d in dates]

def day_reason(places: list[Place], weather: DayWeather | None) -> str:
    if not places:
        return "Free day: no more places were found."
    parts = [f"{p.name} ({WISH_LABEL[p.serves].format(wish=p.wish)})" for p in places]
    reason = "; ".join(parts)
    if len(places) > 1:
        spread = max(_dist(a, b) for a in places for b in places)
        reason += f". All within {spread:.1f} km of each other"
    if weather:
        w = weather
        reason += f". {w.summary}, {w.temp_min_c:.0f}-{w.temp_max_c:.0f} C, rain {w.rain_probability}%"
    return reason + "."

def miss_note(m: Miss, city: str) -> str:
    """The wording agreed for each kind of unmet wish: say what our data showed, not more."""
    if m.reason == "the place search failed":
        return f"The search for {m.wish} failed, so it is not in the plan."
    if m.serves == "must_visit":
        if "km from" in m.reason:
            if m.near_city:
                return (f"{m.wish} is not in this plan because {m.reason}. It is in {m.near_city}; to see it, "
                        f"you can plan a separate trip to {m.near_city}.")
            return f"{m.wish} is not in this plan because {m.reason}. To see it, plan a separate trip closer to it."
        return f"Could not find {m.wish} on Wikipedia, so it could not be planned."
    if m.serves == "popular":
        return f"No well-known sights were found near {city} on Wikipedia."
    return f"No places for '{m.wish}' were found near {city} on Wikipedia; that time is filled with popular sights."

def food_wishes(r: TripRequest) -> set[str]:
    """The user's food wishes: kinds of place about food ('street food') and the purpose 'food'."""
    wishes = {pt.words for pt in r.place_types if "food" in pt.interests}
    if "food" in r.interests and not wishes:
        wishes.add("food")
    return wishes

def build_itinerary(request: TripRequest, places: list[Place], weather: list[DayWeather] | None,
                    misses: list[Miss], city: str) -> Itinerary:
    days = request.days
    dates = [request.start_date + dt.timedelta(days=i) for i in range(days)]
    weather_by_date = {w.date: w for w in weather or []}
    selected, unused, notes = select_places(places, days * config.PLACES_PER_DAY)
    groups = assign_days(group_by_distance(selected, days), weather_by_date, dates)

    plans = []
    for i, (date, group) in enumerate(zip(dates, groups, strict=True), start=1):
        w = weather_by_date.get(date)
        plans.append(DayPlan(day=i, date=date, weather=w, places=group, reason=day_reason(group, w)))
        outdoor = [p.name for p in group if not p.indoor]
        if w and w.rain_probability >= config.RAINY_DAY_PROBABILITY and outdoor:
            notes.append(f"Day {i} may be rainy ({w.rain_probability}%); {', '.join(outdoor)} "
                         f"{'is' if len(outdoor) == 1 else 'are'} outdoors, so keep an eye on the weather.")
    food = food_wishes(request)  # reported later by find_stays_and_food, which may still find food spots
    notes += [miss_note(m, city) for m in misses if m.wish not in food]
    if not places:
        notes.append("No places could be found for this trip, so the days are left free.")
    return Itinerary(days=plans, unused=unused, notes=notes)

def itinerary_node(state: dict) -> dict:
    city = state["destination"].base_city if state.get("destination") else state["request"].destination
    itinerary = build_itinerary(state["request"], state.get("places", []), state.get("weather"),
                                state.get("misses", []), city)
    return {"itinerary": itinerary, "notes": itinerary.notes}

