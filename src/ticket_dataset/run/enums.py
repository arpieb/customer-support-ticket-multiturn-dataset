"""Enumerations describing how a run went (FR-018, FR-018b, FR-026b, FR-036b)."""

from enum import StrEnum


class PIICategory(StrEnum):
    """Identifier types the scan can report.

    The blocking floor is stated at the level of the identifier type actually detected rather
    than as a broad category: naming "government identifiers" would promise coverage of non-US
    identifiers that no offline detector delivers (FR-018, research R8).
    """

    EMAIL = "EMAIL"
    PHONE = "PHONE"
    CREDIT_CARD = "CREDIT_CARD"
    US_SSN = "US_SSN"
    IP_ADDRESS = "IP_ADDRESS"


#: Types that block a record from the corpus. A detector set that cannot demonstrate all four
#: fails the run before generation (FR-018, FR-018a).
BLOCKING_FLOOR: frozenset[PIICategory] = frozenset(
    {
        PIICategory.EMAIL,
        PIICategory.PHONE,
        PIICategory.CREDIT_CARD,
        PIICategory.US_SSN,
    }
)

#: Reported for visibility, never blocking (FR-018b).
#:
#: Postal code is registered in neither tier. It matches ordinary order and account numbers —
#: "order #12345" reads as a ZIP to a regex — and a detector that fires on nearly every record
#: trains maintainers to ignore the report, which costs more than the signal is worth. It joins
#: the declared gaps instead, on the same ground DATE was excluded (research R8).
ADVISORY_CATEGORIES: frozenset[PIICategory] = frozenset({PIICategory.IP_ADDRESS})

#: Identifier types nothing here detects. Restated in every report so a clean result is never
#: mistaken for coverage the scan does not provide (FR-019).
DECLARED_GAPS: tuple[str, ...] = (
    "non-US government identifiers",
    "postal code",
    "full postal address",
    "bank account number (IBAN)",
    "person name",
)


class FindingStatus(StrEnum):
    """Whether a finding blocks, and if not, why not."""

    BLOCKING = "blocking"
    #: Drawn from a range a standard reserves for fiction, so it cannot identify anyone
    #: (FR-021c). Still reported, so the scan never looks cleaner than it was.
    EXEMPT_BY_RANGE = "exempt_by_range"
    #: A reviewer judged this specific value legitimately synthetic (FR-022).
    APPROVED = "approved"
    #: Reported for visibility only; never blocks (FR-018b).
    ADVISORY = "advisory"


class DiscardReason(StrEnum):
    """Why a generated response did not become a record (FR-026b).

    Closed on purpose and closed *by requirement*: FR-026 reconciles
    ``records_generated - discards == records_written``, and an open-ended reason string makes
    that a sum over free text.
    """

    STRUCTURAL_INVALID = "structural_invalid"
    TURN_COUNT_OUT_OF_RANGE = "turn_count_out_of_range"
    SCHEMA_INVALID = "schema_invalid"
    COHERENCE_BELOW_THRESHOLD = "coherence_below_threshold"
    UNJUDGEABLE = "unjudgeable"
    PRIVACY_FINDING = "privacy_finding"
    DETECTOR_ERROR = "detector_error"
    MODEL_REFUSAL = "model_refusal"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"


class Verdict(StrEnum):
    """Whether the run's output qualified (FR-036)."""

    PASS = "pass"
    FAIL = "fail"


class RunOutcome(StrEnum):
    """What happened to the run (FR-036b).

    Four states rather than a binary, because they call for different responses: nothing spent,
    output that did not qualify, and work that is preserved and resumable are different facts.
    """

    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED = "failed"
    STOPPED = "stopped"
