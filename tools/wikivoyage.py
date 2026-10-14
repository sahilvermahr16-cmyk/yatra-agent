"""Wikivoyage tool: is a destination a city or a state/region, which cities does it list, and how
popular is each city (Wikimedia pageviews). Free, no API key; a User-Agent header is required."""
import datetime as dt
import re
from urllib.parse import quote

from pydantic import BaseModel, Field

import config
from schemas import CityCandidate
from tools.http import ToolError, get_json

API = "https://en.wikivoyage.org/w/api.php"
PAGEVIEWS = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/"
             "all-access/user/{title}/monthly/{start}/{end}")
SMALL_WORDS = {"and", "of", "the"}


class WikivoyagePage(BaseModel):
    title: str  # after redirects
    cities: list[CityCandidate] = Field(default_factory=list)  # empty = the page lists no cities
    disambiguation: bool = False
    lat: float | None = None  # the page's own {{geo|lat|long}}: where the guide's place is
    lon: float | None = None


def page_coordinates(wikitext: str) -> tuple[float | None, float | None]:
    m = re.search(r"\{\{\s*geo\s*\|\s*(-?\d+(?:\.\d+)?)\s*\|\s*(-?\d+(?:\.\d+)?)", wikitext, flags=re.IGNORECASE)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def _title_case(name: str) -> str:
    """'tamil nadu' -> 'Tamil Nadu', 'jammu and kashmir' -> 'Jammu and Kashmir' (titles are case-sensitive)."""
    words = name.strip().split()
    return " ".join(w if (i and w.lower() in SMALL_WORDS) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def _cities_section(wikitext: str) -> str:
    """Text of the level-2 'Cities' section (also 'Cities and towns'), or '' if there is none."""
    m = re.search(r"^==\s*Cities\b[^=\n]*==\s*$", wikitext, flags=re.MULTILINE)
    if not m:
        return ""
    rest = wikitext[m.end():]
    nxt = re.search(r"^==[^=]", rest, flags=re.MULTILINE)
    return rest[:nxt.start()] if nxt else rest


def _number(text: str, key: str) -> float | None:
    m = re.search(rf"\|\s*{key}\s*=\s*(-?\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def _list_items(section: str) -> list[str]:
    """Split a section into list items ('*' or '#'). An item runs until the next item, so a marker
    written over several lines stays whole. Text before the first item (images, intro) is dropped."""
    parts = re.split(r"^\s*[*#]+", section, flags=re.MULTILINE)
    return parts[1:]


def _link_name(text: str) -> str | None:
    """First ordinary [[link]] target, without the '#anchor' part; File:/Image:/Category: links skipped."""
    for target in re.findall(r"\[\[([^\]|]+)", text):
        name = target.split("#")[0].strip()
        if name and ":" not in name:
            return name
    return None


def parse_cities(wikitext: str) -> list[CityCandidate]:
    """City names (and coordinates when given) from the Cities section. Two formats exist:
    '* {{marker|type=city|name=[[Jaipur]]|lat=..|long=..}}' (often over several lines) and '* [[Jaipur]] - ...'."""
    cities, seen = [], set()
    for item in _list_items(_cities_section(wikitext)):
        marker = re.search(r"\{\{\s*marker\s*(\|.*?)\}\}", item, flags=re.IGNORECASE | re.DOTALL)
        if marker:
            params = marker.group(1)
            m = re.search(r"\|\s*name\s*=\s*([^|}]+)", params)
            raw = m.group(1).strip() if m else ""
            name = _link_name(raw) if "[[" in raw else raw.split("#")[0].strip() or None
            lat, lon = _number(params, "lat"), _number(params, "long")
        else:
            name, lat, lon = _link_name(item), None, None
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        cities.append(CityCandidate(name=name, lat=lat, lon=lon))
    return cities


def fetch_page(name: str) -> tuple[WikivoyagePage | None, int]:
    """The destination's page (following redirects), or None if Wikivoyage has no such page.
    Tries the name as written, then in title case. Raises ToolError if Wikivoyage cannot be reached."""
    attempts_used = 0
    for title in dict.fromkeys([name.strip(), _title_case(name)]):
        params = {"action": "parse", "page": title, "prop": "wikitext", "redirects": 1,
                  "format": "json", "formatversion": 2}
        data, attempts = get_json("wikivoyage", API, params)
        attempts_used += attempts
        parse = data.get("parse") if isinstance(data, dict) else None
        if not parse:
            continue  # {"error": {"code": "missingtitle"}}
        text = parse.get("wikitext") or ""
        if isinstance(text, dict):  # formatversion=1 shape
            text = text.get("*", "")
        disamb = bool(re.search(r"\{\{\s*disamb", text, flags=re.IGNORECASE))
        lat, lon = page_coordinates(text)
        return WikivoyagePage(title=parse.get("title", title), cities=[] if disamb else parse_cities(text),
                              disambiguation=disamb, lat=lat, lon=lon), attempts_used
    return None, attempts_used


def popularity_window(today: dt.date) -> tuple[str, str, int]:
    """Whole past months covering about POPULARITY_WINDOW_DAYS: (start YYYYMMDD, end YYYYMMDD, months)."""
    months = max(1, round(config.POPULARITY_WINDOW_DAYS / 30))
    end = today.replace(day=1) - dt.timedelta(days=1)  # last day of the previous month
    first = end.replace(day=1)
    for _ in range(months - 1):
        first = (first - dt.timedelta(days=1)).replace(day=1)
    return first.strftime("%Y%m%d"), end.strftime("%Y%m%d"), months


def pageviews(title: str, start: str, end: str, project: str = "en.wikivoyage") -> tuple[int, int]:
    """Total views of a page (Wikivoyage by default, or 'en.wikipedia') in the window.
    A page with no recorded views answers 404 -> 0."""
    url = PAGEVIEWS.format(project=project, title=quote(title.replace(" ", "_"), safe=""), start=start, end=end)
    try:
        data, attempts = get_json("pageviews", url)
    except ToolError as err:
        if err.message == "HTTP 404":
            return 0, err.attempts
        raise
    items = data.get("items", []) if isinstance(data, dict) else []
    return sum(int(i.get("views", 0)) for i in items), attempts
