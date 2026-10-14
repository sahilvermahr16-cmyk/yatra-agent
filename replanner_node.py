"""Budget loop: budget_check (code) costs the plan and checks it; replanner (LLM) chooses one round of changes;
the graph goes back to budget_check until the plan fits, MAX_REPLANS rounds are used, or nothing is left to change.
Code computes every amount and applies the changes; the LLM only weighs trade-offs."""

import time
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError
import config
import costs
import stays
from llm_setup import llm
from prompts import REPLANNER_PROMPT
from schemas import ActionOption, BudgetVerdict, CostBreakdown, Itinerary, ReplanDecision, TraceEvent, TripRequest

structured_llm = llm.with_structured_output(ReplanDecision, method="function_calling")

def rs(x: float) -> str:
    return f"Rs {x:,.0f}"

def replan_facts(r: TripRequest, cost: CostBreakdown, verdict: BudgetVerdict, options: list[ActionOption],
                 round_no: int) -> str:
    """The replanner's input: the gap, the cost lines, the user's wishes and the allowed changes with amounts."""
    c = cost.choices
    limit = (f"must not cost more than {rs(verdict.ceiling)}" if verdict.status == "over"
             else f"should not cost less than {rs(verdict.floor)}")
    verb = "saves" if verdict.status == "over" else "adds"
    kinds = "; ".join(f'"{pt.words}"' for pt in r.place_types) or "none"
    purposes = ", ".join(i for i in r.interests if i != "popular") or "none"
    lines = [
        f"Budget check: {verdict.status.upper()} by {rs(verdict.gap)} (round {round_no} of {config.MAX_REPLANS})",
        f"  Limit: {limit}",
        f"  Current cost: {rs(cost.total)} = hotel {rs(cost.hotel)} ({c.hotel_tier}, {cost.rooms} room(s) x "
        f"{r.nights} night(s)) + food {rs(cost.food)} ({c.food_tier}) + local travel {rs(cost.local_travel)} "
        f"({c.transport}) + tickets {rs(cost.tickets)}",
        "What the user asked for:",
        f"  Style: {r.budget_style or 'not stated'} | Must visit: {'; '.join(r.must_visit) or 'none'} | "
        f"Kinds of place: {kinds} | Purposes: {purposes}",
        "Allowed changes (choose only from these; each amount is already computed):",
    ]
    lines += [f"  {o.action:<22} {o.label:<34} {verb} {rs(o.amount):<10} enough alone: "
              f"{'yes' if o.amount >= verdict.gap else 'no'}" for o in options]
    fewest = costs.default_actions(options, verdict)
    if sum(o.amount for o in options) < verdict.gap:
        lines.append("Even all the allowed changes together do not close the gap.")
    else:
        lines.append(f"Fewest changes that close the gap (largest first): {' + '.join(fewest)}")
    return "\n".join(lines)

def _ask(facts: str, trace: list) -> ReplanDecision | None:
    messages = [("system", REPLANNER_PROMPT), ("user", facts)]
    for attempt in range(2):
        try:
            return structured_llm.invoke(messages)
        except (OutputParserException, ValidationError) as err:
            trace.append(TraceEvent(node="replanner", event="llm_parse_retry" if attempt == 0 else "llm_parse_failed",
                                    detail={"error": str(err)[:500]}))
            messages = messages + [("user", "Your answer did not match the format. Return actions (from the "
                                             "allowed list) and reason again.")]
    return None

def budget_check_node(state: dict) -> dict:
    """Cost the current plan at the current price levels and compare it with the user's limits."""
    r, it = state["request"], state["itinerary"]
    choices = state.get("cost_choices") or costs.initial_choices(r)
    cost = costs.estimate(r, it, choices)
    verdict = costs.check(r, cost)
    out = {"cost": cost, "verdict": verdict, "cost_choices": choices,
           "trace": [TraceEvent(node="budget_check", event="cost",
                                detail={"total": cost.total, "status": verdict.status, "gap": verdict.gap,
                                        "choices": choices.model_dump()})]}
    if state.get("first_cost") is None:
        out["first_cost"] = cost.total
    return out

