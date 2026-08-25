"""Masked renderings of matched values (FR-020a).

A finding must give a reviewer enough to recognise a deliberately synthetic value without
reproducing the value itself. Without a mask, FR-022's approval has no input: the record is
discarded and FR-020 withholds the value, leaving a reviewer asked to judge something no artifact
contains.

Masking is deterministic — the same value always renders the same way, so two runs' reports
compare — and irreversible: what survives is the non-identifying remainder, never enough to
reconstruct the original.
"""

from ticket_dataset_generator.run.enums import PIICategory

REDACTED = "•"


def _shape(value: str) -> str:
    """Length and character classes, with no content."""
    kinds = {"digit": 0, "alpha": 0, "other": 0}
    for char in value:
        if char.isdigit():
            kinds["digit"] += 1
        elif char.isalpha():
            kinds["alpha"] += 1
        else:
            kinds["other"] += 1
    parts = [f"{count}{name[0]}" for name, count in kinds.items() if count]
    return f"<{len(value)} chars: {' '.join(parts)}>"


def mask(category: PIICategory, value: str) -> str:
    """Render ``value`` so a reviewer can adjudicate it without seeing it."""
    value = value.strip()
    if not value:
        return ""

    if category is PIICategory.EMAIL:
        # The domain is what settles the common case — a reviewer seeing @example.com knows the
        # value is fabricated. The local part is the identifying half, so none of it survives.
        local, _, domain = value.rpartition("@")
        return f"{REDACTED * min(len(local), 6)}@{domain}" if domain else _shape(value)

    if category is PIICategory.CREDIT_CARD:
        # The issuer range is public and identifies no one; the account number is the rest.
        digits = "".join(char for char in value if char.isdigit())
        return (
            f"{digits[:6]}{REDACTED * max(len(digits) - 6, 0)}"
            if len(digits) >= 6
            else _shape(value)
        )

    if category is PIICategory.PHONE:
        # Enough to recognise a 555 fictional number without the subscriber line.
        digits = "".join(char for char in value if char.isdigit())
        return f"{digits[:-4]}{REDACTED * 4}" if len(digits) > 4 else _shape(value)

    # For anything else — a government identifier above all — nothing but shape survives. There
    # is no non-identifying remainder of an SSN worth showing.
    return _shape(value)
