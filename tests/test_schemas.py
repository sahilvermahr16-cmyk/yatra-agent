"""Schema guards for LLM output that function calling does not enforce."""
from schemas import ExtractedGoal, PlaceType


def test_unknown_interest_is_dropped_not_fatal():
    g = ExtractedGoal(destination="Kodaikanal", interests=["relaxation", "Nature"],
                      place_types=[{"words": "spas", "interests": ["wellness", "culture"]}])
    assert g.interests == ["nature"]
    assert g.place_types[0].interests == ["culture"]


def test_null_direction_means_not_stated():
    assert ExtractedGoal(budget_direction=None).budget_direction == "not_stated"


def test_llm_sees_budget_fields_as_required_without_default():
    schema = ExtractedGoal.model_json_schema()
    for name in ("budget_phrase", "budget_direction"):
        assert name in schema["required"]
        assert "default" not in schema["properties"][name]


def test_place_type_null_interests():
    assert PlaceType(words="spas", interests=None).interests == []
