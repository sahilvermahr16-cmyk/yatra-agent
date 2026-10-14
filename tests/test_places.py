"""Places tool: Wikipedia answers, distance, the not-a-sight filter and the search text. No network."""
from schemas import Location
from tools import geo
from tools import places as pl

JODHPUR = Location(name="Jodhpur", lat=26.2389, lon=73.0243)


def page(title, idx, desc=None, lat=26.30, lon=73.02):
    return {"title": title, "index": idx, "description": desc, "fullurl": f"https://w/{title}",
            "coordinates": [{"lat": lat, "lon": lon}]}


def test_distance_is_roughly_right():
    assert 275 < geo.distance_km(26.92, 75.79, 26.24, 73.02) < 295  # Jaipur - Jodhpur, about 285 km in a straight line


def test_pages_come_in_rank_order_and_need_coordinates():
    data = {"query": {"pages": [page("B", 2), {"title": "NoCoords", "index": 1}, page("A", 0)]}}
    assert [p.title for p in pl.parse_pages(data)] == ["A", "B"]


def test_city_page_and_non_sights_are_filtered():
    assert not pl.is_sight(pl.Page(title="Jodhpur", lat=0, lon=0), JODHPUR)
    assert not pl.is_sight(pl.Page(title="Jodhpur Junction", lat=0, lon=0, description="railway station in India"),
                           JODHPUR)
    assert pl.is_sight(pl.Page(title="Toorji Ka Jhalra", lat=0, lon=0, description="stepwell in Jodhpur"), JODHPUR)


def test_indoor_from_title_or_description():
    assert pl.is_indoor(pl.Page(title="Umaid Bhawan Palace", lat=0, lon=0))
    assert not pl.is_indoor(pl.Page(title="Mandore Gardens", lat=0, lon=0, description="garden"))


def test_find_limits_the_search_to_the_city_area(monkeypatch):
    seen = {}

    def fake(tool, url, params):
        seen.update(params)
        return {"query": {"pages": [page("Jodhpur", 0), page("Toorji Ka Jhalra", 1, "stepwell")]}}, 1

    monkeypatch.setattr(pl, "get_json", fake)
    pages, _ = pl.find("stepwell", JODHPUR)
    assert seen["gsrsearch"] == "stepwell nearcoord:25km,26.2389,73.0243"
    assert [p.title for p in pages] == ["Toorji Ka Jhalra"]


def _searches(monkeypatch, answers):
    """Fake Wikipedia search: answers maps the start of a search text to page titles (in rank order)."""
    asked = []

    def fake(tool, url, params):
        text = params["gsrsearch"]
        asked.append(text)
        titles = next((t for start, t in answers.items() if text.startswith(start)), [])
        return {"query": {"pages": [page(title, i) for i, title in enumerate(titles)]}}, 1

    monkeypatch.setattr(pl, "get_json", fake)
    return asked


UDAIPUR = Location(name="Udaipur", lat=24.58, lon=73.71)


def test_locate_searches_near_the_city_first(monkeypatch):
    asked = _searches(monkeypatch, {"Mehrangarh Fort nearcoord:60km": ["Mehrangarh"]})
    found, attempts = pl.locate("Mehrangarh Fort", JODHPUR)
    assert found.title == "Mehrangarh" and attempts == 1  # 'Mehrangarh' carries the distinctive word
    assert asked == ["Mehrangarh Fort nearcoord:60km,26.2389,73.0243"]


def test_the_city_page_never_passes_for_the_named_place(monkeypatch):
    _searches(monkeypatch, {"City Palace nearcoord": ["Udaipur", "Lake Pichola", "City Palace, Udaipur"]})
    found, _ = pl.locate("City Palace", UDAIPUR)
    assert found.title == "City Palace, Udaipur"


def test_more_of_the_name_wins_amber_fort_over_the_town(monkeypatch):
    _searches(monkeypatch, {"Amber Fort nearcoord": ["Amber, India", "Nahargarh Fort", "Amber Fort"]})
    found, _ = pl.locate("Amber Fort", Location(name="Jaipur", lat=26.92, lon=75.79))
    assert found.title == "Amber Fort"


def test_a_far_place_is_found_by_name_and_a_lookalike_nearby_is_not_taken(monkeypatch):
    asked = _searches(monkeypatch, {"Taj Mahal nearcoord": ["Jal Mahal", "Rambagh Palace"],
                                    "Taj Mahal Jaipur": ["Taj Mahal"]})
    found, _ = pl.locate("Taj Mahal", Location(name="Jaipur", lat=26.92, lon=75.79))
    assert found.title == "Taj Mahal" and len(asked) == 2


def test_a_misspelt_name_falls_back_to_the_first_result_near_the_city(monkeypatch):
    _searches(monkeypatch, {"Mehrangad fort nearcoord": ["Jodhpur", "Mehrangarh", "Jaswant Thada"]})
    found, attempts = pl.locate("Mehrangad fort", JODHPUR)
    assert found.title == "Mehrangarh" and attempts == 3  # all three searches tried, then the fallback


def test_hotel_in_the_title_is_not_a_sight_and_whole_words_only():
    assert not pl.is_sight(pl.Page(title="LMB Hotel", lat=0, lon=0, description="Building in Rajasthan"), JODHPUR)
    assert pl.is_sight(pl.Page(title="Edward Memorial", lat=0, lon=0, description="monument"), JODHPUR)


