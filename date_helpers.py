"""Calendar arithmetic in code. The LLM only says how a date was named (a DateRef)."""

import datetime as dt
import re
from schemas import DateRef

_MONTH_WORDS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def next_weekday(today: dt.date, weekday: int) -> dt.date:
    """The next such weekday after today (never today itself)."""
    return today + dt.timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)

def weekday_next_week(today: dt.date, weekday: int) -> dt.date:
    """That weekday in the calendar week after this one ("next Friday")."""
    next_monday = today + dt.timedelta(days=7 - today.weekday())
    return next_monday + dt.timedelta(days=weekday)

def coming_weekend(today: dt.date) -> tuple[dt.date, dt.date]:
    """Next Saturday and Sunday. On Saturday this is today; on Sunday it is the next weekend."""
    days_to_sat = 6 if today.weekday() == 6 else (5 - today.weekday()) % 7
    sat = today + dt.timedelta(days=days_to_sat)
    return sat, sat + dt.timedelta(days=1)

def _tokens(text: str) -> set[str]:
    """Words and numbers, with ordinals ('24th' -> '24') and month names ('October' -> 'oct') normalised."""
    out = set()
    for tok in re.findall(r"[a-z]+|\d+", text.lower()):
        if tok in ("st", "nd", "rd", "th"):
            continue
        if tok.isdigit():
            tok = str(int(tok))
        elif len(tok) >= 3 and tok[:3] in _MONTH_WORDS:
            tok = tok[:3]
        out.add(tok)
    return out

def phrase_in_goal(phrase: str, goal: str) -> bool:
    """True if every word and number of a copied phrase (date or budget) appears in the goal.

    Word by word rather than as one string, so 'Oct 24' is accepted for 'Oct 20-24',
    while a number the user never wrote ('8 Nov' for 'starting 5 Nov') is not.
    """
    words = _tokens(phrase)
    return bool(words) and words <= _tokens(goal)

def resolve_date_ref(ref: DateRef, today: dt.date, after: dt.date | None = None
                     ) -> tuple[dt.date | None, str | None]:
    """Turn a DateRef into a date. Returns (date, note); date is None if it cannot be resolved.

    `after` is the resolved start date when resolving an end date, so "till Sunday"
    means the first Sunday on or after the start.
    """
    if ref.kind == "calendar_date":
        if ref.day is None or ref.month is None:
            return None, f"'{ref.phrase}' has no day and month, so it was not used as a date."
        try:
            if ref.year is not None:
                return dt.date(ref.year, ref.month, ref.day), None
            day = dt.date(today.year, ref.month, ref.day)
            if day < today:
                day = dt.date(today.year + 1, ref.month, ref.day)
                return day, f"'{ref.phrase}' has already passed this year, so {day} was used."
            return day, None
        except ValueError:
            return None, f"'{ref.phrase}' is not a real date, so it was ignored."

    if ref.kind == "days_from_today":
        if ref.offset_days is None:
            return None, f"'{ref.phrase}' could not be read as a date, so it was ignored."
        return today + dt.timedelta(days=ref.offset_days), None

    if ref.kind == "weekday":
        if ref.weekday is None:
            return None, f"'{ref.phrase}' has no weekday, so it was ignored."
        idx = WEEKDAYS.index(ref.weekday)
        if after is not None:
            first = after + dt.timedelta(days=(idx - after.weekday()) % 7)
            if ref.which == "next":
                day = max(weekday_next_week(today, idx), first)
                return day, f"'{ref.phrase}' was read as {ref.weekday.capitalize()} {day} (the one in next week)."
            return first, None
        if ref.which == "next":
            day = weekday_next_week(today, idx)
            return day, f"'{ref.phrase}' was read as {ref.weekday.capitalize()} {day} (the one in next week)."
        return next_weekday(today, idx), None

    if ref.kind == "weekend":
        sat, _ = coming_weekend(today)
        if ref.which == "next":
            sat += dt.timedelta(days=7)
        return sat, None

    return None, f"'{ref.phrase}' could not be read as a date, so it was ignored."

# ---------------------------------------------------------------- checks on the LLM's DateRefs

