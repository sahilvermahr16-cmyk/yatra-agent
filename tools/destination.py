"""Resolve the destination: the city itself, or one base city of a state or region, with coordinates.
No LLM: Wikivoyage, Wikimedia pageviews and Open-Meteo geocoding decide; a built-in table covers outages.

Usage for a manual check: python -m tools.destination Jaipur Rajasthan Coorg
"""
import datetime as dt
import sys

import config
from schemas import DestinationResult, Location
from tools import wikivoyage
from tools.calls import ToolLog
from tools.geo import distance_km
from tools.geocode import geocode, prefer_near


def state_key(name: str) -> str:
    """Lower case, single spaces, common other names mapped: 'Orissa' -> 'odisha'."""
    key = " ".join(name.lower().split())
    return config.STATE_ALIASES.get(key, key)


def _same_state(a: str, b: str) -> bool:
    """Geocoding may shorten a name ('Andaman and Nicobar' for '... Islands'), so allow containment."""
    a, b = a.lower(), b.lower()
    return a in b or b in a


def resolve_destination(query: str, today: dt.date, log: ToolLog) -> DestinationResult:
    key = state_key(query)
    is_state = key in config.INDIAN_STATES_AND_UTS and key not in config.CITY_LIKE_UTS
    lookup = key if key != " ".join(query.lower().split()) else query  # an alias is looked up by its real name
    page, reached = log.call("wikivoyage", wikivoyage.fetch_page, lookup,
                             on_fail="decided city or state from the built-in list of Indian states")
    if key in config.CITY_LIKE_UTS:
        dtype = "city"
    elif reached and page and page.cities:
        dtype = "state" if is_state or state_key(page.title) in config.INDIAN_STATES_AND_UTS else "region"
    else:
        dtype = "state" if is_state else "city"  # no page, no Cities section, or Wikivoyage unreachable
    result = DestinationResult(query=query.strip(), destination_type=dtype,
                               wikivoyage_title=page.title if page else None,
                               candidates=page.cities if (page and dtype != "city") else [])
    if dtype == "city":
        return _locate_city(result, page, log)
    return _choose_base_city(result, key, today, log)


def _locate_city(result: DestinationResult, page, log: ToolLog) -> DestinationResult:
    """Geocode the user's name, then the travel guide's title ('Mysore' -> 'Mysuru'); the first town with exactly
    that name wins. If none has it, the guide's own coordinates decide: near an Indian match -> use them;
    far from every Indian match -> the place is outside India."""
    names = list(dict.fromkeys(n for n in (result.query, page.title if page else None) if n))  # 'Bombay' -> 'Mumbai'
    others = []
    for name in names:
        geo, ok = log.call("geocode", geocode, name, on_fail="no coordinates, so the trip cannot be planned")
        if not ok:
            return result
        if geo.chosen and page and page.lat is not None:
            geo = prefer_near(geo, page.lat, page.lon)  # the place the travel guide means
        if geo.chosen:
            c = geo.chosen
            result.location, result.base_city = c, c.name
            result.choice_reason = f"{c.name} was named by the user."
            if geo.ambiguous:
                log.notes.append(f"Several places in India are called {name}; the plan uses {c.name}, {c.region}.")
            return result
        others += geo.other_matches
    if page and page.lat is not None and page.lon is not None:
        near = [o for o in others if distance_km(page.lat, page.lon, o.lat, o.lon) <= config.GEOCODE_TRUST_KM]
        if near:
            result.location = Location(name=page.title, lat=page.lat, lon=page.lon, region=near[0].region,
                                       source="Wikivoyage marker")
            result.base_city, result.choice_reason = page.title, f"{page.title} was named by the user."
            log.notes.append(f"Coordinates of {page.title} were taken from Wikivoyage.")
            return result
        log.notes.append(f"'{result.query}' does not seem to be in India: the travel guide places it far from any "
                         "place in India with a similar name. This planner covers trips in India; please name an "
                         "Indian city.")
        return result
    log.notes.append(f"Could not find '{result.query}' in India. Please check the spelling or name a city.")
    return result


