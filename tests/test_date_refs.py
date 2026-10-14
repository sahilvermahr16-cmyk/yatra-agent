"""Date references are turned into dates by code. Today is fixed to Monday 2026-10-12."""
import datetime as dt

from date_helpers import phrase_in_goal, resolve_date_ref
from normalize_node import normalize
from schemas import DateRef, TripRequest

TODAY = dt.date(2026, 10, 12)  # Monday


def d(month, day, year=2026):
    return dt.date(year, month, day)


def resolve(**ref):
    day, _ = resolve_date_ref(DateRef(phrase="x", **ref), TODAY)
    return day


def test_calendar_date_this_year():
    assert resolve(kind="calendar_date", day=20, month=10) == d(10, 20)


def test_calendar_date_already_passed_moves_to_next_year():
    day, note = resolve_date_ref(DateRef(phrase="2 Jan", kind="calendar_date", day=2, month=1), TODAY)
    assert day == d(1, 2, 2027)
    assert "already passed" in note


def test_calendar_date_with_written_year_is_kept():
    assert resolve(kind="calendar_date", day=5, month=3, year=2027) == d(3, 5, 2027)


def test_impossible_date_is_rejected():
    day, note = resolve_date_ref(DateRef(phrase="31 Feb", kind="calendar_date", day=31, month=2), TODAY)
    assert day is None and "not a real date" in note


def test_days_from_today():
    assert resolve(kind="days_from_today", offset_days=0) == d(10, 12)
    assert resolve(kind="days_from_today", offset_days=1) == d(10, 13)
    assert resolve(kind="days_from_today", offset_days=2) == d(10, 14)


def test_this_weekday_is_the_next_such_day():
    assert resolve(kind="weekday", weekday="friday", which="this") == d(10, 16)
    assert resolve(kind="weekday", weekday="thursday") == d(10, 15)


def test_weekday_named_today_means_next_week():
    assert resolve(kind="weekday", weekday="monday", which="this") == d(10, 19)


def test_next_weekday_is_in_next_week_and_explained():
    day, note = resolve_date_ref(DateRef(phrase="next Friday", kind="weekday",
                                         weekday="friday", which="next"), TODAY)
    assert day == d(10, 23)
    assert "next week" in note


def test_weekend():
    assert resolve(kind="weekend", which="this") == d(10, 17)
    assert resolve(kind="weekend", which="next") == d(10, 24)


def test_end_weekday_counts_from_the_start():
    ref = DateRef(phrase="till Sunday", kind="weekday", weekday="sunday")
    day, _ = resolve_date_ref(ref, TODAY, after=d(10, 21))
    assert day == d(10, 25)


def test_phrase_must_appear_in_goal():
    assert phrase_in_goal("this  Friday", "Varanasi trip This Friday for 3 days")
    assert not phrase_in_goal("8 Nov", "Ooty for 4 days starting 5 Nov")
    assert not phrase_in_goal("  ", "anything")


def test_phrase_from_a_compressed_range_is_accepted():
    goal = "Trip to Shimla from Oct 20-24 with friends"
    assert phrase_in_goal("Oct 24", goal)
    assert phrase_in_goal("October 24th", goal)
    assert not phrase_in_goal("Oct 25", goal)


def req(**fields):
    return TripRequest(destination="Varanasi", **fields)


def test_normalize_resolves_weekday_start():
    start = DateRef(phrase="this Friday", kind="weekday", weekday="friday", which="this")
    r, _ = normalize(req(start=start, days=3), "Varanasi trip this Friday for 3 days", TODAY)
    assert (r.start_date, r.end_date) == (d(10, 16), d(10, 18))


def test_normalize_weekend_covers_two_days():
    start = DateRef(phrase="Weekend", kind="weekend", which="this")
    r, _ = normalize(req(start=start), "Weekend in Pondicherry", TODAY)
    assert (r.start_date, r.end_date, r.days) == (d(10, 17), d(10, 18), 2)


def test_normalize_weekend_with_stated_length():
    start = DateRef(phrase="this weekend", kind="weekend", which="this")
    r, _ = normalize(req(start=start, days=3), "Goa this weekend for 3 days", TODAY)
    assert (r.start_date, r.end_date) == (d(10, 17), d(10, 19))


def test_normalize_drops_end_date_not_in_goal():
    # The LLM computed 8 Nov although the user only gave a start and a length
    start = DateRef(phrase="starting 5 Nov", kind="calendar_date", day=5, month=11)
    end = DateRef(phrase="8 Nov", kind="calendar_date", day=8, month=11)
    r, notes = normalize(req(start=start, end=end, days=4), "Ooty for 4 days starting 5 Nov", TODAY)
    assert (r.start_date, r.end_date) == (d(11, 5), d(11, 8))
    assert any("does not appear in the goal" in n for n in notes)


def test_normalize_till_weekday_after_dated_start():
    start = DateRef(phrase="from 21 Oct", kind="calendar_date", day=21, month=10)
    end = DateRef(phrase="till Sunday", kind="weekday", weekday="sunday")
    r, _ = normalize(req(start=start, end=end), "Ooty from 21 Oct till Sunday", TODAY)
    assert (r.start_date, r.end_date, r.days) == (d(10, 21), d(10, 25), 5)
