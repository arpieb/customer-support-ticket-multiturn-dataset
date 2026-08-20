"""The committed coherence rubric (FR-009g, FR-009p).

A rubric that lives in a prompt string is a rubric that changes invisibly. Committing it and
hashing it into the manifest makes a change in judging standards a change in provenance. And
declaring criteria with weights, rather than prose alone, is what gives the 0.8 threshold a
stable meaning: a holistic score would mean whatever the model read the prose to mean.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from ticket_dataset.errors import RubricError
from ticket_dataset.generation.frontmatter import read_document

WEIGHT_SUM_EPSILON = 1e-6


@dataclass(frozen=True, slots=True)
class Rubric:
    path: Path
    rubric_id: str
    version: str
    weights: dict[str, float]
    body: str
    sha256: str

    @property
    def criteria(self) -> tuple[str, ...]:
        return tuple(sorted(self.weights))

    def score(self, criteria: dict[str, float]) -> float:
        """The weighted mean of the judge's per-criterion scores (FR-009p).

        Computed here rather than taken from a holistic number the model reports alongside its
        own sub-scores: a model can return a score inconsistent with them, and the derived value
        is the one the threshold means.
        """
        missing = set(self.weights) - set(criteria)
        if missing:
            raise RubricError(f"judge omitted criteria: {', '.join(sorted(missing))}")
        for name, value in criteria.items():
            if name in self.weights and not 0.0 <= value <= 1.0:
                raise RubricError(f"criterion {name} scored {value}, outside 0.0–1.0")
        return sum(self.weights[name] * criteria[name] for name in self.weights)


def load_rubric(path: Path) -> Rubric:
    """Read and validate the coherence rubric."""
    path = Path(path)
    if not path.exists():
        raise RubricError(f"coherence rubric not found: {path}")

    front, body = read_document(path)
    rubric_id = front.get("rubric_id")
    if not isinstance(rubric_id, str) or not rubric_id.strip():
        raise RubricError(
            f"{path} declares no `rubric_id`. A score is uninterpretable without one, because "
            "the criteria and weights behind it live in the rubric (FR-009i, FR-009p)."
        )

    declared = front.get("criteria")
    if not isinstance(declared, dict) or not declared:
        raise RubricError(
            f"{path} declares no `criteria` with weights. The score is their weighted mean, so "
            "prose alone is not enough (FR-009p)."
        )

    weights: dict[str, float] = {}
    for name, value in declared.items():
        if not isinstance(value, int | float):
            raise RubricError(f"{path}: weight for {name!r} is not a number: {value!r}")
        if value <= 0:
            raise RubricError(f"{path}: weight for {name!r} must be positive, got {value}")
        weights[name] = float(value)

    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_SUM_EPSILON:
        raise RubricError(
            f"{path}: criterion weights sum to {total:g}, not 1.0 (FR-009p). "
            "A weighted mean over weights that do not sum to 1 is not on a 0–1 scale."
        )
    if not body.strip():
        raise RubricError(
            f"{path}: the rubric body is empty; the judge has nothing to score against"
        )

    return Rubric(
        path=path,
        rubric_id=rubric_id.strip(),
        version=str(front.get("version", "")),
        weights=weights,
        body=body,
        sha256=sha256(path.read_bytes()).hexdigest(),
    )
