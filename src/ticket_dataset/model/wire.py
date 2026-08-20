"""What the model is asked to return, before it is a record (contracts/model-io.md).

Kept deliberately separate from the record contract: the model supplies **content**, the
pipeline supplies **provenance and metadata**. A model that could write ``record_id``,
``run_id``, or ``coherence_score`` could corrupt provenance, so those fields are not in its
vocabulary. Never persisted.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ticket_dataset.schema.enums import Role

NonEmpty = Annotated[str, Field(min_length=1)]


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeneratedTurn(_Wire):
    role: Role
    content: NonEmpty


class GeneratedConversation(_Wire):
    """One conversation as the generating model returns it."""

    scenario: NonEmpty = Field(
        description="The specific situation elaborated within the assigned subdomain."
    )
    turns: list[GeneratedTurn] = Field(min_length=2)


class JudgeVerdict(_Wire):
    """One judgement as the judging model returns it.

    The pipeline computes the coherence score as the weighted mean of ``criteria`` using the
    rubric's declared weights, rather than trusting a holistic number reported alongside them:
    a model can return a score inconsistent with its own sub-scores, and the derived value is
    the one the threshold means (FR-009p).
    """

    criteria: dict[str, float] = Field(min_length=1)
    justification: str = ""


def response_schema(model: type[BaseModel]) -> dict:
    """The JSON Schema sent as ``output_config.format`` for a wire model."""
    schema = model.model_json_schema()
    schema["additionalProperties"] = False
    return schema
