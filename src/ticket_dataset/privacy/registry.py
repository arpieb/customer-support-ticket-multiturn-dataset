"""The detector registry and the blocking gate (FR-017–FR-023a).

Three things live here that a direct call to a detection library would not give:

**Replaceability.** A detector is any object satisfying :class:`Detector`. Adding or swapping one
touches neither the record contract nor the pipeline (FR-017).

**Demonstrated coverage.** Floor coverage is established by probing each type with a committed
canary and requiring a hit — not by reading a detector's declared category list. A detector whose
pattern silently stopped matching still declares the category, passes a declaration check, and
reports clean, which is the failure the floor exists to prevent (FR-018a).

**One place where blocking is decided.** Range exemptions and per-value approvals are applied
here rather than inside a detector, so a value exempted once stays exempt after a detector swap.
Suppression changes a finding's *status*, never its presence (FR-021c, FR-022).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from ticket_dataset.errors import FloorNotCoveredError
from ticket_dataset.privacy.fiction import is_reserved_for_fiction
from ticket_dataset.privacy.masking import mask
from ticket_dataset.run.enums import (
    ADVISORY_CATEGORIES,
    BLOCKING_FLOOR,
    DECLARED_GAPS,
    FindingStatus,
    PIICategory,
)

#: The record fields the scan examines: the model-derived text, and nothing else (FR-023a).
#:
#: Pipeline-assigned fields are excluded by requirement rather than by omission. An identifier can
#: only enter the corpus through model output, and scanning UUIDs and hashes would produce
#: findings every run would then have to except. The accepted consequence is that a prompt
#: document carrying a real identifier is caught by review of a committed file, not by this gate.
SCANNED_FIELDS = ("turns[].content", "scenario")


@dataclass(frozen=True, slots=True)
class Match:
    """A raw detection, before the registry decides what it means."""

    category: PIICategory
    value: str
    detector: str


@dataclass(frozen=True, slots=True)
class Finding:
    """A reported detection. Never carries the matched value (FR-020)."""

    record_id: str
    field: str
    category: PIICategory
    detector: str
    status: FindingStatus
    masked: str

    @property
    def blocks(self) -> bool:
        return self.status is FindingStatus.BLOCKING


@dataclass(frozen=True, slots=True)
class ScanReport:
    """What one scan examined and found (FR-019, FR-023, FR-023a)."""

    findings: list[Finding]
    records_examined: int
    fields_examined: int
    detectors_run: tuple[str, ...]
    covered_types: tuple[str, ...]
    declared_gaps: tuple[str, ...] = DECLARED_GAPS
    scanned_fields: tuple[str, ...] = SCANNED_FIELDS

    @property
    def blocking(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.blocks]


class Detector(Protocol):
    """What the registry needs from a detector."""

    name: str

    @property
    def categories(self) -> frozenset[PIICategory]: ...

    def scan(self, text: str) -> list[Match]: ...


class DetectorError(Exception):
    """A detector failed while examining a record (FR-017a)."""


@dataclass(slots=True)
class DetectorRegistry:
    """Runs the registered detectors and decides what blocks."""

    detectors: list[Detector] = field(default_factory=list)
    #: ``fingerprint -> reason``; a reviewer's per-value approvals (FR-022).
    approvals: set[str] = field(default_factory=set)
    fingerprinter: Callable[[PIICategory, str], str] | None = None

    def register(self, detector: Detector) -> None:
        self.detectors.append(detector)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(detector.name for detector in self.detectors)

    def assert_floor_covered(self, canaries: dict[PIICategory, str]) -> None:
        """Prove each floor type is actually detected, before generating (FR-018, FR-018a)."""
        if not self.detectors:
            raise FloorNotCoveredError("no detectors are registered; the floor cannot be covered")

        undetected: list[str] = []
        for category in sorted(BLOCKING_FLOOR, key=lambda c: c.value):
            probe = canaries.get(category)
            if probe is None:
                undetected.append(f"{category.value}: no canary value is committed for it")
                continue
            found = {
                match.category for detector in self.detectors for match in detector.scan(probe)
            }
            if category not in found:
                undetected.append(
                    f"{category.value}: probed with a committed canary and not detected"
                )
        if undetected:
            raise FloorNotCoveredError(
                "the blocking floor is not demonstrably covered:\n  - "
                + "\n  - ".join(undetected)
                + "\nCoverage is established by probe rather than by a detector's declared "
                "category list, because a detector whose pattern stopped matching still declares "
                "the category (FR-018a)."
            )

    def _status(self, match: Match) -> FindingStatus:
        if match.category in ADVISORY_CATEGORIES:
            return FindingStatus.ADVISORY
        # Range before value: a fabricated-by-construction value never needed a reviewer.
        if is_reserved_for_fiction(match.category, match.value):
            return FindingStatus.EXEMPT_BY_RANGE
        if (
            self.fingerprinter is not None
            and self.fingerprinter(match.category, match.value) in self.approvals
        ):
            return FindingStatus.APPROVED
        return FindingStatus.BLOCKING

    def scan_text(self, text: str, *, record_id: str, field_name: str) -> list[Finding]:
        findings: list[Finding] = []
        for detector in self.detectors:
            try:
                matches = detector.scan(text)
            except Exception as error:  # noqa: BLE001 — any detector failure fails closed
                raise DetectorError(f"{detector.name} failed: {error}") from error
            for match in matches:
                findings.append(
                    Finding(
                        record_id=record_id,
                        field=field_name,
                        category=match.category,
                        detector=match.detector,
                        status=self._status(match),
                        masked=mask(match.category, match.value),
                    )
                )
        return findings

    def scan_record(self, record: dict) -> list[Finding]:
        """Examine one record's model-derived text (FR-023a)."""
        record_id = record.get("record_id", "")
        findings: list[Finding] = []
        for index, turn in enumerate(record.get("turns", [])):
            findings.extend(
                self.scan_text(
                    turn["content"], record_id=record_id, field_name=f"turns[{index}].content"
                )
            )
        scenario = record.get("scenario", "")
        if scenario:
            findings.extend(self.scan_text(scenario, record_id=record_id, field_name="scenario"))
        return findings

    def scan_records(self, records: Iterable[dict]) -> ScanReport:
        findings: list[Finding] = []
        examined = 0
        fields = 0
        for record in records:
            examined += 1
            fields += len(record.get("turns", [])) + (1 if record.get("scenario") else 0)
            findings.extend(self.scan_record(record))
        return ScanReport(
            findings=findings,
            records_examined=examined,
            fields_examined=fields,
            detectors_run=self.names,
            covered_types=tuple(sorted(c.value for c in BLOCKING_FLOOR | ADVISORY_CATEGORIES)),
        )
