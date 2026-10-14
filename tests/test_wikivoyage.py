"""Reading Wikivoyage pages and pageviews. No network: get_json is faked with fixed answers."""
import datetime as dt

from tools import wikivoyage as wv
from tools.http import ToolError

STATE_PAGE = """Intro text
==Regions==
* [[Marwar]]
==Cities==
* {{marker|type=city|name=[[Jaipur]]|lat=26.92|long=75.82|wikidata=Q66485}} — the Pink City
* {{marker|type=city|name=[[Udaipur]] |lat=24.58 |long=73.71}} — City of Lakes, see [[Lake Pichola]]
* [[Jodhpur]] — the Blue City
* [[File:Hawa Mahal.jpg]]
* {{marker|type=city|name=[[Jaipur]]}} — listed twice
==Other destinations==
* [[Ranthambore National Park]]
"""


def test_cities_from_markers_and_plain_links():
    cities = wv.parse_cities(STATE_PAGE)
    assert [c.name for c in cities] == ["Jaipur", "Udaipur", "Jodhpur"]
    assert (cities[0].lat, cities[0].lon) == (26.92, 75.82)
    assert cities[2].lat is None  # a plain link has no coordinates


def test_page_without_a_cities_section_lists_nothing():
    assert wv.parse_cities("==Understand==\n* [[Hawa Mahal]]\n==Get in==") == []


def test_cities_and_towns_heading_is_read():
    assert [c.name for c in wv.parse_cities("==Cities and towns==\n* [[Madikeri]]\n")] == ["Madikeri"]


def test_title_case_keeps_small_words():
    assert wv._title_case("jammu and kashmir") == "Jammu and Kashmir"
    assert wv._title_case("tamil nadu") == "Tamil Nadu"


def test_popularity_window_is_whole_past_months():
    assert wv.popularity_window(dt.date(2026, 10, 12)) == ("20260801", "20260930", 2)
    assert wv.popularity_window(dt.date(2026, 1, 5)) == ("20251101", "20251231", 2)


def fake_api(monkeypatch, answers):
    """answers: page title -> wikitext (str) or None for a missing page."""
    asked = []

    def fake_get_json(tool, url, params=None):
        asked.append(params["page"])
        text = answers.get(params["page"])
        if text is None:
            return {"error": {"code": "missingtitle"}}, 1
        title = "Kodagu" if params["page"] == "Coorg" else params["page"]
        return {"parse": {"title": title, "wikitext": text}}, 1

    monkeypatch.setattr(wv, "get_json", fake_get_json)
    return asked


def test_state_page_gives_cities(monkeypatch):
    fake_api(monkeypatch, {"Rajasthan": STATE_PAGE})
    page, _ = wv.fetch_page("Rajasthan")
    assert page.title == "Rajasthan" and len(page.cities) == 3


def test_redirect_title_is_kept(monkeypatch):
    fake_api(monkeypatch, {"Coorg": "==Cities==\n* [[Madikeri]]\n"})
    page, _ = wv.fetch_page("Coorg")
    assert page.title == "Kodagu" and page.cities[0].name == "Madikeri"


def test_title_case_is_tried_after_a_miss(monkeypatch):
    asked = fake_api(monkeypatch, {"Tamil Nadu": "==Cities==\n* [[Chennai]]\n"})
    page, attempts = wv.fetch_page("tamil nadu")
    assert asked == ["tamil nadu", "Tamil Nadu"] and page.title == "Tamil Nadu" and attempts == 2


def test_missing_page_is_none(monkeypatch):
    fake_api(monkeypatch, {})
    assert wv.fetch_page("Xyzpur")[0] is None


def test_disambiguation_page_lists_no_cities(monkeypatch):
    fake_api(monkeypatch, {"Aurangabad": "{{disamb}}\n==Cities==\n* [[Aurangabad (Maharashtra)]]\n"})
    page, _ = wv.fetch_page("Aurangabad")
    assert page.disambiguation and page.cities == []


def test_pageviews_are_summed(monkeypatch):
    seen = {}

    def fake_get_json(tool, url, params=None):
        seen["url"] = url
        return {"items": [{"views": 5330}, {"views": 8380}]}, 1

    monkeypatch.setattr(wv, "get_json", fake_get_json)
    assert wv.pageviews("Mount Abu", "20260801", "20260930") == (13710, 1)
    assert "/Mount_Abu/monthly/20260801/20260930" in seen["url"]


def test_page_without_views_counts_zero(monkeypatch):
    def not_found(tool, url, params=None):
        raise ToolError("pageviews", "http_error", "HTTP 404", 1)

    monkeypatch.setattr(wv, "get_json", not_found)
    assert wv.pageviews("Tiny Town", "20260801", "20260930") == (0, 1)


# The real Rajasthan page writes each marker over several lines.
MULTILINE_PAGE = """==Cities==
[[Image:JaswantThada_Lake.JPG|thumb|240px|Jaswant Thada, [[Jodhpur]]]]
Here are nine of the most notable cities.
* {{marker|type=city|zoom=12
| name=[[Jaipur]]
| lat=26.91243 | long=75.78727
| description=[[File:Jaipur_03-2016_04_Amber_Fort.jpg]] State capital (aka Pink City)
|wikidata=Q66485}} &mdash; the state capital, also known as the Pink City

* {{marker|type=city|zoom=12
| name=[[Ajmer]]
| lat=26.44990 | long=74.63992
|wikidata=Q200049}} &mdash; tomb of Sufi saint Khwaja Moinuddin Chisti
==Other destinations==
"""


def test_marker_over_several_lines_is_read():
    cities = wv.parse_cities(MULTILINE_PAGE)
    assert [c.name for c in cities] == ["Jaipur", "Ajmer"]  # the intro image link to Jodhpur is not a city
    assert (cities[0].lat, cities[0].lon) == (26.91243, 75.78727)


def test_numbered_list_is_read():
    assert [c.name for c in wv.parse_cities("==Cities==\n# [[Shillong]]\n# [[Cherrapunji]]\n")] == ["Shillong",
                                                                                                "Cherrapunji"]


def test_anchor_is_removed_and_repeats_dropped():
    page = "==Cities==\n* [[Nubra Valley#Q25247408]]\n* [[Nubra Valley#Q24911885]]\n* {{marker|name=Leh#x}}\n"
    assert [c.name for c in wv.parse_cities(page)] == ["Nubra Valley", "Leh"]


def test_page_coordinates_from_the_geo_template(monkeypatch):
    assert wv.page_coordinates("intro {{geo|24.58|73.68|zoom=12}} text") == (24.58, 73.68)
    assert wv.page_coordinates("no template") == (None, None)
    fake_api(monkeypatch, {"Udaipur": "{{geo|24.58|73.68}}\n==Understand=="})
    page, _ = wv.fetch_page("Udaipur")
    assert (page.lat, page.lon) == (24.58, 73.68)
