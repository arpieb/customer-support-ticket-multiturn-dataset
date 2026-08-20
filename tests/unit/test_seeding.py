"""Seeded choices must not depend on the order they are drawn in (FR-012b, SC-013)."""

import random

from ticket_dataset.planning.seeding import slot_random


def _draws(rng: random.Random) -> list[float]:
    return [rng.random() for _ in range(5)]


def test_the_same_slot_yields_the_same_draws() -> None:
    assert _draws(slot_random(42, 7)) == _draws(slot_random(42, 7))


def test_draw_order_across_slots_does_not_matter() -> None:
    # The property that makes concurrency safe: constructing slot 9's generator before slot 3's
    # changes nothing about either.
    forwards = {p: _draws(slot_random(42, p)) for p in range(10)}
    backwards = {p: _draws(slot_random(42, p)) for p in reversed(range(10))}
    assert forwards == backwards


def test_different_positions_differ() -> None:
    assert _draws(slot_random(42, 0)) != _draws(slot_random(42, 1))


def test_different_seeds_differ() -> None:
    assert _draws(slot_random(42, 0)) != _draws(slot_random(43, 0))


def test_a_retry_re_rolls() -> None:
    # Repeating a draw that already produced a rejected record would waste the attempt.
    assert _draws(slot_random(42, 5, attempt=0)) != _draws(slot_random(42, 5, attempt=1))


def test_concurrency_cannot_perturb_a_slot() -> None:
    # Interleaving draws from several slots leaves each slot's sequence intact, which a shared
    # sequential stream would not.
    interleaved: dict[int, list[float]] = {p: [] for p in range(4)}
    generators = {p: slot_random(42, p) for p in range(4)}
    for _ in range(5):
        for p in (2, 0, 3, 1):
            interleaved[p].append(generators[p].random())
    for p in range(4):
        assert interleaved[p] == _draws(slot_random(42, p))
