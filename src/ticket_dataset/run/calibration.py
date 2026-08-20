"""Comparing the judge against human judgement (SC-011).

SC-011 asks that the judge be calibrated before a corpus is released. Calibration itself is a
human act — someone reads conversations and forms an opinion — so what this module provides is
the arithmetic around it and a record that survives the session: which rubric was judged, which
sample, by whom, and what the comparison showed.

**Two measures, because they answer different questions.**

*Gate agreement* asks whether the judge and the reviewer make the same pass/fail decision at the
threshold. That is what the threshold is for, and it is the number a release should turn on.

*Rank correlation* asks whether the judge orders conversations the way a person does. The
distinction matters when they disagree: a judge that is uniformly generous but correctly ordered
is fixable by moving the threshold, while one that ranks badly is not fixable that way at all.

Exact-score agreement is deliberately absent. On a continuous scale it means nothing, and on a
quantised one it would flatter a judge that simply returns the same number every time.
"""

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ScoredRecord:
    """One record a reviewer has scored alongside the judge."""

    record_id: str
    judge_score: float
    human_score: float
    judge_criteria: dict[str, float] = field(default_factory=dict)
    human_criteria: dict[str, float] = field(default_factory=dict)
    #: Which rubric produced ``judge_score``. Checked against the rubric being calibrated.
    rubric_id: str = ""

    def gate(self, threshold: float) -> tuple[bool, bool]:
        """``(judge_passes, human_passes)`` at ``threshold``."""
        return self.judge_score >= threshold, self.human_score >= threshold


@dataclass(frozen=True, slots=True)
class GateAgreement:
    """How often the judge and the reviewer reach the same admit/reject decision."""

    agreed: int
    total: int
    judge_admitted_human_rejected: int
    judge_rejected_human_admitted: int

    @property
    def rate(self) -> float:
        return self.agreed / self.total if self.total else 0.0

    def describe(self) -> str:
        parts = [f"{self.rate:.0%} agreement ({self.agreed}/{self.total})"]
        if self.judge_admitted_human_rejected:
            # The direction that matters most: records the corpus kept that a reviewer would not
            # have. A lenient judge admits work nobody vouched for.
            parts.append(f"{self.judge_admitted_human_rejected} admitted that a reviewer rejected")
        if self.judge_rejected_human_admitted:
            parts.append(f"{self.judge_rejected_human_admitted} rejected that a reviewer accepted")
        return "; ".join(parts)


def gate_agreement(records: Sequence[ScoredRecord], threshold: float) -> GateAgreement:
    """Agreement on the decision the threshold exists to make."""
    agreed = lenient = strict = 0
    for record in records:
        judge_passes, human_passes = record.gate(threshold)
        if judge_passes == human_passes:
            agreed += 1
        elif judge_passes:
            lenient += 1
        else:
            strict += 1
    return GateAgreement(
        agreed=agreed,
        total=len(records),
        judge_admitted_human_rejected=lenient,
        judge_rejected_human_admitted=strict,
    )


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Ranks with ties averaged, which is what Spearman requires."""
    ordered = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(ordered):
        end = position
        while end + 1 < len(ordered) and values[ordered[end + 1]] == values[ordered[position]]:
            end += 1
        shared = (position + end) / 2 + 1
        for index in range(position, end + 1):
            ranks[ordered[index]] = shared
        position = end + 1
    return ranks


def rank_correlation(records: Sequence[ScoredRecord]) -> float | None:
    """Spearman's rho between judge and human scores, or ``None`` when undefined.

    Implemented here rather than pulled from a scientific stack: it is a dozen lines, and this
    project has no other use for the dependency.

    ``None`` when fewer than three records, or when either side gave every record the same score.
    A judge that returns one number has no ordering to correlate — which is exactly the failure
    v1 of the rubric produced, so reporting it as ``None`` rather than 0.0 keeps the distinction
    between "disagrees" and "expressed no opinion".
    """
    if len(records) < 3:
        return None
    judge = [record.judge_score for record in records]
    human = [record.human_score for record in records]
    if len(set(judge)) == 1 or len(set(human)) == 1:
        return None

    judge_ranks = _average_ranks(judge)
    human_ranks = _average_ranks(human)
    n = len(records)
    mean = (n + 1) / 2
    covariance = sum((a - mean) * (b - mean) for a, b in zip(judge_ranks, human_ranks, strict=True))
    judge_variance = sum((a - mean) ** 2 for a in judge_ranks)
    human_variance = sum((b - mean) ** 2 for b in human_ranks)
    denominator = (judge_variance * human_variance) ** 0.5
    return covariance / denominator if denominator else None


def score_spread(values: Sequence[float]) -> dict[str, Any]:
    """How much of the scale a set of scores actually uses.

    ``distinct`` is the number that exposed the v1 rubric: three distinct scores across twenty
    records means the judge is choosing between anchors rather than judging.
    """
    if not values:
        return {"count": 0, "distinct": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "distinct": len({round(value, 4) for value in ordered}),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
        "median": ordered[len(ordered) // 2],
    }


@dataclass(slots=True)
class CalibrationRecord:
    """The committed evidence that a calibration happened, and what it found."""

    rubric_id: str
    rubric_sha256: str
    threshold: float
    reviewer: str
    calibrated_on: str
    sample_size: int
    sample_seed: int | None
    corpus: str
    gate_agreement_rate: float
    gate_agreement_detail: str
    rank_correlation: float | None
    judge_spread: dict[str, Any]
    human_spread: dict[str, Any]
    per_criterion_gap: dict[str, float] = field(default_factory=dict)
    notes: str = ""
    record_version: str = "1.0.0"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, directory: Path) -> Path:
        """Write ``<rubric_id>.calibration.json``, named so a release can find it by rubric."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.rubric_id}.calibration.json"
        path.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n")
        return path


