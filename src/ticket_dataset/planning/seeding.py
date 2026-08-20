"""Counter-based derivation of a slot's seeded choices (FR-012b, research R2).

Every seeded choice for a record is a pure function of ``(seed, position, attempt)``. Nothing
is drawn from a shared sequential stream, because under bounded concurrency the draw order is
the completion order, which is not reproducible. This is what SC-013 measures: two runs at
different concurrency assign the same choices to the same positions.
"""

import random
from hashlib import blake2b


def slot_key(seed: int, position: int, attempt: int) -> int:
    """The 64-bit key seeding one slot's generator."""
    digest = blake2b(f"{seed}/{position}/{attempt}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def slot_random(seed: int, position: int, attempt: int = 0) -> random.Random:
    """An independent generator for one slot attempt.

    ``attempt`` is part of the key so a retried slot re-rolls its non-metadata choices rather
    than repeating a draw that already failed (FR-009c). The metadata assignment is not drawn
    here — it is apportioned, and stays fixed across attempts, so a discard costs calls but not
    corpus shape (research R3).
    """
    return random.Random(slot_key(seed, position, attempt))
