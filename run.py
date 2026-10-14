"""Run the agent from the command line and watch it work, stage by stage.

Usage:
  python run.py "3 days in Jodhpur next weekend, must see Mehrangarh Fort, under 20k for two"
  python run.py "..." --inject-failure weather_timeout   (also: places_timeout, geocode_timeout, osm_timeout)
  python run.py "..." --out samples/run1                  (saves run1.md, run1.json and run1.log)
"""

import argparse
import datetime as dt
import json
import pathlib
import sys
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import config
import timeline as T
from graph import build_graph
from replanner_node import rs
from tools.http import inject_failures

console = Console(record=True, width=110)
APPEND = ("trace", "notes", "errors", "budget_changes")
SELF_CORRECTION = ("llm_self_check_retry", "llm_parse_retry", "planner_fallback", "replanner_fallback")

def panel(title: str, body, style: str = "cyan") -> None:
    console.print(Panel(body, title=f"[bold]{title}[/bold]", title_align="left", border_style=style,
                        box=box.ROUNDED, padding=(0, 1)))

def corrections(update: dict) -> list[Text]:
    return [Text(f"self-correction: {e.event} {e.detail.get('problems') or e.detail.get('actions') or ''}",
                 style="yellow") for e in update.get("trace", []) if e.event in SELF_CORRECTION]

def show_goal(update: dict) -> None:
    r = update.get("request")
    if not r:
        return
    t = Table.grid(padding=(0, 2))
    t.add_row("[dim]Destination[/dim]", str(r.destination), "[dim]Days[/dim]", str(r.days),
              "[dim]Travellers[/dim]", str(r.travellers or "not given"))
    t.add_row("[dim]Budget words[/dim]", f"{r.budget_phrase or 'not given'} ({r.budget_direction})",
              "[dim]Must visit[/dim]", ", ".join(r.must_visit) or "-", "", "")
    t.add_row("[dim]Kinds of place[/dim]", ", ".join(pt.words for pt in r.place_types) or "-",
              "[dim]Purposes[/dim]", ", ".join(r.interests) or "-", "", "")
    panel("1 · Read the goal  (LLM)", Group(t, *corrections(update)))

def show_request(update: dict) -> None:
    r = update["request"]
    limits = ", ".join(f"{k} {rs(v)}" for k, v in (("max", r.budget_ceiling), ("min", r.budget_floor)) if v)
    panel("2 · Complete the request  (code)",
          f"{r.start_date:%a %d %b} → {r.end_date:%a %d %b}  ·  {r.days} days, {r.nights} nights  ·  "
          f"{r.travellers} traveller(s)  ·  budget {rs(r.total_budget)} ({limits or 'a guide only'})")

def show_plan(update: dict) -> None:
    plan = update["plan"]
    t = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False)
    for col in ("#", "Tool", "Looks up", "For", "Why"):
        t.add_column(col, style="bold" if col == "Tool" else None, overflow="fold")
    for s in plan.steps:
        t.add_row(str(s.step), s.tool, s.query or "", (s.serves or "").replace("_", " "), s.reason)
    panel("3 · Plan before acting  (LLM, checked by code)", Group(Text(plan.summary, style="italic"), t,
                                                                  *corrections(update)))

def show_execution(update: dict) -> None:
    t = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False)
    for col in ("#", "Tool", "", "Result"):
        t.add_column(col, overflow="fold")
    for s in update.get("step_results", []):
        t.add_row(str(s.step), s.tool, "[green]ok[/green]" if s.ok else "[yellow]miss[/yellow]", s.summary)
    handled = [Text(f"handled: {e.where} {e.error_type} ({e.message}) → {e.handled_by}", style="magenta")
               for e in update.get("errors", [])]
    panel("4 · Execute the plan  (tools)", Group(t, *handled))

STYLE = {"visit": "bold", "travel": "dim", "start": "cyan", "bags": "cyan", "stay": "cyan", "end": "cyan"}

def _timeline_table(items) -> Table:
    t = Table.grid(padding=(0, 2), expand=True)
    t.add_column(style="dim")
    t.add_column(ratio=1)
    t.add_column(justify="right", style="dim")
    for i in items:
        t.add_row(f"{i.start:%H:%M}", Text(T.text(i), style=STYLE.get(i.kind, "")), T.takes(i))
    return t

def show_days(itinerary) -> None:
    for d in itinerary.days:
        w = d.weather
        title = f"Day {d.day} · {d.date:%a %d %b}" + (
            f" · {w.summary}, {w.temp_min_c:.0f}–{w.temp_max_c:.0f}°C, rain {w.rain_probability}%" if w else "")
        if d.timeline:
            notes = [Text(f"note: {n}", style="yellow") for n in d.day_notes]
            panel(title, Group(_timeline_table(d.timeline), *notes), style="green")
            continue
        lines = []
        if d.breakfast:
            lines.append(f"🍳 [dim]Breakfast[/dim]  {d.breakfast.name} ({d.breakfast.distance_km} km)")
        for i, p in enumerate(d.places, 1):
            wish = {"must_visit": "must visit", "popular": "popular sight"}.get(p.serves, f"for: {p.wish}")
            lines.append(f"{i}. [bold]{p.name}[/bold]  [dim]{wish}[/dim]")
        if not d.places:
            lines.append("Free day")
        if d.food_stop:
            lines.append(f"🍢 [dim]Food stop[/dim]  {d.food_stop.name} ({d.food_stop.distance_km} km)")
        if d.stay:
            lines.append(f"🏨 [dim]Stay[/dim]  {d.stay.name} ({d.stay.kind.replace('_', ' ')}, "
                         f"{d.stay.distance_km} km from tomorrow's places)")
        lines += [f"[yellow]note:[/yellow] {n}" for n in d.day_notes]
        panel(title, "\n".join(lines), style="green")

