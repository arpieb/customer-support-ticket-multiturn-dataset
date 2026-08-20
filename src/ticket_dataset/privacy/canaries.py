"""Committed probe values proving each floor type is actually detected (FR-018a).

Coverage is a demonstration, not a declaration. A detector whose pattern silently stopped
matching still declares its category, passes a declaration check, and reports clean — which is
precisely the failure the floor exists to prevent.

Every value here is drawn from a range reserved for fiction, so committing them creates no
identifier-shaped content in the repository worth worrying about. They are chosen to match what
the detectors actually recognise: a seven-digit `555-0142` is *not* detected, so the phone canary
carries a full ten-digit number.
"""

from ticket_dataset.run.enums import PIICategory

#: One probe per blocking-floor type (FR-018, FR-018a).
FLOOR_CANARIES: dict[PIICategory, str] = {
    PIICategory.EMAIL: "canary.probe@example.com",
    PIICategory.PHONE: "212-555-0142",
    PIICategory.CREDIT_CARD: "4111111111111111",
    # No published range reserves SSNs for fiction, so this is a shape probe only. It is the one
    # canary that would itself block if it appeared in a record, which is correct: an
    # SSN-shaped value always blocks (FR-021c).
    PIICategory.US_SSN: "123-45-6789",
}

#: Values that must *not* be reported, so a probe cannot pass by matching everything.
NEGATIVE_CANARIES: tuple[str, ...] = (
    "order ORD-4417 shipped on Tuesday",
    "the agent said it would take 3-5 business days",
)
