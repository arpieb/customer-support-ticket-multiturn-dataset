"""The scan examines the model-derived text and nothing else (FR-023a).

This test pins an *accepted limitation*, not just a behaviour: `subdomain` comes from a committed
prompt document and is deliberately out of scope, so widening the field set later means deleting
a test that says why it was narrow.
"""

from ticket_dataset.privacy.detectors.datafog_detector import DataFogDetector
from ticket_dataset.privacy.registry import SCANNED_FIELDS, DetectorRegistry

REAL_LOOKING = "jane.roe@acme-corp.co.uk"


def _registry() -> DetectorRegistry:
    registry = DetectorRegistry()
    registry.register(DataFogDetector())
    return registry


def _record(**overrides) -> dict:
    base = {
        "record_id": "rec-1",
        "run_id": "run-1",
        "subdomain": "billing-duplicate-charge",
        "scenario": "a duplicate charge on an annual plan",
        "turns": [
            {"index": 0, "role": "customer", "content": "I was charged twice."},
            {"index": 1, "role": "agent", "content": "Let me check."},
        ],
    }
    return {**base, **overrides}


def test_turn_content_is_scanned() -> None:
    record = _record(
        turns=[
            {"index": 0, "role": "customer", "content": f"reach me at {REAL_LOOKING}"},
            {"index": 1, "role": "agent", "content": "Noted."},
        ]
    )
    findings = _registry().scan_record(record)
    assert [f.field for f in findings] == ["turns[0].content"]
    assert findings[0].blocks


def test_the_scenario_is_scanned() -> None:
    findings = _registry().scan_record(_record(scenario=f"customer wrote from {REAL_LOOKING}"))
    assert [f.field for f in findings] == ["scenario"]


def test_the_subdomain_is_not_scanned() -> None:
    # Accepted by requirement: an identifier can only enter through model output, and the
    # subdomain comes from a committed file that review covers (FR-023a). A prompt document
    # carrying a real identifier is caught by reading it, not by this gate.
    findings = _registry().scan_record(_record(subdomain=REAL_LOOKING))
    assert findings == []


def test_identifiers_and_metadata_are_not_scanned() -> None:
    # Scanning pipeline-assigned values would produce findings on UUIDs and hashes that every
    # run would then have to except.
    findings = _registry().scan_record(
        _record(record_id=REAL_LOOKING, run_id=REAL_LOOKING, source_id=REAL_LOOKING)
    )
    assert findings == []


def test_the_scanned_field_set_is_declared() -> None:
    assert SCANNED_FIELDS == ("turns[].content", "scenario")