_WEEKDAY_ABBR = {"monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "wed": 2,
                 "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4, "fri": 4,
                 "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}
_WEEKDAY_RE = re.compile(r"\b(" + "|".join(_WEEKDAY_ABBR) + r")s?\b")

def _days_in(phrase: str) -> list[int]:
    return [int(n) for n in re.findall(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?(?!\d)", phrase.lower())]

def _months_in(phrase: str) -> list[int]:
    """Months named in words, plus the month of a numeric day/month such as '5/11' (Indian DD/MM)."""
    text = phrase.lower()
    months = [i + 1 for i, m in enumerate(_MONTH_WORDS) if re.search(rf"\b{m}[a-z]*\b", text)]
    for _, month in re.findall(r"(?<!\d)(\d{1,2})\s*[/.]\s*(\d{1,2})(?!\d)", text):
        if 1 <= int(month) <= 12:
            months.append(int(month))
    return months

def fix_kind_from_phrase(ref: DateRef) -> tuple[DateRef, str | None]:
    """Words in the phrase decide kind/weekday/which when they are unambiguous; the code wins."""
    text = ref.phrase.lower()
    which = "next" if re.search(r"\bnext\b", text) else "this"
    weekdays = {_WEEKDAY_ABBR[m.group(1)] for m in _WEEKDAY_RE.finditer(text)}
    fixed = None
    if re.search(r"\bweekend\b", text):
        fixed = ref.model_copy(update={"kind": "weekend", "which": which})
    elif len(weekdays) == 1 and not _days_in(text):
        fixed = ref.model_copy(update={"kind": "weekday", "weekday": WEEKDAYS[weekdays.pop()], "which": which})
    elif re.search(r"\bday after tomorrow\b", text):
        fixed = ref.model_copy(update={"kind": "days_from_today", "offset_days": 2})
    elif re.search(r"\btomorrow\b", text):
        fixed = ref.model_copy(update={"kind": "days_from_today", "offset_days": 1})
    elif re.search(r"\btoday\b", text):
        fixed = ref.model_copy(update={"kind": "days_from_today", "offset_days": 0})
    if fixed is None:
        return ref, None
    keys = ("kind", "weekday", "which", "offset_days")
    if all(getattr(fixed, k) == getattr(ref, k) for k in keys):
        return ref, None
    if fixed.kind == "days_from_today":
        desc = f"{fixed.offset_days} day(s) from today"
    elif fixed.kind == "weekday":
        desc = f"{fixed.which} {fixed.weekday}"
    else:
        desc = f"{fixed.which} weekend"
    return fixed, f"'{ref.phrase}' was re-read from its own words as {desc}."

def ref_problems(ref: DateRef, goal: str, start: DateRef | None = None) -> list[str]:
    """Ways the DateRef disagrees with its own phrase. Empty list = consistent.

    `start` is passed when checking the end, so a range phrase shared by both edges
    and an end date that borrows the start's month ("from 3rd Nov till the 7th") are allowed.
    """
    if not phrase_in_goal(ref.phrase, goal):
        return [f"the phrase '{ref.phrase}' does not appear in the goal"]
    problems = []
    days, months = _days_in(ref.phrase), _months_in(ref.phrase)
    if ref.kind == "calendar_date":
        if ref.day is None or ref.month is None:
            return [f"'{ref.phrase}' names no exact day, so it is not a date"]
        if ref.day not in days:
            problems.append(f"day {ref.day} is not written in '{ref.phrase}'")
        borrowed = start is not None and start.kind == "calendar_date" and ref.month == start.month
        if ref.month not in months and not borrowed:
            problems.append(f"month {ref.month} is not written in '{ref.phrase}'")
        if ref.year is not None and str(ref.year) not in ref.phrase:
            problems.append(f"year {ref.year} is not written in '{ref.phrase}'")
        if start is not None and start.phrase.strip().lower() == ref.phrase.strip().lower() and len(set(days)) < 2:
            problems.append(f"'{ref.phrase}' names only one day, so it cannot be both the start and the end")
    elif ref.kind == "weekday":
        if not ref.weekday or not _WEEKDAY_RE.search(ref.phrase.lower()):
            problems.append(f"no weekday is written in '{ref.phrase}'")
    elif ref.kind == "weekend":
        if "weekend" not in ref.phrase.lower():
            problems.append(f"'weekend' is not written in '{ref.phrase}'")
    elif ref.kind == "days_from_today":
        text = ref.phrase.lower()
        named = re.search(r"\b(today|tomorrow)\b", text)
        if not named and ref.offset_days not in days:
            problems.append(f"{ref.offset_days} days from today is not written in '{ref.phrase}'")
    return problems

def check_date_refs(start: DateRef | None, end: DateRef | None, goal: str
                    ) -> tuple[DateRef | None, DateRef | None, list[str]]:
    """Code net for the LLM's dates: re-read kind from the phrase, then drop any ref
    that still disagrees with its own phrase. Returns (start, end, notes)."""
    notes = []
    checked = {}
    for label, ref in (("Start", start), ("End", end)):
        if ref is None:
            checked[label] = None
            continue
        ref, note = fix_kind_from_phrase(ref)
        if note:
            notes.append(note)
        if re.search(r"\bafter next\b", ref.phrase.lower()):
            notes.append(f"'{ref.phrase}' was read as 'next'; two weeks ahead is not supported, "
                         "so please give exact dates if this is wrong.")
        problems = ref_problems(ref, goal, start=checked.get("Start") if label == "End" else None)
        if problems:
            notes.append(f"{label} date ignored because " + "; ".join(problems) + ".")
            ref = None
        checked[label] = ref
    return checked["Start"], checked["End"], notes
