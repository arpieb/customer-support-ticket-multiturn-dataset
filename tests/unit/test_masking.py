"""Masked renderings must help a reviewer without leaking the value (FR-020, FR-020a)."""

import pytest

from ticket_dataset_generator.privacy.masking import mask
from ticket_dataset_generator.run.enums import PIICategory


@pytest.mark.parametrize(
    ("category", "value"),
    [
        (PIICategory.EMAIL, "j.doe@example.com"),
        (PIICategory.PHONE, "212-555-0142"),
        (PIICategory.CREDIT_CARD, "4111111111111111"),
        (PIICategory.US_SSN, "123-45-6789"),
        (PIICategory.IP_ADDRESS, "10.0.0.7"),
    ],
)
def test_masking_is_deterministic(category: PIICategory, value: str) -> None:
    assert mask(category, value) == mask(category, value)


@pytest.mark.parametrize(
    ("category", "value"),
    [
        (PIICategory.EMAIL, "j.doe@example.com"),
        (PIICategory.PHONE, "212-555-0142"),
        (PIICategory.CREDIT_CARD, "4111111111111111"),
        (PIICategory.US_SSN, "123-45-6789"),
    ],
)
def test_no_mask_contains_the_whole_value(category: PIICategory, value: str) -> None:
    assert value not in mask(category, value)


def test_an_email_keeps_the_domain_and_drops_the_local_part() -> None:
    # The domain settles the common case: a reviewer seeing @example.com knows it is fabricated.
    masked = mask(PIICategory.EMAIL, "j.doe@example.com")
    assert masked.endswith("@example.com")
    assert "j.doe" not in masked


def test_a_card_keeps_only_the_issuer_range() -> None:
    masked = mask(PIICategory.CREDIT_CARD, "4111111111111111")
    assert masked.startswith("411111")
    assert "1111111111" not in masked[6:]


def test_a_phone_number_drops_the_subscriber_line() -> None:
    # Enough to recognise a 555 fictional number; not enough to call anyone.
    masked = mask(PIICategory.PHONE, "212-555-0142")
    assert "0142" not in masked
    assert "212555" in masked


def test_a_government_identifier_leaves_only_shape() -> None:
    # There is no non-identifying remainder of an SSN worth showing.
    masked = mask(PIICategory.US_SSN, "123-45-6789")
    assert "123" not in masked
    assert "6789" not in masked
    assert "chars" in masked


def test_masks_of_different_values_can_differ_without_leaking() -> None:
    first = mask(PIICategory.EMAIL, "alice@example.com")
    second = mask(PIICategory.EMAIL, "bob@other.test")
    assert first != second
    assert "alice" not in first and "bob" not in second


def test_an_empty_value_masks_to_nothing() -> None:
    assert mask(PIICategory.EMAIL, "   ") == ""
