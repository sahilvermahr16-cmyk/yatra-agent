"""The day as a timed story: visit lengths, travel, lunch and rest, the evening meal, places that do not fit."""
import datetime as dt
import os
from itertools import pairwise

import config
import stays
import timeline as T
from schemas import CostChoices, DayPlan, Itinerary, Place
from tools.osm import OsmPlace

START = dt.date(2026, 10, 24)
MID = CostChoices(hotel_tier="mid", food_tier="mid")


def place(name, lat, lon=73.02, description=None, serves="popular", views=1000):
    return Place(name=name, lat=lat, lon=lon, distance_km=1, description=description, serves=serves, wish="w",
                 category="history", indoor=False, pageviews=views)


def spot(name, kind, lat, lon=73.02):
    return OsmPlace(name=name, kind=kind, lat=lat, lon=lon, url=f"https://osm/{name}")


def trip(*day_places):
    return Itinerary(days=[DayPlan(day=i + 1, date=START + dt.timedelta(days=i), places=list(ps), reason="r")
                           for i, ps in enumerate(day_places)])


def minutes(t: dt.time) -> int:
    return T.minutes_of(t)


FORT = place("Mehrangarh Fort", 26.2978, description="fort in Jodhpur", serves="must_visit")
THADA = place("Jaswant Thada", 26.3005, description="cenotaph in Jodhpur")
WELL = place("Toorji Ka Jhalra", 26.2945, description="stepwell in Jodhpur")
SPOTS = [spot("Cafe Fort", "cafe", 26.2985), spot("Thali House", "restaurant", 26.2990),
         spot("Night Dhaba", "fast_food", 26.2946), spot("Supper Club", "restaurant", 26.2950),
         spot("Hotel Blue", "hotel", 26.2960)]


def test_visit_length_comes_from_the_name_first_then_the_description():
    assert T.visit_minutes(FORT) == 150
    assert T.visit_minutes(THADA) == 45  # the name says nothing; the description says cenotaph
    assert T.visit_minutes(place("Chamunda Temple", 26.3, description="temple in a fort complex")) == 60
    assert T.visit_minutes(place("Mandore Gardens", 26.3)) == 60  # plural still matches
    assert T.visit_minutes(place("Somewhere", 26.3)) == config.DEFAULT_VISIT_MINUTES


def test_short_hops_are_walked_and_longer_ones_go_by_road():
    a = (26.300, 73.02)
    assert T.travel_minutes(a, (26.302, 73.02)) == 5  # about 0.3 km on foot
    assert T.travel_title(a, (26.302, 73.02)).startswith("→ walk")
    far = T.travel_minutes(a, (26.390, 73.02))  # 10 km straight, 13 km by road at 20 km/h, plus the buffer
    assert far == 50 and T.travel_title(a, (26.390, 73.02)) == "→ by road 13.0 km"


def test_a_day_reads_as_a_story_with_lunch_and_a_rest_in_the_middle():
    it, _ = stays.assign(trip([FORT, THADA, WELL], [place("Umaid Bhawan Palace", 26.2810)]), SPOTS, MID,
                         want_food=False)
    day = it.days[0]
    kinds = [i.kind for i in day.timeline]
    assert kinds[:4] == ["start", "bags", "travel", "breakfast"]  # arrive, drop the bags, go to breakfast
    assert kinds[-3:] == ["dinner", "travel", "stay"]  # dinner, back to the hotel, check in
    assert kinds.index("rest") == kinds.index("lunch") + 1  # the rest follows lunch
    assert kinds.count("visit") == 3
    lunch = day.timeline[kinds.index("lunch")]
    rest = day.timeline[kinds.index("rest")]
    assert config.LUNCH_EARLIEST <= minutes(lunch.start) <= config.LUNCH_BY
    assert minutes(rest.end) - minutes(rest.start) == config.REST_MINUTES
    assert day.lunch.name == "Thali House" and day.dinner.name == "Supper Club"
    for before, after in pairwise(day.timeline):
        assert minutes(after.start) >= minutes(before.end)  # nothing overlaps
    fort = next(i for i in day.timeline if i.title == "Mehrangarh Fort")
    assert T.takes(fort) == "2 h 30 min" and fort.detail == "must visit"
    breakfast = day.timeline[kinds.index("breakfast")]
    assert minutes(breakfast.start) == config.DAY_START  # the morning is worked back from breakfast


def test_the_trip_starts_on_arrival_with_the_bags_left_at_the_hotel():
    it, _ = stays.assign(trip([FORT], [THADA], [WELL]), SPOTS, MID, want_food=False, arrival=(26.24, 73.02),
                         city="Jodhpur")
    first, middle, last = (d.timeline for d in it.days)
    assert first[0].title == "Arrive in Jodhpur" and first[1].kind == "travel"
    assert first[2].title == "Drop the bags at Hotel Blue" and first[-1].title == "Check in at Hotel Blue"
    assert middle[0].title == "Leave Hotel Blue" and middle[-1].title == "Night at Hotel Blue"
    assert last[0].title == "Check out of Hotel Blue" and "leave the bags" in last[0].detail
    assert last[-2].title == "Collect the bags from Hotel Blue" and last[-1].kind == "end"
    assert minutes(first[0].start) < minutes(middle[0].start) < config.DAY_START


