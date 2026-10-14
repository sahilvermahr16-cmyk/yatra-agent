"""Planner: trip facts, plan checks, default plan and the retry/fallback flow. The LLM is faked."""
import datetime as dt
import os

import pytest

from plan_checks import default_plan, forecast_available, plan_problems, purposes_needing_search, tidy, trip_facts
from schemas import PlaceType, Plan, PlanStep, TripRequest

TODAY = dt.date(2026, 10, 12)


def request(start_in=5, **fields):
    start = TODAY + dt.timedelta(days=start_in)
    base = dict(destination="Jodhpur", start_date=start, end_date=start + dt.timedelta(days=2), days=3,
                travellers=2, total_budget=30000, budget_ceiling=30000, interests=["popular"])
    base.update(fields)
    return TripRequest(**base)


RICH = dict(must_visit=["Mehrangarh Fort"],
            place_types=[PlaceType(words="stepwells", interests=["history", "culture"])],
            interests=["food", "history", "culture"])


def step(tool, query=None, serves=None):
    return PlanStep(step=1, tool=tool, query=query, serves=serves, reason="because")


def good_plan(weather=True):
    steps = [step("resolve_destination")] + ([step("weather")] if weather else []) + [
        step("locate_place", "Mehrangarh Fort", "must_visit"),
        step("find_places", "stepwell", "place_type"),
        step("find_places", "food market", "interest"),
        step("find_places", "tourist attraction", "popular"),
        step("build_itinerary"), step("find_stays_and_food"), step("estimate_costs"), step("check_budget")]
    return Plan(summary="3 days in Jodhpur", steps=steps)


def test_forecast_window_is_computed_by_code():
    assert forecast_available(request(start_in=15), TODAY)
    assert not forecast_available(request(start_in=16), TODAY)


def test_a_purpose_served_by_a_kind_of_place_needs_no_search():
    assert purposes_needing_search(request(**RICH)) == ["food"]


def test_trip_facts_carry_the_computed_facts():
    facts = trip_facts(request(**RICH), TODAY)
    assert "starts in 5 days; a forecast IS available" in facts
    assert "food (needs its own search)" in facts and "history (already served" in facts
    assert '"stepwells" (history, culture)' in facts
    assert "(not in the list of Indian states)" in facts
    assert "(in the list" in trip_facts(request(destination="Rajasthan"), TODAY)


def test_a_good_plan_has_no_problems():
    assert plan_problems(good_plan(), request(**RICH), TODAY) == []


def test_missing_must_visit_is_reported():
    plan = good_plan()
    plan.steps = [s for s in plan.steps if s.tool != "locate_place"]
    assert any("Mehrangarh Fort" in p for p in plan_problems(plan, request(**RICH), TODAY))


def test_weather_without_forecast_is_reported():
    problems = plan_problems(good_plan(weather=True), request(start_in=30, **RICH), TODAY)
    assert any("NOT available" in p for p in problems)


def test_extra_wish_the_user_did_not_ask_for_is_reported():
    plan = good_plan()
    plan.steps.insert(5, step("find_places", "temple", "interest"))
    assert any("purpose that needs its own search" in p for p in plan_problems(plan, request(**RICH), TODAY))


def test_wrong_order_is_reported():
    plan = good_plan()
    plan.steps = plan.steps[:-4] + [step("check_budget"), step("estimate_costs"), step("find_stays_and_food"),
                                    step("build_itinerary")]
    assert any("in that order" in p for p in plan_problems(plan, request(**RICH), TODAY))


def test_place_step_after_costs_is_reported():
    plan = good_plan()
    plan.steps.insert(-1, step("find_places", "museum", "popular"))
    problems = plan_problems(plan, request(**RICH), TODAY)
    assert any("come before build_itinerary" in p or "popular" in p for p in problems)


def test_long_query_is_reported():
    plan = good_plan()
    plan.steps[3] = step("find_places", "beautiful old stepwells that look amazing", "place_type")
    assert any("too long" in p for p in plan_problems(plan, request(**RICH), TODAY))


RAJASTHAN = {"destination": "Rajasthan", "must_visit": ["Amber Fort", "Hawa Mahal"]}


@pytest.mark.parametrize("fields,start_in", [(RICH, 5), (RICH, 40), ({}, 5), (RAJASTHAN, 3)])
def test_default_plan_always_passes_the_checks(fields, start_in):
    r = request(start_in=start_in, **fields)
    plan = default_plan(r, TODAY)
    assert plan_problems(plan, r, TODAY) == []
    assert [s.step for s in plan.steps] == list(range(1, len(plan.steps) + 1))


def test_tidy_renumbers_and_drops_stray_queries():
    plan = tidy(Plan(summary="x", steps=[step("resolve_destination", query="Jodhpur", serves="popular"),
                                         step("check_budget")]))
    assert [(s.step, s.query, s.serves) for s in plan.steps] == [(1, None, None), (2, None, None)]


# ---- the node, with a fake LLM ----
pytest.importorskip("langchain_openai")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
import planner_node  # noqa: E402


class FakeLLM:
    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def invoke(self, messages):
        self.calls.append(messages)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def test_valid_plan_needs_one_call(monkeypatch):
    fake = FakeLLM(good_plan())
    monkeypatch.setattr(planner_node, "structured_llm", fake)
    plan, trace, notes = planner_node.make_plan(request(**RICH), TODAY)
    assert len(fake.calls) == 1 and notes == [] and trace[-1].event == "plan"
    assert "Trip facts:" in fake.calls[0][1][1]


def test_invalid_plan_is_retried_with_its_problems(monkeypatch):
    bad = good_plan()
    bad.steps = [s for s in bad.steps if s.tool != "locate_place"]
    fake = FakeLLM(bad, good_plan())
    monkeypatch.setattr(planner_node, "structured_llm", fake)
    plan, trace, notes = planner_node.make_plan(request(**RICH), TODAY)
    assert len(fake.calls) == 2 and "Mehrangarh Fort" in fake.calls[1][-1][1]
    assert any(s.tool == "locate_place" for s in plan.steps) and notes == []


def test_two_invalid_plans_fall_back_to_the_default(monkeypatch):
    bad = good_plan(weather=True)
    fake = FakeLLM(bad, bad)
    monkeypatch.setattr(planner_node, "structured_llm", fake)
    r = request(start_in=30, **RICH)  # no forecast, so the weather step is wrong both times
    plan, trace, notes = planner_node.make_plan(r, TODAY)
    assert "planner_fallback" in [e.event for e in trace] and "default plan" in notes[0]
    assert plan_problems(plan, r, TODAY) == [] and "weather" not in [s.tool for s in plan.steps]


def test_unreadable_output_twice_falls_back(monkeypatch):
    from langchain_core.exceptions import OutputParserException
    fake = FakeLLM(OutputParserException("bad"), OutputParserException("bad"))
    monkeypatch.setattr(planner_node, "structured_llm", fake)
    plan, trace, notes = planner_node.make_plan(request(**RICH), TODAY)
    events = [e.event for e in trace]
    assert "llm_parse_retry" in events and "planner_fallback" in events and plan.steps[0].tool == "resolve_destination"
