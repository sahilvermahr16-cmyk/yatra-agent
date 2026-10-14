"""Timing helpers for the story of each day. Pure code; every number comes from config.py and is an assumption:
there is no free API for how long a visit takes or how long a ride across an Indian city takes."""

import datetime as dt
import math
import re
import config
from schemas import Place, TimelineItem
from tools.geo import distance_km

Point = tuple[float, float]

def clock(minutes: int) -> dt.time:
    minutes = max(0, min(int(minutes), 24 * 60 - 1))
    return dt.time(minutes // 60, minutes % 60)

def minutes_of(t: dt.time) -> int:
    return t.hour * 60 + t.minute

def duration(minutes: int) -> str:
    """135 -> '2 h 15 min'."""
    h, m = divmod(int(minutes), 60)
    return " ".join(part for part in (f"{h} h" if h else "", f"{m} min" if m else "") if part) or "0 min"

def visit_minutes(p: Place) -> int:
    """Time inside a place, by the kind of place: the name decides first ('Jaswant Thada' says nothing, so its
    description 'cenotaph in Jodhpur' decides), so a temple described as 'in a fort complex' is still a temple."""
    for text in (p.name, p.description or ""):
        low = text.lower()
        for words, minutes in config.VISIT_MINUTES:
            if any(re.search(rf"\b{re.escape(w)}s?\b", low) for w in words):
                return minutes
    return config.DEFAULT_VISIT_MINUTES

def road_km(a: Point, b: Point) -> float:
    return distance_km(a[0], a[1], b[0], b[1]) * config.ROAD_FACTOR

def walks(a: Point | None, b: Point) -> bool:
    return a is not None and road_km(a, b) <= config.WALK_MAX_KM

def travel_minutes(a: Point | None, b: Point) -> int:
    """A short hop is walked; otherwise road distance at city speed plus a buffer for finding a ride.
    Rounded up to 5 minutes. From an unknown point: the buffer only."""
    if walks(a, b):
        raw = road_km(a, b) / config.WALK_SPEED_KMPH * 60
    else:
        km = road_km(a, b) if a else 0.0
        raw = km / config.CITY_SPEED_KMPH * 60 + config.TRAVEL_BUFFER_MINUTES
    return max(5, int(math.ceil(raw / 5) * 5))

def km(distance: float) -> str:
    """'0.6 km'; a few metres read '<0.1 km', not '0.0 km'."""
    return "<0.1 km" if distance < 0.05 else f"{distance:.1f} km"

def short(name: str) -> str:
    """A Wikipedia title without its bracketed disambiguation: 'Ghanta Ghar (Jodhpur)' -> 'Ghanta Ghar'."""
    return re.sub(r"\s*\([^)]*\)$", "", name) or name

def travel_title(a: Point, b: Point) -> str:
    """'-> walk 0.6 km' / '-> by road 9.9 km'."""
    return f"→ {'walk' if walks(a, b) else 'by road'} {km(road_km(a, b))}"

def wish_label(p: Place) -> str:
    return {"must_visit": "must visit", "popular": "popular sight"}.get(p.serves, f"for: {p.wish}")

def item(start: int, end: int, kind: str, title: str, detail: str = "", url: str | None = None) -> TimelineItem:
    return TimelineItem(start=clock(start), end=clock(end), kind=kind, title=title, detail=detail, url=url)

def text(i: TimelineItem) -> str:
    """'Breakfast at Cafe Mehran (cafe, 0.1 km)'."""
    return f"{i.title} ({i.detail})" if i.detail else i.title

def takes(i: TimelineItem) -> str:
    """How long the item takes: '2 h 30 min', '~10 min' for travel, nothing for a moment."""
    m = minutes_of(i.end) - minutes_of(i.start)
    if m <= 0:
        return ""
    return f"~{duration(m)}" if i.kind == "travel" else duration(m)

def assumptions() -> list[str]:
    """The timing assumptions, for the report."""
    visits = "; ".join(f"{', '.join(words[:3])} {duration(m)}" for words, m in config.VISIT_MINUTES)
    return [f"The traveller reaches the city early on day 1, goes to the first night's hotel and leaves the bags at "
            f"the desk ({config.BAG_MINUTES} min; check-in is later), and is at breakfast by "
            f"{clock(config.DAY_START):%H:%M}. On the last day the bags stay at the hotel desk after check-out and are "
            "collected in the evening. Arrival and departure travel to the city are not planned.",
            f"Each day runs from {clock(config.DAY_START):%H:%M} (breakfast, {config.BREAKFAST_MINUTES} min); "
            f"sightseeing ends by {clock(config.DAY_END):%H:%M}, and a place that would end later moves to 'If you "
            f"have more time'. Lunch ({config.LUNCH_MINUTES} min) comes between {clock(config.LUNCH_EARLIEST):%H:%M} "
            f"and {clock(config.LUNCH_BY):%H:%M}, followed by {duration(config.REST_MINUTES)} of rest; the evening "
            f"meal is at {clock(config.DINNER_AT):%H:%M}.",
            f"Visit lengths are assumed by kind of place ({visits}; "
            f"other places {duration(config.DEFAULT_VISIT_MINUTES)}). "
            f"Travel: up to {config.WALK_MAX_KM:g} km is walked at {config.WALK_SPEED_KMPH:g} km/h; longer trips go by "
            f"road at {config.CITY_SPEED_KMPH} km/h plus {config.TRAVEL_BUFFER_MINUTES} min to find a ride, with roads "
            f"{config.ROAD_FACTOR:g}x the straight-line distance."]

