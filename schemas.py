"""Pydantic models for every piece of data the agent produces. No logic here."""

import datetime as dt
from typing import Literal, get_args
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Fixed choices - the LLM can only pick from these
Interest = Literal[
    "history", "food", "nature", "religious",
    "shopping", "adventure", "culture", "nightlife", "popular",
]
DestinationType = Literal["city", "state", "region"]
BudgetStyle = Literal["budget", "mid", "luxury"]
Status = Literal["running", "done", "needs_city", "gave_up"]
BudgetDirection = Literal["at_most", "about", "at_least", "range", "not_stated"]
DateKind = Literal["calendar_date", "days_from_today", "weekday", "weekend"]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

class DateRef(BaseModel):
    """How the user named one edge of the trip. Code turns it into a calendar date."""
    phrase: str = Field(description="The user's exact words for this date, copied from the goal")
    kind: DateKind
    day: int | None = Field(default=None, ge=1, le=31)  # calendar_date
    month: int | None = Field(default=None, ge=1, le=12)  # calendar_date
    year: int | None = None  # calendar_date, only if the user wrote a year
    offset_days: int | None = Field(default=None, ge=0)  # days_from_today: tomorrow = 1
    weekday: Weekday | None = None  # weekday
    which: Literal["this", "next"] | None = None  # weekday / weekend

def _known_interests(values):
    """Keep only valid categories, so one unknown word cannot fail the whole extraction."""
    allowed = set(get_args(Interest))
    return [x.strip().lower() for x in (values or []) if isinstance(x, str) and x.strip().lower() in allowed]

def _require_budget_fields(schema: dict) -> None:
    """Show budget_phrase and budget_direction to the LLM as required and without defaults,
    so it must copy the words and decide instead of skipping both."""
    schema.setdefault("required", [])
    for name in ("budget_phrase", "budget_direction"):
        if name not in schema["required"]:
            schema["required"].append(name)
        schema.get("properties", {}).get(name, {}).pop("default", None)

class PlaceType(BaseModel):
    """A kind of place or activity the user likes, with the purposes it serves."""
    words: str = Field(description="The user's own words for this kind of place, e.g. 'waterfalls'")
    interests: list[Interest] = Field(
        default_factory=list,
        description="Why people visit such a place; at least one category",
    )

    @field_validator("interests", mode="before")
    @classmethod
    def _known_interests_only(cls, v):
        return _known_interests(v)

class ExtractedGoal(BaseModel):
    """Filled by the LLM with only what the user stated. Missing = None."""
    model_config = ConfigDict(json_schema_extra=_require_budget_fields)
    destination: str | None = None
    start: DateRef | None = None
    end: DateRef | None = None
    days: int | None = Field(default=None, ge=1)
    travellers: int | None = Field(default=None, ge=1)
    # Budget: evidence first (the user's words), then the numbers, then what they mean.
    budget_phrase: str | None = Field(
        default=None,
        description="The money figure copied exactly as written, with the words attached to it; "
                    "null only when there is no figure")
    budget_amount: float | None = Field(
        default=None, gt=0, description="The figure in rupees; for a range, the smaller number")
    budget_amount_max: float | None = Field(
        default=None, gt=0, description="Only for a range: the larger number; otherwise null")
    budget_is_per_person: bool = False
    budget_is_per_day: bool = False
    budget_direction: BudgetDirection = Field(
        default="not_stated",
        description="Which way the figure limits the cost, read from the words of budget_phrase")
    budget_style: BudgetStyle | None = None
    # Order matters: named places and kinds first, then purposes stated on their own.
    must_visit: list[str] = Field(default_factory=list)
    place_types: list[PlaceType] = Field(default_factory=list)
    interests: list[Interest] = Field(
        default_factory=list,
        description="Purposes the user stated directly, without naming a kind of place "
                    "(e.g. a history buff). Code adds the interests of every place_types entry.",
    )

    # Function calling does not enforce the schema, so the LLM may send null for "no".
    @field_validator("budget_is_per_person", "budget_is_per_day", mode="before")
    @classmethod
    def _null_flag_is_false(cls, v):
        return False if v is None else v

    @field_validator("must_visit", "place_types", mode="before")
    @classmethod
    def _null_list_is_empty(cls, v):
        return [] if v is None else v

    @field_validator("interests", mode="before")
    @classmethod
    def _known_interests_only(cls, v):
        return _known_interests(v)

    @field_validator("budget_direction", mode="before")
    @classmethod
    def _null_direction_is_not_stated(cls, v):
        return "not_stated" if v is None else v