def per_criterion_gap(records: Sequence[ScoredRecord]) -> dict[str, float]:
    """Mean signed gap per criterion, judge minus human.

    Positive means the judge is more generous on that criterion. Says *where* a disagreement
    lives, which a single overall number cannot: a judge may read coherence well and metadata fit
    badly, and only the criterion-level view suggests what to change in the rubric.
    """
    totals: dict[str, list[float]] = {}
    for record in records:
        for criterion, human_value in record.human_criteria.items():
            judge_value = record.judge_criteria.get(criterion)
            if judge_value is None:
                continue
            totals.setdefault(criterion, []).append(judge_value - human_value)
    return {
        criterion: round(sum(gaps) / len(gaps), 4)
        for criterion, gaps in sorted(totals.items())
        if gaps
    }


def calibrate(
    records: Sequence[ScoredRecord],
    *,
    rubric_id: str,
    rubric_sha256: str,
    threshold: float,
    reviewer: str,
    corpus: str,
    sample_seed: int | None = None,
    notes: str = "",
    now: datetime | None = None,
) -> CalibrationRecord:
    """Compare a scored sample and build the record."""
    if not records:
        raise ValueError("no scored records; a calibration over nothing measures nothing")
    agreement = gate_agreement(records, threshold)
    return CalibrationRecord(
        rubric_id=rubric_id,
        rubric_sha256=rubric_sha256,
        threshold=threshold,
        reviewer=reviewer,
        calibrated_on=(now or datetime.now(UTC)).date().isoformat(),
        sample_size=len(records),
        sample_seed=sample_seed,
        corpus=corpus,
        gate_agreement_rate=round(agreement.rate, 4),
        gate_agreement_detail=agreement.describe(),
        rank_correlation=(
            round(value, 4) if (value := rank_correlation(records)) is not None else None
        ),
        judge_spread=score_spread([record.judge_score for record in records]),
        human_spread=score_spread([record.human_score for record in records]),
        per_criterion_gap=per_criterion_gap(records),
        notes=notes,
    )


def load_scored_sample(path: Path) -> list[ScoredRecord]:
    """Read a sample a reviewer has scored (JSONL, one record per line)."""
    records: list[ScoredRecord] = []
    for number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if "human_score" not in payload:
            raise ValueError(
                f"{path}:{number} has no `human_score`. Add one to every line before "
                "calibrating; a partially scored sample would silently measure a subset."
            )
        records.append(
            ScoredRecord(
                record_id=payload.get("record_id", f"line-{number}"),
                judge_score=float(payload["coherence_score"]),
                human_score=float(payload["human_score"]),
                judge_criteria=payload.get("judge_criteria", {}) or {},
                human_criteria=payload.get("human_criteria", {}) or {},
                rubric_id=payload.get("rubric_id", ""),
            )
        )
    return records


def assert_sample_matches_rubric(records: Sequence[ScoredRecord], rubric_id: str) -> None:
    """Refuse to calibrate scores that a different rubric produced.

    A sample carries the rubric each record was judged against. Calibrating it while pointing at
    a different rubric would produce a record claiming to calibrate a rubric those scores never
    saw — the same shape of provenance lie the manifest's input hashes exist to prevent. It is an
    easy mistake to make right after revising a rubric, which is precisely when a calibration is
    most likely to be run.
    """
    found = {record.rubric_id for record in records if record.rubric_id}
    mismatched = sorted(found - {rubric_id})
    if mismatched:
        raise ValueError(
            f"the sample was judged against {', '.join(mismatched)} but the rubric given is "
            f"{rubric_id}. Re-judge the corpus with the current rubric before calibrating it, or "
            "pass the rubric the sample was actually scored with."
        )
