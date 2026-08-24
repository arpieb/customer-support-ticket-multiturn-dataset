"""Comparing the judge against human judgement (SC-011).

The measures here exist to answer two different questions, and the tests pin the difference: gate
agreement is about the decision the threshold makes, rank correlation about whether the judge
orders conversations the way a person does. A judge can score everything generously and still
rank perfectly, and the two numbers must say so.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ticket_dataset.run.calibration import (
    ScoredRecord,
    calibrate,
    gate_agreement,
    load_scored_sample,
    per_criterion_gap,
    rank_correlation,
    score_spread,
    unusable_criteria,
)


def _records(pairs: list[tuple[float, float]]) -> list[ScoredRecord]:
    return [
        ScoredRecord(record_id=f"r{i}", judge_score=judge, human_score=human)
        for i, (judge, human) in enumerate(pairs)
    ]


# --- gate agreement: the decision the threshold exists to make ------------------------------


def test_full_agreement_when_both_sides_decide_alike() -> None:
    records = _records([(0.9, 0.95), (0.9, 0.85), (0.5, 0.4), (0.7, 0.6)])
    agreement = gate_agreement(records, threshold=0.8)
    assert agreement.rate == 1.0
    assert agreement.judge_admitted_human_rejected == 0


def test_a_lenient_judge_is_reported_as_such() -> None:
    # The direction that matters most: records the corpus kept that a reviewer would not have.
    records = _records([(1.0, 0.5), (1.0, 0.6), (0.9, 0.9)])
    agreement = gate_agreement(records, threshold=0.8)
    assert agreement.judge_admitted_human_rejected == 2
    assert agreement.judge_rejected_human_admitted == 0
    assert "admitted that a reviewer rejected" in agreement.describe()


def test_a_strict_judge_is_reported_separately() -> None:
    records = _records([(0.5, 0.9), (0.6, 0.85), (0.9, 0.9)])
    agreement = gate_agreement(records, threshold=0.8)
    assert agreement.judge_rejected_human_admitted == 2
    assert "rejected that a reviewer accepted" in agreement.describe()


def test_agreement_is_measured_at_the_configured_threshold() -> None:
    # Same scores, different gate: agreement is a property of the pair *and* the threshold.
    records = _records([(0.85, 0.75)])
    assert gate_agreement(records, threshold=0.8).rate == 0.0
    assert gate_agreement(records, threshold=0.7).rate == 1.0


def test_a_score_exactly_at_the_threshold_passes() -> None:
    assert gate_agreement(_records([(0.8, 0.8)]), threshold=0.8).rate == 1.0


# --- rank correlation: whether the judge orders as a person does ----------------------------


def test_perfect_ordering_correlates_fully() -> None:
    records = _records([(0.9, 0.5), (0.8, 0.4), (0.7, 0.3), (0.6, 0.2)])
    assert rank_correlation(records) == pytest.approx(1.0)


def test_reversed_ordering_correlates_negatively() -> None:
    records = _records([(0.9, 0.2), (0.8, 0.3), (0.7, 0.4), (0.6, 0.5)])
    assert rank_correlation(records) == pytest.approx(-1.0)


def test_a_generous_judge_can_still_rank_perfectly() -> None:
    # Worth separating from agreement: this judge admits everything at a 0.8 gate while ordering
    # the records exactly as the reviewer did. That is fixable by moving the threshold; a judge
    # that ranked badly would not be.
    records = _records([(0.99, 0.7), (0.97, 0.6), (0.95, 0.5), (0.93, 0.4)])
    assert rank_correlation(records) == pytest.approx(1.0)
    assert gate_agreement(records, threshold=0.8).judge_admitted_human_rejected == 4


def test_a_judge_with_one_opinion_has_no_ordering() -> None:
    # The v1 rubric's failure. Reported as undefined rather than 0.0, because "expressed no
    # opinion" and "disagrees" are different findings.
    assert rank_correlation(_records([(1.0, 0.9), (1.0, 0.5), (1.0, 0.7)])) is None


def test_too_few_records_to_correlate() -> None:
    assert rank_correlation(_records([(0.9, 0.8), (0.8, 0.7)])) is None


def test_ties_are_ranked_by_average() -> None:
    # Without tie handling, a judge that scores two records alike would correlate wrongly.
    records = _records([(1.0, 0.9), (1.0, 0.8), (0.5, 0.2), (0.4, 0.1)])
    rho = rank_correlation(records)
    assert rho is not None and rho > 0.9


# --- spread: how much of the scale is actually used -----------------------------------------


def test_spread_counts_distinct_scores() -> None:
    # The number that exposed the v1 rubric: three distinct scores across twenty records.
    spread = score_spread([1.0] * 14 + [0.9] * 4 + [0.85] * 2)
    assert spread["count"] == 20
    assert spread["distinct"] == 3
    assert spread["max"] == 1.0
    assert spread["median"] == 1.0


def test_spread_of_nothing_is_not_an_error() -> None:
    assert score_spread([])["count"] == 0


# --- per-criterion gap ------------------------------------------------------------------------


def test_the_gap_says_which_criterion_disagrees() -> None:
    # A single overall number cannot say that a judge reads coherence well and metadata badly.
    records = [
        ScoredRecord(
            record_id="r1",
            judge_score=0.95,
            human_score=0.7,
            judge_criteria={"single_issue": 1.0, "metadata_fit": 1.0},
            human_criteria={"single_issue": 0.95, "metadata_fit": 0.4},
        )
    ]
    gaps = per_criterion_gap(records)
    assert gaps["metadata_fit"] == pytest.approx(0.6)
    assert gaps["single_issue"] == pytest.approx(0.05)


def test_criteria_the_judge_did_not_report_are_skipped() -> None:
    # Judge criteria are not persisted on records (FR-009p), so a sample drawn from a corpus has
    # none. The comparison degrades to empty rather than inventing a zero.
    records = [
        ScoredRecord(
            record_id="r1",
            judge_score=0.9,
            human_score=0.8,
            human_criteria={"single_issue": 0.8},
        )
    ]
    assert per_criterion_gap(records) == {}


# --- the record ------------------------------------------------------------------------------


def test_a_calibration_record_names_what_was_judged() -> None:
    record = calibrate(
        _records([(1.0, 0.7), (0.9, 0.6), (0.85, 0.9), (1.0, 0.95)]),
        rubric_id="coherence-v2",
        rubric_sha256="a" * 64,
        threshold=0.8,
        reviewer="rbates8",
        corpus="data/interim/run/records.partial.jsonl",
        sample_seed=5,
        notes="judge is lenient on metadata fit",
        now=datetime(2026, 8, 20, tzinfo=UTC),
    )
    assert record.rubric_id == "coherence-v2"
    assert record.rubric_sha256 == "a" * 64
    assert record.reviewer == "rbates8"
    assert record.calibrated_on == "2026-08-20"
    assert record.sample_size == 4
    assert record.sample_seed == 5
    assert record.notes


def test_calibrating_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="measures nothing"):
        calibrate([], rubric_id="x", rubric_sha256="y", threshold=0.8, reviewer="me", corpus="c")


def test_the_record_is_named_by_rubric_so_a_release_can_find_it(tmp_path: Path) -> None:
    record = calibrate(
        _records([(0.9, 0.8), (0.8, 0.7), (0.7, 0.6)]),
        rubric_id="coherence-v2",
        rubric_sha256="b" * 64,
        threshold=0.8,
        reviewer="me",
        corpus="c",
    )
    path = record.write(tmp_path)
    assert path.name == "coherence-v2.calibration.json"
    assert json.loads(path.read_text())["rubric_id"] == "coherence-v2"


def test_a_record_round_trips_as_json(tmp_path: Path) -> None:
    record = calibrate(
        _records([(0.9, 0.8), (0.8, 0.7), (0.7, 0.6)]),
        rubric_id="coherence-v2",
        rubric_sha256="c" * 64,
        threshold=0.8,
        reviewer="me",
        corpus="c",
    )
    payload = json.loads(record.write(tmp_path).read_text())
    assert set(payload) == set(record.as_dict())


# --- reading a scored sample -------------------------------------------------------------------


def _sample(tmp_path: Path, lines: list[dict]) -> Path:
    path = tmp_path / "sample.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def test_a_scored_sample_loads(tmp_path: Path) -> None:
    path = _sample(
        tmp_path,
        [
            {"record_id": "r1", "coherence_score": 1.0, "human_score": 0.7},
            {"record_id": "r2", "coherence_score": 0.9, "human_score": 0.85},
        ],
    )
    records = load_scored_sample(path)
    assert [r.record_id for r in records] == ["r1", "r2"]
    assert records[0].judge_score == 1.0
    assert records[0].human_score == 0.7


def test_an_unscored_line_is_refused_by_name(tmp_path: Path) -> None:
    # A partially scored sample would silently measure a subset, and report an agreement figure
    # for records nobody looked at.
    path = _sample(
        tmp_path,
        [
            {"record_id": "r1", "coherence_score": 1.0, "human_score": 0.7},
            {"record_id": "r2", "coherence_score": 0.9},
        ],
    )
    with pytest.raises(ValueError, match="has no `human_score`"):
        load_scored_sample(path)


def test_the_placeholder_null_counts_as_unscored(tmp_path: Path) -> None:
    # sample-for-review writes `human_score: null`; leaving it is not scoring it.
    path = _sample(tmp_path, [{"record_id": "r1", "coherence_score": 1.0, "human_score": None}])
    with pytest.raises((ValueError, TypeError)):
        load_scored_sample(path)


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "sample.jsonl"
    path.write_text('{"record_id":"r1","coherence_score":1.0,"human_score":0.8}\n\n')
    assert len(load_scored_sample(path)) == 1


# --- the sample must match the rubric being calibrated ---------------------------------------


def test_a_sample_judged_by_another_rubric_is_refused() -> None:
    """Calibrating v1 scores while pointing at v2 would claim a rubric those scores never saw.

    Easy to do right after revising a rubric — which is exactly when a calibration is most likely
    to be run.
    """
    from ticket_dataset.run.calibration import assert_sample_matches_rubric

    records = [
        ScoredRecord(record_id="r1", judge_score=1.0, human_score=0.7, rubric_id="coherence-v1")
    ]
    with pytest.raises(ValueError, match="judged against coherence-v1"):
        assert_sample_matches_rubric(records, "coherence-v2")


def test_a_matching_sample_passes() -> None:
    from ticket_dataset.run.calibration import assert_sample_matches_rubric

    records = [
        ScoredRecord(record_id="r1", judge_score=1.0, human_score=0.7, rubric_id="coherence-v2")
    ]
    assert_sample_matches_rubric(records, "coherence-v2")


def test_a_sample_without_rubric_ids_is_not_second_guessed() -> None:
    # A hand-assembled sample may carry no rubric_id; the check has nothing to compare and says so
    # by passing rather than by inventing a mismatch.
    from ticket_dataset.run.calibration import assert_sample_matches_rubric

    assert_sample_matches_rubric(_records([(1.0, 0.7)]), "coherence-v2")


def test_the_loaded_sample_carries_its_rubric(tmp_path: Path) -> None:
    path = _sample(
        tmp_path,
        [
            {
                "record_id": "r1",
                "coherence_score": 1.0,
                "human_score": 0.7,
                "rubric_id": "coherence-v1",
            }
        ],
    )
    assert load_scored_sample(path)[0].rubric_id == "coherence-v1"


def test_criteria_scored_with_nothing_to_compare_them_to_is_reported() -> None:
    """Scoring per criterion is real effort; discarding it silently is the wrong failure.

    A record carries only the weighted mean (FR-009p), so nothing supplies the judge's side.
    A reviewer who fills `human_criteria` in gets an empty comparison, and needs to be told.
    """
    records = [
        ScoredRecord(
            record_id="a",
            judge_score=0.9,
            human_score=0.7,
            human_criteria={"single_issue": 0.8, "metadata_fit": 0.6},
        )
    ]
    assert unusable_criteria(records)
    assert per_criterion_gap(records) == {}


def test_criteria_that_can_be_compared_are_not_reported_as_unusable() -> None:
    records = [
        ScoredRecord(
            record_id="a",
            judge_score=0.9,
            human_score=0.7,
            judge_criteria={"single_issue": 1.0},
            human_criteria={"single_issue": 0.8},
        )
    ]
    assert not unusable_criteria(records)
    assert per_criterion_gap(records) == {"single_issue": 0.2}


def test_a_sample_scored_only_overall_is_not_reported_as_unusable() -> None:
    # The normal case. Nothing to warn about when the reviewer scored what is measured.
    records = [ScoredRecord(record_id="a", judge_score=0.9, human_score=0.7)]
    assert not unusable_criteria(records)
