"""The agent as a LangGraph state machine.

extract -> normalize -> planner -> executor -> itinerary -> stays -> budget_check <-> replanner -> reporter
A goal that cannot be planned (no destination, a failed step) goes straight to the reporter, which explains why.
"""

from langgraph.graph import END, StateGraph
from executor_node import executor_node
from extract_node import extract_node
from normalize_node import normalize_node
from planner_node import planner_node
from replanner_node import budget_check_node, needs_replan, replanner_node
from reporter import reporter_node
from scheduler import itinerary_node
from state import AgentState
from stays import stays_node

NODES = {"extract": extract_node, "normalize": normalize_node, "planner": planner_node,
         "executor": executor_node, "itinerary": itinerary_node, "stays": stays_node,
         "budget_check": budget_check_node,
         "replanner": replanner_node, "reporter": reporter_node}

def _stopped(state: dict) -> bool:
    return state.get("status") in ("needs_city", "gave_up")

def build_graph(nodes: dict | None = None):
    """nodes: replace any node function (used by tests)."""
    fns = {**NODES, **(nodes or {})}
    g = StateGraph(AgentState)
    for name, fn in fns.items():
        g.add_node(name, fn)
    g.set_entry_point("extract")
    g.add_conditional_edges("extract", lambda s: "stop" if _stopped(s) else "go",
                            {"stop": "reporter", "go": "normalize"})
    g.add_edge("normalize", "planner")
    g.add_edge("planner", "executor")
    g.add_conditional_edges("executor", lambda s: "stop" if _stopped(s) else "go",
                            {"stop": "reporter", "go": "itinerary"})
    g.add_edge("itinerary", "stays")
    g.add_edge("stays", "budget_check")
    g.add_conditional_edges("budget_check", lambda s: "replan" if needs_replan(s) else "report",
                            {"replan": "replanner", "report": "reporter"})
    g.add_edge("replanner", "budget_check")
    g.add_edge("reporter", END)
    return g.compile()




