"""The rubric declares what a coherence score means (FR-009g, FR-009p)."""

from pathlib import Path

import pytest

from ticket_dataset_generator.errors import RubricError
from ticket_dataset_generator.generation.rubric import load_rubric

VALID = """---
rubric_id: test-v1
version: 1.0.0
criteria:
  single_issue: 0.6
  flow: 0.4
---

# Rubric body

How to score.
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rubric.md"
    path.write_text(text)
    return path


def test_a_valid_rubric_parses(tmp_path: Path) -> None:
    rubric = load_rubric(_write(tmp_path, VALID))
    assert rubric.rubric_id == "test-v1"
    assert rubric.criteria == ("flow", "single_issue")


def test_the_committed_rubric_is_valid() -> None:
    rubric = load_rubric(Path("prompts/coherence-rubric.md"))
    assert abs(sum(rubric.weights.values()) - 1.0) < 1e-9


def test_weights_must_sum_to_one(tmp_path: Path) -> None:
    # A weighted mean over weights that do not sum to 1 is not on a 0-1 scale, so the threshold
    # would not mean what FR-009h says it means.
    text = VALID.replace("flow: 0.4", "flow: 0.9")
    with pytest.raises(RubricError, match="sum to 1.5"):
        load_rubric(_write(tmp_path, text))


def test_a_rubric_without_an_id_is_refused(tmp_path: Path) -> None:
    text = VALID.replace("rubric_id: test-v1\n", "")
    with pytest.raises(RubricError, match="declares no `rubric_id`"):
        load_rubric(_write(tmp_path, text))


def test_a_rubric_without_criteria_is_refused(tmp_path: Path) -> None:
    text = "---\nrubric_id: test-v1\n---\n\n# Body\n\nProse only.\n"
    with pytest.raises(RubricError, match="declares no `criteria`"):
        load_rubric(_write(tmp_path, text))


def test_a_non_positive_weight_is_refused(tmp_path: Path) -> None:
    text = VALID.replace("flow: 0.4", "flow: 0.0").replace("single_issue: 0.6", "single_issue: 1.0")
    with pytest.raises(RubricError, match="must be positive"):
        load_rubric(_write(tmp_path, text))


# --- scoring (FR-009p) ---------------------------------------------------------------------


def test_the_score_is_the_weighted_mean(tmp_path: Path) -> None:
    rubric = load_rubric(_write(tmp_path, VALID))
    assert rubric.score({"single_issue": 1.0, "flow": 0.0}) == pytest.approx(0.6)
    assert rubric.score({"single_issue": 0.5, "flow": 0.5}) == pytest.approx(0.5)


def test_a_holistic_score_from_the_model_is_not_used(tmp_path: Path) -> None:
    # A model can return a headline number inconsistent with its own sub-scores. The derived
    # value is the one the threshold means, so an extra key is simply ignored.
    rubric = load_rubric(_write(tmp_path, VALID))
    assert rubric.score({"single_issue": 0.0, "flow": 0.0, "score": 0.99}) == pytest.approx(0.0)


def test_a_missing_criterion_is_an_error(tmp_path: Path) -> None:
    # Scoring a partial verdict would silently weight the missing criterion at zero.
    rubric = load_rubric(_write(tmp_path, VALID))
    with pytest.raises(RubricError, match="omitted criteria: flow"):
        rubric.score({"single_issue": 1.0})


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_a_criterion_outside_the_scale_is_an_error(tmp_path: Path, value: float) -> None:
    rubric = load_rubric(_write(tmp_path, VALID))
    with pytest.raises(RubricError, match="outside 0.0"):
        rubric.score({"single_issue": value, "flow": 0.5})


def test_editing_the_rubric_changes_its_identity(tmp_path: Path) -> None:
    # A change in judging standards is a change in provenance (FR-009g).
    before = load_rubric(_write(tmp_path, VALID)).sha256
    after = load_rubric(_write(tmp_path, VALID + "\nMore guidance.\n")).sha256
    assert before != after
