"""Scheduler: choosing in priority order, grouping nearby places, rainy days, honest notes. Pure code."""
import datetime as dt

import scheduler as sc
from schemas import DayWeather, Miss, Place, TripRequest

START = dt.date(2026, 10, 24)


def place(name, serves="popular", wish="best-known sights", lat=26.30, lon=73.02, indoor=False):
    return Place(name=name, lat=lat, lon=lon, distance_km=1, serves=serves, wish=wish, category="popular",
                 indoor=indoor)


def request(days=2):
    return TripRequest(destination="Jodhpur", start_date=START, end_date=START + dt.timedelta(days=days - 1),
                       days=days)


def test_every_wish_gets_a_place_before_extra_matches():
    places = [place("Fort", "must_visit", "Mehrangarh Fort"),
              place("Stepwell A", "place_type", "stepwells"), place("Stepwell B", "place_type", "stepwells"),
              place("Market", "interest", "food"),
              place("Lake", "popular"), place("Garden", "popular")]
    selected, unused, _ = sc.select_places(places, capacity=4)
    assert [p.name for p in selected] == ["Fort", "Stepwell A", "Market", "Stepwell B"]
    assert [p.name for p in unused] == ["Lake", "Garden"]


def test_popular_fills_the_rest():
    selected, _, _ = sc.select_places([place("Fort", "must_visit", "X"), place("Lake"), place("Garden")], capacity=6)
    assert [p.name for p in selected] == ["Fort", "Lake", "Garden"]


def test_too_many_must_visits_are_cut_with_a_note():
    places = [place(f"M{i}", "must_visit", f"M{i}") for i in range(5)] + [place("Lake")]
    selected, unused, notes = sc.select_places(places, capacity=3)
    assert [p.name for p in selected] == ["M0", "M1", "M2"] and "left out: M3, M4" in notes[0]
    assert {p.name for p in unused} == {"M3", "M4", "Lake"}


def test_day_sizes_are_even():
    assert sc.day_sizes(7, 3) == [3, 2, 2] and sc.day_sizes(2, 3) == [1, 1, 0]


def test_nearby_places_share_a_day():
    north = [place("N1", lat=26.40), place("N2", lat=26.41), place("N3", lat=26.42)]
    south = [place("S1", lat=26.10), place("S2", lat=26.11), place("S3", lat=26.12)]
    selected = [north[0], south[0], north[1], south[1], north[2], south[2]]  # interleaved by priority
    groups = sc.group_by_distance(selected, days=2)
    assert {p.name[0] for p in groups[0]} == {"N"} and {p.name[0] for p in groups[1]} == {"S"}


def test_rainy_day_gets_the_indoor_group():
    outdoor = [place("Lake"), place("Garden")]
    indoor = [place("Museum", indoor=True), place("Temple", indoor=True)]
    dates = [START, START + dt.timedelta(days=1)]
    weather = {dates[0]: DayWeather(date=dates[0], temp_max_c=30, temp_min_c=20, rain_probability=80, summary="Rain")}
    assert sc.assign_days([outdoor, indoor], weather, dates) == [indoor, outdoor]
    assert sc.assign_days([outdoor, indoor], {}, dates) == [outdoor, indoor]  # no rain: priority order kept


def test_itinerary_has_one_plan_per_day_with_reasons():
    places = [place("Fort", "must_visit", "Mehrangarh Fort"), place("Stepwell", "place_type", "stepwells"),
              place("Lake", lat=26.0)]
    it = sc.build_itinerary(request(days=2), places, None, [], "Jodhpur")
    assert [d.date for d in it.days] == [START, START + dt.timedelta(days=1)]
    assert "Fort (must visit)" in it.days[0].reason and "you wanted stepwells" in it.days[0].reason


def test_misses_become_the_agreed_notes():
    misses = [Miss(serves="must_visit", wish="Mehrangarh Fort", reason="it is 284 km from Jaipur", near_city="Jodhpur"),
              Miss(serves="must_visit", wish="Lone Temple", reason="it is 90 km from Jaipur"),
              Miss(serves="place_type", wish="street food", reason="no matching places ..."),
              Miss(serves="must_visit", wish="Xyz Palace", reason="it could not be found on Wikipedia"),
              Miss(serves="interest", wish="food", reason="the place search failed")]
    notes = sc.build_itinerary(request(), [place("Lake")], None, misses, "Jaipur").notes
    assert ("Mehrangarh Fort is not in this plan because it is 284 km from Jaipur. It is in Jodhpur; to see it, "
            "you can plan a separate trip to Jodhpur.") in notes
    assert "Lone Temple is not in this plan because it is 90 km from Jaipur. To see it, plan a separate trip " \
           "closer to it." in notes
    assert any("No places for 'street food' were found near Jaipur on Wikipedia" in n for n in notes)
    assert "Could not find Xyz Palace on Wikipedia, so it could not be planned." in notes
    assert "The search for food failed, so it is not in the plan." in notes


def test_rainy_outdoor_day_gets_a_warning():
    rain = [DayWeather(date=START, temp_max_c=30, temp_min_c=20, rain_probability=75, summary="Rain")]
    it = sc.build_itinerary(request(days=1), [place("Lake")], rain, [], "Jodhpur")
    assert any("Day 1 may be rainy (75%); Lake is outdoors" in n for n in it.notes)


def test_no_places_at_all_does_not_crash():
    it = sc.build_itinerary(request(days=2), [], None, [], "Jodhpur")
    assert len(it.days) == 2 and it.days[0].places == [] and "left free" in it.notes[-1]


def test_one_day_trip():
    it = sc.build_itinerary(request(days=1), [place(f"P{i}") for i in range(5)], None, [], "Jodhpur")
    assert len(it.days) == 1 and len(it.days[0].places) == 3 and len(it.unused) == 2