def _choose_base_city(result: DestinationResult, key: str, today: dt.date, log: ToolLog) -> DestinationResult:
    dtype, query = result.destination_type, result.query
    start, end, months = wikivoyage.popularity_window(today)
    candidates = result.candidates[:config.POPULARITY_MAX_CANDIDATES]
    for c in candidates:
        views, ok = log.call("pageviews", wikivoyage.pageviews, c.name, start, end,
                             on_fail=f"popularity of {c.name} counted as unknown")
        c.pageviews = views if ok else None
    counted = [c for c in candidates if c.pageviews is not None]

    if counted:
        best = max(counted, key=lambda c: c.pageviews)  # max keeps the first of equals: Wikivoyage order
        result.base_city = best.name
        result.choice_reason = (f"{query} is a {dtype}, so the trip is based in {best.name}, the most viewed of its "
                                f"{len(candidates)} listed cities on Wikivoyage in the last {months} months "
                                f"({best.pageviews:,} views).")
    elif key in config.STATE_BASE_CITY_FALLBACK:
        why = ("popularity data could not be fetched" if candidates
               else "no list of its cities could be read from Wikivoyage")
        result.base_city, result.used_fallback = config.STATE_BASE_CITY_FALLBACK[key], True
        result.choice_reason = (f"{query} is a {dtype}, so the trip is based in {result.base_city} from the built-in "
                                f"list, because {why}.")
    elif candidates:
        result.base_city, result.used_fallback = candidates[0].name, True
        result.choice_reason = (f"{query} is a {dtype}, so the trip is based in {result.base_city}, the first city "
                                "Wikivoyage lists for it, because popularity data could not be fetched.")
    else:
        log.notes.append(f"Could not choose a city in {query}. Please name the city you want to visit.")
        return result
    log.notes.append(result.choice_reason)
    result.location = _base_city_location(result, key, log)
    return result


def _base_city_location(result: DestinationResult, key: str, log: ToolLog) -> Location | None:
    """Geocode the base city; for a state, only a match inside that state counts. Else the Wikivoyage marker."""
    base = result.base_city
    geo, ok = log.call("geocode", geocode, base, on_fail="used the coordinates from Wikivoyage")
    marker = next((c for c in result.candidates if c.name == base and c.lat is not None and c.lon is not None), None)
    if ok and geo.chosen:
        if marker:
            geo = prefer_near(geo, marker.lat, marker.lon)
        options = [geo.chosen] + geo.alternatives
        if result.destination_type == "state":
            options = [o for o in options if o.region and _same_state(o.region, key)]
        if options:
            return options[0]
    if marker:
        log.notes.append(f"Coordinates of {base} were taken from Wikivoyage.")
        region = result.wikivoyage_title if result.destination_type == "state" else None
        return Location(name=base, lat=marker.lat, lon=marker.lon, region=region, source="Wikivoyage marker")
    log.notes.append(f"Could not find {base} on the map. Please name the city you want to visit.")
    return None


if __name__ == "__main__":
    for q in sys.argv[1:] or ["Rajasthan"]:
        log = ToolLog("resolve_destination")
        r = resolve_destination(q, dt.date.today(), log)
        print(f"\n=== {q!r} -> {r.destination_type} | page: {r.wikivoyage_title} | base city: {r.base_city}"
              f"{' (fallback)' if r.used_fallback else ''}")
        if r.location:
            loc = r.location
            print(f"    location: {loc.name}, {loc.region} ({loc.lat:.4f}, {loc.lon:.4f}) from {loc.source}")
        else:
            print("    location: none -> needs_city")
        print(f"    cities parsed: {len(r.candidates)}")
        if r.candidates:
            ranked = sorted(r.candidates, key=lambda c: -(c.pageviews or -1))
            print("    candidates: " + ", ".join(f"{c.name} ({c.pageviews if c.pageviews is not None else '?'})"
                                                for c in ranked))
        for note in log.notes:
            print(f"    note: {note}")
        for err in log.errors:
            print(f"    error: {err.where} {err.error_type}: {err.message} -> {err.handled_by}")
        print(f"    tool calls: {len(log.trace)}, attempts: "
              f"{sum(e.detail.get('attempts', 0) for e in log.trace)}")
