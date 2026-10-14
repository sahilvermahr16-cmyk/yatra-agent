"""The report: every section is present and the JSON matches the TripReport schema."""
import datetime as dt
import os

import pytest

pytest.importorskip("langchain_openai")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

import costs  # noqa: E402
from reporter import reporter_node  # noqa: E402
from schemas import (  # noqa: E402
    DayPlan,
    DayWeather,
    DestinationResult,
    ErrorRecord,
    Itinerary,
    Location,
    Place,
    Plan,
    PlanStep,
    StepResult,
    TripReport,
    TripRequest,
)

START = dt.date(2026, 10, 24)


def state():
    r = TripRequest(destination="Jodhpur", start_date=START, end_date=START + dt.timedelta(days=1), days=2, nights=1,
                    travellers=2, total_budget=20000, budget_ceiling=20000)
    fort = Place(name="Mehrangarh", lat=26.29, lon=73.02, distance_km=3.5, serves="must_visit", wish="Mehrangarh Fort",
                 category="popular", indoor=False, entry_fee=100, url="https://en.wikipedia.org/wiki/Mehrangarh",
                 description="Medieval fort")
    w = DayWeather(date=START, temp_max_c=36, temp_min_c=24, rain_probability=0, summary="Clear sky")
    it = Itinerary(days=[DayPlan(day=1, date=START, weather=w, places=[fort], reason="Mehrangarh (must visit)."),
                         DayPlan(day=2, date=START + dt.timedelta(days=1), places=[], reason="Free day.")],
                   notes=["No places for 'street food' were found near Jodhpur on Wikipedia."])
    choices = costs.initial_choices(r)
    cost = costs.estimate(r, it, choices)
    return {"goal": "2 days in Jodhpur", "status": "running", "request": r, "itinerary": it, "cost": cost,
            "verdict": costs.check(r, cost), "cost_choices": choices, "first_cost": cost.total, "replan_count": 0,
            "destination": DestinationResult(query="Jodhpur", destination_type="city", base_city="Jodhpur",
                                             wikivoyage_title="Jodhpur",
                                             location=Location(name="Jodhpur", lat=26.27, lon=73.0,
                                                               region="Rajasthan")),
            "plan": Plan(summary="2 days in Jodhpur", steps=[PlanStep(step=1, tool="resolve_destination", reason="r")]),
            "step_results": [StepResult(step=2, tool="weather", ok=False, summary="forecast unavailable")],
            "errors": [ErrorRecord(where="weather", error_type="timeout", message="simulated (after 3 attempt(s))",
                                   handled_by="continued without a forecast")],
            "notes": ["Start date not given, so the trip starts tomorrow."], "trace": []}


def test_report_has_every_section_and_valid_json():
    out = reporter_node(state())
    md = out["report_md"]
    for section in ("## Summary", "## The plan", "## What the agent did", "**Failures handled:**", "## Day by day",
                    "## Cost and budget", "## Notes", "## Assumptions", "## Sources"):
        assert section in md, section
    assert "[Mehrangarh](https://en.wikipedia.org/wiki/Mehrangarh)" in md and "Free day." in md
    assert "https://en.wikivoyage.org/wiki/Jodhpur" in md
    rep = TripReport.model_validate(out["report_json"])
    assert rep.status == "done" and rep.errors[0].where == "weather" and len(rep.assumptions) >= 4
