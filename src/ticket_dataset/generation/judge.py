"""Coherence judging against the committed rubric (FR-009f–FR-009l).

The score is computed from the judge's per-criterion scores using the rubric's declared weights,
not taken from any holistic number the model reports. A judge that cannot be parsed after the
configured attempts is a discard under its own reason — never an admitted unjudged record.
"""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from ticket_dataset.errors import RubricError
from ticket_dataset.generation.rubric import Rubric
from ticket_dataset.model.wire import JudgeVerdict
from ticket_dataset.run.enums import DiscardReason


@dataclass(frozen=True, slots=True)
class JudgeFailure:
    reason: DiscardReason
    detail: str


@dataclass(frozen=True, slots=True)
class Score:
    value: float
    rubric_id: str
    criteria: dict[str, float]


def score_response(text: str, rubric: Rubric) -> Score | JudgeFailure:
    """Parse a judge response and derive the coherence score (FR-009f, FR-009p)."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        return JudgeFailure(DiscardReason.UNJUDGEABLE, f"verdict is not JSON: {error}")

    try:
        verdict = JudgeVerdict.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "(root)"
        return JudgeFailure(DiscardReason.UNJUDGEABLE, f"{location}: {first['msg']}")

    try:
        value = rubric.score(verdict.criteria)
    except RubricError as error:
        return JudgeFailure(DiscardReason.UNJUDGEABLE, str(error))

    return Score(value=value, rubric_id=rubric.rubric_id, criteria=dict(verdict.criteria))


def meets_threshold(score: Score, threshold: float) -> bool:
    """Whether the record clears the run's coherence bar (FR-009h)."""
    return score.value >= threshold