class TripRequest(ExtractedGoal):
    """ExtractedGoal completed by code: defaults, derived values, resolved destination."""
    start_date: dt.date | None = None  # resolved from start / end by code
    end_date: dt.date | None = None
    destination_type: DestinationType | None = None
    base_city: str | None = None
    nights: int | None = Field(default=None, ge=0)
    # Rupee bounds for the whole group and the whole trip, computed by code from budget_direction.
    total_budget: float | None = Field(default=None, gt=0)  # the target
    budget_ceiling: float | None = None  # the plan must not cost more; None = no upper bound
    budget_floor: float | None = None  # the plan should not cost less; None = no lower bound

ToolName = Literal["resolve_destination", "weather", "locate_place", "find_places",
                   "build_itinerary", "find_stays_and_food", "estimate_costs", "check_budget"]
Serves = Literal["must_visit", "place_type", "interest", "popular"]

class PlanStep(BaseModel):
    """One step of the visible plan, written by the planner before any tool runs."""
    step: int = Field(ge=1)
    tool: ToolName
    query: str | None = Field(
        default=None, description="What to look up: a place name (locate_place) or a 1-3 word search "
                                  "phrase (find_places); null for the other tools")
    serves: Serves | None = Field(default=None, description="Which wish of the user this step is for")
    reason: str = Field(description="Why this step is needed, in one short line")

class Plan(BaseModel):
    summary: str = Field(description="The goal restated in one line")
    steps: list[PlanStep]

class Location(BaseModel):
    """A place on the map. Every later tool (weather, places) works from these coordinates."""
    name: str
    lat: float
    lon: float
    region: str | None = None  # state (admin1), e.g. "Rajasthan"
    feature_code: str | None = None  # GeoNames code: PPLC, PPLA, PPL ...
    population: int | None = None
    source: str = "Open-Meteo geocoding"

class GeocodeResult(BaseModel):
    """Output of the geocode tool. chosen=None means no place in India matched (not a failure)."""
    query: str
    chosen: Location | None = None
    alternatives: list[Location] = Field(default_factory=list)  # other Indian matches, for the trace
    rejected_outside_india: int = 0  # results dropped by the country check
    ambiguous: bool = False  # a match in another state ranks as high as the chosen one
    # Indian results with another name or not a town ('Pariswani' for 'Paris', 'Mysore Airport'); never chosen,
    # only used as evidence that a place the travel guide knows lies in India
    other_matches: list[Location] = Field(default_factory=list)

class CityCandidate(BaseModel):
    """One city listed in the 'Cities' section of a state or region page on Wikivoyage."""
    name: str
    lat: float | None = None  # from the Wikivoyage marker, if given
    lon: float | None = None
    pageviews: int | None = None  # None = not fetched, or the call failed

class DestinationResult(BaseModel):
    """Where the trip is planned: the city itself, or one base city of a state or region."""
    query: str  # the destination as the user wrote it
    destination_type: DestinationType
    wikivoyage_title: str | None = None  # page title after redirects (Coorg -> Kodagu)
    candidates: list[CityCandidate] = Field(default_factory=list)  # state / region only
    base_city: str | None = None  # the city the trip is planned in
    choice_reason: str = ""  # why this city; shown in the report
    location: Location | None = None  # None -> the trip cannot be planned (needs_city)
    used_fallback: bool = False

class DayWeather(BaseModel):
    date: dt.date
    temp_max_c: float
    temp_min_c: float
    rain_probability: int = Field(ge=0, le=100)
    summary: str

class Place(BaseModel):
    """A sight found by locate_place or find_places, tied to the user's wish it serves."""
    name: str
    lat: float
    lon: float
    distance_km: float  # from the base city
    description: str | None = None  # Wikipedia short description, e.g. "stepwell in Jodhpur"
    serves: Serves  # must_visit / place_type / interest / popular
    wish: str  # the user's words it serves: "Mehrangarh Fort", "stepwells", "food"
    category: Interest
    indoor: bool  # used to schedule rainy days
    entry_fee: float = Field(default=0, ge=0)  # per person, assumed (config)
    url: str | None = None
    pageviews: int | None = None  # Wikipedia views in the popularity window (popular sights only)
    source: str = "Wikipedia"

class Miss(BaseModel):
    """A wish that could not be met; becomes an honest note in the report."""
    serves: Serves
    wish: str
    reason: str  # "290 km from Jaipur" / "no matching places found on Wikipedia ..." / "the search failed"
    near_city: str | None = None  # for a far must-visit place: the city it is in, if known

class StepResult(BaseModel):
    """One line per executed plan step: the visible execution trace."""
    step: int
    tool: ToolName
    ok: bool
    summary: str

