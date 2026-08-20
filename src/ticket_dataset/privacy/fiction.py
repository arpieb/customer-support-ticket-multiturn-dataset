"""Ranges that published standards reserve for fiction (FR-021c).

A value from one of these ranges cannot identify a real person, because no real person can hold
one. Recognising them is not a weakening of the gate — it is the difference between a gate that
protects a corpus and a gate that fails every run on a corpus that mentions an email address.

This is a **pattern tier above** the per-value approvals in
:mod:`ticket_dataset.privacy.exceptions_store`. The per-value mechanism is right for a judgement
call about one value; it does not scale to the thousands of distinct fabricated addresses a
synthetic corpus legitimately contains.

Findings matched here are still reported, marked exempt by range, so the scan never looks
cleaner than it was.
"""

import re

from ticket_dataset.run.enums import PIICategory

#: RFC 2606 §2 and §3 reserve these for documentation and testing. No one is issued a mailbox
#: at any of them.
RESERVED_DOMAINS = ("example.com", "example.org", "example.net")
RESERVED_TLDS = (".test", ".example", ".invalid", ".localhost")

#: NANP fictional range: any area code, exchange 555, line 0100–0199 (ATIS-0300115).
_FICTIONAL_PHONE = re.compile(r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?555[\s.\-]?01\d{2}\b")

#: Test card numbers published by the card networks for exactly this purpose.
TEST_CARD_NUMBERS = frozenset(
    {
        "4111111111111111",
        "4012888888881881",
        "4222222222222",
        "5555555555554444",
        "5105105105105100",
        "378282246310005",
        "371449635398431",
        "6011111111111117",
        "3530111333300000",
    }
)


def _digits(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def is_reserved_for_fiction(category: PIICategory, value: str) -> bool:
    """Whether ``value`` comes from a range a standard reserves for fiction."""
    candidate = value.strip().lower()

    if category is PIICategory.EMAIL:
        _, _, domain = candidate.rpartition("@")
        if domain.endswith(RESERVED_TLDS):
            return True
        # The whole zone is reserved, not only the apex: nobody is issued a mailbox at
        # sub.example.com either. Matched as a suffix on a dot so notexample.com does not slip
        # through on a bare endswith.
        return any(
            domain == reserved or domain.endswith(f".{reserved}") for reserved in RESERVED_DOMAINS
        )

    if category is PIICategory.PHONE:
        return bool(_FICTIONAL_PHONE.fullmatch(candidate.strip()))

    if category is PIICategory.CREDIT_CARD:
        return _digits(candidate) in TEST_CARD_NUMBERS

    # There is no reserved-for-fiction range for a Social Security number. The SSA publishes
    # never-issued groups, but treating them as exempt would be this project inventing a policy
    # rather than applying a standard, so an SSN-shaped value always blocks.
    return False


def describe_ranges() -> dict[str, list[str]]:
    """What the report states about the exemption, so it is visible rather than silent."""
    return {
        "EMAIL": [*RESERVED_DOMAINS, *(f"*{tld}" for tld in RESERVED_TLDS)],
        "PHONE": ["NANP 555-0100 through 555-0199"],
        "CREDIT_CARD": ["published network test card numbers"],
    }
