"""Exact-duplicate reporting (FR-034, FR-039, research R13).

Duplicates are **reported, never discarded**. FR-034 asks for duplicate visibility as a
diversity signal, and discarding them would suppress the very signal the requirement exists to
surface — while inflating the discard tallies FR-009k uses to detect a defective generator.

The fingerprint covers the turn sequence only. Assigned metadata varies by construction, so
including it would mean two identical conversations almost never fingerprint identically, which
is the opposite of useful.
"""

import unicodedata
from dataclasses import dataclass, field
from hashlib import sha256


def fingerprint(turns: list[dict[str, str]]) -> str:
    """A digest of the conversation itself: each turn's role and content, in order.

    Content is NFC-normalized first, so two visually identical strings that differ only in
    Unicode composition are recognized as the same conversation rather than as two.
    """
    parts = []
    for turn in turns:
        content = unicodedata.normalize("NFC", turn["content"]).strip()
        parts.append(f"{turn['role']}\x1f{content}")
    return sha256("\x1e".join(parts).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class DuplicateCounter:
    """Counts repeats within one run (FR-039).

    Within a single run only: comparing against previously generated corpora would need a
    persistent cross-run registry the pipeline does not otherwise require.

    Memory is a digest per accepted record — about 3 MB at 100,000 records — which is bounded
    and independent of conversation length.
    """

    _seen: set[str] = field(default_factory=set)
    duplicates: int = 0

    def observe(self, turns: list[dict[str, str]]) -> bool:
        """Record a conversation; return True when it repeats one already seen."""
        digest = fingerprint(turns)
        if digest in self._seen:
            self.duplicates += 1
            return True
        self._seen.add(digest)
        return False

    @property
    def unique(self) -> int:
        return len(self._seen)
