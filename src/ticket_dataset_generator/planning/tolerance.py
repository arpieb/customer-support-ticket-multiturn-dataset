"""Per-member composition tolerance (FR-031, FR-031a).

The tolerance is evaluated **per member of each dimension**, not in aggregate. A dimension passes
only when its worst member passes, and a failure names the member and its drift.

Aggregate measures were rejected in the requirement itself, and the reason is worth restating:
someone slicing the corpus by one category cares about *that* category's drift, and an average
would let a badly-served member hide behind well-served ones. A total-variation or mean-absolute
measure over six categories can sit comfortably inside 2pp while `shipping` is 5pp light.
"""

from dataclasses import dataclass

from ticket_dataset_generator.schema.enums import COMPOSITION_DIMENSIONS


@dataclass(frozen=True, slots=True)
class Breach:
    """One member outside the tolerance."""

    dimension: str
    member: str
    requested: float
    achieved: float

    @property
    def drift_pp(self) -> float:
        return abs(self.achieved - self.requested) * 100

    def describe(self) -> str:
        return (
            f"composition.{self.dimension}.{self.member}: requested {self.requested:.1%}, "
            f"achieved {self.achieved:.1%} — {self.drift_pp:.2f}pp drift"
        )


def check(
    requested: dict[str, dict[str, float]],
    achieved: dict[str, dict[str, float]],
    tolerance_pp: float,
) -> list[Breach]:
    """Every member outside the tolerance. An empty list is the pass condition (FR-031)."""
    limit = tolerance_pp / 100
    breaches: list[Breach] = []
    for dimension in COMPOSITION_DIMENSIONS:
        wanted = requested.get(dimension, {})
        got = achieved.get(dimension, {})
        for member in sorted(set(wanted) | set(got)):
            want = wanted.get(member, 0.0)
            have = got.get(member, 0.0)
            if abs(have - want) > limit:
                breaches.append(
                    Breach(dimension=dimension, member=member, requested=want, achieved=have)
                )
    return breaches


def attribute(
    requested: dict[str, dict[str, float]],
    assigned: dict[str, dict[str, float]],
    achieved: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Split each member's drift into apportionment error and discard-induced drift (FR-031a).

    Requested → assigned is what apportionment could not represent; assigned → achieved is what
    discards took away. Without the middle term a tolerance failure has no attributable cause, and
    the two call for entirely different responses: one is a corpus-size problem, the other a
    generator problem.
    """
    attribution: dict[str, dict[str, float]] = {}
    for dimension in COMPOSITION_DIMENSIONS:
        wanted = requested.get(dimension, {})
        planned = assigned.get(dimension, {})
        got = achieved.get(dimension, {})
        members = set(wanted) | set(planned) | set(got)
        attribution[dimension] = {
            member: round((planned.get(member, 0.0) - wanted.get(member, 0.0)) * 100, 4)
            for member in sorted(members)
        }
    return attribution
