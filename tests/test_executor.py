"""Executor: runs the plan's data steps, keeps priorities, and turns failures into notes. Tools are faked."""
import datetime as dt
import os

import pytest

pytest.importorskip("httpx")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

import executor_node as ex  # noqa: E402
from schemas import DayWeather, DestinationResult, Location, PlaceType, Plan, PlanStep, TripRequest  # noqa: E402
from tools import http  # noqa: E402
from tools.places import Page  # noqa: E402
from tools.weather import forecast as real_forecast  # noqa: E402

TODAY = dt.date(2026, 10, 12)
JODHPUR = Location(name="Jodhpur", lat=26.2389, lon=73.0243, region="Rajasthan")


def request(**fields):
    base = dict(destination="Jodhpur", start_date=dt.date(2026, 10, 24), end_date=dt.date(2026, 10, 26), days=3,
                travellers=2, must_visit=["Mehrangarh Fort"],
                place_types=[PlaceType(words="stepwells", interests=["history"])], interests=["history", "food"])
    base.update(fields)
    return TripRequest(**base)


def plan(*extra):
    steps = [PlanStep(step=1, tool="resolve_destination", reason="r"), PlanStep(step=2, tool="weather", reason="r"),
             PlanStep(step=3, tool="locate_place", query="Mehrangarh Fort", serves="must_visit", reason="r"),
             PlanStep(step=4, tool="find_places", query="stepwell", serves="place_type", reason="you want stepwells"),
             PlanStep(step=5, tool="find_places", query="food market", serves="interest", reason="you enjoy food"),
             PlanStep(step=6, tool="find_places", query="tourist attraction", serves="popular", reason="r"),
             PlanStep(step=7, tool="estimate_costs", reason="r"), PlanStep(step=8, tool="build_itinerary", reason="r"),
             PlanStep(step=9, tool="check_budget", reason="r")]
    return Plan(summary="s", steps=steps)


def pg(title, lat=26.30, lon=73.02, desc=None):
    return Page(title=title, lat=lat, lon=lon, description=desc)


@pytest.fixture
def tools(monkeypatch):
    def install(location=JODHPUR, mehrangarh=None, search=None, weather=None, near_city="Jodhpur"):
        mehrangarh = mehrangarh or pg("Mehrangarh", desc="fort")
        def resolve(query, today, log):
            return DestinationResult(query=query, destination_type="city", base_city="Jodhpur", location=location)

        def forecast(loc, start, end, today):
            if isinstance(weather, Exception):
                raise weather
            return (weather if weather is not None else
                    [DayWeather(date=start, temp_max_c=33, temp_min_c=22, rain_probability=10,
                                summary="Clear sky")] * 3), 1

        results = search or {"stepwell": [pg("Toorji Ka Jhalra", desc="stepwell")],
                             "food market": [pg("Sardar Market", desc="market")],
                             "tourist attraction": [pg("Mehrangarh"), pg("Jaswant Thada", desc="cenotaph")]}

        def find(query, city, limit=6):
            r = results.get(query, [])
            if isinstance(r, Exception):
                raise r
            return r, 1

        monkeypatch.setattr(ex, "resolve_destination", resolve)
        monkeypatch.setattr(ex.weather_tool, "forecast", forecast)
        monkeypatch.setattr(ex.places_tool, "locate", lambda name, city: (mehrangarh, 1))
        monkeypatch.setattr(ex.places_tool, "find", find)
        monkeypatch.setattr(ex.places_tool, "popular",
                            lambda query, city, limit, prefer=None: (find(query, city)[0][:limit], 1))
        monkeypatch.setattr(ex.places_tool, "city_of", lambda page: (near_city, 1))
    return install


def test_normal_run_finds_each_wish(tools):
    tools()
    out = ex.execute(plan(), request(), TODAY)
    assert out["status"] == "running" and out["misses"] == [] and len(out["weather"]) == 3
    by_name = {p.name: p for p in out["places"]}
    assert by_name["Toorji Ka Jhalra"].wish == "stepwells" and by_name["Toorji Ka Jhalra"].category == "history"
    assert by_name["Sardar Market"].wish == "food" and by_name["Sardar Market"].category == "food"
    assert [r.tool for r in out["step_results"]] == ["resolve_destination", "weather", "locate_place",
                                                     "find_places", "find_places", "find_places"]


def test_a_place_found_twice_keeps_the_more_important_wish(tools):
    tools()
    out = ex.execute(plan(), request(), TODAY)
    mehrangarh = [p for p in out["places"] if p.name == "Mehrangarh"]
    assert len(mehrangarh) == 1 and mehrangarh[0].serves == "must_visit"
    assert out["places"][0].serves == "must_visit"  # ordered by priority


