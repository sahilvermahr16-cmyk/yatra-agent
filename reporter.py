"""Node 8 (reporter): the final structured result, as JSON (TripReport) and as a Markdown report. Pure code."""

from urllib.parse import quote
import config
import timeline as T
from replanner_node import budget_note, rs
from schemas import TripReport

STATUS_TEXT = {"done": "Plan ready", "needs_city": "Could not plan: the destination is unclear",
               "gave_up": "Could not plan: a required step failed"}

def assumptions(state: dict) -> list[str]:
    c = state.get("cost")
    items = []
    if c:
        ch = c.choices
        t = config.PRICE_TABLE
        items.append(f"Prices are assumed (there is no free live price API for India): hotel "
                     f"{rs(t[ch.hotel_tier]['hotel_per_night'])} per room per night ({ch.hotel_tier}), food "
                     f"{rs(t[ch.food_tier]['food_per_day'])} per person per day ({ch.food_tier}), "
                     + (f"cab {rs(t[ch.hotel_tier]['vehicle_per_day'])} per day" if ch.transport == "cab" else
                        f"public transport {rs(config.PUBLIC_TRANSPORT_PER_PERSON_PER_DAY)} per person per day")
                     + " (config.py).")
        items.append(f"Each sight is assumed to cost {rs(config.DEFAULT_ENTRY_FEE)} per person to enter; "
                     f"{config.PEOPLE_PER_ROOM} people share a room and {config.PEOPLE_PER_VEHICLE} share a cab.")
    items += [f"Sights come from Wikipedia within {config.SEARCH_RADIUS_KM} km of the base city; 'popular' means "
              f"most read on Wikipedia in the last {config.POPULARITY_WINDOW_DAYS} days.",
              f"Must-visit places farther than {config.MUST_VISIT_RADIUS_KM} km from the base city are not planned.",
              f"Weather comes from the Open-Meteo forecast, which reaches {config.FORECAST_MAX_DAYS} days ahead.",
              f"At most {config.PLACES_PER_DAY} places are planned per day.",
              "Stays and places to eat come from OpenStreetMap, which has no prices or ratings: a stay is chosen "
              "for the planned price level and for being near the next day's places, not for its quality.",
              f"A hotel {config.OUTSIDE_CENTRE_MIN_KM}-{config.OUTSIDE_CENTRE_MAX_KM} km outside the centre is "
              f"assumed to cost {config.OUTSIDE_CENTRE_HOTEL_DISCOUNT:.0%} less."]
    return items + T.assumptions()

def sources(state: dict) -> list[str]:
    out = ["Open-Meteo geocoding and forecast: https://open-meteo.com",
           "Wikipedia (places, descriptions, page views): https://en.wikipedia.org",
           "OpenStreetMap via the Overpass API (stays and places to eat): https://www.openstreetmap.org"]
    d = state.get("destination")
    if d and d.wikivoyage_title:
        out.append(f"Wikivoyage: https://en.wikivoyage.org/wiki/{quote(d.wikivoyage_title.replace(' ', '_'))}")
    return out

def build_report(state: dict, extra_notes: list[str]) -> TripReport:
    status = state.get("status") or "done"
    return TripReport(
        goal=state["goal"], status="done" if status == "running" else status,
        request=state.get("request"), destination=state.get("destination"), plan=state.get("plan"),
        step_results=state.get("step_results", []), weather=state.get("weather"),
        itinerary=state.get("itinerary"), cost=state.get("cost"), verdict=state.get("verdict"),
        first_cost=state.get("first_cost"), replan_rounds=state.get("replan_count", 0),
        budget_changes=state.get("budget_changes", []), notes=state.get("notes", []) + extra_notes,
        errors=state.get("errors", []), assumptions=assumptions(state), sources=sources(state),
        trace=state.get("trace", []))

def _place_md(p) -> str:
    name = f"[{p.name}]({p.url})" if p.url else p.name
    return f"{name} — {p.description or 'sight'}, {p.distance_km} km from the centre"

def _spot_md(s) -> str:
    stars = f", {s.stars}-star" if s.stars else ""
    return f"[{s.name}]({s.url}) ({s.kind.replace('_', ' ')}{stars})"

def _cell(text: str) -> str:
    return text.replace("|", "/")

def _timeline_md(items) -> list[str]:
    rows = ["| Time | Plan | Takes |", "|---|---|---|"]
    for i in items:
        title = f"[{_cell(i.title)}]({i.url})" if i.url else _cell(i.title)
        if i.kind == "visit":
            title = f"**{title}**"
        text = f"{title} ({_cell(i.detail)})" if i.detail else title
        rows.append(f"| {i.start:%H:%M} | {text} | {T.takes(i)} |")
    return rows + [""]

