"""resolve_destination decides city / state / region and the base city. Every tool is faked."""
import datetime as dt

import pytest

from schemas import CityCandidate, GeocodeResult, Location
from tools import destination as d
from tools.calls import ToolLog
from tools.http import ToolError
from tools.wikivoyage import WikivoyagePage

TODAY = dt.date(2026, 10, 12)


def loc(name, region, lat=1.0, lon=2.0):
    return Location(name=name, lat=lat, lon=lon, region=region)


def down(tool):
    def fail(*args):
        raise ToolError(tool, "timeout", "no answer within 8 s", 3)
    return fail


@pytest.fixture
def tools(monkeypatch):
    """Configure fake answers: pages {query: WikivoyagePage|None}, views {city: int|Exception},
    places {name: GeocodeResult}. Set pages=None to make Wikivoyage unreachable."""
    def install(pages=None, views=None, places=None):
        if pages is None:
            monkeypatch.setattr(d.wikivoyage, "fetch_page", down("wikivoyage"))
        else:
            monkeypatch.setattr(d.wikivoyage, "fetch_page", lambda name: (pages.get(name), 1))

        def fake_views(title, start, end):
            v = (views or {}).get(title, 0)
            if isinstance(v, Exception):
                raise v
            return v, 1

        monkeypatch.setattr(d.wikivoyage, "pageviews", fake_views)
        monkeypatch.setattr(d, "geocode", lambda name: ((places or {}).get(name, GeocodeResult(query=name)), 1))
    return install


RAJASTHAN = WikivoyagePage(title="Rajasthan", cities=[CityCandidate(name="Jaipur", lat=26.9, lon=75.8),
                                                      CityCandidate(name="Udaipur"), CityCandidate(name="Jodhpur")])
JAIPUR_GEO = GeocodeResult(query="Jaipur", chosen=loc("Jaipur", "Rajasthan"))


def run(query):
    log = ToolLog("resolve_destination")
    return d.resolve_destination(query, TODAY, log), log


def test_city_page_without_cities_is_a_city(tools):
    tools(pages={"Jaipur": WikivoyagePage(title="Jaipur")}, places={"Jaipur": JAIPUR_GEO})
    r, log = run("Jaipur")
    assert (r.destination_type, r.base_city, r.location.region) == ("city", "Jaipur", "Rajasthan")
    assert log.errors == []


def test_state_is_based_in_its_most_viewed_city(tools):
    views = {"Jaipur": 8380, "Udaipur": 5000, "Jodhpur": ToolError("pageviews", "timeout", "slow", 3)}
    tools(pages={"Rajasthan": RAJASTHAN}, views=views, places={"Jaipur": JAIPUR_GEO})
    r, log = run("Rajasthan")
    assert (r.destination_type, r.base_city, r.used_fallback) == ("state", "Jaipur", False)
    assert "most viewed" in r.choice_reason and "8,380 views" in r.choice_reason
    assert [e.where for e in log.errors] == ["pageviews"]  # Jodhpur's failure is recorded, not fatal


def test_all_pageviews_failing_uses_the_built_in_table(tools):
    fail = ToolError("pageviews", "timeout", "slow", 3)
    tools(pages={"Rajasthan": RAJASTHAN}, views={"Jaipur": fail, "Udaipur": fail, "Jodhpur": fail},
          places={"Jaipur": JAIPUR_GEO})
    r, _ = run("Rajasthan")
    assert (r.base_city, r.used_fallback) == ("Jaipur", True) and "built-in" in r.choice_reason


def test_wikivoyage_down_state_from_the_built_in_list(tools):
    tools(pages=None, places={"Shillong": GeocodeResult(query="Shillong", chosen=loc("Shillong", "Meghalaya"))})
    r, log = run("Meghalaya")
    assert (r.destination_type, r.base_city, r.used_fallback) == ("state", "Shillong", True)
    assert log.errors[0].handled_by.startswith("decided city or state from the built-in list")


def test_wikivoyage_down_city_still_geocoded(tools):
    tools(pages=None, places={"Jaipur": JAIPUR_GEO})
    r, _ = run("Jaipur")
    assert (r.destination_type, r.location.name) == ("city", "Jaipur")


def test_city_union_territory_is_a_city(tools):
    delhi_page = WikivoyagePage(title="Delhi", cities=[CityCandidate(name="New Delhi")])
    tools(pages={"Delhi": delhi_page}, places={"Delhi": GeocodeResult(query="Delhi", chosen=loc("Delhi", "Delhi"))})
    r, _ = run("Delhi")
    assert r.destination_type == "city" and r.candidates == []


def test_region_page_with_cities_is_a_region(tools):
    kodagu = WikivoyagePage(title="Kodagu", cities=[CityCandidate(name="Madikeri"), CityCandidate(name="Virajpet")])
    tools(pages={"Coorg": kodagu}, views={"Madikeri": 900, "Virajpet": 100},
          places={"Madikeri": GeocodeResult(query="Madikeri", chosen=loc("Madikeri", "Karnataka"))})
    r, _ = run("Coorg")
    assert (r.destination_type, r.wikivoyage_title, r.base_city) == ("region", "Kodagu", "Madikeri")


