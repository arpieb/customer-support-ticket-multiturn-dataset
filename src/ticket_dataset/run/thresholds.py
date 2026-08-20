"""Run-level thresholds, evaluated during the run (FR-037, FR-037a).

Evaluating only at completion means a generator emitting identifiers on every record still costs
a full release-scale run before anyone is told. So the discard rates are re-checked as the run
proceeds, and a breach stops it.

The minimum sample is what keeps that from being trigger-happy: early in a run a single discard
is a huge proportion, and failing on it would fail runs that would have been fine. Nothing is
evaluated until enough records exist for a rate to mean something.

The composition tolerance is deliberately *not* here. A partial corpus has no achieved
composition — apportionment is only satisfied once every slot has been attempted — so an early
check would measure incompleteness rather than drift (FR-037a).
"""

from collections.abc import Mapping
from dataclasses import dataclass

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.run.enums import DiscardReason

#: Absolute floor before any rate is judged; below this, one discard swamps the proportion.
MINIMUM_SAMPLE = 1_000

#: Proportion of the requested corpus that must exist before judging, for corpora large enough
#: that the absolute floor would be reached too early to be representative.
SAMPLE_FRACTION = 0.05


def minimum_sample(record_count: int) -> int:
    """How many responses must exist before a rate is judged (FR-037)."""
    return max(MINIMUM_SAMPLE, int(record_count * SAMPLE_FRACTION))


@dataclass(frozen=True, slots=True)
class Breach:
    reason: DiscardReason
    rate: float
    limit: float
    count: int
    generated: int
    requirement: str

    def describe(self) -> str:
        label = "privacy" if self.reason is DiscardReason.PRIVACY_FINDING else "coherence"
        return (
            f"{label} discard rate {self.rate:.2%} exceeds the configured {self.limit:.2%} "
            f"({self.count} of {self.generated} responses, {self.requirement})"
        )


def discard_rate_breaches(
    config: GenerationConfig,
    discards: Mapping[DiscardReason, int],
    generated: int,
) -> list[Breach]:
    """Which discard-rate thresholds are exceeded right now.

    Both rates divide by ``records_generated`` — every response counted once per attempt — which
    is the one denominator every threshold uses, so a threshold cannot be computed two ways
    (FR-026a).
    """
    if generated <= 0:
        return []
    checks = (
        (DiscardReason.PRIVACY_FINDING, config.privacy.max_discard_rate, "FR-021a"),
        (DiscardReason.COHERENCE_BELOW_THRESHOLD, config.coherence.max_discard_rate, "FR-009k"),
    )
    breaches: list[Breach] = []
    for reason, limit, requirement in checks:
        count = discards.get(reason, 0)
        rate = count / generated
        if rate > limit:
            breaches.append(
                Breach(
                    reason=reason,
                    rate=rate,
                    limit=limit,
                    count=count,
                    generated=generated,
                    requirement=requirement,
                )
            )
    return breaches


def should_stop_early(
    config: GenerationConfig,
    discards: Mapping[DiscardReason, int],
    generated: int,
) -> list[Breach]:
    """Breaches that justify stopping mid-run, or an empty list while the sample is too small."""
    if generated < minimum_sample(config.record_count):
        return []
    return discard_rate_breaches(config, discards, generated)
