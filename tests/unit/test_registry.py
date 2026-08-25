"""Floor coverage is demonstrated, not declared (FR-017, FR-017a, FR-018, FR-018a, FR-018b)."""

import pytest

from ticket_dataset_generator.errors import FloorNotCoveredError
from ticket_dataset_generator.privacy.canaries import FLOOR_CANARIES, NEGATIVE_CANARIES
from ticket_dataset_generator.privacy.detectors.datafog_detector import DataFogDetector
from ticket_dataset_generator.privacy.registry import DetectorError, DetectorRegistry, Match
from ticket_dataset_generator.run.enums import BLOCKING_FLOOR, FindingStatus, PIICategory


class StubDetector:
    """A detector whose behaviour the test dictates."""

    def __init__(self, name="stub", categories=None, matches=None, raises=False):
        self.name = name
        self._categories = frozenset(categories or BLOCKING_FLOOR)
        self._matches = matches or {}
        self._raises = raises

    @property
    def categories(self):
        return self._categories

    def scan(self, text: str):
        if self._raises:
            raise RuntimeError("detector exploded")
        return [
            Match(category=category, value=value, detector=self.name)
            for category, value in self._matches.items()
            if value in text
        ]


def _real_registry() -> DetectorRegistry:
    registry = DetectorRegistry()
    registry.register(DataFogDetector())
    return registry


# --- demonstrated coverage (FR-018a) --------------------------------------------------------


def test_the_real_detector_covers_the_floor() -> None:
    _real_registry().assert_floor_covered(FLOOR_CANARIES)


def test_a_detector_that_declares_but_does_not_detect_fails_the_probe() -> None:
    # The whole point of probing. This detector declares every floor category and matches
    # nothing; a declaration check would pass it, and the run would report clean.
    registry = DetectorRegistry()
    registry.register(StubDetector(categories=BLOCKING_FLOOR, matches={}))
    with pytest.raises(FloorNotCoveredError, match="not detected"):
        registry.assert_floor_covered(FLOOR_CANARIES)


def test_a_detector_that_lost_one_pattern_fails_the_probe() -> None:
    # The realistic regression: an upstream change drops SSN matching while the declaration and
    # every other category stay intact.
    matches = {category: FLOOR_CANARIES[category] for category in BLOCKING_FLOOR}
    del matches[PIICategory.US_SSN]
    registry = DetectorRegistry()
    registry.register(StubDetector(categories=BLOCKING_FLOOR, matches=matches))
    with pytest.raises(FloorNotCoveredError, match="US_SSN"):
        registry.assert_floor_covered(FLOOR_CANARIES)


def test_no_detectors_at_all_fails_closed() -> None:
    with pytest.raises(FloorNotCoveredError, match="no detectors"):
        DetectorRegistry().assert_floor_covered(FLOOR_CANARIES)


def test_a_missing_canary_fails_the_probe() -> None:
    with pytest.raises(FloorNotCoveredError, match="no canary"):
        _real_registry().assert_floor_covered({PIICategory.EMAIL: "a@example.com"})


def test_negative_canaries_are_not_reported() -> None:
    # A probe that passed by matching everything would be worthless.
    registry = _real_registry()
    for text in NEGATIVE_CANARIES:
        findings = registry.scan_text(text, record_id="r", field_name="turns[0].content")
        assert [f for f in findings if f.blocks] == [], text


# --- what blocks and what does not (FR-018b, FR-021c, FR-022) -------------------------------


def test_a_real_looking_email_blocks() -> None:
    registry = _real_registry()
    findings = registry.scan_text(
        "write to me at jane.roe@acme-corp.co.uk", record_id="r", field_name="turns[0].content"
    )
    assert [f.status for f in findings] == [FindingStatus.BLOCKING]
    assert findings[0].category is PIICategory.EMAIL


def test_a_reserved_for_fiction_email_does_not_block_but_is_reported() -> None:
    # Without this the gate fails every run on a corpus whose conversations mention an email.
    registry = _real_registry()
    findings = registry.scan_text(
        "write to me at j.doe@example.com", record_id="r", field_name="turns[0].content"
    )
    assert len(findings) == 1
    assert findings[0].status is FindingStatus.EXEMPT_BY_RANGE
    assert findings[0].blocks is False


def test_a_fictional_phone_number_does_not_block() -> None:
    registry = _real_registry()
    findings = registry.scan_text("call 212-555-0142", record_id="r", field_name="turns[0].content")
    assert all(f.status is FindingStatus.EXEMPT_BY_RANGE for f in findings)


def test_a_real_looking_phone_number_blocks() -> None:
    registry = _real_registry()
    findings = registry.scan_text("call 212-867-5309", record_id="r", field_name="turns[0].content")
    assert any(f.blocks for f in findings)


def test_an_ssn_always_blocks_even_though_it_looks_synthetic() -> None:
    # No published range reserves SSNs for fiction, so exempting one would be this project
    # inventing a policy rather than applying a standard.
    registry = _real_registry()
    findings = registry.scan_text("SSN 123-45-6789", record_id="r", field_name="turns[0].content")
    assert any(f.blocks and f.category is PIICategory.US_SSN for f in findings)


def test_an_advisory_category_never_blocks() -> None:
    registry = _real_registry()
    findings = registry.scan_text("from 10.0.0.7", record_id="r", field_name="turns[0].content")
    assert findings and all(f.status is FindingStatus.ADVISORY for f in findings)


def test_an_order_number_is_not_reported_as_a_postal_code() -> None:
    # Postal code is registered in neither tier: it matches ordinary order and account numbers,
    # and a detector firing on nearly every record trains maintainers to ignore the report.
    registry = _real_registry()
    findings = registry.scan_text("order #12345", record_id="r", field_name="turns[0].content")
    assert findings == []


def test_an_approved_value_stops_blocking_but_stays_visible() -> None:
    registry = _real_registry()
    registry.fingerprinter = lambda category, value: f"{category.value}:{value.lower()}"
    registry.approvals.add("EMAIL:jane.roe@acme-corp.co.uk")
    findings = registry.scan_text(
        "jane.roe@acme-corp.co.uk", record_id="r", field_name="turns[0].content"
    )
    assert findings[0].status is FindingStatus.APPROVED
    assert findings[0].blocks is False


# --- failure handling (FR-017a) -------------------------------------------------------------


def test_a_raising_detector_fails_closed() -> None:
    registry = DetectorRegistry()
    registry.register(StubDetector(raises=True))
    with pytest.raises(DetectorError, match="failed"):
        registry.scan_text("anything", record_id="r", field_name="turns[0].content")


# --- what the report states (FR-019, FR-023, FR-023a) ---------------------------------------


def test_the_report_states_what_it_examined() -> None:
    registry = _real_registry()
    records = [
        {
            "record_id": "r1",
            "scenario": "a duplicate charge",
            "turns": [
                {"role": "customer", "content": "charged twice"},
                {"role": "agent", "content": "checking"},
            ],
        }
    ]
    report = registry.scan_records(records)
    assert report.records_examined == 1
    assert report.fields_examined == 3  # two turns plus the scenario
    assert report.detectors_run == ("datafog-regex",)
    assert "US_SSN" in report.covered_types
    assert any("postal" in gap for gap in report.declared_gaps)
    assert report.scanned_fields == ("turns[].content", "scenario")


def test_findings_never_carry_the_matched_value() -> None:
    registry = _real_registry()
    findings = registry.scan_text(
        "jane.roe@acme-corp.co.uk", record_id="r", field_name="turns[0].content"
    )
    for finding in findings:
        assert "jane.roe" not in finding.masked
        assert "jane.roe" not in repr(finding)
