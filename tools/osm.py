"""OpenStreetMap tool (Overpass API, free, no key): places to stay and to eat around the planned sights.
One query per trip: lodging around each day's places and food around each place; the choice is made in code.

Diagnostic (no LLM): python -m tools.osm
  asks every server (one attempt each) a light query and the full query for a 2-day Jaipur trip, and prints
  status, time and size.
"""
import time
from urllib.parse import urlparse

from pydantic import BaseModel

import config
from tools.http import ToolError, get_json

LODGING = {"hotel", "guest_house", "hostel"}
FOOD = {"cafe", "restaurant", "fast_food", "food_court"}


class OsmPlace(BaseModel):
    name: str
    kind: str
    lat: float
    lon: float
    stars: int | None = None
    url: str


def build_query(day_centres: list[tuple[float, float]], place_points: list[tuple[float, float]]) -> str:
    """Overpass QL: named lodging near each day's centre, named food places near each sight."""
    lodging = "|".join(sorted(LODGING))
    food = "|".join(sorted(FOOD))
    parts = [f'nwr["tourism"~"^({lodging})$"]["name"](around:{config.HOTEL_SEARCH_KM * 1000},{lat:.5f},{lon:.5f});'
             for lat, lon in day_centres]
    parts += [f'nwr["amenity"~"^({food})$"]["name"](around:{config.FOOD_SEARCH_KM * 1000},{lat:.5f},{lon:.5f});'
              for lat, lon in place_points]
    return f"[out:json][timeout:{config.OSM_TIMEOUT_SECONDS}];(" + "".join(parts) + ");out center tags;"


def parse_elements(data) -> list[OsmPlace]:
    out, seen = [], set()
    for e in (data.get("elements") or []) if isinstance(data, dict) else []:
        tags = e.get("tags") or {}
        name = tags.get("name:en") or tags.get("name")
        kind = tags.get("tourism") if tags.get("tourism") in LODGING else tags.get("amenity")
        lat = e.get("lat", (e.get("center") or {}).get("lat"))
        lon = e.get("lon", (e.get("center") or {}).get("lon"))
        key = (e.get("type"), e.get("id"))
        if not name or kind not in LODGING | FOOD or lat is None or lon is None or key in seen:
            continue
        seen.add(key)
        stars = tags.get("stars", "")
        out.append(OsmPlace(name=name, kind=kind, lat=lat, lon=lon,
                            stars=int(stars[0]) if stars[:1].isdigit() else None,
                            url=f"https://www.openstreetmap.org/{e.get('type')}/{e.get('id')}"))
    return out


def fetch(day_centres: list[tuple[float, float]], place_points: list[tuple[float, float]]
          ) -> tuple[tuple[list[OsmPlace], str], int]:
    """Ask each Overpass server in turn until one answers: a quick refusal (429 / 5xx) is asked once more after a
    short wait, a timeout is not.
    Returns ((places, the server that answered), attempts). Raises ToolError naming every server's failure."""
    query = {"data": build_query(day_centres, place_points)}
    attempts, failures, last = 0, [], None
    for url in config.OSM_SERVERS:
        try:
            data, used = get_json("osm", url, query, timeout=config.OSM_CLIENT_TIMEOUT_SECONDS, retries=1,
                                  retry_timeouts=False, retry_wait=config.OSM_RETRY_WAIT_SECONDS)
        except ToolError as err:
            attempts += err.attempts
            failures.append(f"{urlparse(url).netloc}: {err.error_type} ({err.message})")
            last = err
            continue
        return (parse_elements(data), urlparse(url).netloc), attempts + used
    raise ToolError("osm", last.error_type if last else "network_error", "; ".join(failures), attempts)


# --- Diagnostic: is a failure the servers' load, or our query's weight? ---
JAIPUR_CENTRES = [(26.9530, 75.8230), (26.9200, 75.8150)]
JAIPUR_SIGHTS = [(26.9855, 75.8513), (26.9258, 75.8237), (26.9239, 75.8267),  # Amber Fort, City Palace, Hawa Mahal
                 (26.9535, 75.8462), (26.9373, 75.8155), (26.9116, 75.8195)]  # Jal Mahal, Nahargarh, Albert Hall


def _try(url: str, query: str) -> str:
    start = time.perf_counter()
    try:
        data, _ = get_json("osm", url, {"data": query}, timeout=config.OSM_CLIENT_TIMEOUT_SECONDS, retries=0)
    except ToolError as err:
        return f"FAIL {err.error_type} ({err.message}) after {time.perf_counter() - start:.1f} s"
    return f"ok   {len(parse_elements(data))} places in {time.perf_counter() - start:.1f} s"


if __name__ == "__main__":
    light = build_query([JAIPUR_CENTRES[0]], [])
    full = build_query(JAIPUR_CENTRES, JAIPUR_SIGHTS)
    print(f"light query: 1 hotel search, {len(light)} characters")
    print(f"full query:  {len(JAIPUR_CENTRES)} hotel + {len(JAIPUR_SIGHTS)} food searches, {len(full)} characters\n")
    for url in config.OSM_SERVERS:
        print(urlparse(url).netloc)
        print(f"  light: {_try(url, light)}")
        print(f"  full:  {_try(url, full)}")

