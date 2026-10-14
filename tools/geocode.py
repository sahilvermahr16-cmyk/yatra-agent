"""Geocode tool: place name -> coordinates in India (Open-Meteo geocoding, free, no API key).

Usage for a manual check: python -m tools.geocode Jaipur
"""
import sys
import unicodedata

import config
from schemas import GeocodeResult, Location
from tools.geo import distance_km
from tools.http import get_json

URL = "https://geocoding-api.open-meteo.com/v1/search"
MAX_ALTERNATIVES = 4


def _rank(loc: Location) -> tuple[int, int]:
    """Lower is better: the bigger place first (a traveller means the well-known one: Udaipur in Rajasthan,
    451,100 people, not the district town in Tripura); the administrative level only breaks ties."""
    priority = config.GEOCODE_FEATURE_PRIORITY
    level = priority.index(loc.feature_code) if loc.feature_code in priority else len(priority)
    return -(loc.population or 0), level


def _comparable(alt: Location, chosen: Location) -> bool:
    """A namesake only matters if it is a real town: its population is known and not tiny next to the chosen one."""
    if alt.population is None:
        return False
    return chosen.population is None or alt.population >= config.AMBIGUOUS_MIN_POPULATION_SHARE * chosen.population


def same_name(a: str, b: str) -> bool:
    """'Parīsal' == 'parisal'; case, accents, spaces and dots do not count."""
    def key(text: str) -> str:
        plain = unicodedata.normalize("NFKD", text)
        return "".join(ch for ch in plain if ch.isalnum()).lower()
    return key(a) == key(b)


def is_town(loc: Location) -> bool:
    """A populated place (GeoNames PPL, PPLA, PPLC ...), not an airport, a toll gate's road or a district."""
    return (loc.feature_code or "").startswith("PPL")


def pick_location(query: str, results: list[dict]) -> GeocodeResult:
    """Pure code: keep Indian towns with the searched name, rank them, flag a tie with another state.
    The API matches the start of a name ('Paris' -> 'Pariswani'), so other names are never chosen; they are kept
    in other_matches as evidence of where the place is."""
    indian, rejected = [], 0
    for r in results:
        if r.get("country_code") != config.GEOCODE_COUNTRY:
            rejected += 1  # the API can return matches outside India even with countryCode=IN
            continue
        if r.get("name") is None or r.get("latitude") is None or r.get("longitude") is None:
            continue  # an incomplete entry is useless for the later tools
        indian.append(Location(name=r["name"], lat=r["latitude"], lon=r["longitude"], region=r.get("admin1"),
                               feature_code=r.get("feature_code"), population=r.get("population")))
    matching = [loc for loc in indian if same_name(loc.name, query) and is_town(loc)]
    others = [loc for loc in indian if loc not in matching]
    if not matching:
        return GeocodeResult(query=query, rejected_outside_india=rejected, other_matches=others)
    matching.sort(key=_rank)
    return _result(query, matching, rejected, others)


def _result(query: str, ordered: list[Location], rejected: int, others: list[Location]) -> GeocodeResult:
    chosen, rest = ordered[0], ordered[1:]
    ambiguous = any(alt.region != chosen.region and _comparable(alt, chosen) for alt in rest)
    return GeocodeResult(query=query, chosen=chosen, alternatives=rest[:MAX_ALTERNATIVES],
                         rejected_outside_india=rejected, ambiguous=ambiguous, other_matches=others)


def prefer_near(result: GeocodeResult, lat: float, lon: float) -> GeocodeResult:
    """Choose the match nearest to a known point (the Wikivoyage page's own coordinates), if one lies within
    GEOCODE_TRUST_KM of it; otherwise keep the ranking. This is how 'Udaipur' means the travellers' Udaipur."""
    if result.chosen is None:
        return result
    options = [result.chosen] + result.alternatives
    nearest = min(options, key=lambda o: distance_km(lat, lon, o.lat, o.lon))
    if distance_km(lat, lon, nearest.lat, nearest.lon) > config.GEOCODE_TRUST_KM or nearest is result.chosen:
        return result
    ordered = [nearest] + [o for o in options if o is not nearest]
    return _result(result.query, ordered, result.rejected_outside_india, result.other_matches)


def geocode(name: str) -> tuple[GeocodeResult, int]:
    """Look up a place name. Returns (result, attempts used). Raises ToolError if the API fails."""
    params = {"name": name.strip(), "count": 10, "language": "en", "format": "json",
              "countryCode": config.GEOCODE_COUNTRY}
    data, attempts = get_json("geocode", URL, params)
    results = (data.get("results") or []) if isinstance(data, dict) else []
    return pick_location(name.strip(), results), attempts


if __name__ == "__main__":
    for query in sys.argv[1:] or ["Jaipur"]:
        result, attempts = geocode(query)
        print(f"\n{query!r} ({attempts} attempt(s)), rejected outside India: {result.rejected_outside_india}")
        if result.chosen is None:
            print("  no town in India with this name")
            for o in result.other_matches[:MAX_ALTERNATIVES]:
                print(f"  other name: {o.name}, {o.region} {o.feature_code} pop={o.population}")
            continue
        c = result.chosen
        print(f"  chosen: {c.name}, {c.region} ({c.lat:.4f}, {c.lon:.4f}) {c.feature_code} pop={c.population}")
        print(f"  ambiguous: {result.ambiguous}")
        for alt in result.alternatives:
            print(f"  also:   {alt.name}, {alt.region} {alt.feature_code} pop={alt.population}")
