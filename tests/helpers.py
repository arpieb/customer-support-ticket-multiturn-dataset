"""Shared test fixtures. Nothing here touches a network."""

from datetime import UTC, datetime, timedelta

from ticket_dataset_generator.planning.slots import Slot

CREATED = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def make_slot(
    *,
    position: int = 0,
    turn_count: int = 4,
    resolution_status: str = "resolved",
    **overrides,
) -> Slot:
    """A slot with plausible defaults, for tests that do not care about planning."""
    fields = {
        "position": position,
        "category": "billing",
        "priority": "normal",
        "channel": "email",
        "resolution_status": resolution_status,
        "turn_count": turn_count,
        "subdomain": "billing-duplicate-charge",
        "created_at": CREATED,
        "resolved_at": CREATED + timedelta(hours=4) if resolution_status == "resolved" else None,
    }
    fields.update(overrides)
    return Slot(**fields)
