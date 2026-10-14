"""Cost of the plan, the budget check, and the changes the replanner may choose from. Pure code:
every amount is computed here, so the LLM only weighs trade-offs and never does arithmetic."""

import math
import config
from scheduler import day_reason
from schemas import ActionOption, BudgetVerdict, CostBreakdown, CostChoices, Itinerary, Place, TripRequest

TIERS = ["budget", "mid", "luxury"]
DROP_ORDER = config.DROP_ORDER


def initial_choices(r: TripRequest) -> CostChoices:
    tier = r.budget_style or config.DEFAULT_STYLE
    return CostChoices(hotel_tier=tier, food_tier=tier, transport="cab")

def planned_places(it: Itinerary) -> list[Place]:
    return [p for d in it.days for p in d.places]

def estimate(r: TripRequest, it: Itinerary, c: CostChoices) -> CostBreakdown:
    rooms = math.ceil(r.travellers / config.PEOPLE_PER_ROOM)
    vehicles = math.ceil(r.travellers / config.PEOPLE_PER_VEHICLE)
    night = config.PRICE_TABLE[c.hotel_tier]["hotel_per_night"]
    if c.hotel_outside_centre:
        night *= 1 - config.OUTSIDE_CENTRE_HOTEL_DISCOUNT
    hotel = rooms * r.nights * night
    food = r.travellers * r.days * config.PRICE_TABLE[c.food_tier]["food_per_day"]
    if c.transport == "cab":  # the cab follows the hotel's level of comfort
        travel = vehicles * r.days * config.PRICE_TABLE[c.hotel_tier]["vehicle_per_day"]
    else:
        travel = r.travellers * r.days * config.PUBLIC_TRANSPORT_PER_PERSON_PER_DAY
    tickets = r.travellers * sum(p.entry_fee for p in planned_places(it))
    return CostBreakdown(hotel=hotel, food=food, local_travel=travel, tickets=tickets,
                         total=hotel + food + travel + tickets, choices=c, rooms=rooms, vehicles=vehicles)

def check(r: TripRequest, cost: CostBreakdown) -> BudgetVerdict:
    ceiling, floor = r.budget_ceiling, r.budget_floor
    if ceiling is not None and cost.total > ceiling:
        return BudgetVerdict(status="over", total=cost.total, ceiling=ceiling, floor=floor, gap=cost.total - ceiling)
    if floor is not None and cost.total < floor:
        return BudgetVerdict(status="under", total=cost.total, ceiling=ceiling, floor=floor, gap=floor - cost.total)
    return BudgetVerdict(status="within", total=cost.total, ceiling=ceiling, floor=floor)

def next_place_to_drop(it: Itinerary) -> Place | None:
    """The least important paid place still planned: popular sights first, never a must-visit place."""
    for serves in DROP_ORDER:
        paid = [p for p in planned_places(it) if p.serves == serves and p.entry_fee > 0]
        if paid:
            return paid[-1]  # the last chosen of its kind is the least important one
    return None

def _shift(tier: str, step: int) -> str | None:
    i = TIERS.index(tier) + step
    return TIERS[i] if 0 <= i < len(TIERS) else None

def _with(c: CostChoices, **change) -> CostChoices:
    return c.model_copy(update=change)

def allowed_actions(r: TripRequest, it: Itinerary, c: CostChoices, verdict: BudgetVerdict) -> list[ActionOption]:
    """Changes that move the cost the right way, with their effect. A tier the user stated is never offered."""
    base = estimate(r, it, c).total
    options = []

    def offer(action, label, new_choices=None, new_it=None):
        amount = abs(base - estimate(r, new_it or it, new_choices or c).total)
        if amount > 0:
            options.append(ActionOption(action=action, label=label, amount=amount))

    if verdict.status == "over":
        lower = _shift(c.hotel_tier, -1)
        if lower and not r.budget_style:
            cab = " and cab" if c.transport == "cab" else ""
            offer("lower_hotel", f"{c.hotel_tier} -> {lower} hotel{cab}", _with(c, hotel_tier=lower))
        lower = _shift(c.food_tier, -1)
        if lower:
            offer("lower_food", f"{c.food_tier} -> {lower} meals", _with(c, food_tier=lower))
        if c.transport == "cab":
            offer("use_public_transport", "cab -> public transport", _with(c, transport="public"))
        if not c.hotel_outside_centre:
            offer("stay_outside_centre", "hotel 3-8 km outside the centre", _with(c, hotel_outside_centre=True))
        place = next_place_to_drop(it)
        if place:
            offer("drop_paid_place", f"{place.name} ({place.serves.replace('_', ' ')})", new_it=_drop(it, place))
    elif verdict.status == "under":
        higher = _shift(c.hotel_tier, +1)
        if higher and not r.budget_style:
            cab = " and cab" if c.transport == "cab" else ""
            offer("raise_hotel", f"{c.hotel_tier} -> {higher} hotel{cab}", _with(c, hotel_tier=higher))
        higher = _shift(c.food_tier, +1)
        if higher:
            offer("raise_food", f"{c.food_tier} -> {higher} meals", _with(c, food_tier=higher))
        if c.transport == "public":
            offer("use_cab", "public transport -> cab", _with(c, transport="cab"))
    return options

def _drop(it: Itinerary, place: Place) -> Itinerary:
    new = it.model_copy(deep=True)
    for d in new.days:
        if any(p.name == place.name for p in d.places):
            d.places = [p for p in d.places if p.name != place.name]
            d.reason = day_reason(d.places, d.weather)
    new.unused = [place] + new.unused
    return new

def apply(actions: list[str], r: TripRequest, it: Itinerary, c: CostChoices, verdict: BudgetVerdict
          ) -> tuple[CostChoices, Itinerary, list[str], list[str]]:
    """Apply chosen actions one by one; each must still be allowed at that moment.
    Returns (choices, itinerary, applied labels, ignored actions)."""
    applied, ignored = [], []
    for action in actions:
        option = next((o for o in allowed_actions(r, it, c, verdict) if o.action == action), None)
        if option is None:
            ignored.append(action)
            continue
        if action == "drop_paid_place":
            it = _drop(it, next_place_to_drop(it))
            applied.append(f"dropped {option.label}")
            continue
        change = {"lower_hotel": ("hotel_tier", -1), "raise_hotel": ("hotel_tier", +1),
                  "lower_food": ("food_tier", -1), "raise_food": ("food_tier", +1)}.get(action)
        if change:
            field, step = change
            c = _with(c, **{field: _shift(getattr(c, field), step)})
        elif action == "stay_outside_centre":
            c = _with(c, hotel_outside_centre=True)
        else:
            c = _with(c, transport="public" if action == "use_public_transport" else "cab")
        applied.append(option.label)
    return c, it, applied, ignored

def default_actions(options: list[ActionOption], verdict: BudgetVerdict) -> list[str]:
    """Used when the replanner cannot answer: biggest effect first, until the gap is closed."""
    chosen, covered = [], 0.0
    for o in sorted(options, key=lambda o: -o.amount):
        if covered >= verdict.gap:
            break
        chosen.append(o.action)
        covered += o.amount
    return chosen










