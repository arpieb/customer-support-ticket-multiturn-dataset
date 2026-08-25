"""Closed enumerations for the record contract (FR-005, FR-006).

Any value outside these sets is a validation failure. Adding a member is an additive MINOR
schema change; removing one, or narrowing a constraint, is breaking and requires a MAJOR bump
(Constitution I).
"""

from enum import StrEnum


class Role(StrEnum):
    """Who is speaking in a turn (FR-005).

    Two-party by default. Additional roles are accommodated by enumerating them here rather
    than by relaxing the alternation rule (spec Assumptions).
    """

    CUSTOMER = "customer"
    AGENT = "agent"


class Category(StrEnum):
    """Topic category of the ticket (FR-006)."""

    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    SHIPPING = "shipping"
    PRODUCT = "product"
    OTHER = "other"


class Priority(StrEnum):
    """Priority assigned to the ticket (FR-006)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Channel(StrEnum):
    """Channel the ticket arrived through (FR-006)."""

    EMAIL = "email"
    CHAT = "chat"
    PHONE = "phone"
    WEB_FORM = "web_form"


class ResolutionStatus(StrEnum):
    """How the ticket ended (FR-006)."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"


#: The four dimensions an operator can control the distribution of (FR-030).
COMPOSITION_DIMENSIONS: dict[str, type[StrEnum]] = {
    "category": Category,
    "priority": Priority,
    "channel": Channel,
    "resolution_status": ResolutionStatus,
}
