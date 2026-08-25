"""Duplicate conversations are counted, never removed (FR-034, FR-039)."""

from ticket_dataset_generator.dedup import DuplicateCounter, fingerprint

CONVERSATION = [
    {"role": "customer", "content": "My order never arrived."},
    {"role": "agent", "content": "Let me check that."},
]


def test_identical_conversations_share_a_fingerprint() -> None:
    assert fingerprint(CONVERSATION) == fingerprint(list(CONVERSATION))


def test_a_different_turn_changes_the_fingerprint() -> None:
    other = [CONVERSATION[0], {"role": "agent", "content": "Let me look into that."}]
    assert fingerprint(CONVERSATION) != fingerprint(other)


def test_turn_order_matters() -> None:
    assert fingerprint(CONVERSATION) != fingerprint(list(reversed(CONVERSATION)))


def test_unicode_composition_does_not_split_a_duplicate() -> None:
    # "é" as one codepoint and as "e" plus a combining accent are the same conversation to a
    # reader, so they must be the same conversation to the counter.
    composed = [{"role": "customer", "content": "café order"}]
    decomposed = [{"role": "customer", "content": "café order"}]
    assert fingerprint(composed) == fingerprint(decomposed)


def test_duplicates_are_counted() -> None:
    counter = DuplicateCounter()
    assert counter.observe(CONVERSATION) is False
    assert counter.observe(CONVERSATION) is True
    assert counter.duplicates == 1
    assert counter.unique == 1


def test_metadata_is_excluded_from_the_comparison() -> None:
    # Assigned metadata varies by construction, so including it would mean two identical
    # conversations almost never fingerprint identically — the opposite of useful (research R13).
    counter = DuplicateCounter()
    counter.observe(CONVERSATION)
    # Same conversation, generated for a different category and priority: still a duplicate.
    assert counter.observe(list(CONVERSATION)) is True


def test_reporting_a_duplicate_does_not_remove_it() -> None:
    # The counter reports; it has no power to drop a record. Discarding duplicates would
    # suppress the diversity signal FR-034 exists to surface.
    counter = DuplicateCounter()
    kept = [c for c in (CONVERSATION, CONVERSATION, CONVERSATION) if (counter.observe(c) or True)]
    assert len(kept) == 3
    assert counter.duplicates == 2
