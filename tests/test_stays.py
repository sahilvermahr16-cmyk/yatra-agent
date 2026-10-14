"""Choosing stays, breakfast and food stops from OpenStreetMap places. Pure code."""
import datetime as dt

import stays
from schemas import CostChoices, DayPlan, Itinerary, Place, PlaceType, TripRequest
from tools.osm import OsmPlace

START = dt.date(2026, 10, 24)
MID = CostChoices(hotel_tier="mid", food_tier="mid")


def place(name, lat, lon=73.0):
    return Place(name=name, lat=lat, lon=lon, distance_km=1, serves="popular", wish="w", category="popular",
                 indoor=False)


def osm_place(name, kind, lat, lon=73.0, stars=None):
    return OsmPlace(name=name, kind=kind, lat=lat, lon=lon, stars=stars, url=f"https://osm/{name}")


def trip(*day_places):
    return Itinerary(days=[DayPlan(day=i + 1, date=START + dt.timedelta(days=i), places=list(ps), reason="r")
                           for i, ps in enumerate(day_places)])


# Day 1 around lat 26.30, day 2 around lat 26.40 (about 11 km north), day 3 around 26.401
IT = trip([place("Fort", 26.300), place("Well", 26.301)], [place("Lake", 26.400)], [place("Garden", 26.401)])
SPOTS = [osm_place("Hotel South", "hotel", 26.300), osm_place("Hotel North", "hotel", 26.399),
         osm_place("Hostel North", "hostel", 26.398), osm_place("Lux North", "hotel", 26.402, stars=5),
         osm_place("Cafe Fort", "cafe", 26.3005), osm_place("Dhaba Well", "fast_food", 26.3012),
         osm_place("Cafe Lake", "cafe", 26.4002)]


def test_hotel_is_near_the_next_days_places_and_kept_when_still_close():
    it, _ = stays.assign(IT, SPOTS, MID, want_food=False)
    assert it.days[0].stay.name == "Hotel North"  # night 1: near day 2's lake, not near day 1's fort
    assert it.days[1].stay.name == "Hotel North"  # day 3 is 100 m from day 2: no need to move
    assert it.days[2].stay is None  # the last day ends the trip


def test_hotel_matches_the_price_level():
    it, _ = stays.assign(IT, SPOTS, CostChoices(hotel_tier="budget", food_tier="budget"), want_food=False)
    assert it.days[0].stay.name == "Hostel North"
    it, _ = stays.assign(IT, SPOTS, CostChoices(hotel_tier="luxury", food_tier="luxury"), want_food=False)
    assert it.days[0].stay.name == "Lux North"


def test_no_matching_level_takes_the_nearest_stay_with_a_note():
    it, notes = stays.assign(IT, [osm_place("Hostel North", "hostel", 26.398)], MID, want_food=False)
    assert it.days[0].stay.name == "Hostel North" and "No mid-level stay" in notes[0]


def test_staying_outside_the_centre_picks_a_hotel_3_to_8_km_away():
    spots = SPOTS + [osm_place("Hotel Outskirts", "hotel", 26.445)]  # about 5 km from day 2
    it, _ = stays.assign(IT, spots, MID.model_copy(update={"hotel_outside_centre": True}), want_food=False)
    assert it.days[0].stay.name == "Hotel Outskirts" and 3 <= it.days[0].stay.distance_km <= 8


def test_breakfast_near_the_first_place_and_food_stop_only_when_asked():
    it, _ = stays.assign(IT, SPOTS, MID, want_food=False)
    assert it.days[0].breakfast.name == "Cafe Fort" and it.days[0].food_stop is None
    it, _ = stays.assign(IT, SPOTS, MID, want_food=True)
    assert it.days[0].food_stop.name == "Dhaba Well"


def test_food_wishes_come_from_food_kinds_of_place_or_the_food_purpose():
    r = TripRequest(destination="Jodhpur", place_types=[PlaceType(words="street food", interests=["food"]),
                                                        PlaceType(words="stepwells", interests=["history"])])
    assert stays.food_wishes(r) == {"street food"}
    assert stays.food_wishes(TripRequest(destination="Jodhpur", interests=["food"])) == {"food"}


def test_a_food_stop_is_not_repeated_while_another_exists_and_repeats_are_said():
    it2 = trip([place("Fort", 26.300)], [place("Well", 26.301)], [place("Gate", 26.302)])
    spots = [osm_place("Dhaba A", "fast_food", 26.3001), osm_place("Dhaba B", "fast_food", 26.3015),
             osm_place("Thali House", "restaurant", 26.3002)]  # lunch goes to the restaurant
    it, _ = stays.assign(it2, spots, MID, want_food=True)
    assert [d.food_stop.name for d in it.days] == ["Dhaba A", "Dhaba B", "Dhaba B"]
    assert "same as on day 2" in it.days[2].day_notes[-1]


def test_a_day_without_breakfast_nearby_says_so():
    it, _ = stays.assign(trip([place("Lake", 26.9)]), SPOTS, MID, want_food=False)
    assert it.days[0].breakfast is None and "have breakfast near your stay" in it.days[0].day_notes[0]