class Spot(BaseModel):
    """A place from OpenStreetMap: somewhere to stay or to eat. OSM has no prices or ratings."""
    name: str
    kind: str  # hotel / guest_house / hostel / cafe / restaurant / fast_food / food_court
    lat: float
    lon: float
    distance_km: float = 0  # from what it was chosen for (the next day's places, the day's first place ...)
    stars: int | None = None
    url: str

TimelineKind = Literal["start", "bags", "breakfast", "travel", "visit", "lunch", "rest", "free", "food", "dinner", "stay", "end"]

class TimelineItem(BaseModel):
    """One line of a day's story: leave the hotel, breakfast, travel, visit, lunch, rest ... night stay.
    Times are estimates from config.py (visit length by kind of place, city speed, meal times)."""
    start: dt.time
    end: dt.time
    kind: TimelineKind
    title: str  # "Arrive in Jodhpur", "Mehrangarh Fort", "Lunch at Gypsy Restaurant", "-> walk 0.6 km"
    detail: str = ""  # shown in brackets: "must visit", "restaurant, 0.2 km"
    url: str | None = None

class DayPlan(BaseModel):
    day: int = Field(ge=1)
    date: dt.date
    weather: DayWeather | None = None
    places: list[Place] = Field(default_factory=list)  # in visiting order
    reason: str  # which wishes, how far apart, what weather
    stay: Spot | None = None  # where to sleep after this day (none on the last day)
    breakfast: Spot | None = None  # near the day's first place
    lunch: Spot | None = None  # near where the traveller is at lunch time
    food_stop: Spot | None = None  # near the day's last place, only if the user asked for food
    dinner: Spot | None = None  # near the day's last place, when there is no food stop
    day_notes: list[str] = Field(default_factory=list)  # e.g. no breakfast place nearby, same food stop as before
    timeline: list[TimelineItem] = Field(default_factory=list)  # the day as a timed story

class Itinerary(BaseModel):
    days: list[DayPlan]
    unused: list[Place] = Field(default_factory=list)  # found but did not fit: "if you have more time"
    notes: list[str] = Field(default_factory=list)  # honest notes about wishes that could not be met

class CostChoices(BaseModel):
    """The levels the cost is computed at; the replanner changes these, never the user's wishes."""
    hotel_tier: BudgetStyle
    food_tier: BudgetStyle
    transport: Literal["cab", "public"] = "cab"
    hotel_outside_centre: bool = False  # a hotel a little away from the sights, assumed cheaper

class CostBreakdown(BaseModel):
    """Whole group, whole trip, INR, from the assumed price table in config.py."""
    hotel: float = 0
    food: float = 0
    local_travel: float = 0
    tickets: float = 0
    total: float = 0
    choices: CostChoices
    rooms: int = 0
    vehicles: int = 0

class BudgetVerdict(BaseModel):
    status: Literal["within", "over", "under"]
    total: float
    ceiling: float | None = None
    floor: float | None = None
    gap: float = 0  # how far above the ceiling / below the floor

ReplanAction = Literal["lower_hotel", "raise_hotel", "lower_food", "raise_food", "use_public_transport", "use_cab", "drop_paid_place", "stay_outside_centre"]

class ActionOption(BaseModel):
    """One change the replanner may choose, with its effect computed by code."""
    action: ReplanAction
    label: str  # "mid -> budget hotel" / "Jaigarh Fort (popular sight)"
    amount: float  # rupees saved (when over budget) or added (when under)

class ReplanDecision(BaseModel):
    actions: list[ReplanAction] = Field(description="Chosen changes, from the allowed list only")
    reason: str = Field(description="Why, in one or two sentences, in terms of the user's words")

    @field_validator("actions", mode="before")
    @classmethod
    def _known_actions_only(cls, v):
        allowed = set(get_args(ReplanAction))
        return [a for a in (v or []) if a in allowed]

class ErrorRecord(BaseModel):
    where: str
    error_type: str
    message: str
    handled_by: str  # how the agent recovered

class TraceEvent(BaseModel):
    node: str
    event: str
    detail: dict = Field(default_factory=dict)
    duration_ms: int | None = None
    timestamp: dt.datetime = Field(default_factory=dt.datetime.now)

class TripReport(BaseModel):
    """The final structured output (JSON). The Markdown report is written from the same data."""
    goal: str
    status: Status
    created_at: dt.datetime = Field(default_factory=dt.datetime.now)
    request: TripRequest | None = None
    destination: DestinationResult | None = None
    plan: Plan | None = None
    step_results: list[StepResult] = Field(default_factory=list)
    weather: list[DayWeather] | None = None
    itinerary: Itinerary | None = None
    cost: CostBreakdown | None = None
    verdict: BudgetVerdict | None = None
    first_cost: float | None = None
    replan_rounds: int = 0
    budget_changes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    errors: list[ErrorRecord] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)






