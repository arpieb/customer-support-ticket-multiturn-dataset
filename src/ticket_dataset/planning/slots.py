"""Slot planning — every seeded choice a record needs, computed before dispatch.

A run is N ordered slots. Each slot's choices are a pure function of ``(seed, position)``:
composition assignment, turn count, subdomain, and ticket timestamps (FR-012b, FR-006a). That
is what makes the corpus reproducible in structure regardless of concurrency (SC-013), and what
lets a discarded slot be retried in place without perturbing the corpus shape (research R3).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.planning.apportion import apportion
from ticket_dataset.planning.seeding import slot_random
from ticket_dataset.schema.enums import COMPOSITION_DIMENSIONS, ResolutionStatus


@dataclass(frozen=True, slots=True)
class Slot:
    """One unit of work. ``position`` becomes the record's ``record_index``."""

    position: int
    category: str
    priority: str
    channel: str
    resolution_status: str
    turn_count: int
    subdomain: str
    created_at: datetime
    resolved_at: datetime | None

    def metadata(self) -> dict[str, object]:
        """The assignment, shaped for :class:`~ticket_dataset.schema.record.TicketMetadata`."""
        return {
            "category": self.category,
            "priority": self.priority,
            "channel": self.channel,
            "resolution_status": self.resolution_status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


def _assignment_pools(config: GenerationConfig, seed: int) -> dict[str, list[str]]:
    """Apportioned members, shuffled by a seed-derived generator, one list per dimension.

    Shuffling matters: without it every billing ticket would occupy the first block of
    positions, and any consumer taking a prefix of the corpus would get a skewed sample.
    """
    counts = apportion(config)
    pools: dict[str, list[str]] = {}
    for dimension in COMPOSITION_DIMENSIONS:
        pool: list[str] = []
        for member, count in sorted(counts[dimension].items()):
            pool.extend([member] * count)
        # A dimension-specific derivation so the four are shuffled independently.
        slot_random(seed, -1, abs(hash(dimension)) % 1_000).shuffle(pool)
        pools[dimension] = pool
    return pools


def plan_slots(config: GenerationConfig, seed: int) -> list[Slot]:
    """Every slot for the run, in position order."""
    pools = _assignment_pools(config, seed)
    window_start = datetime.combine(config.time_window.start, datetime.min.time(), tzinfo=UTC)
    window_end = datetime.combine(config.time_window.end, datetime.min.time(), tzinfo=UTC)
    window_seconds = max(int((window_end - window_start).total_seconds()), 1)
    resolution_min = int(config.resolution_duration.min.total_seconds())
    resolution_max = int(config.resolution_duration.max.total_seconds())

    slots: list[Slot] = []
    for position in range(config.record_count):
        rng = slot_random(seed, position)
        resolution_status = pools["resolution_status"][position]
        created_at = window_start + timedelta(seconds=rng.randrange(window_seconds))
        # Present when and only when the ticket was resolved (FR-006b).
        resolved_at = (
            created_at + timedelta(seconds=rng.randint(resolution_min, resolution_max))
            if resolution_status == ResolutionStatus.RESOLVED
            else None
        )
        slots.append(
            Slot(
                position=position,
                category=pools["category"][position],
                priority=pools["priority"][position],
                channel=pools["channel"][position],
                resolution_status=resolution_status,
                # Uniform over the range: naming the distribution is what stops two conforming
                # implementations producing materially different corpora (FR-009d).
                turn_count=rng.randint(config.turns.min, config.turns.max),
                subdomain="",  # assigned below, once the document's list is known
                created_at=created_at,
                resolved_at=resolved_at,
            )
        )
    return slots


def assign_subdomains(slots: Sequence[Slot], subdomains: Sequence[str], seed: int) -> list[Slot]:
    """Draw each slot's subdomain from the prompt document's declared list (FR-008d).

    Separate from :func:`plan_slots` because the list comes from a committed document that the
    planner should not have to read. The draw uses the same position-derived generator, so the
    subdomain is as reproducible as everything else.
    """
    if not subdomains:
        raise ValueError("no subdomains declared; the prompt document must list them (FR-008d)")
    ordered = sorted(subdomains)
    return [
        replace(
            slot,
            subdomain=ordered[slot_random(seed, slot.position, 0).randrange(len(ordered))],
        )
        for slot in slots
    ]
