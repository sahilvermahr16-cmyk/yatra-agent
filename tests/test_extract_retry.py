"""The extract node retries the LLM once when its output fails a self-check. No network: the LLM is faked."""
import datetime as dt
import os

import pytest
from pydantic import ValidationError

pytest.importorskip("langchain_openai")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

import extract_node  # noqa: E402
from schemas import DateRef, ExtractedGoal, PlaceType  # noqa: E402

GOAL = "Kodaikanal from 5 Nov for 4 days"


class FakeLLM:
    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def invoke(self, messages):
        self.calls.append(messages)
        return self.outputs.pop(0)


def goal_with_start(day):
    return ExtractedGoal(destination="Kodaikanal", days=4,
                         start=DateRef(phrase="from 5 Nov", kind="calendar_date", day=day, month=11))


def test_retry_when_day_is_not_in_phrase(monkeypatch):
    fake = FakeLLM(goal_with_start(8), goal_with_start(5))
    monkeypatch.setattr(extract_node, "structured_llm", fake)
    out = extract_node.extract_node({"goal": GOAL, "today": dt.date(2026, 10, 12)})
    assert len(fake.calls) == 2
    assert "day 8" in fake.calls[1][-1][1]
    assert out["request"].start.day == 5
    assert [e.event for e in out["trace"]] == ["llm_extract", "llm_self_check_retry"]


def test_no_retry_when_dates_are_consistent(monkeypatch):
    fake = FakeLLM(goal_with_start(5))
    monkeypatch.setattr(extract_node, "structured_llm", fake)
    extract_node.extract_node({"goal": GOAL, "today": dt.date(2026, 10, 12)})
    assert len(fake.calls) == 1


def test_retry_when_a_place_type_has_no_interest(monkeypatch):
    first = ExtractedGoal(destination="Kodaikanal", place_types=[PlaceType(words="lakes")])
    fixed = ExtractedGoal(destination="Kodaikanal", place_types=[PlaceType(words="lakes", interests=["nature"])])
    fake = FakeLLM(first, fixed)
    monkeypatch.setattr(extract_node, "structured_llm", fake)
    out = extract_node.extract_node({"goal": "Kodaikanal, lakes", "today": dt.date(2026, 10, 12)})
    assert len(fake.calls) == 2 and "'lakes' has no interests" in fake.calls[1][-1][1]
    assert out["request"].place_types[0].interests == ["nature"]


def run_budget(monkeypatch, goal, *outputs):
    fake = FakeLLM(*outputs)
    monkeypatch.setattr(extract_node, "structured_llm", fake)
    return fake, extract_node.extract_node({"goal": goal, "today": dt.date(2026, 10, 12)})


def test_figure_without_its_words_is_retried(monkeypatch):
    first = ExtractedGoal(destination="Kodaikanal", budget_amount=9000)
    fixed = first.model_copy(update={"budget_phrase": "strictly within 9000", "budget_direction": "at_most"})
    fake, out = run_budget(monkeypatch, "Kodaikanal strictly within 9000", first, fixed)
    assert len(fake.calls) == 2 and "budget_phrase is empty" in fake.calls[1][-1][1]
    assert out["request"].budget_direction == "at_most"


def test_budget_phrase_not_in_goal_is_retried(monkeypatch):
    first = ExtractedGoal(destination="Kodaikanal", budget_amount=9000, budget_phrase="at most 9000",
                          budget_direction="at_most")
    fixed = first.model_copy(update={"budget_phrase": "9000", "budget_direction": "not_stated"})
    fake, _ = run_budget(monkeypatch, "Kodaikanal 2 days, 9000", first, fixed)
    assert len(fake.calls) == 2 and "does not appear in the goal" in fake.calls[1][-1][1]


def test_budget_phrase_without_the_figure_is_retried(monkeypatch):
    first = ExtractedGoal(destination="Kodaikanal", budget_amount=9000, budget_phrase="strictly within",
                          budget_direction="at_most")
    fixed = first.model_copy(update={"budget_phrase": "strictly within 9000"})
    fake, _ = run_budget(monkeypatch, "Kodaikanal strictly within 9000", first, fixed)
    assert len(fake.calls) == 2 and "does not contain the money figure" in fake.calls[1][-1][1]