def to_markdown(rep: TripReport) -> str:
    r, d = rep.request, rep.destination
    lines = [f"# Trip plan: {d.base_city if d and d.base_city else (r.destination if r else 'unknown')}",
             "", f"**Goal:** {rep.goal}", "", f"**Status:** {STATUS_TEXT.get(rep.status, rep.status)}", ""]
    if r and r.start_date and r.end_date:
        where = f"{d.base_city}, {d.location.region or ''}" if d and d.location else r.destination
        lines += ["## Summary", "",
                  f"- **Where:** {where}"
                  + (f" ({d.choice_reason})" if d and d.destination_type != 'city' and d.choice_reason else ""),
                  f"- **When:** {r.start_date:%a %d %b %Y} to {r.end_date:%a %d %b %Y} "
                  f"({r.days} days, {r.nights} nights)",
                  f"- **Travellers:** {r.travellers}"]
        if rep.cost and rep.verdict:
            limit = f"limit {rs(rep.verdict.ceiling)}" if rep.verdict.ceiling else "no limit given"
            lines.append(f"- **Cost:** {rs(rep.cost.total)} for the group ({limit}) → **{rep.verdict.status}**")
        lines.append("")
    if rep.plan:
        lines += ["## The plan (written before any tool ran)", "", f"_{rep.plan.summary}_", ""]
        lines += [f"{s.step}. `{s.tool}`" + (f" \"{s.query}\"" if s.query else "") + f" — {s.reason}"
                  for s in rep.plan.steps]
        lines.append("")
    if rep.step_results:
        lines += ["## What the agent did", "", "| Step | Tool | Result |", "|---|---|---|"]
        lines += [f"| {s.step} | {s.tool} | {'✅' if s.ok else '⚠️'} {s.summary} |" for s in rep.step_results]
        lines.append("")
    if rep.errors:
        lines += ["**Failures handled:**", ""]
        lines += [f"- `{e.where}` {e.error_type}: {e.message} → {e.handled_by}" for e in rep.errors]
        lines.append("")
    if rep.itinerary:
        lines += ["## Day by day", ""]
        for day in rep.itinerary.days:
            w = day.weather
            weather = (f" — {w.summary}, {w.temp_min_c:.0f}–{w.temp_max_c:.0f} °C, rain {w.rain_probability}%"
                       if w else "")
            lines += [f"### Day {day.day}: {day.date:%a %d %b}{weather}", ""]
            if day.timeline:
                lines += _timeline_md(day.timeline)
                lines += [f"- _Note: {n}_" for n in day.day_notes]
                lines += ["", f"_Why these places: {day.reason}_", ""]
                continue
            if day.breakfast:
                lines += [f"- **Breakfast:** {_spot_md(day.breakfast)}", ""]
            lines += [f"{i}. {_place_md(p)}" for i, p in enumerate(day.places, 1)] or ["Free day."]
            lines.append("")
            if day.food_stop:
                lines += [f"- **Food stop:** {_spot_md(day.food_stop)}"]
            if day.stay:
                lines += [f"- **Stay tonight:** {_spot_md(day.stay)}, {day.stay.distance_km} km from tomorrow's places"]
            lines += [f"- _Note: {n}_" for n in day.day_notes]
            lines += ["", f"_Why: {day.reason}_", ""]
        if rep.itinerary.unused:
            lines += ["**If you have more time:** " + ", ".join(p.name for p in rep.itinerary.unused), ""]
    if rep.cost:
        c, ch = rep.cost, rep.cost.choices
        lines += ["## Cost and budget", "", "| Item | Amount |", "|---|---|",
                  f"| Hotel ({ch.hotel_tier}{', outside the centre' if ch.hotel_outside_centre else ''}, "
                  f"{c.rooms} room(s)) | {rs(c.hotel)} |",
                  f"| Food ({ch.food_tier}) | {rs(c.food)} |",
                  f"| Local travel ({'cab' if ch.transport == 'cab' else 'public transport'}) | {rs(c.local_travel)} |",
                  f"| Entry tickets | {rs(c.tickets)} |", f"| **Total** | **{rs(c.total)}** |", ""]
        if rep.replan_rounds:
            lines += [f"The first draft cost {rs(rep.first_cost)}. Replanning rounds: {rep.replan_rounds}; "
                      f"changes made: {'; '.join(rep.budget_changes) or 'none'}.", ""]
            for e in rep.trace:
                if e.event == "replan":
                    d = e.detail
                    lines.append(f"- Round {d['round']}: {', '.join(d['applied']) or 'no change'} — "
                                 f"_{d['reason']}_ ({rs(d['cost_before'])} → {rs(d['cost_after'])})")
            lines.append("")
    if rep.notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in rep.notes] + [""]
    lines += ["## Assumptions", ""] + [f"- {a}" for a in rep.assumptions] + [""]
    lines += ["## Sources", ""] + [f"- {s}" for s in rep.sources] + [""]
    return "\n".join(lines)

def reporter_node(state: dict) -> dict:
    extra: list[str] = []
    if state.get("verdict") is not None:
        note: str | None = budget_note(state)
        if note:
            extra.append(note)
    rep = build_report(state, extra)
    return {"status": rep.status, "notes": extra, "report_json": rep.model_dump(mode="json"),
            "report_md": to_markdown(rep)}






