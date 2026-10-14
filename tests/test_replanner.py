"""The budget loop with a fake replanner LLM: fixes, ignores bad choices, falls back, stays honest."""
import datetime as dt
import os

import pytest

pytest.importorskip("langchain_openai")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

import replanner_node as rn  # noqa: E402
from schemas import DayPlan, Itinerary, Place, ReplanDecision, TripRequest  # noqa: E402

START = dt.date(2026, 10, 24)


def request(**fields):
    base = dict(destination="Udaipur", start_date=START, end_date=START + dt.timedelta(days=3), days=4, nights=3,
                travellers=2, total_budget=15000, budget_ceiling=15000)
    base.update(fields)
    return TripRequest(**base)


IT = Itinerary(days=[DayPlan(day=1, date=START, reason="r", places=[
    Place(name=f"P{i}", lat=0, lon=0, distance_km=1, serves="popular", wish="w", category="popular", indoor=False,
          entry_fee=100) for i in range(12)])])


@pytest.fixture(autouse=True)
def no_retiming(monkeypatch):
    """These tests are about money: the 12 sights of IT stay in one day (timing is tested in test_stays)."""
    monkeypatch.setattr(rn.stays, "assign", lambda it, *args, **kwargs: (it, []))


class FakeLLM:
    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def invoke(self, messages):
        self.calls.append(messages)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def test_within_budget_needs_no_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(rn, "structured_llm", fake)
    _, cost, verdict, _, notes, rounds = rn.fit_budget(request(budget_ceiling=50000), IT)
    assert verdict.status == "within" and rounds == 0 and fake.calls == [] and notes == []


def test_replanner_choice_fits_the_budget(monkeypatch):
    fake = FakeLLM(ReplanDecision(actions=["lower_hotel", "lower_food"], reason="you named no comfort level"))
    monkeypatch.setattr(rn, "structured_llm", fake)
    _, cost, verdict, trace, notes, rounds = rn.fit_budget(request(), IT)
    assert verdict.status == "within" and cost.total == 14000 and rounds == 1
    facts = fake.calls[0][1][1]
    assert "OVER by Rs 12,000" in facts and "lower_hotel" in facts and "saves Rs 8,200" in facts
    assert "first draft cost Rs 27,000" in notes[0] and "Rs 14,000" in notes[0]
    assert [e.event for e in trace] == ["cost", "replan", "cost"]  # check, one round, check again


def test_not_enough_in_round_one_continues_in_round_two(monkeypatch):
    fake = FakeLLM(ReplanDecision(actions=["use_public_transport"], reason="a"),
                   ReplanDecision(actions=["lower_hotel", "lower_food"], reason="b"))
    monkeypatch.setattr(rn, "structured_llm", fake)
    _, _, verdict, _, _, rounds = rn.fit_budget(request(), IT)
    assert rounds == 2 and verdict.status == "within"


def test_a_change_against_the_users_words_is_ignored(monkeypatch):
    fake = FakeLLM(ReplanDecision(actions=["lower_hotel"], reason="x"), ReplanDecision(actions=[], reason="y"))
    monkeypatch.setattr(rn, "structured_llm", fake)
    _, _, _, trace, notes, _ = rn.fit_budget(request(budget_style="mid"), IT)
    assert trace[1].detail["ignored"] == ["lower_hotel"] and any("ignored changes" in n for n in notes)


def test_unreadable_answers_fall_back_to_the_default_order(monkeypatch):
    from langchain_core.exceptions import OutputParserException
    fake = FakeLLM(OutputParserException("bad"), OutputParserException("bad"))
    monkeypatch.setattr(rn, "structured_llm", fake)
    _, _, verdict, trace, _, _ = rn.fit_budget(request(), IT)
    assert "replanner_fallback" in [e.event for e in trace] and verdict.status == "within"


def test_still_over_after_every_change_is_reported_honestly(monkeypatch):
    many = [ReplanDecision(actions=["lower_hotel", "lower_food", "use_public_transport"] + ["drop_paid_place"] * 12,
                           reason="all")]
    monkeypatch.setattr(rn, "structured_llm", FakeLLM(*many, *many, *many))
    _, cost, verdict, _, notes, _ = rn.fit_budget(request(budget_ceiling=5000, total_budget=5000), IT)
    assert verdict.status == "over"
    assert "the cheapest plan that keeps your wishes costs" in notes[-1]
    assert "fewer days or a higher budget" in notes[-1]


def test_facts_say_which_change_is_enough_and_the_fewest_that_close_the_gap(monkeypatch):
    fake = FakeLLM(ReplanDecision(actions=["lower_hotel", "lower_food"], reason="r"))
    monkeypatch.setattr(rn, "structured_llm", fake)
    rn.fit_budget(request(), IT)
    facts = fake.calls[0][1][1]
    assert "saves Rs 8,200" in facts and "enough alone: no" in facts
    assert "Fewest changes that close the gap (largest first): lower_hotel + lower_food" in facts
