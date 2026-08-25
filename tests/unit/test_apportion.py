"""Apportionment must be exact, deterministic, and refuse what it cannot do (FR-030–FR-032)."""

from pathlib import Path

import pytest

from ticket_dataset_generator.config.models import Composition, GenerationConfig
from ticket_dataset_generator.errors import UnsatisfiableCompositionError
from ticket_dataset_generator.planning.apportion import (
    achievability_problems,
    apportion,
    apportion_dimension,
    minimum_records_for_tolerance,
)
from ticket_dataset_generator.schema.enums import COMPOSITION_DIMENSIONS


def _config(**overrides) -> GenerationConfig:
    base = {"record_count": 500, "output_path": Path("data/release/x.jsonl")}
    return GenerationConfig(**{**base, **overrides})


@pytest.mark.parametrize("n", [50, 97, 500, 1000, 99_999])
def test_counts_sum_exactly_to_the_corpus_size(n: int) -> None:
    counts = apportion(_config(record_count=n))
    for dimension in COMPOSITION_DIMENSIONS:
        assert sum(counts[dimension].values()) == n, dimension


@pytest.mark.parametrize("n", [50, 97, 500, 1000])
def test_per_member_error_stays_below_one_record(n: int) -> None:
    # This bound is the arithmetic behind FR-031b's refusal, so it is worth pinning.
    config = _config(record_count=n)
    counts = apportion(config)
    composition = config.effective_composition.as_dict()
    for dimension, distribution in composition.items():
        for member, requested in distribution.items():
            achieved = counts[dimension][member] / n
            assert abs(achieved - requested) < 1 / n, f"{dimension}.{member}"


def test_apportionment_does_not_depend_on_member_order() -> None:
    forwards = apportion_dimension({"a": 0.5, "b": 0.3, "c": 0.2}, 7)
    backwards = apportion_dimension({"c": 0.2, "b": 0.3, "a": 0.5}, 7)
    assert forwards == backwards


def test_remainders_go_to_the_largest_fractions() -> None:
    # 0.34/0.33/0.33 of 10 = 3.4/3.3/3.3 -> floors 3,3,3 with one record left over.
    counts = apportion_dimension({"a": 0.34, "b": 0.33, "c": 0.33}, 10)
    assert counts == {"a": 4, "b": 3, "c": 3}


# --- refusals (FR-032) ---------------------------------------------------------------------


def test_proportions_that_do_not_sum_are_refused() -> None:
    composition = Composition(
        category={"billing": 0.7, "technical": 0.7},
        priority={"normal": 1.0},
        channel={"email": 1.0},
        resolution_status={"resolved": 1.0},
    )
    with pytest.raises(UnsatisfiableCompositionError, match="sum to 1.4"):
        apportion(_config(composition=composition))


def test_an_unknown_member_is_refused() -> None:
    composition = Composition(
        category={"billing": 0.5, "telepathy": 0.5},
        priority={"normal": 1.0},
        channel={"email": 1.0},
        resolution_status={"resolved": 1.0},
    )
    with pytest.raises(UnsatisfiableCompositionError, match="is not a member"):
        apportion(_config(composition=composition))


def test_a_share_too_small_to_round_is_refused() -> None:
    composition = Composition(
        category={"billing": 0.999, "other": 0.001},
        priority={"normal": 1.0},
        channel={"email": 1.0},
        resolution_status={"resolved": 1.0},
    )
    with pytest.raises(UnsatisfiableCompositionError, match="rounds to zero"):
        apportion(_config(record_count=100, composition=composition))


def test_a_tolerance_the_corpus_cannot_achieve_is_refused_up_front() -> None:
    # 2pp needs at least 50 records; refusing before generating is the point (FR-031b).
    with pytest.raises(UnsatisfiableCompositionError, match="unachievable at 20 records"):
        apportion(_config(record_count=20, composition_tolerance_pp=2.0))


def test_the_refusal_names_both_remedies() -> None:
    problems = achievability_problems(_config(record_count=20, composition_tolerance_pp=2.0))
    assert any("at least 50 records" in p and "at least 5.00pp" in p for p in problems)


def test_a_widened_tolerance_makes_a_small_corpus_satisfiable() -> None:
    # What configs/samples/smoke.toml does: 20 records at 10pp rather than the 2pp default.
    assert achievability_problems(_config(record_count=20, composition_tolerance_pp=10.0)) == []


@pytest.mark.parametrize(("tolerance", "expected"), [(2.0, 50), (5.0, 20), (10.0, 10), (0.5, 200)])
def test_minimum_corpus_size_for_a_tolerance(tolerance: float, expected: int) -> None:
    assert minimum_records_for_tolerance(tolerance) == expected


def test_every_problem_is_reported_not_just_the_first() -> None:
    composition = Composition(
        category={"billing": 0.7, "nope": 0.7},
        priority={"normal": 1.0},
        channel={"email": 1.0},
        resolution_status={"resolved": 1.0},
    )
    with pytest.raises(UnsatisfiableCompositionError) as caught:
        apportion(_config(record_count=20, composition_tolerance_pp=2.0, composition=composition))
    assert len(caught.value.problems) >= 3
