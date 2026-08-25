"""Run and record identifiers (FR-003a, FR-003b).

The run identifier is generated fresh per run instance and carried in the checkpoint, so a
*resume* continues under the identifier it started with while a *rerun* — even one with the
same seed and configuration — receives a new one. Deriving it from the inputs would make two
legitimate reruns indistinguishable and give two separate corpora the same record identifiers.

Record identifiers are then derived from ``(run_id, record_index)``, which makes uniqueness
within a run structural rather than checked, and makes FR-015b true by construction: a resumed
run regenerating a position yields the identifier that position always had, so no identifier
can be issued twice.
"""

import uuid

#: Stable namespace for record identifiers. Changing it would reissue every identifier in
#: every corpus ever produced, so it is a constant, not a setting.
RECORD_NAMESPACE = uuid.UUID("6f6cf1ee-6a5f-5f2a-9c1e-7f0f1a2b3c4d")


def new_run_id() -> str:
    """A fresh identifier for one run instance (FR-003a)."""
    return str(uuid.uuid4())


def record_id(run_id: str, record_index: int) -> str:
    """The identifier position ``record_index`` of ``run_id`` always has (FR-003b)."""
    if record_index < 0:
        raise ValueError("record_index must not be negative")
    return str(uuid.uuid5(RECORD_NAMESPACE, f"{run_id}/{record_index}"))