def test_outdoor_words_win_over_indoor_words():
    assert not pl.is_indoor(pl.Page(title="Sisodiya Rani Bagh", lat=0, lon=0, description="Palace garden in India"))


def test_city_from_the_description_skips_states_and_the_country():
    assert pl.city_from_description("Medieval fort in Jodhpur, Rajasthan, India") == "Jodhpur"
    assert pl.city_from_description("Hindu temple in Rajasthan, India") is None
    assert pl.city_from_description("World Heritage Site in India") is None
    assert pl.city_from_description(None) is None


def test_city_of_falls_back_to_the_nearest_town(monkeypatch):
    def fake(tool, url, params):
        assert params["generator"] == "geosearch"
        return {"query": {"pages": [page("Osian", 0, "town in Rajasthan, India", lat=26.72, lon=72.91),
                                    page("Sachiya Mata", 1, "Hindu temple", lat=26.71, lon=72.90)]}}, 1

    monkeypatch.setattr(pl, "get_json", fake)
    city, _ = pl.city_of(pl.Page(title="Osian temples", lat=26.70, lon=72.90, description="temple group"))
    assert city == "Osian"


def test_views_come_with_the_page():
    data = {"query": {"pages": [dict(page("City Palace", 0), pageviews={"2026-09-01": 300, "2026-09-02": None,
                                                                          "2026-09-03": 200})]}}
    assert pl.parse_pages(data)[0].views == 500


def test_popular_joins_search_and_nearby_and_ranks_by_views(monkeypatch):
    UDAIPUR = Location(name="Udaipur", lat=24.58, lon=73.71)

    def fake(tool, url, params):
        if params.get("generator") == "geosearch":
            pages = [dict(page("City Palace, Udaipur", 0, "palace"), pageviews={"d": 30000}),
                     dict(page("Udaipur City railway station", 1, "railway station"), pageviews={"d": 9000}),
                     dict(page("Lake Pichola", 2, "lake"), pageviews={"d": 20000})]
        else:
            pages = [dict(page("Jagdish Temple", 0, "temple"), pageviews={"d": 3700}),
                     dict(page("Lake Pichola", 1, "lake"), pageviews={"d": 20000}),
                     page("Unknown Shrine", 2, "shrine")]
        return {"query": {"pages": pages}}, 1

    monkeypatch.setattr(pl, "get_json", fake)
    pages, attempts = pl.popular("tourist attraction", UDAIPUR, limit=3)
    assert [p.title for p in pages] == ["City Palace, Udaipur", "Lake Pichola", "Jagdish Temple"]
    assert attempts == 2


def test_view_counts_given_in_parts_are_all_collected(monkeypatch):
    answers = [
        {"query": {"pages": [dict(page("A", 0), pageid=1, pageviews={"d1": 10}), dict(page("B", 1), pageid=2)]},
         "continue": {"pvipcontinue": "x", "continue": "||"}},
        {"query": {"pages": [{"pageid": 2, "title": "B", "pageviews": {"d1": 99}}]}},
    ]
    calls = []

    def fake(tool, url, params):
        calls.append(params.get("pvipcontinue"))
        return answers[len(calls) - 1], 1

    monkeypatch.setattr(pl, "get_json", fake)
    pages, attempts = pl._search("x", 2)
    assert calls == [None, "x"] and {p.title: p.views for p in pages} == {"A": 10, "B": 99} and attempts == 2


def test_popular_needs_a_description_and_enough_views_and_prefers_the_kind_asked():
    UDAIPUR = Location(name="Udaipur", lat=24.58, lon=73.71)

    def fake(tool, url, params):
        pages = [dict(page("Lake Pichola", 0, "lake"), pageviews={"d": 20000}),
                 dict(page("City Palace", 1, "palace"), pageviews={"d": 9000}),
                 dict(page("Defence Laboratory", 2), pageviews={"d": 5000}),          # no description
                 dict(page("Old Stone", 3, "geological site"), pageviews={"d": 120})]  # too few views
        return {"query": {"pages": pages}}, 1

    import tools.places as module
    module_get = module.get_json
    try:
        module.get_json = fake
        pages, _ = pl.popular("tourist attraction", UDAIPUR, limit=5, prefer={"history"})
    finally:
        module.get_json = module_get
    assert [p.title for p in pages] == ["City Palace", "Lake Pichola"]  # history first, then by views


def test_a_page_with_only_secondary_coordinates_is_kept_and_the_primary_point_preferred():
    secondary_only = {"title": "City Palace, Udaipur", "index": 0,
                      "coordinates": [{"lat": 24.576, "lon": 73.68, "primary": False}]}
    both = {"title": "B", "index": 1, "coordinates": [{"lat": 1.0, "lon": 1.0, "primary": False},
                                                      {"lat": 2.0, "lon": 2.0, "primary": True}]}
    pages = pl.parse_pages({"query": {"pages": [secondary_only, both]}})
    assert [(p.title, p.lat) for p in pages] == [("City Palace, Udaipur", 24.576), ("B", 2.0)]


def test_locate_asks_for_secondary_coordinates_too(monkeypatch):
    seen = []

    def fake(tool, url, params):
        seen.append(params.get("coprimary"))
        return {"query": {"pages": [page("City Palace, Udaipur", 0)]}}, 1

    monkeypatch.setattr(pl, "get_json", fake)
    found, _ = pl.locate("City Palace", UDAIPUR)
    assert found.title == "City Palace, Udaipur" and seen == ["all"]
