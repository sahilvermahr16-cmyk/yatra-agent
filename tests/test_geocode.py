"""Choosing a place from geocoding results is pure code, so it is tested on fixed API answers."""
from tools.geocode import pick_location


def entry(name, admin1, feature, population, country="IN", lat=26.9, lon=75.8):
    return {"name": name, "admin1": admin1, "feature_code": feature, "population": population,
            "country_code": country, "latitude": lat, "longitude": lon}


def test_places_outside_india_are_dropped():
    r = pick_location("Hyderabad", [entry("Hyderabad", "Sindh", "PPLA2", 1_700_000, country="PK"),
                                    entry("Hyderabad", "Telangana", "PPLA", 3_600_000)])
    assert r.chosen.region == "Telangana" and r.rejected_outside_india == 1


# Real answer for "Udaipur" (2026-10-13): the district town in Tripura is coded PPLA2, the famous city PPL.
UDAIPUR = [entry("Udaipur", "Tripura", "PPLA2", 32758, lat=23.53, lon=91.48),
           entry("Udaipur", "Rajasthan", "PPL", 451100, lat=24.57, lon=73.69),
           entry("Udaipur", "Rajasthan", "PPL", 30264, lat=24.60, lon=73.70),
           entry("Udaipur", "Odisha", "PPL", None)]


def test_the_bigger_place_beats_a_higher_administrative_level():
    r = pick_location("Udaipur", UDAIPUR)
    assert (r.chosen.region, r.chosen.population) == ("Rajasthan", 451100)
    assert r.ambiguous  # Tripura's town is 7% of it: worth a note, whatever its level


def test_the_point_of_the_travel_guide_decides():
    from tools.geocode import prefer_near
    ranked = pick_location("Aurangabad", [entry("Aurangabad", "Maharashtra", "PPLA2", 1_175_116, lat=19.88, lon=75.34),
                                          entry("Aurangabad", "Bihar", "PPL", 102_244, lat=24.75, lon=84.37)])
    assert prefer_near(ranked, 24.76, 84.38).chosen.region == "Bihar"  # the guide's page is about Bihar's
    assert prefer_near(ranked, 10.0, 10.0).chosen.region == "Maharashtra"  # nothing within 50 km: ranking stays


def test_population_breaks_a_tie_of_the_same_level():
    r = pick_location("Aurangabad", [entry("Aurangabad", "Bihar", "PPLA2", 100_000),
                                     entry("Aurangabad", "Maharashtra", "PPLA2", 1_200_000)])
    assert r.chosen.region == "Maharashtra"
    assert r.ambiguous  # same level in another state: the report must say which one was used


def test_a_lower_level_match_elsewhere_is_not_ambiguous():
    r = pick_location("Jaipur", [entry("Jaipur", "Rajasthan", "PPLA", 3_000_000),
                                 entry("Jaipur", "Odisha", "PPL", 5_000)])
    assert r.chosen.name == "Jaipur" and not r.ambiguous


def test_no_indian_match_is_not_an_error():
    r = pick_location("Xyzpur", [])
    assert r.chosen is None and r.alternatives == [] and not r.ambiguous


def test_incomplete_entries_are_skipped():
    broken = {"name": "Agra", "country_code": "IN"}  # no coordinates
    r = pick_location("Agra", [broken, entry("Agra", "Uttar Pradesh", "PPLA2", 1_500_000)])
    assert r.chosen.lat == 26.9 and r.alternatives == []


def test_alternatives_are_capped():
    many = [entry("Rampur", f"State {i}", "PPL", 1000 + i) for i in range(8)]
    r = pick_location("Rampur", many)
    assert len(r.alternatives) == 4


def test_geocode_sends_country_and_reads_results(monkeypatch):
    from tools import geocode as g
    seen = {}

    def fake_get_json(tool, url, params):
        seen.update(params)
        return {"results": [entry("Jaipur", "Rajasthan", "PPLA", 3_000_000)]}, 1

    monkeypatch.setattr(g, "get_json", fake_get_json)
    result, attempts = g.geocode("  Jaipur ")
    assert (seen["name"], seen["countryCode"], attempts) == ("Jaipur", "IN", 1)
    assert result.chosen.region == "Rajasthan"


def test_geocode_handles_an_answer_without_results(monkeypatch):
    from tools import geocode as g
    monkeypatch.setattr(g, "get_json", lambda tool, url, params: ({"generationtime_ms": 0.1}, 1))
    assert g.geocode("Xyzpur")[0].chosen is None


def test_a_tiny_or_unknown_namesake_is_not_ambiguous():
    r = pick_location("Jodhpur", [entry("Jodhpur", "Rajasthan", "PPLA2", 1_000_000),
                                  entry("Jodhpur", "Gujarat", "PPLA2", None)])
    assert not r.ambiguous


def test_a_different_name_is_never_chosen_but_kept_as_evidence():
    r = pick_location("Paris", [entry("Pariswani", "Jammu and Kashmir", "PPL", 1088),
                                entry("Parīsal", "Rajasthan", "PPL", None)])
    assert r.chosen is None and [o.name for o in r.other_matches] == ["Pariswani", "Parīsal"]


def test_only_towns_count_not_an_airport_or_a_toll_gate():
    r = pick_location("Mysore", [entry("Mysore Road Tolgate", "Karnataka", "PPL", None),
                                 entry("Mysore Airport", "Karnataka", "AIRP", None),
                                 entry("Mysore", "Karnataka", "ADM2", 3_000_000)])  # a district is not a town
    assert r.chosen is None and len(r.other_matches) == 3


def test_case_and_accents_do_not_matter():
    r = pick_location("parisal", [entry("Parīsal", "Rajasthan", "PPL", None)])
    assert r.chosen.name == "Parīsal" and r.other_matches == []
