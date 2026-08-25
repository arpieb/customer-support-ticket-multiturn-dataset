"""Identifier derivation (FR-003a, FR-003b, FR-015b)."""

import pytest

from ticket_dataset_generator.run.ids import new_run_id, record_id


def test_each_run_gets_a_fresh_identifier() -> None:
    # A rerun with identical inputs must be distinguishable from a resume (FR-003a).
    assert new_run_id() != new_run_id()


def test_record_ids_are_stable_for_a_run_and_position() -> None:
    run = new_run_id()
    assert record_id(run, 7) == record_id(run, 7)


def test_record_ids_are_unique_within_a_run() -> None:
    run = new_run_id()
    ids = [record_id(run, position) for position in range(1000)]
    assert len(set(ids)) == len(ids)


def test_two_runs_never_share_a_record_id() -> None:
    # Uniqueness across runs follows from the run identifier being fresh, not from a check.
    first, second = new_run_id(), new_run_id()
    assert {record_id(first, p) for p in range(100)}.isdisjoint(
        record_id(second, p) for p in range(100)
    )


def test_regenerating_a_position_reuses_its_identifier() -> None:
    # This is what makes FR-015b true by construction: a resumed run cannot issue a new
    # identifier for a position, and cannot issue an old one twice, because the identifier is
    # a function of the position rather than of a counter.
    run = new_run_id()
    before = record_id(run, 42)
    assert record_id(run, 42) == before


def test_a_negative_position_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        record_id(new_run_id(), -1)
