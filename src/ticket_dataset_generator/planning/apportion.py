"""Composition apportionment by the largest-remainder method (FR-030–FR-032, research R3).

Composition is made correct by construction rather than by measurement and correction: the
requested distribution is turned into whole-record counts before any model call, and the model
is told what metadata to write a conversation *for*. The only thing that can then perturb the
achieved composition is discards.

Largest-remainder bounds per-member error below one record — below ``1 / record_count`` in
proportion terms — which is also the arithmetic behind FR-031b's up-front refusal when a corpus
is too small for the tolerance it asks for.
"""

import math

from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.errors import UnsatisfiableCompositionError
from ticket_dataset_generator.schema.enums import COMPOSITION_DIMENSIONS


def apportion_dimension(distribution: dict[str, float], record_count: int) -> dict[str, int]:
    """Whole-record counts summing exactly to ``record_count``.

    Each member receives ``floor(p * n)``, then the remaining records go to the members with
    the largest fractional remainders. Ties break on member name so the result does not depend
    on dictionary order.
    """
    exact = {member: p * record_count for member, p in distribution.items()}
    counts = {member: int(value) for member, value in exact.items()}
    shortfall = record_count - sum(counts.values())
    if shortfall:
        by_remainder = sorted(
            exact,
            key=lambda member: (-(exact[member] - counts[member]), member),
        )
        for member in by_remainder[:shortfall]:
            counts[member] += 1
    return counts


def minimum_records_for_tolerance(tolerance_pp: float) -> int:
    """The smallest corpus in which ``tolerance_pp`` is achievable at all (FR-031b)."""
    return max(1, math.ceil(100.0 / tolerance_pp))


def achievability_problems(config: GenerationConfig) -> list[str]:
    """Reasons this corpus size and tolerance cannot work together (FR-031b, FR-032).

    Assigning whole records bounds per-member error at ``1 / record_count`` before any discard,
    so a tolerance below that is unsatisfiable by arithmetic alone. This is a *necessary*
    condition, not a sufficient one: meeting it does not guarantee the tolerance survives
    discards.
    """
    problems: list[str] = []
    n = config.record_count
    floor_pp = 100.0 / n
    if config.composition_tolerance_pp < floor_pp:
        needed = minimum_records_for_tolerance(config.composition_tolerance_pp)
        problems.append(
            f"composition_tolerance_pp {config.composition_tolerance_pp:g}pp is unachievable at "
            f"{n} records: assigning whole records bounds per-member error at {floor_pp:.2f}pp "
            f"before any discard. Use at least {needed} records, or a tolerance of at least "
            f"{floor_pp:.2f}pp."
        )

    composition = config.effective_composition
    for dimension in COMPOSITION_DIMENSIONS:
        distribution: dict[str, float] = getattr(composition, dimension)
        for member, proportion in distribution.items():
            if proportion > 0 and proportion * n < 1:
                problems.append(
                    f"composition.{dimension}.{member}: {proportion:g} of {n} records rounds to "
                    f"zero; the smallest representable share is {1 / n:g}"
                )
    return problems


def apportion(config: GenerationConfig) -> dict[str, dict[str, int]]:
    """Whole-record counts per dimension, or a refusal naming what cannot be satisfied."""
    composition = config.effective_composition
    problems = composition.problems() + achievability_problems(config)
    if problems:
        raise UnsatisfiableCompositionError(problems)
    return {
        dimension: apportion_dimension(getattr(composition, dimension), config.record_count)
        for dimension in COMPOSITION_DIMENSIONS
    }
