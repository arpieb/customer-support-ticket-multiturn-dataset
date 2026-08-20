"""The single serialized configuration a run takes as input (FR-008).

Recorded verbatim in the manifest and hashed into the checkpoint's input fingerprints, so a
resume under changed configuration is refused rather than producing a corpus the manifest
cannot honestly describe (FR-015e).
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ticket_dataset.config import defaults
from ticket_dataset.schema.enums import COMPOSITION_DIMENSIONS

Proportion = Annotated[float, Field(ge=0.0, le=1.0)]

#: Proportions are floats; a tolerance avoids rejecting a distribution that sums to 0.9999998.
SUM_EPSILON = 1e-6


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelSpec(_Config):
    """Identity and parameters of one model role, recorded in the manifest (FR-027)."""

    model_id: str = defaults.DEFAULT_MODEL_ID
    effort: str = defaults.DEFAULT_EFFORT
    max_tokens: int = Field(default=defaults.DEFAULT_MAX_TOKENS, ge=1)
    thinking: str = "adaptive"
    #: Null states plainly that no sampling seed was used, rather than implying a
    #: reproducibility the run cannot deliver (FR-010).
    sampling_seed: int | None = None
    #: A declined request is rescued on another model unless this is off. A rescued record
    #: stays in the corpus and names its actual producer (FR-009n, FR-027a).
    fallback_enabled: bool = True


class Models(_Config):
    generator: ModelSpec = Field(default_factory=ModelSpec)
    judge: ModelSpec = Field(default_factory=ModelSpec)


class TurnRange(_Config):
    """Bounds on conversation length; each length is drawn uniformly (FR-009d)."""

    min: int = Field(default=defaults.DEFAULT_TURNS_MIN, ge=defaults.MINIMUM_TURNS)
    max: int = Field(default=defaults.DEFAULT_TURNS_MAX, ge=defaults.MINIMUM_TURNS)


class TimeWindow(_Config):
    """The window ticket creation times are drawn from (FR-006a)."""

    start: date
    end: date


class ResolutionDuration(_Config):
    """Bounds on the seeded gap between creation and resolution (FR-006a)."""

    min: timedelta = defaults.DEFAULT_RESOLUTION_MIN
    max: timedelta = defaults.DEFAULT_RESOLUTION_MAX


class Coherence(_Config):
    threshold: Proportion = defaults.DEFAULT_COHERENCE_THRESHOLD
    max_discard_rate: Proportion = defaults.DEFAULT_COHERENCE_MAX_DISCARD_RATE


class Privacy(_Config):
    max_discard_rate: Proportion = defaults.DEFAULT_PRIVACY_MAX_DISCARD_RATE
    exceptions: Path = Path(defaults.DEFAULT_EXCEPTIONS)


class Budget(_Config):
    """Ceilings that stop and checkpoint a run rather than failing it (FR-012f)."""

    max_runtime: timedelta | None = None
    max_model_calls: int | None = Field(default=None, ge=1)

    @property
    def is_declared(self) -> bool:
        return self.max_runtime is not None or self.max_model_calls is not None


class Composition(_Config):
    """Four independent distributions, one per controlled dimension (FR-030).

    Independent by design: any combination of the four may occur and no joint distribution is
    expressible. An implausible pairing is the model's problem to render coherently and the
    judge's to catch, not a composition concern (spec Assumptions).
    """

    category: dict[str, Proportion]
    priority: dict[str, Proportion]
    channel: dict[str, Proportion]
    resolution_status: dict[str, Proportion]

    @classmethod
    def default(cls) -> Self:
        return cls(**defaults.DEFAULT_COMPOSITION)

    def as_dict(self) -> dict[str, dict[str, float]]:
        return {dim: dict(getattr(self, dim)) for dim in COMPOSITION_DIMENSIONS}

    def problems(self) -> list[str]:
        """Every reason this request cannot be satisfied, not just the first (FR-032)."""
        found: list[str] = []
        for dimension, enum in COMPOSITION_DIMENSIONS.items():
            distribution: dict[str, float] = getattr(self, dimension)
            if not distribution:
                found.append(f"composition.{dimension}: no members given")
                continue
            valid = {member.value for member in enum}
            for name in distribution:
                if name not in valid:
                    found.append(
                        f"composition.{dimension}: {name!r} is not a member "
                        f"({', '.join(sorted(valid))})"
                    )
            total = sum(distribution.values())
            if abs(total - 1.0) > SUM_EPSILON:
                found.append(f"composition.{dimension}: proportions sum to {total:g}, not 1.0")
        return found


class GenerationConfig(_Config):
    """What to generate. The run's only configuration input (FR-008)."""

    record_count: int = Field(ge=1)
    output_path: Path
    prompt_document: Path = Path(defaults.DEFAULT_PROMPT_DOCUMENT)
    rubric: Path = Path(defaults.DEFAULT_RUBRIC)
    language: str = defaults.DEFAULT_LANGUAGE
    composition: Composition | None = None
    turns: TurnRange = Field(default_factory=TurnRange)
    time_window: TimeWindow | None = None
    resolution_duration: ResolutionDuration = Field(default_factory=ResolutionDuration)
    coherence: Coherence = Field(default_factory=Coherence)
    privacy: Privacy = Field(default_factory=Privacy)
    budget: Budget = Field(default_factory=Budget)
    models: Models = Field(default_factory=Models)
    composition_tolerance_pp: float = Field(
        default=defaults.DEFAULT_COMPOSITION_TOLERANCE_PP, gt=0.0, le=100.0
    )
    max_concurrency: int = Field(default=defaults.DEFAULT_MAX_CONCURRENCY, ge=1)
    requests_per_minute: int = Field(default=defaults.DEFAULT_REQUESTS_PER_MINUTE, ge=1)
    max_attempts_per_slot: int = Field(default=defaults.DEFAULT_MAX_ATTEMPTS_PER_SLOT, ge=1)
    consecutive_failure_limit: int = Field(default=defaults.DEFAULT_CONSECUTIVE_FAILURE_LIMIT, ge=1)
    checkpoint_interval: int = Field(default=defaults.DEFAULT_CHECKPOINT_INTERVAL, ge=1)

    @property
    def effective_composition(self) -> Composition:
        """The requested composition, or the documented default (FR-033)."""
        return self.composition or Composition.default()

    @model_validator(mode="after")
    def _window_defaults_to_the_recent_past(self) -> Self:
        if self.time_window is None:
            end = date(2026, 1, 1)
            start = end - timedelta(days=defaults.DEFAULT_TIME_WINDOW_DAYS)
            object.__setattr__(self, "time_window", TimeWindow(start=start, end=end))
        return self