def show_budget(update: dict) -> None:
    c, v = update["cost"], update["verdict"]
    ch = c.choices
    t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    t.add_column()
    t.add_column(justify="right")
    hotel = f"Hotel ({ch.hotel_tier}{', outside centre' if ch.hotel_outside_centre else ''}, {c.rooms} room)"
    for label, amount in ((hotel, c.hotel), (f"Food ({ch.food_tier})", c.food),
                          (f"Local travel ({ch.transport})", c.local_travel), ("Entry tickets", c.tickets)):
        t.add_row(label, rs(amount))
    colour = {"within": "green", "over": "red", "under": "yellow"}[v.status]
    limit = f"limit {rs(v.ceiling)}" if v.ceiling else (f"floor {rs(v.floor)}" if v.floor else "no limit given")
    t.add_row("[bold]Total[/bold]", f"[bold]{rs(c.total)}[/bold]")
    verdict = Text(f"{v.status.upper()}" + (f" by {rs(v.gap)}" if v.status != "within" else "") + f"  ({limit})",
                   style=f"bold {colour}")
    panel("6 · Budget check  (code)", Group(t, verdict), style=colour)

def show_replan(update: dict) -> None:
    for e in update["trace"]:
        if e.event == "replan":
            d = e.detail
            body = (f"chose {', '.join(d['chosen'])} → applied: {'; '.join(d['applied']) or 'nothing'}"
                    + (f"\nignored (not allowed): {', '.join(d['ignored'])}" if d["ignored"] else "")
                    + f"\n[italic]why: {d['reason']}[/italic]\n{rs(d['cost_before'])} → {rs(d['cost_after'])}")
            panel(f"7 · Replan, round {d['round']}  (LLM chooses, code applies)", body, style="magenta")

def show(node: str, update: dict, state: dict) -> None:
    if node == "extract":
        show_goal(update)
    elif node == "normalize":
        show_request(update)
    elif node == "planner":
        show_plan(update)
    elif node == "executor":
        show_execution(update)
    elif node == "itinerary":
        days = "\n".join(f"Day {d.day}: " + (" → ".join(p.name for p in d.places) or "free")
                         for d in update["itinerary"].days)
        panel("5 · Build the days  (code: priority order, nearby places together, rainy days indoors)", days)
    elif node == "stays":
        for e in update.get("errors", []):
            console.print(Text(f"handled: {e.where} {e.error_type} ({e.message}) → {e.handled_by}", style="magenta"))
    elif node == "budget_check":
        show_budget(update)
    elif node == "replanner":
        show_replan(update)

def main() -> int:
    parser = argparse.ArgumentParser(description="Budget trip planner for India (agentic, LangGraph)")
    parser.add_argument("goal", help="the trip goal in plain words")
    parser.add_argument("--inject-failure", default="",
                        help=f"one of: {', '.join(config.INJECTABLE_FAILURES)} (comma-separated for several)")
    parser.add_argument("--out", default="", help="path prefix to save the report: PREFIX.md, PREFIX.json, PREFIX.log")
    args = parser.parse_args()

    injected = set()
    for name in filter(None, (n.strip() for n in args.inject_failure.split(","))):
        if name not in config.INJECTABLE_FAILURES:
            parser.error(f"unknown failure '{name}'")
        injected |= config.INJECTABLE_FAILURES[name]
    inject_failures(injected)

    console.rule("[bold]yatra-agent")
    console.print(f"[bold]Goal:[/bold] {args.goal}")
    if injected:
        tools = ", ".join(sorted(injected))
        console.print(f"[magenta]Injected failure: {tools} will time out on every attempt[/magenta]")
    state: dict = {"goal": args.goal, "today": dt.date.today(), "replan_count": 0}
    for step in build_graph().stream(state, stream_mode="updates"):
        for node, update in step.items():
            for key, value in update.items():  # keep a local copy of the state for printing
                state[key] = state.get(key, []) + value if key in APPEND else value
            show(node, update, state)

    if state.get("itinerary"):
        console.rule("[bold]Your trip, day by day")
        show_days(state["itinerary"])
    notes = state.get("notes") or []
    panel(f"8 · Report  ·  status: {state.get('status')}", "\n".join(f"• {n}" for n in notes) or "No notes.",
          style="blue")
    if args.out:
        prefix = pathlib.Path(args.out)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        prefix.with_suffix(".md").write_text(state["report_md"], encoding="utf-8")
        prefix.with_suffix(".json").write_text(json.dumps(state["report_json"], indent=2, ensure_ascii=False),
                                               encoding="utf-8")
        md, js, log = (prefix.with_suffix(ext) for ext in (".md", ".json", ".log"))
        console.print(f"Saved {md}, {js} and {log}")
        prefix.with_suffix(".log").write_text(console.export_text(), encoding="utf-8")
    return 0 if state.get("status") == "done" else 1

if __name__ == "__main__":
    sys.exit(main())
