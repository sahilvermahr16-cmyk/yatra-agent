"""normalize() is pure code, so these tests need no network and no OpenAI key."""
import datetime as dt

import config
from normalize_node import normalize
from schemas import DateRef, PlaceType, TripRequest

TODAY = dt.date(2026, 10, 12)  # Monday
TOMORROW = dt.date(2026, 10, 13)


def cal(phrase, month, day):
    return DateRef(phrase=phrase, kind="calendar_date", day=day, month=month)


def run(goal, **fields):
    return normalize(TripRequest(destination="Jaipur", **fields), goal, TODAY)


def test_dates_give_days_and_nights():
    r, _ = run("Jaipur 20 to 23 Oct", start=cal("20 to 23 Oct", 10, 20), end=cal("20 to 23 Oct", 10, 23))
    assert (r.days, r.nights) == (4, 3)


def test_dates_win_over_conflicting_days():
    r, notes = run("Jaipur 3 days, 20 to 25 Oct", days=3,
                   start=cal("20 to 25 Oct", 10, 20), end=cal("20 to 25 Oct", 10, 25))
    assert r.days == 6
    assert any("dates were used" in n for n in notes)


def test_past_start_moves_to_tomorrow():
    r, notes = run("Jaipur from 1 Oct 2026 for 2 days", days=2,
                   start=DateRef(phrase="1 Oct 2026", kind="calendar_date", day=1, month=10, year=2026))
    assert r.start_date == TOMORROW
    assert any("in the past" in n for n in notes)


def test_end_before_start_is_ignored():
    r, notes = run("Jaipur 25 to 20 Oct", days=2,
                   start=cal("25 to 20 Oct", 10, 25), end=cal("25 to 20 Oct", 10, 20))
    assert r.end_date == dt.date(2026, 10, 26)
    assert any("before the start" in n for n in notes)


def test_defaults_when_nothing_given():
    r, notes = run("Plan a trip to Jaipur")
    assert r.days == config.DEFAULT_DAYS
    assert r.start_date == TOMORROW
    assert r.travellers == config.DEFAULT_TRAVELLERS
    assert r.interests == config.DEFAULT_INTERESTS
    assert r.total_budget == config.DEFAULT_BUDGET_PER_PERSON_PER_DAY * r.days
    # our own default is a guide only: no limit, so the plan is never cut to fit a number the user never gave
    assert (r.budget_ceiling, r.budget_floor) == (None, None)
    assert len(notes) == 5  # days, start, travellers, budget, interests


def test_long_trip_is_capped():
    r, notes = run("Jaipur for 15 days", days=15)
    assert r.days == config.MAX_DAYS
    assert any("limited" in n for n in notes)


def test_one_day_trip_has_no_nights():
    r, _ = run("Jaipur day trip", days=1)
    assert r.nights == 0


def test_budget_total():
    cases = [
        (dict(), 15000),                                                 # total
        (dict(budget_is_per_day=True), 15000 * 3),                       # per day
        (dict(budget_is_per_person=True), 15000 * 2),                    # per person
        (dict(budget_is_per_person=True, budget_is_per_day=True), 15000 * 2 * 3),
    ]
    for flags, expected in cases:
        r, _ = run("Jaipur 3 days for 2 people", days=3, travellers=2, budget_amount=15000, **flags)
        assert r.total_budget == expected, flags


def test_per_person_budget_without_group_size_is_flagged():
    r, notes = run("Jaipur 2 days, 10000 per person", days=2, budget_amount=10000, budget_is_per_person=True)
    assert r.total_budget == 10000
    assert any("per person but the group size" in n for n in notes)


def test_must_visit_duplicates_removed():
    r, _ = run("Jaipur", must_visit=["Amber Fort", "amber fort", "Hawa Mahal"])
    assert r.must_visit == ["Amber Fort", "Hawa Mahal"]


def test_bare_budget_uses_the_configured_default():
    r, notes = run("Jaipur 2 days, budget 10000", days=2, travellers=1, budget_amount=10000)
    assert config.PLAIN_BUDGET_DIRECTION == "at_most"
    assert (r.total_budget, r.budget_ceiling, r.budget_floor) == (10000, 10000, None)
    assert any("treated as a maximum" in n for n in notes)


def test_each_direction_gives_its_bounds_without_a_note():
    expected = {
        "at_most": (10000, 10000, None),
        "about": (10000, 11000, None),
        "at_least": (10000, None, 10000),
    }
    for direction, bounds in expected.items():
        r, notes = run("Jaipur 2 days", days=2, travellers=1, budget_amount=10000, budget_direction=direction)
        assert (r.total_budget, r.budget_ceiling, r.budget_floor) == bounds, direction
        assert not any("treated as" in n for n in notes)


def test_range_per_person_gives_floor_and_ceiling_for_the_group():
    r, _ = run("Bhopal 2 days for 2, 6000-8000 per person", days=2, travellers=2, budget_amount=6000,
               budget_amount_max=8000, budget_is_per_person=True, budget_direction="range")
    assert (r.total_budget, r.budget_ceiling, r.budget_floor) == (14000, 16000, 12000)


def test_range_with_one_number_becomes_an_estimate_with_a_note():
    r, notes = run("Bhopal 2 days, around 6000", days=2, travellers=1, budget_amount=6000,
                   budget_phrase="around 6000", budget_direction="range")
    assert r.budget_ceiling == round(6000 * (1 + config.BUDGET_FLEX))
    assert any("Only one budget figure" in n for n in notes)


def test_larger_number_is_ignored_outside_a_range():
    r, _ = run("Bhopal 2 days, up to 6000", days=2, travellers=1, budget_amount=6000,
               budget_amount_max=8000, budget_direction="at_most")
    assert (r.total_budget, r.budget_ceiling) == (6000, 6000)


def test_interests_combine_direct_purposes_and_place_types():
    r, notes = run("Jaipur, history buff, stepwells and kebabs", interests=["history"],
                   place_types=[PlaceType(words="stepwells", interests=["history", "culture"]),
                                PlaceType(words="kebabs", interests=["food"])])
    assert r.interests == ["history", "culture", "food"]
    assert not any("No interests" in n for n in notes)


def test_budget_phrase_is_named_in_the_note_when_undecided():
    r, notes = run("Jaipur 2 days, budget 10000", days=2, travellers=1, budget_amount=10000,
                   budget_phrase="budget 10000")
    assert any("'budget 10000'" in n for n in notes)
