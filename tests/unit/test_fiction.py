"""Ranges standards reserve for fiction (FR-021c).

This is the logic that keeps the gate from failing every realistic run, so its edges matter: too
broad and a real identifier walks through; too narrow and synthetic content blocks.
"""

import pytest

from ticket_dataset_generator.privacy.fiction import describe_ranges, is_reserved_for_fiction
from ticket_dataset_generator.run.enums import PIICategory


@pytest.mark.parametrize(
    "value",
    [
        "j.doe@example.com",
        "Someone@EXAMPLE.ORG",
        "a@example.net",
        "user@anything.test",
        "user@my-app.invalid",
        "user@sub.example.com",
    ],
)
def test_reserved_email_domains_are_exempt(value: str) -> None:
    assert is_reserved_for_fiction(PIICategory.EMAIL, value)


@pytest.mark.parametrize(
    "value",
    [
        "j.doe@gmail.com",
        "jane.roe@acme-corp.co.uk",
        "someone@example.company.com",  # not a reserved domain, merely similar
        "user@notexample.com",
    ],
)
def test_a_real_looking_email_is_not_exempt(value: str) -> None:
    assert not is_reserved_for_fiction(PIICategory.EMAIL, value)


@pytest.mark.parametrize(
    "value",
    ["212-555-0142", "(212) 555-0199", "+1-212-555-0100", "212.555.0155", "2125550142"],
)
def test_nanp_fictional_numbers_are_exempt(value: str) -> None:
    assert is_reserved_for_fiction(PIICategory.PHONE, value)


@pytest.mark.parametrize(
    "value",
    [
        "212-867-5309",  # a real-looking subscriber number
        "212-555-0200",  # exchange 555 but outside the 0100-0199 line range
        "212-556-0142",  # not the 555 exchange
    ],
)
def test_numbers_outside_the_fictional_range_are_not_exempt(value: str) -> None:
    assert not is_reserved_for_fiction(PIICategory.PHONE, value)


@pytest.mark.parametrize(
    "value", ["4111111111111111", "4111 1111 1111 1111", "5555-5555-5555-4444"]
)
def test_published_test_cards_are_exempt(value: str) -> None:
    assert is_reserved_for_fiction(PIICategory.CREDIT_CARD, value)


def test_an_ordinary_card_number_is_not_exempt() -> None:
    assert not is_reserved_for_fiction(PIICategory.CREDIT_CARD, "4929123456789012")


def test_a_government_identifier_is_never_exempt() -> None:
    # No published range reserves SSNs for fiction. Exempting one would be this project inventing
    # policy rather than applying a standard, so an SSN-shaped value always blocks.
    for value in ("123-45-6789", "000-00-0000", "078-05-1120"):
        assert not is_reserved_for_fiction(PIICategory.US_SSN, value)


def test_an_advisory_category_is_not_exempted_here() -> None:
    # Advisory categories never block anyway; the range check has no opinion about them.
    assert not is_reserved_for_fiction(PIICategory.IP_ADDRESS, "10.0.0.7")


def test_the_ranges_are_described_for_the_report() -> None:
    # The exemption must be visible rather than silent (FR-021c).
    described = describe_ranges()
    assert "example.com" in described["EMAIL"]
    assert any("555" in entry for entry in described["PHONE"])
