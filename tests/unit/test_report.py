"""One object behind the JSON, the human text, and the exit status (FR-035, FR-036, FR-036b)."""

import json

import pytest

from ticket_dataset.privacy.registry import Finding, ScanReport
from ticket_dataset.run.enums import FindingStatus, PIICategory, RunOutcome, Verdict
from ticket_dataset.run.report import EXIT_STATUS, RunReport


def _report(**overrides) -> RunReport:
    base = {
        "run_id": "run-1",
        "schema_version": "1.0.0",
        "outcome": RunOutcome.COMPLETED,
        "records_generated": 12,
        "records_written": 10,
        "discards": {"coherence_below_threshold": 2},
        "retry_counts": {"transport": 1},
        "duplicate_count": 1,
        "coherence_score_distribution": {"0.90-0.95": 10, "_count": 10},
        "composition_requested": {"category": {"billing": 1.0}},
        "composition_assigned": {"category": {"billing": 1.0}},
        "composition_achieved": {"category": {"billing": 1.0}},
    }
    return RunReport(**{**base, **overrides})


@pytest.mark.parametrize(
    ("outcome", "verdict", "status"),
    [
        (RunOutcome.COMPLETED, Verdict.PASS, 0),
        (RunOutcome.FAILED, Verdict.FAIL, 1),
        (RunOutcome.REFUSED, Verdict.FAIL, 2),
        (RunOutcome.STOPPED, Verdict.FAIL, 3),
    ],
)
def test_verdict_and_exit_status_follow_the_outcome(outcome, verdict, status) -> None:
    # Four statuses rather than a binary, because "nothing was spent", "output did not qualify",
    # and "work is preserved and resumable" call for different responses (FR-036b).
    report = _report(outcome=outcome)
    assert report.verdict is verdict
    assert report.exit_status == status


def test_every_outcome_has_an_exit_status() -> None:
    assert set(EXIT_STATUS) == set(RunOutcome)


def test_the_json_and_the_rendering_come_from_one_object() -> None:
    # Disagreement between the machine verdict and the human text is structurally impossible
    # rather than a thing to test for — but that only holds if both derive from here (FR-036).
    report = _report(outcome=RunOutcome.FAILED, failures=["privacy discard rate 3% exceeds 0.5%"])
    payload = json.loads(report.to_json())
    rendered = report.render()
    assert payload["verdict"] == "fail"
    assert "fail" in rendered
    assert payload["failures"][0] in rendered


def test_a_failure_is_named_in_both_surfaces() -> None:
    report = _report(outcome=RunOutcome.FAILED, failures=["composition.category.billing drifted"])
    assert "composition.category.billing" in report.render()
    assert "composition.category.billing" in report.to_json()


def test_the_privacy_section_states_what_was_examined() -> None:
    scan = ScanReport(
        findings=[
            Finding(
                record_id="r1",
                field="turns[0].content",
                category=PIICategory.EMAIL,
                detector="datafog-regex",
                status=FindingStatus.EXEMPT_BY_RANGE,
                masked="••••@example.com",
            )
        ],
        records_examined=10,
        fields_examined=41,
        detectors_run=("datafog-regex",),
        covered_types=("EMAIL", "PHONE"),
    )
    payload = json.loads(_report(scan=scan).to_json())["privacy"]
    assert payload["records_examined"] == 10
    assert payload["fields_examined"] == 41
    assert payload["findings_by_status"] == {"exempt_by_range": 1}
    assert payload["blocking"] == 0
    # Covered *and* uncovered, so a clean result is never mistaken for broader coverage (FR-019).
    assert payload["covered_types"] and payload["declared_gaps"]


def test_a_finding_never_carries_the_matched_value() -> None:
    scan = ScanReport(
        findings=[
            Finding(
                record_id="r1",
                field="turns[0].content",
                category=PIICategory.EMAIL,
                detector="datafog-regex",
                status=FindingStatus.BLOCKING,
                masked="••••@acme-corp.co.uk",
            )
        ],
        records_examined=1,
        fields_examined=2,
        detectors_run=("datafog-regex",),
        covered_types=("EMAIL",),
    )
    payload = json.loads(_report(scan=scan).to_json())
    assert "jane.roe" not in json.dumps(payload)
    assert payload["privacy"]["findings"][0]["masked"] == "••••@acme-corp.co.uk"


def test_the_rendering_names_the_worst_composition_member() -> None:
    report = _report(
        composition_requested={"category": {"billing": 0.5, "technical": 0.5}},
        composition_achieved={"category": {"billing": 0.6, "technical": 0.4}},
    )
    # Both members are 10pp off; the tie breaks on name, so the report is stable across runs.
    assert "category.billing" in report.render()
    assert "10.00pp" in report.render()


def test_the_report_is_written_where_a_run_id_can_find_it(tmp_path) -> None:
    published = _report().write(tmp_path, published=True)
    assert published.name == "run-1.report.json"
    interim = _report().write(tmp_path / "interim", published=False)
    assert interim.name == "report.json"
