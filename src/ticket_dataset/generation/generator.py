"""Turning a model response into a candidate record, or an accounted discard (FR-009b).

Structural validation is the pipeline's own obligation, not the SDK's. Constraining the response
format makes malformed output rare; it does not make it impossible, and FR-009b requires every
failure to land under exactly one named reason rather than escaping as an exception or being
coerced into a record.
"""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from ticket_dataset.model.client import StopReason
from ticket_dataset.model.wire import GeneratedConversation
from ticket_dataset.planning.slots import Slot
from ticket_dataset.run.enums import DiscardReason
from ticket_dataset.schema.enums import Role


@dataclass(frozen=True, slots=True)
class StructuralFailure:
    """Why a response could not become a record."""

    reason: DiscardReason
    detail: str


@dataclass(frozen=True, slots=True)
class Candidate:
    """A structurally valid conversation, not yet judged or scanned."""

    scenario: str
    turns: list[dict[str, str]]


def validate_response(
    text: str,
    slot: Slot,
    *,
    stop_reason: StopReason = StopReason.END_TURN,
) -> Candidate | StructuralFailure:
    """Parse and structurally check one response (FR-009, FR-009b, FR-009d).

    A truncated response is structurally invalid rather than salvageable: a conversation cut off
    mid-sentence is not a shorter conversation, and coercing one into a record would put
    truncated content into the corpus.
    """
    if stop_reason is StopReason.MAX_TOKENS:
        return StructuralFailure(
            DiscardReason.STRUCTURAL_INVALID,
            "response hit the token ceiling and is truncated",
        )

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        return StructuralFailure(DiscardReason.STRUCTURAL_INVALID, f"response is not JSON: {error}")

    try:
        conversation = GeneratedConversation.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "(root)"
        return StructuralFailure(DiscardReason.STRUCTURAL_INVALID, f"{location}: {first['msg']}")

    # The turn count is checked before the shape of the turns, and under its own reason: a
    # length the model would not honor and output it could not form are different causes, and
    # the accounting is only useful if each response lands under one reason predictably (FR-009b).
    if len(conversation.turns) != slot.turn_count:
        return StructuralFailure(
            DiscardReason.TURN_COUNT_OUT_OF_RANGE,
            f"asked for {slot.turn_count} turns, got {len(conversation.turns)}",
        )

    if conversation.turns[0].role is not Role.CUSTOMER:
        return StructuralFailure(DiscardReason.STRUCTURAL_INVALID, "the customer must speak first")

    for previous, current in zip(conversation.turns, conversation.turns[1:], strict=False):
        if previous.role is current.role:
            return StructuralFailure(
                DiscardReason.STRUCTURAL_INVALID,
                f"roles must alternate; {previous.role.value} speaks twice",
            )

    for index, turn in enumerate(conversation.turns):
        if not turn.content.strip():
            return StructuralFailure(
                DiscardReason.STRUCTURAL_INVALID, f"turn {index} is empty or whitespace"
            )

    if not conversation.scenario.strip():
        return StructuralFailure(DiscardReason.STRUCTURAL_INVALID, "scenario is empty")

    return Candidate(
        scenario=conversation.scenario.strip(),
        turns=[{"role": turn.role.value, "content": turn.content} for turn in conversation.turns],
    )
