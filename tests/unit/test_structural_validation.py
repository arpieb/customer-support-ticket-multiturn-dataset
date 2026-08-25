"""Every rejection path lands under exactly one reason (FR-009b, FR-009m)."""

import json

import pytest

from tests.helpers import make_slot
from ticket_dataset_generator.generation.generator import (
    Candidate,
    StructuralFailure,
    validate_response,
)
from ticket_dataset_generator.model.client import StopReason
from ticket_dataset_generator.planning.slots import Slot
from ticket_dataset_generator.run.enums import DiscardReason


def _conversation(turns: list[tuple[str, str]], scenario: str = "a specific situation") -> str:
    return json.dumps(
        {"scenario": scenario, "turns": [{"role": r, "content": c} for r, c in turns]}
    )


def _four_turns() -> list[tuple[str, str]]:
    return [
        ("customer", "My order never arrived."),
        ("agent", "Let me check that for you."),
        ("customer", "Thanks, the number is ORD-4417."),
        ("agent", "It shipped yesterday; here is the tracking link."),
    ]


@pytest.fixture
def slot() -> Slot:
    return make_slot(turn_count=4)


def test_a_well_formed_response_becomes_a_candidate(slot: Slot) -> None:
    result = validate_response(_conversation(_four_turns()), slot)
    assert isinstance(result, Candidate)
    assert len(result.turns) == 4
    assert result.scenario == "a specific situation"


def test_unparseable_output_is_structurally_invalid(slot: Slot) -> None:
    result = validate_response("{not json", slot)
    assert isinstance(result, StructuralFailure)
    assert result.reason is DiscardReason.STRUCTURAL_INVALID


def test_a_missing_key_is_structurally_invalid(slot: Slot) -> None:
    result = validate_response(json.dumps({"turns": []}), slot)
    assert isinstance(result, StructuralFailure)
    assert result.reason is DiscardReason.STRUCTURAL_INVALID


def test_a_wrong_turn_count_has_its_own_reason(slot: Slot) -> None:
    # A length the model would not honor and output it could not form are different causes; the
    # accounting is only useful if each response lands under one reason predictably.
    result = validate_response(_conversation(_four_turns()[:2]), slot)
    assert isinstance(result, StructuralFailure)
    assert result.reason is DiscardReason.TURN_COUNT_OUT_OF_RANGE
    assert "asked for 4" in result.detail


def test_an_agent_first_conversation_is_rejected(slot: Slot) -> None:
    turns = [("agent", "How can I help?"), ("customer", "My order never arrived.")]
    result = validate_response(_conversation(turns), make_slot(turn_count=2))
    assert isinstance(result, StructuralFailure)
    assert "customer must speak first" in result.detail


def test_non_alternating_roles_are_rejected(slot: Slot) -> None:
    turns = [
        ("customer", "My order never arrived."),
        ("customer", "It has been a week."),
        ("agent", "Checking now."),
        ("agent", "Still checking."),
    ]
    result = validate_response(_conversation(turns), slot)
    assert isinstance(result, StructuralFailure)
    assert "alternate" in result.detail


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_an_empty_turn_is_rejected(slot: Slot, blank: str) -> None:
    turns = _four_turns()
    turns[2] = ("customer", blank)
    result = validate_response(_conversation(turns), slot)
    assert isinstance(result, StructuralFailure)
    assert result.reason is DiscardReason.STRUCTURAL_INVALID


def test_a_truncated_response_is_never_coerced(slot: Slot) -> None:
    # A conversation cut off mid-sentence is not a shorter conversation.
    result = validate_response(
        _conversation(_four_turns()), slot, stop_reason=StopReason.MAX_TOKENS
    )
    assert isinstance(result, StructuralFailure)
    assert "truncated" in result.detail


def test_an_empty_scenario_is_rejected(slot: Slot) -> None:
    result = validate_response(_conversation(_four_turns(), scenario="   "), slot)
    assert isinstance(result, StructuralFailure)
    assert "scenario" in result.detail


def test_an_unknown_role_is_rejected(slot: Slot) -> None:
    payload = json.dumps({"scenario": "x", "turns": [{"role": "supervisor", "content": "hi"}] * 4})
    result = validate_response(payload, slot)
    assert isinstance(result, StructuralFailure)


def test_the_model_cannot_smuggle_provenance_fields(slot: Slot) -> None:
    # The wire model forbids extras, so a model that tried to write record_id would be rejected
    # rather than have the value silently ignored (contracts/model-io.md).
    payload = json.loads(_conversation(_four_turns()))
    payload["record_id"] = "attacker-supplied"
    result = validate_response(json.dumps(payload), slot)
    assert isinstance(result, StructuralFailure)


def test_non_latin_content_passes(slot: Slot) -> None:
    turns = [
        ("customer", "注文が届きませんでした"),
        ("agent", "確認いたします"),
        ("customer", "ありがとうございます"),
        ("agent", "昨日発送されています"),
    ]
    assert isinstance(validate_response(_conversation(turns), slot), Candidate)
