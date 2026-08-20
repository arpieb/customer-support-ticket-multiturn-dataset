"""The record contract — the authoritative definition every producer writes against.

This module is the contract (Constitution I). It exports
``specs/001-ticket-generation-pipeline/contracts/record.schema.json`` via
:mod:`ticket_dataset.schema.export`, and a contract test fails on any drift between the two.

The layering matters: this model enforces *shape* — types, enums, presence, and the
relationships between fields within one record. Whether a corpus is coherent, deduplicated, or
free of identifiers is enforced elsewhere, which is what lets a record fail a gate while still
being structurally parseable.
"""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ticket_dataset.schema.enums import Category, Channel, Priority, ResolutionStatus, Role

NonEmptyText = Annotated[str, Field(min_length=1)]


class _Contract(BaseModel):
    """Base for every contract model: unknown fields are an error, not a silent pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ConversationTurn(_Contract):
    """A single utterance within a record (FR-004)."""

    index: int = Field(ge=0, description="Position in the conversation; ascends from 0.")
    role: Role
    # The pattern carries the non-blank guarantee into the exported JSON Schema, so a consumer
    # validating with the schema alone gets it too; the validator below repeats it to produce a
    # clearer message than a regex failure would.
    content: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def _content_is_not_blank(self) -> Self:
        # Any Unicode is valid content — non-Latin, emoji, RTL (spec Edge Cases). What is not
        # valid is whitespace pretending to be an utterance (FR-009).
        if not self.content.strip():
            raise ValueError("turn content must not be empty or whitespace-only")
        return self


class TicketMetadata(_Contract):
    """Descriptive attributes of the interaction (FR-006).

    Every field here is assigned by the pipeline before the model is called, not chosen by the
    model. That is what makes the composition tolerance achievable by construction, and what
    makes the timestamps reproducible (FR-006a, research R3).
    """

    category: Category
    priority: Priority
    channel: Channel
    resolution_status: ResolutionStatus
    created_at: datetime
    resolved_at: datetime | None = None

    @model_validator(mode="after")
    def _resolution_time_matches_status(self) -> Self:
        resolved = self.resolution_status is ResolutionStatus.RESOLVED
        if resolved and self.resolved_at is None:
            raise ValueError("resolved tickets must carry a resolution time (FR-006b)")
        if not resolved and self.resolved_at is not None:
            # A ticket that was escalated, abandoned, or left unresolved has no resolution to
            # time; recording one anyway would make the field mean different things in
            # different records (FR-006b).
            raise ValueError(
                f"resolution time is only valid when resolved; status is "
                f"{self.resolution_status.value} (FR-006b)"
            )
        if self.resolved_at is not None and self.resolved_at < self.created_at:
            raise ValueError("resolution time must not precede creation time")
        return self

    @model_validator(mode="after")
    def _timestamps_are_aware(self) -> Self:
        for name in ("created_at", "resolved_at"):
            value: datetime | None = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware (FR-006)")
        return self


class RecordQuality(_Contract):
    """The judge's verdict, retained so the corpus can be filtered without re-judging (FR-009i)."""

    coherence_score: float = Field(ge=0.0, le=1.0)
    rubric_id: NonEmptyText = Field(
        description="Which rubric produced the score; a bare number cannot be interpreted."
    )


class GenerationInfo(_Contract):
    """Which models actually served this record (FR-027a).

    Recorded per record rather than only per run because a refusal fallback can change the
    serving model mid-run, and a single run-level identity would then be false for part of the
    corpus.
    """

    model_id: NonEmptyText
    judge_model_id: NonEmptyText


class TicketRecord(_Contract):
    """One complete multi-turn support interaction."""

    # Required, not defaulted: FR-002 says every record *declares* the version it was written
    # against, and a default would let a producer omit the declaration and still validate.
    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    record_id: NonEmptyText
    run_id: NonEmptyText
    record_index: int = Field(ge=0)
    source_id: NonEmptyText = Field(description="Domain prompt document identity: name@sha-prefix.")
    subdomain: NonEmptyText = Field(
        description="Seeded choice from the prompt document's declared list; reproducible."
    )
    scenario: NonEmptyText = Field(
        description="The situation the model elaborated within that subdomain; model text."
    )
    metadata: TicketMetadata
    turns: list[ConversationTurn] = Field(min_length=2)
    quality: RecordQuality
    generation: GenerationInfo

    @model_validator(mode="after")
    def _turns_are_ordered_and_alternating(self) -> Self:
        for expected, turn in enumerate(self.turns):
            if turn.index != expected:
                raise ValueError(
                    f"turn indices must ascend contiguously from 0; got {turn.index} "
                    f"at position {expected} (FR-004)"
                )
        # The customer opens: a support interaction begins with the party raising the issue.
        # Leaving this unstated would let two conforming implementations produce corpora that
        # differ on every record (FR-009).
        if self.turns[0].role is not Role.CUSTOMER:
            raise ValueError("the customer speaks first (FR-009)")
        for previous, current in zip(self.turns, self.turns[1:], strict=False):
            if previous.role is current.role:
                raise ValueError(
                    f"roles must alternate; {previous.role.value} speaks twice at index "
                    f"{current.index} (FR-009)"
                )
        return self
