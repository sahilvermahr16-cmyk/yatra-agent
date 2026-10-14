"""Places tool: find sights near the base city on Wikipedia (free, no API key).

locate(): where one named place is (must-visit).  find(): places matching a short phrase, limited to
SEARCH_RADIUS_KM around the city by Wikipedia's own 'nearcoord:' search filter.
"""
import re
import unicodedata

from pydantic import BaseModel

import config
from schemas import Location
from tools.geo import distance_km
from tools.http import get_json

API = "https://en.wikipedia.org/w/api.php"


class Page(BaseModel):
    title: str
    lat: float
    lon: float
    description: str | None = None
    url: str | None = None
    views: int | None = None  # Wikipedia views over the last POPULARITY_WINDOW_DAYS, from the same answer


def parse_pages(data) -> list[Page]:
    """Pages in search-rank order; pages without coordinates are useless for planning and skipped."""
    pages = ((data.get("query") or {}).get("pages") or []) if isinstance(data, dict) else []
    pages = sorted(pages, key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        coords = p.get("coordinates") or []
        if not coords or not p.get("title"):
            continue
        coords = [next((c for c in coords if c.get("primary")), coords[0])]  # the primary point when there is one
        daily = p.get("pageviews")
        views = sum(v for v in daily.values() if v) if isinstance(daily, dict) else None
        out.append(Page(title=p["title"], lat=coords[0]["lat"], lon=coords[0]["lon"],
                        description=p.get("description"), url=p.get("fullurl"), views=views))
    return out


# Every query asks for coordinates, the short description, the URL and the recent views in one answer.
PAGE_PROPS = {"prop": "coordinates|description|info|pageviews", "inprop": "url", "colimit": "max",
              "pvipdays": config.POPULARITY_WINDOW_DAYS}


def _query(params: dict) -> tuple[list[Page], int]:
    """One Wikipedia query. View counts come in parts (pvipcontinue): follow them so every page has its count."""
    pages: dict = {}
    attempts, cont = 0, {}
    for _ in range(5):
        data, used = get_json("places", API, {**params, **cont})
        attempts += used
        for p in ((data.get("query") or {}).get("pages") or []) if isinstance(data, dict) else []:
            key = p.get("pageid") or p.get("title")
            if key in pages:
                if p.get("pageviews"):
                    pages[key]["pageviews"] = {**(pages[key].get("pageviews") or {}), **p["pageviews"]}
            else:
                pages[key] = p
        more = data.get("continue") if isinstance(data, dict) else None
        if not more or "pvipcontinue" not in more:
            break
        cont = {"pvipcontinue": more["pvipcontinue"], "continue": more.get("continue", "")}
    return parse_pages({"query": {"pages": list(pages.values())}}), attempts


def _by_views(pages: list[Page]) -> list[Page]:
    return sorted(pages, key=lambda p: -(p.views if p.views is not None else -1))


def _search(text: str, limit: int, extra: dict | None = None) -> tuple[list[Page], int]:
    params = {"action": "query", "format": "json", "formatversion": 2, "generator": "search",
              "gsrsearch": text, "gsrlimit": limit, **PAGE_PROPS, **(extra or {})}
    return _query(params)


def _has_word(text: str, words: list[str]) -> bool:
    """Whole words only, so 'ward' does not match 'Edward' and 'bank' does not match 'Banke Bihari'."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def is_sight(page: Page, city: Location) -> bool:
    """Code filter: the city's own page and stations, schools, hotels, areas ... are not sights.
    Title and description are both checked ('LMB Hotel' is described only as a 'Building')."""
    if page.title.lower() == city.name.lower():
        return False
    return not _has_word(f"{page.title} {page.description or ''}".lower(), config.NOT_A_SIGHT_WORDS)


def is_indoor(page: Page) -> bool:
    """Outdoor words win ('Palace garden' is a garden); otherwise indoor words decide."""
    text = f"{page.title} {page.description or ''}".lower()
    if _has_word(text, config.OUTDOOR_WORDS):
        return False
    return _has_word(text, config.INDOOR_WORDS)


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text).lower()
    return re.findall(r"[a-z0-9]+", plain)


def name_match(name: str, title: str) -> float | None:
    """None if the title lacks a distinctive word of the name (any word but fort / palace / temple ...);
    otherwise the share of all the name's words found in it, to rank 'Amber Fort' above 'Amber, India'."""
    words = _words(name)
    key = [w for w in words if w not in config.LANDMARK_WORDS] or words
    in_title = set(_words(title))
    if not words or not all(w in in_title for w in key):
        return None
    return sum(w in in_title for w in words) / len(words)


def locate(name: str, city: Location) -> tuple[Page | None, int]:
    """Where a named place is. Searches near the city first, then 'name city', then 'name' (a must-visit place may
    be far away). A page counts only if its title carries the name's distinctive words, and the city's own page
    never does. If no page anywhere carries them (a misspelt name), the first result near the city is used."""
    near = f"{name} nearcoord:{config.MUST_VISIT_RADIUS_KM}km,{city.lat:.4f},{city.lon:.4f}"
    used, fallback = 0, None
    for text in dict.fromkeys([near, f"{name} {city.name}", name]):
        # some articles have only secondary coordinates ('City Palace, Udaipur'): ask for those too
        pages, attempts = _search(text, config.LOCATE_RESULTS, {"coprimary": "all"})
        used += attempts
        pages = [p for p in pages if p.title.lower() != city.name.lower()]
        if fallback is None and pages:
            fallback = pages[0]
        scored = [(score, -rank, p) for rank, p in enumerate(pages)
                  if (score := name_match(name, p.title)) is not None]
        if scored:
            return max(scored, key=lambda s: (s[0], s[1]))[2], used
    return fallback, used


def find(query: str, city: Location, limit: int = config.MAX_PLACES_PER_SEARCH) -> tuple[list[Page], int]:
    """Sights matching a short phrase within SEARCH_RADIUS_KM of the city, best match first."""
    text = f"{query} nearcoord:{config.SEARCH_RADIUS_KM}km,{city.lat:.4f},{city.lon:.4f}"
    pages, attempts = _search(text, limit * 2)  # extra, as the filter drops some
    best = [p for p in pages if is_sight(p, city)][:limit]
    return _by_views(best), attempts  # among the matches, the best known first


def nearby(city: Location) -> tuple[list[Page], int]:
    """Every geotagged sight within NEARBY_RADIUS_KM of the city centre (Wikipedia geosearch)."""
    params = {"action": "query", "format": "json", "formatversion": 2, "generator": "geosearch",
              "ggscoord": f"{city.lat}|{city.lon}", "ggsradius": config.NEARBY_RADIUS_KM * 1000,
              "ggslimit": config.NEARBY_LIMIT, **PAGE_PROPS}
    pages, attempts = _query(params)
    return [p for p in pages if is_sight(p, city)], attempts


def category_of(page: Page) -> str | None:
    """The kind of sight a page describes ('Medieval fort in Jodhpur' -> history), from CATEGORY_WORDS."""
    text = f"{page.title} {page.description or ''}".lower()
    for category, words in config.CATEGORY_WORDS.items():
        if _has_word(text, words):
            return category
    return None


def popular(query: str, city: Location, limit: int, prefer: set[str] | None = None) -> tuple[list[Page], int]:
    """The best-known sights: the text search plus everything geotagged near the centre. Only pages with a
    description and at least POPULAR_MIN_VIEWS views count; the kinds in 'prefer' come first, then by views."""
    found, a1 = find(query, city, config.POPULAR_CANDIDATES)
    near, a2 = nearby(city)
    pages = [p for p in {p.title.lower(): p for p in found + near}.values()
             if p.description and (p.views or 0) >= config.POPULAR_MIN_VIEWS]
    prefer = prefer or set()
    pages.sort(key=lambda p: (category_of(p) not in prefer, -(p.views or 0)))
    return pages[:limit], a1 + a2


def _not_a_city(name: str) -> bool:
    key = name.strip().lower()
    return key == "india" or key in config.INDIAN_STATES_AND_UTS or key in config.STATE_ALIASES


def city_from_description(description: str | None) -> str | None:
    """'Medieval fort in Jodhpur, Rajasthan, India' -> 'Jodhpur'. A state or the country is not a city."""
    for m in re.finditer(r"\bin ([A-Z][^,]*?)(?:,|$)", description or ""):
        name = m.group(1).strip()
        if name and not _not_a_city(name):
            return name
    return None


def city_of(page: Page) -> tuple[str | None, int]:
    """The city a place is in: from its description, else the nearest page described as a city or town."""
    name = city_from_description(page.description)
    if name:
        return name, 0
    params = {"action": "query", "format": "json", "formatversion": 2, "generator": "geosearch",
              "ggscoord": f"{page.lat}|{page.lon}", "ggsradius": config.NEAR_CITY_RADIUS_KM * 1000,
              "ggslimit": 50, "prop": "coordinates|description", "colimit": "max"}
    data, attempts = get_json("places", API, params)
    towns = [p for p in parse_pages(data)
             if re.search(r"\b(city|town)\b", (p.description or "").lower()) and p.title != page.title]
    if not towns:
        return None, attempts
    nearest = min(towns, key=lambda p: distance_km(page.lat, page.lon, p.lat, p.lon))
    return nearest.title, attempts
