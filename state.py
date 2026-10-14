"""Shared LangGraph state. Data shapes live in schemas.py.

Lists marked Annotated[..., operator.add] are append-only: every node adds to them, none overwrites them."""

import datetime as dt
import operator
from typing import Annotated, TypedDict
from schemas import (BudgetVerdict, CostBreakdown, CostChoices, DayWeather, DestinationResult, ErrorRecord,  Itinerary, Location, Miss, 
    Place, Plan, Status, StepResult, TraceEvent, TripRequest,)

class AgentState(TypedDict, total=False):
    # Input
    goal: str
    today: dt.date

    # Understanding the goal (extract, normalize)
    request: TripRequest

    # Planning (planner)
    plan: Plan

    # Tool results (executor)
    destination: DestinationResult | None
    step_results: list[StepResult]  # one line per executed plan step
    misses: list[Miss]  # wishes that could not be met, for honest notes
    location: Location | None
    weather: list[DayWeather] | None  # None = forecast unavailable
    places: list[Place]

    # Itinerary and budget (itinerary, budget_check <-> replanner)
    itinerary: Itinerary
    osm_spots: list  # places to stay and eat from OpenStreetMap, kept so the replanner can choose again
    osm_ok: bool  # False when OpenStreetMap could not be reached (the days are timed without naming stays or meals)
    cost_choices: CostChoices
    cost: CostBreakdown | None
    verdict: BudgetVerdict | None
    first_cost: float | None  # cost of the first draft, before any replanning
    replan_count: int
    last_round_applied: bool
    budget_changes: Annotated[list[str], operator.add]

    # Control
    status: Status

    # Append-only records
    notes: Annotated[list[str], operator.add]
    errors: Annotated[list[ErrorRecord], operator.add]
    trace: Annotated[list[TraceEvent], operator.add]

    # Output (reporter)
    report_md: str | None
    report_json: dict | None