def needs_replan(state: dict) -> bool:
    """Route after budget_check: another replanner round only if it can still help."""
    verdict = state["verdict"]
    rounds = state.get("replan_count", 0)
    if verdict.status == "within" or rounds >= config.MAX_REPLANS:
        return False
    if rounds > 0 and not state.get("last_round_applied", False):
        return False  # the last round changed nothing; another would not either
    return bool(costs.allowed_actions(state["request"], state["itinerary"], state["cost_choices"], verdict))

def replanner_node(state: dict) -> dict:
    """One round: the LLM chooses from the allowed changes; code applies them (or its own default order)."""
    r, it, choices, verdict, cost = (state["request"], state["itinerary"], state["cost_choices"], state["verdict"],
                                     state["cost"])
    trace, notes = [], []
    round_no = state.get("replan_count", 0) + 1
    options = costs.allowed_actions(r, it, choices, verdict)
    start = time.perf_counter()
    decision = _ask(replan_facts(r, cost, verdict, options, round_no), trace)
    actions, reason = (decision.actions, decision.reason) if decision else ([], "")
    if not actions:  # no usable answer: code's own order, biggest effect first
        actions, reason = costs.default_actions(options, verdict), "default order (biggest effect first)"
        trace.append(TraceEvent(node="replanner", event="replanner_fallback", detail={"actions": actions}))
    choices, it, applied, ignored = costs.apply(actions, r, it, choices, verdict)
    if applied:  # stays, meals and the day's timeline follow the changes
        arrival, city = stays.arrival_of(state)
        it, _ = stays.assign(it, state.get("osm_spots") or [], choices, bool(stays.food_wishes(r)),
                             osm_ok=state.get("osm_ok", True), arrival=arrival, city=city)
    after = costs.estimate(r, it, choices)
    trace.append(TraceEvent(node="replanner", event="replan", duration_ms=int((time.perf_counter() - start) * 1000),
                            detail={"round": round_no, "chosen": actions, "applied": applied, "ignored": ignored,
                                    "reason": reason, "cost_before": cost.total, "cost_after": after.total,
                                    "status": costs.check(r, after).status}))
    if ignored:
        notes.append(f"Replanner round {round_no}: ignored changes that were not allowed: {', '.join(ignored)}.")
    return {"cost_choices": choices, "itinerary": it, "replan_count": round_no, "last_round_applied": bool(applied),
            "budget_changes": applied, "trace": trace, "notes": notes}

def budget_note(state: dict) -> str | None:
    """The honest closing note about the budget, written once the loop has ended."""
    verdict, cost, changes = state["verdict"], state["cost"], state.get("budget_changes", [])
    if verdict.status == "within":
        if not changes:
            return None
        return (f"Budget: the first draft cost {rs(state['first_cost'])}, outside your budget, so the agent changed: "
                f"{'; '.join(changes)}. The plan now costs {rs(cost.total)}.")
    if verdict.status == "over":
        tried = f" Tried: {'; '.join(changes)}." if changes else ""
        return (f"Budget: the cheapest plan that keeps your wishes costs {rs(cost.total)}, {rs(verdict.gap)} above "
                f"your limit of {rs(verdict.ceiling)}.{tried} To fit, consider fewer days or a higher budget.")
    return (f"Budget: the plan costs {rs(cost.total)}, {rs(verdict.gap)} below the {rs(verdict.floor)} you wanted "
            "to spend; the most comfortable options available are already chosen.")

APPEND = ("trace", "notes", "budget_changes")

def _merge(state: dict, update: dict) -> None:
    for k, v in update.items():
        state[k] = state.get(k, []) + v if k in APPEND else v

def fit_budget(r: TripRequest, it: Itinerary) -> tuple[Itinerary, CostBreakdown, BudgetVerdict, list, list[str], int]:
    """The same loop as the graph, without the graph (used by tests). Returns
    (itinerary, cost, verdict, trace, notes, rounds)."""
    state = {"request": r, "itinerary": it, "replan_count": 0}
    _merge(state, budget_check_node(state))
    while needs_replan(state):
        _merge(state, replanner_node(state))
        _merge(state, budget_check_node(state))
    note = budget_note(state)
    notes = state.get("notes", []) + ([note] if note else [])
    return state["itinerary"], state["cost"], state["verdict"], state.get("trace", []), notes, state["replan_count"]





