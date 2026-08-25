"""Mid-run threshold evaluation (FR-037, FR-037a)."""

from pathlib import Path

import pytest

from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.run.enums import DiscardReason
from ticket_dataset_generator.run.thresholds import (
    discard_rate_breaches,
    minimum_sample,
    should_stop_early,
)


def _config(**overrides) -> GenerationConfig:
    base = {"record_count": 100_000, "output_path": Path("data/release/x.jsonl")}
    return GenerationConfig(**{**base, **overrides})


@pytest.mark.parametrize(
    ("record_count", "expected"),
    [(20, 1_000), (1_000, 1_000), (20_000, 1_000), (100_000, 5_000), (1_000_000, 50_000)],
)
def test_the_minimum_sample_scales_with_the_corpus(record_count: int, expected: int) -> None:
    assert minimum_sample(record_count) == expected


def test_nothing_is_judged_before_the_minimum_sample() -> None:
    # Early in a run a single discard is a huge proportion; failing on it would fail runs that
    # would have been fine.
    config = _config()
    every_response_discarded = {DiscardReason.PRIVACY_FINDING: 100}
    assert should_stop_early(config, every_response_discarded, generated=100) == []


def test_an_early_cluster_does_not_fail_a_run_that_recovers() -> None:
    config = _config(record_count=100_000)
    # 40 privacy discards in the first 500 responses is 8%, far above the 0.5% limit — but the
    # sample is too small to judge. By 12,000 responses the same 40 discards are 0.33%, under it.
    assert should_stop_early(config, {DiscardReason.PRIVACY_FINDING: 40}, generated=500) == []
    assert should_stop_early(config, {DiscardReason.PRIVACY_FINDING: 40}, generated=12_000) == []


def test_a_sustained_breach_stops_the_run() -> None:
    config = _config(record_count=100_000)
    breaches = should_stop_early(config, {DiscardReason.PRIVACY_FINDING: 200}, generated=6_000)
    assert len(breaches) == 1
    assert breaches[0].reason is DiscardReason.PRIVACY_FINDING
    assert "privacy discard rate" in breaches[0].describe()


def test_the_coherence_rate_is_judged_too() -> None:
    config = _config(record_count=100_000)
    breaches = should_stop_early(
        config, {DiscardReason.COHERENCE_BELOW_THRESHOLD: 1_200}, generated=6_000
    )
    assert breaches and breaches[0].reason is DiscardReason.COHERENCE_BELOW_THRESHOLD


def test_both_rates_divide_by_the_same_denominator() -> None:
    # FR-026a: every response counted once per attempt, so a threshold cannot be computed two
    # ways. With 100 discards in 10,000 responses the rate is 1%, not 1% of records written.
    config = _config()
    breaches = discard_rate_breaches(config, {DiscardReason.PRIVACY_FINDING: 100}, generated=10_000)
    assert breaches[0].rate == pytest.approx(0.01)
    assert breaches[0].generated == 10_000


def test_a_rate_exactly_at_the_limit_does_not_breach() -> None:
    config = _config()
    assert (
        discard_rate_breaches(config, {DiscardReason.PRIVACY_FINDING: 50}, generated=10_000) == []
    )


def test_no_responses_yet_means_no_breach() -> None:
    assert discard_rate_breaches(_config(), {DiscardReason.PRIVACY_FINDING: 0}, generated=0) == []


def test_other_discard_reasons_do_not_trip_the_rate_thresholds() -> None:
    # Only the two rates FR-009k and FR-021a name are thresholds; a structurally invalid response
    # is accounted for but does not fail the run on its own.
    config = _config()
    assert (
        discard_rate_breaches(config, {DiscardReason.STRUCTURAL_INVALID: 9_000}, generated=10_000)
        == []
    )
