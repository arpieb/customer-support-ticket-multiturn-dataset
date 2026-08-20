"""Coherence judging (FR-009f–FR-009l, FR-009p)."""

import json
from pathlib import Path

import pytest

from ticket_dataset.generation.judge import JudgeFailure, Score, meets_threshold, score_response
from ticket_dataset.generation.rubric import load_rubric

RUBRIC_TEXT = """---
rubric_id: test-v1
criteria:
  single_issue: 0.5
  flow: 0.5
---

# Body

Guidance.
"""


@pytest.fixture
def rubric(tmp_path: Path):
    path = tmp_path / "rubric.md"
    path.write_text(RUBRIC_TEXT)
    return load_rubric(path)


def test_the_score_comes_from_the_criteria(rubric) -> None:
    verdict = json.dumps({"criteria": {"single_issue": 1.0, "flow": 0.0}, "justification": "x"})
    result = score_response(verdict, rubric)
    assert isinstance(result, Score)
    assert result.value == pytest.approx(0.5)
    assert result.rubric_id == "test-v1"


def test_a_holistic_score_from_the_model_is_ignored(rubric) -> None:
    # The derived value is the one the threshold means; a model can return a headline number
    # inconsistent with its own sub-scores (FR-009p).
    verdict = json.dumps({"criteria": {"single_issue": 0.0, "flow": 0.0}, "justification": "poor"})
    result = score_response(verdict, rubric)
    assert isinstance(result, Score)
    assert result.value == pytest.approx(0.0)


def test_an_unparseable_verdict_is_unjudgeable(rubric) -> None:
    result = score_response("not json", rubric)
    assert isinstance(result, JudgeFailure)
    assert result.reason.value == "unjudgeable"


def test_a_verdict_missing_a_criterion_is_unjudgeable(rubric) -> None:
    # Scoring a partial verdict would silently weight the missing criterion at zero, which is
    # not the same as the judge having scored it zero.
    verdict = json.dumps({"criteria": {"single_issue": 1.0}, "justification": "x"})
    result = score_response(verdict, rubric)
    assert isinstance(result, JudgeFailure)
    assert "omitted criteria" in result.detail


def test_a_criterion_outside_the_scale_is_unjudgeable(rubric) -> None:
    verdict = json.dumps({"criteria": {"single_issue": 1.4, "flow": 0.5}, "justification": "x"})
    assert isinstance(score_response(verdict, rubric), JudgeFailure)


def test_an_unknown_key_in_the_verdict_is_rejected(rubric) -> None:
    verdict = json.dumps(
        {"criteria": {"single_issue": 1.0, "flow": 1.0}, "justification": "x", "score": 0.99}
    )
    assert isinstance(score_response(verdict, rubric), JudgeFailure)


def test_extra_criteria_do_not_affect_the_weighted_mean(rubric) -> None:
    verdict = json.dumps(
        {"criteria": {"single_issue": 1.0, "flow": 1.0, "invented": 0.0}, "justification": "x"}
    )
    result = score_response(verdict, rubric)
    assert isinstance(result, Score)
    assert result.value == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("value", "threshold", "passes"),
    [(0.8, 0.8, True), (0.79, 0.8, False), (1.0, 0.8, True), (0.0, 0.0, True)],
)
def test_threshold_comparison_is_inclusive(value: float, threshold: float, passes: bool) -> None:
    score = Score(value=value, rubric_id="test-v1", criteria={})
    assert meets_threshold(score, threshold) is passes
