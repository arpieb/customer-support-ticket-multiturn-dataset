"""The one seam through which every model call passes (contracts/model-io.md).

Nothing outside :mod:`ticket_dataset.model.anthropic_client` imports ``anthropic``. That is
what lets the whole pipeline — and therefore the whole test suite — run offline against a fake,
which keeps CI free and deterministic.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ModelRole(StrEnum):
    """Which configured model spec a call uses."""

    GENERATOR = "generator"
    JUDGE = "judge"


class StopReason(StrEnum):
    """Why the model stopped, reduced to what the pipeline acts on."""

    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """One response, carrying what provenance and accounting need."""

    text: str
    #: The model that **actually** served the request, which a refusal fallback can change.
    #: Recorded per record so a fallback cannot make the manifest's model identity a lie
    #: (FR-027a).
    model_id: str
    stop_reason: StopReason = StopReason.END_TURN
    #: Transport-level retries the SDK performed. Reported separately from discards, because a
    #: degraded provider and a defective generator are different facts (FR-012d).
    retries: int = 0
    usage: dict[str, Any] = field(default_factory=dict)


class ModelRefusal(Exception):
    """The model declined on safety grounds — distinct from malformed output (FR-009m)."""


class ModelUnavailable(Exception):
    """A transport failure that survived the SDK's own retries."""


class ModelClient(Protocol):
    """What the pipeline needs from a model. Deliberately narrow."""

    async def complete_json(
        self,
        *,
        role: ModelRole,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> ModelResponse:
        """Return a response constrained to ``schema``.

        Raises :class:`ModelRefusal` on a safety decline that survived any fallback, and
        :class:`ModelUnavailable` on a transport failure. Malformed-but-returned content is
        **not** an exception: FR-009b makes validating it the pipeline's own obligation, so it
        comes back as text and is discarded with an accounted reason.
        """
        ...
