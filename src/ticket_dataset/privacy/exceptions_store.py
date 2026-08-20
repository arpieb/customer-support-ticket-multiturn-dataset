"""Per-value approvals, stored as fingerprints (FR-022, FR-022a, FR-022b, research R9).

A file listing the literal strings that tripped the scanner would itself be a file of
identifier-shaped values in the repository — precisely what the gate exists to keep out. So an
approval records a fingerprint, never the value.

Suppression is applied in the registry rather than through a detector's own allowlist, so a value
approved once stays approved after a detector swap. That is the whole point of the replaceable
detector design.

This is the *per-value* tier. Values from ranges a standard reserves for fiction never reach it —
they are handled by :mod:`ticket_dataset.privacy.fiction`, because approving thousands of
distinct fabricated addresses one at a time is not a workflow.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from ticket_dataset.errors import ReasonContainsIdentifierError
from ticket_dataset.run.enums import PIICategory


def fingerprint(category: PIICategory, value: str) -> str:
    """A stable, non-reversible identity for one approved value."""
    normalized = value.strip().lower()
    return sha256(f"{category.value}:{normalized}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovedException:
    fingerprint: str
    category: str
    reason: str
    approved_by: str
    approved_on: str


@dataclass(slots=True)
class ExceptionStore:
    """The committed approvals file."""

    path: Path
    entries: list[ApprovedException] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> ExceptionStore:
        path = Path(path)
        if not path.exists():
            return cls(path=path)
        payload = json.loads(path.read_text() or "[]")
        return cls(
            path=path,
            entries=[ApprovedException(**entry) for entry in payload],
        )

    @property
    def fingerprints(self) -> set[str]:
        return {entry.fingerprint for entry in self.entries}

    def approve(
        self,
        *,
        category: PIICategory,
        value: str,
        reason: str,
        approved_by: str,
        scan_reason: callable | None = None,
        now: datetime | None = None,
    ) -> ApprovedException:
        """Record an approval. The value is fingerprinted here and never written.

        ``scan_reason`` runs the detectors over the stated reason and returns any matches. A
        free-text field that may hold a value would otherwise defeat the fingerprinting it sits
        beside (FR-022b).
        """
        if not reason.strip():
            raise ValueError("an approval must carry a stated reason (FR-022)")
        if not approved_by.strip():
            raise ValueError("an approval must record who made it (FR-022a)")

        if scan_reason is not None and scan_reason(reason):
            # The offending value is deliberately not echoed here.
            raise ReasonContainsIdentifierError(
                "the stated reason contains an identifier-shaped value. Describe why the value "
                "is synthetic without reproducing it (FR-022b)."
            )

        entry = ApprovedException(
            fingerprint=fingerprint(category, value),
            category=category.value,
            reason=reason.strip(),
            approved_by=approved_by.strip(),
            approved_on=(now or datetime.now(UTC)).date().isoformat(),
        )
        self.entries.append(entry)
        return entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "fingerprint": entry.fingerprint,
                "category": entry.category,
                "reason": entry.reason,
                "approved_by": entry.approved_by,
                "approved_on": entry.approved_on,
            }
            for entry in self.entries
        ]
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