def test_far_must_visit_becomes_a_miss(tools):
    tools(mehrangarh=pg("Mehrangarh", lat=26.92, lon=75.79))  # placed in Jaipur: ~280 km away
    out = ex.execute(plan(), request(), TODAY)
    assert out["misses"][0].serves == "must_visit" and "km from Jodhpur" in out["misses"][0].reason
    assert out["misses"][0].near_city == "Jodhpur"
    assert out["places"][0].name != "Mehrangarh" or out["places"][0].serves == "popular"


def test_empty_search_becomes_an_honest_miss(tools):
    tools(search={"stepwell": [], "food market": [], "tourist attraction": []})
    out = ex.execute(plan(), request(), TODAY)
    reasons = {m.wish: m.reason for m in out["misses"]}
    assert "no matching places were found on Wikipedia" in reasons["stepwells"]


def test_weather_failure_is_noted_and_the_run_continues(tools):
    tools(weather=http.ToolError("weather", "timeout", "simulated", 3))
    out = ex.execute(plan(), request(), TODAY)
    assert out["weather"] is None and out["status"] == "running"
    assert out["errors"][0].where == "weather" and "without a forecast" in out["errors"][0].handled_by
    assert any("could not be fetched" in n for n in out["notes"])


def test_injected_weather_timeout_goes_through_the_real_wrapper(tools, monkeypatch):
    tools()
    monkeypatch.setattr(ex.weather_tool, "forecast", real_forecast)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    http.inject_failures({"weather"})
    try:
        out = ex.execute(plan(), request(), TODAY)
    finally:
        http.inject_failures(set())
    err = out["errors"][0]
    assert (err.where, err.error_type) == ("weather", "timeout") and "after 3 attempt" in err.message
    assert out["status"] == "running" and len(out["places"]) >= 3


def test_failed_search_is_a_miss_not_a_crash(tools):
    tools(search={"stepwell": http.ToolError("places", "timeout", "slow", 3), "food market": [],
                  "tourist attraction": [pg("Jaswant Thada")]})
    out = ex.execute(plan(), request(), TODAY)
    assert any(m.reason == "the place search failed" and m.wish == "stepwells" for m in out["misses"])
    assert out["status"] == "running"


def test_no_location_stops_with_needs_city(tools):
    tools(location=None)
    out = ex.execute(plan(), request(), TODAY)
    assert out["status"] == "needs_city" and len(out["step_results"]) == 1


def test_wishes_pair_by_shared_words_not_only_by_order():
    r = request(place_types=[PlaceType(words="lakes", interests=["nature"]),
                             PlaceType(words="stepwells", interests=["history"])], interests=["nature", "history"])
    p = Plan(summary="s", steps=[
        PlanStep(step=4, tool="find_places", query="stepwell", serves="place_type", reason="you want stepwells"),
        PlanStep(step=5, tool="find_places", query="lake", serves="place_type", reason="you want lakes")])
    assert ex.match_wishes(p, r) == {4: ("stepwells", "history"), 5: ("lakes", "nature")}


def test_popular_views_reach_the_places_and_the_trip_length_sets_how_many(tools, monkeypatch):
    asked = {}

    def popular(query, city, limit, prefer=None):
        asked["limit"], asked["prefer"] = limit, prefer
        return [Page(title="Umaid Bhawan Palace", lat=26.28, lon=73.04, views=40000)], 1

    tools()
    monkeypatch.setattr(ex.places_tool, "popular", popular)
    out = ex.execute(plan(), request(), TODAY)
    assert asked["limit"] == 3 * 3 and asked["prefer"] == {"history"}  # Mehrangarh is described as a fort
    assert any("Because you chose Mehrangarh Fort, other historic sights" in n for n in out["notes"])
    assert [p.pageviews for p in out["places"] if p.serves == "popular"] == [40000]


def test_a_trip_beyond_the_forecast_says_the_weather_was_not_checked(tools):
    tools()
    far = request(start_date=dt.date(2026, 12, 20), end_date=dt.date(2026, 12, 22))
    steps = [st for st in plan().steps if st.tool != "weather"]  # the planner leaves weather out for such dates
    out = ex.execute(Plan(summary="s", steps=steps), far, TODAY)
    assert any("starts in 69 days" in n and "forecasts reach only 16 days" in n for n in out["notes"])


def test_a_trip_inside_the_forecast_gets_no_such_note(tools):
    tools()
    out = ex.execute(plan(), request(), TODAY)
    assert not any("forecasts reach only" in n for n in out["notes"])
