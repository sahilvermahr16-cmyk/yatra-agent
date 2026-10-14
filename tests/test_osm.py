"""OpenStreetMap tool: the Overpass query and reading its answer. No network."""
from tools import osm


def test_query_asks_lodging_near_day_centres_and_food_near_places():
    q = osm.build_query([(26.29, 73.02)], [(26.30, 73.02), (26.28, 73.03)])
    assert q.startswith("[out:json][timeout:25];(") and q.endswith(");out center tags;")
    assert q.count('nwr["tourism"~"^(guest_house|hostel|hotel)$"]["name"](around:8000,') == 1
    assert q.count('nwr["amenity"~"^(cafe|fast_food|food_court|restaurant)$"]["name"](around:2000,') == 2


def test_elements_become_places_and_unnamed_or_repeated_ones_are_skipped():
    data = {"elements": [
        {"type": "node", "id": 1, "lat": 26.3, "lon": 73.0,
         "tags": {"tourism": "hotel", "name": "Hotel A", "stars": "4"}},
        {"type": "way", "id": 2, "center": {"lat": 26.31, "lon": 73.01}, "tags": {"amenity": "cafe", "name": "Cafe B"}},
        {"type": "node", "id": 3, "lat": 26.3, "lon": 73.0, "tags": {"amenity": "restaurant"}},  # no name
        {"type": "node", "id": 1, "lat": 26.3, "lon": 73.0, "tags": {"tourism": "hotel", "name": "Hotel A"}},  # repeat
    ]}
    places = osm.parse_elements(data)
    assert [(p.name, p.kind, p.stars) for p in places] == [("Hotel A", "hotel", 4), ("Cafe B", "cafe", None)]
    assert places[1].lat == 26.31 and places[1].url == "https://www.openstreetmap.org/way/2"


def _servers(monkeypatch, answers):
    """Fake Overpass: each server either answers with data or fails with (error_type, message)."""
    import config
    from tools.http import ToolError

    asked = []

    def fake_get_json(tool, url, params=None, timeout=None, **kwargs):
        asked.append((url, kwargs))
        answer = answers[config.OSM_SERVERS.index(url)]
        if isinstance(answer, tuple):
            raise ToolError(tool, answer[0], answer[1], 1)
        return answer, 1

    monkeypatch.setattr(osm, "get_json", fake_get_json)
    return asked


def test_a_busy_server_is_skipped_and_the_next_one_answers(monkeypatch):
    data = {"elements": [{"type": "node", "id": 1, "lat": 26.3, "lon": 73.0,
                          "tags": {"tourism": "hotel", "name": "Hotel A"}}]}
    asked = _servers(monkeypatch, [("http_error", "HTTP 429"), data, data, data])
    (places, server), attempts = osm.fetch([(26.3, 73.0)], [(26.3, 73.0)])
    assert [p.name for p in places] == ["Hotel A"] and server == "maps.mail.ru" and attempts == 2
    # each server: one more try only after a quick refusal, never after a timeout
    assert len(asked) == 2 and all(k["retries"] == 1 and k["retry_timeouts"] is False for _, k in asked)


def test_when_every_server_fails_the_error_names_each_one(monkeypatch):
    import pytest

    from tools.http import ToolError

    _servers(monkeypatch, [("http_error", "HTTP 429"), ("timeout", "no answer"), ("http_error", "HTTP 504"),
                           ("http_error", "HTTP 504")])
    with pytest.raises(ToolError) as err:
        osm.fetch([(26.3, 73.0)], [(26.3, 73.0)])
    assert err.value.attempts == 4 and err.value.error_type == "http_error"
    assert "overpass-api.de: http_error (HTTP 429)" in err.value.message and "timeout" in err.value.message
