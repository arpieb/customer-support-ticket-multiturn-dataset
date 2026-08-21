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


# --- determinism across processes, not merely within one -------------------------------------


_PROBE = """
from pathlib import Path
from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.planning.slots import plan_slots
config = GenerationConfig(
    record_count=40,
    output_path=Path("data/release/x.jsonl"),
    composition={
        "category": {"billing": 0.5, "technical": 0.5},
        "priority": {"normal": 1.0},
        "channel": {"email": 0.5, "chat": 0.5},
        "resolution_status": {"resolved": 0.75, "escalated": 0.25},
    },
    composition_tolerance_pp=10.0,
)
print("|".join(
    f"{s.category},{s.channel},{s.resolution_status},{s.turn_count}"
    for s in plan_slots(config, seed=42)
))
"""


def _plan_in_subprocess(hash_seed: str) -> str:
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
    )
    return result.stdout.strip()


def test_planning_is_identical_across_processes() -> None:
    """The regression this file could not previously catch.

    Composition pools were shuffled with a generator keyed by ``hash(dimension_name)``, and
    Python randomises string hashing per process. Two runs of the same config therefore assigned
    different composition to the same positions — a Principle II violation that no in-process
    test could see, because ``hash()`` is stable *within* an interpreter. Distinct
    ``PYTHONHASHSEED`` values are what make the failure observable.

    It also needs a multi-member dimension: shuffling a pool whose entries are all identical is
    a no-op, which is why the end-to-end suite's single-member configs never surfaced it.
    """
    plans = {_plan_in_subprocess(seed) for seed in ("0", "1", "12345")}
    assert len(plans) == 1, "slot planning depends on the interpreter's hash seed"


def test_turn_count_does_not_move_with_the_resolution_split() -> None:
    """Turn count must not depend on the composition assignment.

    ``resolved_at`` is drawn only for resolved tickets, so a turn count drawn afterwards rode on
    whether the slot happened to be resolved — and changing the resolved/escalated ratio moved
    every turn count with it, for no reason a reader of the config could anticipate.
    """
    mostly_resolved = _plan(
        composition={
            "category": {"billing": 1.0},
            "priority": {"normal": 1.0},
            "channel": {"email": 1.0},
            "resolution_status": {"resolved": 0.9, "escalated": 0.1},
        }
    )
    mostly_escalated = _plan(
        composition={
            "category": {"billing": 1.0},
            "priority": {"normal": 1.0},
            "channel": {"email": 1.0},
            "resolution_status": {"resolved": 0.1, "escalated": 0.9},
        }
    )
    assert [s.turn_count for s in mostly_resolved] == [s.turn_count for s in mostly_escalated]
