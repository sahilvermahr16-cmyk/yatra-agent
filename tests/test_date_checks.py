"""Code nets on the LLM's DateRefs: kind re-read from the phrase, and numbers checked against it."""
import datetime as dt

from date_helpers import check_date_refs, fix_kind_from_phrase, ref_problems
from normalize_node import normalize
from schemas import DateRef, TripRequest

TODAY = dt.date(2026, 10, 12)  # Monday


def cal(phrase, day, month, year=None):
    return DateRef(phrase=phrase, kind="calendar_date", day=day, month=month, year=year)


def test_next_in_phrase_overrides_this():
    ref = DateRef(phrase="next Saturday", kind="weekday", weekday="saturday", which="this")
    fixed, note = fix_kind_from_phrase(ref)
    assert fixed.which == "next" and "re-read" in note


def test_weekday_name_overrides_wrong_kind():
    ref = cal("on Thu", 15, 10)
    fixed, _ = fix_kind_from_phrase(ref)
    assert (fixed.kind, fixed.weekday, fixed.which) == ("weekday", "thursday", "this")


def test_tomorrow_overrides_wrong_offset():
    ref = DateRef(phrase="from tomorrow", kind="days_from_today", offset_days=0)
    fixed, _ = fix_kind_from_phrase(ref)
    assert fixed.offset_days == 1


def test_consistent_ref_is_untouched():
    ref = DateRef(phrase="this Friday", kind="weekday", weekday="friday", which="this")
    assert fix_kind_from_phrase(ref) == (ref, None)


def test_dated_phrase_with_weekday_is_not_rewritten():
    ref = cal("Friday 23 Oct", 23, 10)
    assert fix_kind_from_phrase(ref)[0].kind == "calendar_date"


def test_wrong_day_number_is_a_problem():
    goal = "Kodaikanal from 5 Nov for 4 days"
    assert ref_problems(cal("from 5 Nov", 5, 11), goal) == []
    assert any("day 8" in p for p in ref_problems(cal("from 5 Nov", 8, 11), goal))


def test_wrong_month_is_a_problem():
    goal = "Kodaikanal from 5 Nov"
    assert any("month 12" in p for p in ref_problems(cal("from 5 Nov", 5, 12), goal))


def test_end_may_borrow_start_month():
    goal = "Tawang from the 3rd of November till the 7th"
    start = cal("from the 3rd of November", 3, 11)
    assert ref_problems(cal("till the 7th", 7, 11), goal, start=start) == []


def test_range_phrase_shared_by_both_edges():
    goal = "Gokarna from Dec 28 to Jan 2"
    start = cal("Dec 28 to Jan 2", 28, 12)
    assert ref_problems(cal("Dec 28 to Jan 2", 2, 1), goal, start=start) == []


def test_start_phrase_copied_into_end_is_a_problem():
    goal = "Kodaikanal from 12 Nov for 4 days"
    start = cal("from 12 Nov", 12, 11)
    problems = ref_problems(cal("from 12 Nov", 15, 11), goal, start=start)
    assert problems  # day 15 is not in the phrase, and one day cannot be both edges


def test_unwritten_year_is_a_problem():
    goal = "Kodaikanal on 5 Jan"
    assert any("year" in p for p in ref_problems(cal("on 5 Jan", 5, 1, 2028), goal))


def test_check_date_refs_drops_bad_end_and_keeps_start():
    goal = "Kodaikanal from 5 Nov for 4 days"
    start, end, notes = check_date_refs(cal("from 5 Nov", 5, 11), cal("from 5 Nov", 8, 11), goal)
    assert start is not None and end is None
    assert any("End date ignored" in n for n in notes)


def test_normalize_uses_the_reread_weekday():
    start = DateRef(phrase="next Saturday", kind="weekday", weekday="saturday", which="this")
    r, notes = normalize(TripRequest(destination="Khajuraho", start=start, days=1),
                         "Khajuraho next Saturday for a day", TODAY)
    assert r.start_date == dt.date(2026, 10, 24)
    assert any("re-read" in n for n in notes)


def test_next_weekday_as_end_is_next_week():
    start = DateRef(phrase="on Friday", kind="weekday", weekday="friday", which="this")
    end = DateRef(phrase="next Sunday", kind="weekday", weekday="sunday", which="next")
    r, notes = normalize(TripRequest(destination="Orchha", start=start, end=end),
                         "Orchha on Friday, returning next Sunday", TODAY)
    assert (r.start_date, r.end_date) == (dt.date(2026, 10, 16), dt.date(2026, 10, 25))
    assert any("next week" in n for n in notes)


def test_numeric_day_month_is_accepted():
    assert ref_problems(cal("on 5/11", 5, 11), "Bundi on 5/11 for 3 days") == []
    assert ref_problems(cal("on 5/11", 5, 12), "Bundi on 5/11 for 3 days")  # wrong month still caught


def test_range_with_dash_is_not_a_month():
    # '20-24' is a range of days, not day 20 of month 24 or day 20 of month 12
    assert any("month" in p for p in ref_problems(cal("20-12", 20, 12), "Shimla 20-12"))


def test_month_without_day_has_a_clear_note():
    ref = DateRef(phrase="the first week of November", kind="calendar_date", month=11)
    _, _, notes = check_date_refs(ref, None, "Pachmarhi in the first week of November")
    assert any("names no exact day" in n for n in notes)


def test_after_next_gets_a_warning():
    ref = DateRef(phrase="the weekend after next", kind="weekend", which="next")
    _, _, notes = check_date_refs(ref, None, "Lonavala over the weekend after next")
    assert any("two weeks ahead is not supported" in n for n in notes)