def schema_error():
    try:
        ExtractedGoal(days=0)
    except ValidationError as err:
        return err


class RaisingLLM(FakeLLM):
    def invoke(self, messages):
        self.calls.append(messages)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def test_parse_error_is_retried_once(monkeypatch):
    fake = RaisingLLM(schema_error(), goal_with_start(5))
    monkeypatch.setattr(extract_node, "structured_llm", fake)
    out = extract_node.extract_node({"goal": GOAL, "today": dt.date(2026, 10, 12)})
    assert len(fake.calls) == 2 and "did not match" in fake.calls[1][-1][1]
    assert out["status"] == "running" and out["trace"][0].event == "llm_parse_retry"


def test_two_parse_errors_give_up_without_crashing(monkeypatch):
    fake = RaisingLLM(schema_error(), schema_error())
    monkeypatch.setattr(extract_node, "structured_llm", fake)
    out = extract_node.extract_node({"goal": GOAL, "today": dt.date(2026, 10, 12)})
    assert out["status"] == "gave_up" and out["errors"][0].where == "extract"
    assert "request" not in out


def test_null_flags_from_the_llm_mean_false():
    g = ExtractedGoal(destination="Kodaikanal", budget_is_per_person=None, budget_is_per_day=None,
                      place_types=None, must_visit=None)
    assert (g.budget_is_per_person, g.budget_is_per_day, g.place_types, g.must_visit) == (False, False, [], [])


def test_direction_without_any_figure_is_retried(monkeypatch):
    first = ExtractedGoal(destination="Kodaikanal", budget_direction="at_most")
    fixed = first.model_copy(update={"budget_direction": "not_stated"})
    fake, out = run_budget(monkeypatch, "Kodaikanal for 2 days", first, fixed)
    assert len(fake.calls) == 2 and "no money figure" in fake.calls[1][-1][1]
    assert out["request"].budget_direction == "not_stated"


def test_bare_figure_with_its_words_needs_no_retry(monkeypatch):
    goal = ExtractedGoal(destination="Kodaikanal", budget_amount=9000, budget_phrase="budget 9000")
    fake, out = run_budget(monkeypatch, "Kodaikanal, budget 9000", goal)
    assert len(fake.calls) == 1 and out["request"].budget_direction == "not_stated"


def test_range_without_its_larger_number_is_retried(monkeypatch):
    first = ExtractedGoal(destination="Bhopal", budget_amount=6000, budget_phrase="6000-8000",
                          budget_direction="range")
    fixed = first.model_copy(update={"budget_amount_max": 8000})
    fake, out = run_budget(monkeypatch, "Bhopal, 6000-8000", first, fixed)
    assert len(fake.calls) == 2 and "budget_amount_max is empty" in fake.calls[1][-1][1]
    assert out["request"].budget_amount_max == 8000


def test_range_with_one_number_in_the_phrase_is_retried(monkeypatch):
    first = ExtractedGoal(destination="Bhopal", budget_amount=6000, budget_amount_max=8000,
                          budget_phrase="around 6000", budget_direction="range")
    fixed = first.model_copy(update={"budget_amount_max": None, "budget_direction": "about"})
    fake, _ = run_budget(monkeypatch, "Bhopal, around 6000", first, fixed)
    assert len(fake.calls) == 2 and "has only one number" in fake.calls[1][-1][1]


def test_larger_number_outside_a_range_is_retried(monkeypatch):
    first = ExtractedGoal(destination="Bhopal", budget_amount=6000, budget_amount_max=8000,
                          budget_phrase="up to 6000", budget_direction="at_most")
    fixed = first.model_copy(update={"budget_amount_max": None})
    fake, _ = run_budget(monkeypatch, "Bhopal, up to 6000", first, fixed)
    assert len(fake.calls) == 2 and "only for a range" in fake.calls[1][-1][1]