def test_namesake_in_another_state_is_skipped(tools):
    up = WikivoyagePage(title="Uttar Pradesh", cities=[CityCandidate(name="Aurangabad")])
    geo = GeocodeResult(query="Aurangabad", chosen=loc("Aurangabad", "Maharashtra"),
                        alternatives=[loc("Aurangābād", "Uttar Pradesh", lat=28.4)])
    tools(pages={"Uttar Pradesh": up}, views={"Aurangabad": 10}, places={"Aurangabad": geo})
    r, _ = run("Uttar Pradesh")
    assert r.location.region == "Uttar Pradesh" and r.location.lat == 28.4


def test_marker_coordinates_when_geocoding_finds_nothing(tools):
    tools(pages={"Rajasthan": RAJASTHAN}, views={"Jaipur": 10}, places={})
    r, log = run("Rajasthan")
    assert (r.location.lat, r.location.source) == (26.9, "Wikivoyage marker")
    assert any("taken from Wikivoyage" in n for n in log.notes)


def test_unknown_place_has_no_location_and_a_note(tools):
    tools(pages={}, places={})
    r, log = run("Xyzpur")
    assert r.location is None and any("Could not find 'Xyzpur'" in n for n in log.notes)


def test_alias_is_looked_up_by_its_real_name(tools):
    odisha = WikivoyagePage(title="Odisha", cities=[CityCandidate(name="Puri")])
    tools(pages={"odisha": odisha}, views={"Puri": 50},
          places={"Puri": GeocodeResult(query="Puri", chosen=loc("Puri", "Odisha"))})
    r, _ = run("Orissa")
    assert (r.destination_type, r.base_city) == ("state", "Puri")


def test_ambiguous_city_gets_a_note(tools):
    geo = GeocodeResult(query="Aurangabad", chosen=loc("Aurangabad", "Maharashtra"), ambiguous=True)
    tools(pages={}, places={"Aurangabad": geo})
    r, log = run("Aurangabad")
    assert any("Several places in India are called Aurangabad" in n for n in log.notes)


def test_geocode_down_for_a_city_is_an_error_not_a_crash(tools, monkeypatch):
    tools(pages={})
    monkeypatch.setattr(d, "geocode", down("geocode"))
    r, log = run("Jaipur")
    assert r.location is None and log.errors[0].where == "geocode"


def test_state_without_readable_cities_says_so(tools):
    tools(pages={"Kerala": WikivoyagePage(title="Kerala")},
          places={"Kochi": GeocodeResult(query="Kochi", chosen=loc("Kochi", "Kerala"))})
    r, _ = run("Kerala")
    assert (r.base_city, r.used_fallback) == ("Kochi", True)
    assert "no list of its cities could be read" in r.choice_reason
    assert "popularity" not in r.choice_reason


def test_city_uses_the_wikivoyage_point_to_pick_the_right_namesake(tools):
    page = WikivoyagePage(title="Udaipur", lat=24.58, lon=73.68)
    geo = GeocodeResult(query="Udaipur", chosen=loc("Udaipur", "Tripura", lat=23.53, lon=91.48),
                        alternatives=[loc("Udaipur", "Rajasthan", lat=24.57, lon=73.69)])
    tools(pages={"Udaipur": page}, places={"Udaipur": geo})
    r, _ = run("Udaipur")
    assert r.location.region == "Rajasthan"


def test_the_travel_guides_title_is_tried_when_the_users_name_finds_no_town(tools):
    mysuru = GeocodeResult(query="Mysuru", chosen=loc("Mysuru", "Karnataka", 12.30, 76.64))
    airport_only = GeocodeResult(query="Mysore", other_matches=[loc("Mysore Airport", "Karnataka", 12.23, 76.66)])
    tools(pages={"Mysore": WikivoyagePage(title="Mysuru", lat=12.31, lon=76.65)},
          places={"Mysore": airport_only, "Mysuru": mysuru})
    r, _ = run("Mysore")
    assert r.base_city == "Mysuru" and r.location.region == "Karnataka"


def test_no_town_with_the_name_but_the_guide_is_near_an_indian_match_uses_the_guides_coordinates(tools):
    airport_only = GeocodeResult(query="Hampi", other_matches=[loc("Hampi Airstrip", "Karnataka", 15.30, 76.50)])
    tools(pages={"Hampi": WikivoyagePage(title="Hampi", lat=15.33, lon=76.46)}, places={"Hampi": airport_only})
    r, log = run("Hampi")
    assert (r.base_city, r.location.lat, r.location.source) == ("Hampi", 15.33, "Wikivoyage marker")
    assert "taken from Wikivoyage" in log.notes[-1]


def test_a_place_the_guide_puts_far_from_india_is_not_planned(tools):
    prefix_only = GeocodeResult(query="Paris", other_matches=[loc("Pariswani", "Jammu and Kashmir", 34.06, 74.49)])
    tools(pages={"Paris": WikivoyagePage(title="Paris", lat=48.86, lon=2.35)}, places={"Paris": prefix_only})
    r, log = run("Paris")
    assert r.location is None and "does not seem to be in India" in log.notes[-1]
