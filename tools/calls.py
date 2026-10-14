"""ToolLog: runs a tool call and records it, so every call shows up in the trace and every failure
becomes an ErrorRecord that says how the agent carried on."""
import time

from schemas import ErrorRecord, TraceEvent
from tools.http import ToolError


class ToolLog:
    def __init__(self, node: str):
        self.node = node
        self.trace: list[TraceEvent] = []
        self.errors: list[ErrorRecord] = []
        self.notes: list[str] = []

    def call(self, tool: str, fn, *args, on_fail: str):
        """Run fn(*args), which returns (result, attempts). Returns (result, True) on success,
        (None, False) on a ToolError; on_fail says how the agent continues without this result."""
        start = time.perf_counter()
        try:
            result, attempts = fn(*args)
        except ToolError as err:
            ms = int((time.perf_counter() - start) * 1000)
            self.trace.append(TraceEvent(node=self.node, event=f"{tool}_failed", duration_ms=ms,
                                         detail={"args": [str(a) for a in args], "error_type": err.error_type,
                                                 "message": err.message, "attempts": err.attempts,
                                                 "next": on_fail}))
            self.errors.append(ErrorRecord(where=tool, error_type=err.error_type,
                                           message=f"{err.message} (after {err.attempts} attempt(s))",
                                           handled_by=on_fail))
            return None, False
        ms = int((time.perf_counter() - start) * 1000)
        self.trace.append(TraceEvent(node=self.node, event=f"{tool}_ok", duration_ms=ms,
                                     detail={"args": [str(a) for a in args], "attempts": attempts}))
        return result, True
