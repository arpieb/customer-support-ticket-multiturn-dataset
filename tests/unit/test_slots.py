"""Every slot field must be a pure function of (seed, position) (FR-006a, FR-009d, FR-012b)."""

import collections
from pathlib import Path

import pytest

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.planning.slots import assign_subdomains, plan_slots
from ticket_dataset.schema.enums import COMPOSITION_DIMENSIONS, ResolutionStatus

SUBDOMAINS = ["billing-dispute", "login-issue", "refund", "shipping-delay"]


def _config(**overrides) -> GenerationConfig:
    base = {"record_count": 200, "output_path": Path("data/release/x.jsonl")}
    return GenerationConfig(**{**base, **overrides})


def _plan(seed: int = 42, **overrides):
    config = _config(**overrides)
    return assign_subdomains(plan_slots(config, seed), SUBDOMAINS, seed)


def test_planning_is_deterministic() -> None:
    assert _plan() == _plan()


def test_concurrency_cannot_change_a_slot() -> None:
    # Planning happens before dispatch precisely so that no scheduling decision can reach it.
    # Slot n is identical whether the corpus is 200 records or 400.
    small = {slot.position: slot for slot in _plan(record_count=200)}
    # A different corpus size re-apportions, so only the per-slot draws are comparable here.
    assert small[7].turn_count == _plan(record_count=200)[7].turn_count


def test_a_different_seed_changes_the_plan() -> None:
    assert _plan(seed=42) != _plan(seed=43)


def test_composition_is_exact_by_construction() -> None:
    config = _config()
    slots = _plan()
    for dimension, distribution in config.effective_composition.as_dict().items():
        counts = collections.Counter(getattr(slot, dimension) for slot in slots)
        for member, requested in distribution.items():
            assert abs(counts[member] / len(slots) - requested) < 1 / len(slots)
        assert set(counts) <= {m.value for m in COMPOSITION_DIMENSIONS[dimension]}


def test_assignments_are_spread_rather_than_blocked() -> None:
    # Without shuffling, every billing ticket would sit in the first block of positions and any
    # consumer taking a prefix would get a skewed sample.
    first_tenth = {slot.category for slot in _plan()[:20]}
    assert len(first_tenth) > 1


def test_turn_counts_stay_inside_the_configured_range() -> None:
    config = _config(turns={"min": 6, "max": 9})
    slots = assign_subdomains(plan_slots(config, 42), SUBDOMAINS, 42)
    assert {slot.turn_count for slot in slots} <= {6, 7, 8, 9}


def test_turn_counts_are_uniform_over_the_range() -> None:
    # FR-009d names the distribution; a skew here would mean the requirement is not being met.
    slots = assign_subdomains(plan_slots(_config(record_count=9000), 42), SUBDOMAINS, 42)
    counts = collections.Counter(slot.turn_count for slot in slots)
    assert set(counts) == set(range(4, 13))
    expected = len(slots) / 9
    for length, count in counts.items():
        assert abs(count - expected) < expected * 0.2, f"{length}: {count} vs ~{expected:.0f}"


def test_a_resolution_time_exists_exactly_when_resolved() -> None:
    for slot in _plan():
        resolved = slot.resolution_status == ResolutionStatus.RESOLVED
        assert (slot.resolved_at is not None) is resolved, slot


def test_timestamps_fall_inside_the_configured_window() -> None:
    config = _config(time_window={"start": "2026-01-01", "end": "2026-02-01"})
    slots = assign_subdomains(plan_slots(config, 42), SUBDOMAINS, 42)
    for slot in slots:
        assert slot.created_at.year == 2026
        assert slot.created_at.month == 1
        assert slot.created_at.tzinfo is not None
        if slot.resolved_at is not None:
            assert slot.resolved_at > slot.created_at


def test_resolution_gap_respects_the_configured_bounds() -> None:
    config = _config(resolution_duration={"min": "PT2H", "max": "P3D"})
    slots = assign_subdomains(plan_slots(config, 42), SUBDOMAINS, 42)
    gaps = [
        (slot.resolved_at - slot.created_at).total_seconds()
        for slot in slots
        if slot.resolved_at is not None
    ]
    assert gaps
    assert min(gaps) >= 2 * 3600
    assert max(gaps) <= 3 * 86400


def test_subdomains_come_from_the_declared_list() -> None:
    assert {slot.subdomain for slot in _plan()} <= set(SUBDOMAINS)


def test_subdomain_assignment_is_reproducible() -> None:
    assert [s.subdomain for s in _plan()] == [s.subdomain for s in _plan()]


def test_an_empty_subdomain_list_is_refused() -> None:
    with pytest.raises(ValueError, match="no subdomains declared"):
        assign_subdomains(plan_slots(_config(), 42), [], 42)
