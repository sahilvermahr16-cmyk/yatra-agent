"""The LangGraph wiring: routes for a normal run, a stopped run and the budget loop. Nodes are stubs or fakes."""
import datetime as dt
import os

import pytest

pytest.importorskip("langgraph")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

import graph  # noqa: E402
import replanner_node as rn  # noqa: E402
from schemas import (  # noqa: E402
    DayPlan,
    DestinationResult,
    Itinerary,
    Location,
    Place,
    Plan,
    PlanStep,
    ReplanDecision,
    TraceEvent,
    TripRequest,
)

START = dt.date(2026, 10, 24)
REQUEST = TripRequest(destination="Udaipur", start_date=START, end_date=START + dt.timedelta(days=3), days=4,
                      nights=3, travellers=2, total_budget=15000, budget_ceiling=15000)
ITINERARY = Itinerary(days=[DayPlan(day=1, date=START, reason="r", places=[
    Place(name=f"P{i}", lat=24.58, lon=73.71, distance_km=1, serves="popular", wish="w", category="popular",
          indoor=False, entry_fee=100) for i in range(12)])])


def stub(name, update=None):
    def node(state):
        return {"trace": [TraceEvent(node=name, event="ran")], **(update or {})}
    return node


def stubs(**overrides):
    nodes = {
        "extract": stub("extract", {"request": REQUEST, "status": "running"}),
        "normalize": stub("normalize", {"request": REQUEST}),
        "planner": stub("planner", {"plan": Plan(summary="s", steps=[PlanStep(step=1, tool="resolve_destination",
                                                                              reason="r")])}),
        "executor": stub("executor", {"status": "running", "destination": DestinationResult(
            query="Udaipur", destination_type="city", base_city="Udaipur",
            location=Location(name="Udaipur", lat=24.58, lon=73.71, region="Rajasthan"))}),
        "itinerary": stub("itinerary", {"itinerary": ITINERARY}),
        "stays": stub("stays", {"osm_spots": []}),
    }
    nodes.update(overrides)
    return nodes


class FakeLLM:
    def __init__(self, *outputs):
        self.outputs = list(outputs)

    def invoke(self, messages):
        return self.outputs.pop(0)


def run(nodes):
    return graph.build_graph(nodes).invoke({"goal": "4 days in Udaipur for 2, under 15000", "replan_count": 0})


def visited(state):
    return [e.node for e in state["trace"] if e.event in ("ran", "cost", "replan")]


def test_over_budget_loops_through_the_replanner_and_reports(monkeypatch):
    monkeypatch.setattr(rn, "structured_llm", FakeLLM(ReplanDecision(actions=["lower_hotel", "lower_food"],
                                                                     reason="no comfort level was asked for")))
    state = run(stubs())
    assert visited(state) == ["extract", "normalize", "planner", "executor", "itinerary", "stays",
                              "budget_check", "replanner", "budget_check"]
    assert state["status"] == "done" and state["verdict"].status == "within" and state["replan_count"] == 1
    assert "Budget: the first draft cost Rs 27,000" in state["notes"][-1]
    assert "## The plan" in state["report_md"] and state["report_json"]["replan_rounds"] == 1


def test_the_loop_stops_after_max_rounds(monkeypatch):
    tiny = REQUEST.model_copy(update={"budget_ceiling": 1000, "total_budget": 1000})
    answers = [ReplanDecision(actions=["drop_paid_place"], reason="r") for _ in range(5)]
    monkeypatch.setattr(rn, "structured_llm", FakeLLM(*answers))
    state = run(stubs(extract=stub("extract", {"request": tiny, "status": "running"}),
                      normalize=stub("normalize", {"request": tiny})))
    assert state["replan_count"] == 3 and state["verdict"].status == "over"
    assert "the cheapest plan that keeps your wishes" in state["notes"][-1]


def test_no_destination_goes_straight_to_the_report():
    state = run(stubs(extract=stub("extract", {"request": REQUEST.model_copy(update={"destination": None}),
                                               "status": "needs_city", "notes": ["No destination found."]})))
    assert visited(state) == ["extract"] and state["status"] == "needs_city"
    assert "Could not plan" in state["report_md"]


def test_a_failed_executor_goes_straight_to_the_report():
    state = run(stubs(executor=stub("executor", {"status": "gave_up"})))
    assert visited(state)[-1] == "executor" and state["status"] == "gave_up" and "itinerary" not in state