def test_a_new_hotel_means_check_out_drop_the_bags_and_check_in_again():
    north1, north2 = place("North One", 26.400), place("North Two", 26.500)
    spots = SPOTS + [spot("Hotel N1", "hotel", 26.401), spot("Hotel N2", "hotel", 26.501)]
    it, _ = stays.assign(trip([FORT], [north1], [north2]), spots, MID, want_food=False)
    day2 = it.days[1].timeline
    assert day2[0].title == "Check out of Hotel N1" and "take the bags" in day2[0].detail
    assert any(i.title == "Drop the bags at Hotel N2" for i in day2) and day2[-1].title == "Check in at Hotel N2"


def test_a_food_wish_turns_the_evening_meal_into_a_food_stop():
    it, _ = stays.assign(trip([FORT, WELL]), SPOTS, MID, want_food=True)
    day = it.days[0]
    assert day.food_stop.name == "Night Dhaba" and day.dinner is None
    meal = next(i for i in day.timeline if i.kind == "food")
    assert minutes(meal.start) == config.DINNER_AT


def test_a_place_that_does_not_fit_moves_to_more_time_least_important_first():
    far = [place(f"Fort {i}", 26.30 + 0.09 * i, description="fort", views=1000 * i) for i in range(1, 5)]
    it, _ = stays.assign(trip([FORT, *far]), SPOTS, MID, want_food=False)
    day = it.days[0]
    assert FORT in day.places  # a must-visit place is never given up
    assert [p.name for p in it.unused][0] == "Fort 1"  # the least read popular sight goes first
    assert "did not fit in the day" in day.day_notes[0] and day.reason != "r"
    last_visit = [i for i in day.timeline if i.kind == "visit"][-1]
    assert minutes(last_visit.end) <= config.DAY_END


def test_must_visit_places_are_kept_even_when_the_day_runs_long():
    forts = [place(f"Fort {i}", 26.30 + 0.09 * i, description="fort", serves="must_visit") for i in range(4)]
    it, _ = stays.assign(trip(forts), SPOTS, MID, want_food=False)
    assert len(it.days[0].places) == 4 and not it.unused
    assert any("long day" in n for n in it.days[0].day_notes)


def test_without_openstreetmap_the_days_are_still_timed_without_naming_meals():
    it, notes = stays.assign(trip([FORT, THADA], [WELL]), [], MID, want_food=True, osm_ok=False)
    day = it.days[0]
    assert day.breakfast is None and day.day_notes == [] and notes == []
    titles = [i.title for i in day.timeline]
    assert "Breakfast near your stay" in titles and "Rest" in titles and "Mehrangarh Fort" in titles


def test_a_free_day_is_shown_as_free():
    it, _ = stays.assign(trip([FORT], []), SPOTS, MID, want_food=False)
    assert [i.kind for i in it.days[1].timeline] == ["start", "free", "bags", "end"]


def test_the_timeline_becomes_a_markdown_table_with_links():
    os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")  # the reporter imports the replanner's LLM
    from reporter import _timeline_md

    it, _ = stays.assign(trip([FORT]), SPOTS, MID, want_food=False)
    md = "\n".join(_timeline_md(it.days[0].timeline))
    assert md.startswith("| Time | Plan | Takes |") and "[Breakfast at Cafe Fort](https://osm/Cafe Fort) (cafe" in md
    assert "| Rest (a break in the middle of the day) | 1 h |" in md and "| **Mehrangarh Fort** (must visit) |" in md


def test_when_openstreetmap_fails_the_node_still_returns_timed_days(monkeypatch):
    from schemas import TripRequest
    from tools.http import ToolError

    def fail(*args):
        raise ToolError("osm", "timeout", "injected", 3)

    monkeypatch.setattr(stays.osm, "fetch", fail)
    state = {"request": TripRequest(destination="Jodhpur"), "itinerary": trip([FORT, THADA], [WELL])}
    out = stays.stays_node(state)
    assert out["osm_ok"] is False and out["errors"][0].handled_by == "planned without stays and meals"
    assert all(d.timeline for d in out["itinerary"].days)


def test_display_names_and_short_distances_read_cleanly():
    assert T.short("Ghanta Ghar (Jodhpur)") == "Ghanta Ghar"
    assert T.short("Jagdish Temple, Udaipur") == "Jagdish Temple, Udaipur"
    assert T.km(0.02) == "<0.1 km" and T.km(0.64) == "0.6 km"
    assert T.travel_title((26.3, 73.02), (26.3001, 73.02)) == "→ walk <0.1 km"
