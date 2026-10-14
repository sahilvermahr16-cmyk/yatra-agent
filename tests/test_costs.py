"""Cost, budget check and the replanner's allowed changes. Pure code."""
import datetime as dt

import costs
from schemas import BudgetVerdict, CostChoices, DayPlan, Itinerary, Place, TripRequest

START = dt.date(2026, 10, 24)


def place(name, serves="popular", fee=100):
    return Place(name=name, lat=0, lon=0, distance_km=1, serves=serves, wish="w", category="popular",
                 indoor=False, entry_fee=fee)


def itinerary(places):
    return Itinerary(days=[DayPlan(day=1, date=START, places=places, reason="r")])


def request(**fields):
    base = dict(destination="Udaipur", start_date=START, end_date=START + dt.timedelta(days=3), days=4, nights=3,
                travellers=2, total_budget=15000, budget_ceiling=15000)
    base.update(fields)
    return TripRequest(**base)


MID = CostChoices(hotel_tier="mid", food_tier="mid")
TWELVE = itinerary([place(f"P{i}") for i in range(12)])


def test_cost_formula():
    c = costs.estimate(request(), TWELVE, MID)
    assert (c.rooms, c.vehicles) == (1, 1)
    assert (c.hotel, c.food, c.local_travel, c.tickets, c.total) == (9000, 9600, 6000, 2400, 27000)


def test_rooms_and_vehicles_round_up_and_day_trip_has_no_hotel():
    c = costs.estimate(request(travellers=5, days=1, nights=0), itinerary([]), MID)
    assert (c.rooms, c.vehicles, c.hotel) == (3, 2, 0)


def test_public_transport_is_per_person():
    c = costs.estimate(request(), itinerary([]), MID.model_copy(update={"transport": "public"}))
    assert c.local_travel == 2 * 4 * 300


def test_verdicts():
    r = request(budget_ceiling=15000, budget_floor=None)
    assert costs.check(r, costs.estimate(r, TWELVE, MID)).model_dump() == \
        BudgetVerdict(status="over", total=27000, ceiling=15000, gap=12000).model_dump()
    rich = request(budget_ceiling=None, budget_floor=60000)
    assert costs.check(rich, costs.estimate(rich, TWELVE, MID)).status == "under"
    ok = request(budget_ceiling=30000)
    assert costs.check(ok, costs.estimate(ok, TWELVE, MID)).status == "within"


def over(r=None):
    r = r or request()
    return costs.check(r, costs.estimate(r, TWELVE, MID))


def test_allowed_changes_with_their_savings():
    options = {o.action: o.amount for o in costs.allowed_actions(request(), TWELVE, MID, over())}
    assert options == {"lower_hotel": 5400 + 2800, "lower_food": 4800, "use_public_transport": 3600,
                       "stay_outside_centre": 3 * 3000 * 0.25, "drop_paid_place": 200}


def test_a_stated_style_locks_the_hotel():
    r = request(budget_style="luxury")
    choices = costs.initial_choices(r)
    actions = [o.action for o in costs.allowed_actions(r, TWELVE, choices, over(r))]
    assert choices.hotel_tier == "luxury" and "lower_hotel" not in actions and "lower_food" in actions


def test_must_visit_is_never_dropped_and_popular_goes_first():
    it = itinerary([place("Fort", "must_visit"), place("Lake", "place_type"), place("Garden", "popular")])
    assert costs.next_place_to_drop(it).name == "Garden"
    only_must = itinerary([place("Fort", "must_visit"), place("Free Park", "popular", fee=0)])
    assert costs.next_place_to_drop(only_must) is None


def test_apply_changes_and_ignores_what_is_not_allowed():
    r = request(budget_style="mid")
    c, it, applied, ignored = costs.apply(["lower_hotel", "use_public_transport", "drop_paid_place",
                                           "drop_paid_place"], r, TWELVE, MID, over(r))
    assert ignored == ["lower_hotel"] and c.transport == "public" and c.hotel_tier == "mid"
    assert len(applied) == 3 and len(costs.planned_places(it)) == 10 and len(it.unused) == 2


def test_under_budget_offers_upgrades():
    r = request(budget_ceiling=None, budget_floor=60000)
    v = costs.check(r, costs.estimate(r, TWELVE, MID))
    assert {o.action for o in costs.allowed_actions(r, TWELVE, MID, v)} == {"raise_hotel", "raise_food"}


def test_default_actions_take_the_biggest_first_until_the_gap_closes():
    options = costs.allowed_actions(request(), TWELVE, MID, over())
    assert costs.default_actions(options, over()) == ["lower_hotel", "lower_food"]  # 8,200 + 4,800 >= 12,000


def test_a_hotel_outside_the_centre_costs_less():
    c = costs.estimate(request(), TWELVE, MID.model_copy(update={"hotel_outside_centre": True}))
    assert c.hotel == 9000 * (1 - 0.25)
    _, _, applied, _ = costs.apply(["stay_outside_centre"], request(), TWELVE, MID, over())
    assert applied == ["hotel 3-8 km outside the centre"]
