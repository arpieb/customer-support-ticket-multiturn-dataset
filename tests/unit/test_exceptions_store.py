"""Approvals never become a store of identifier-shaped values (FR-022, FR-022a, FR-022b)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ticket_dataset.errors import ReasonContainsIdentifierError
from ticket_dataset.privacy.exceptions_store import ExceptionStore, fingerprint
from ticket_dataset.run.enums import PIICategory

VALUE = "Jane.Roe@Acme-Corp.co.uk"


def _store(tmp_path: Path) -> ExceptionStore:
    return ExceptionStore.load(tmp_path / "exceptions.json")


def test_the_raw_value_is_never_written(tmp_path: Path) -> None:
    # A file listing the strings that tripped the scanner would be exactly what the gate exists
    # to keep out of the repository (research R9).
    store = _store(tmp_path)
    store.approve(
        category=PIICategory.EMAIL, value=VALUE, reason="vendor sandbox address", approved_by="me"
    )
    store.save()
    text = store.path.read_text()
    assert "jane.roe" not in text.lower()
    assert "acme-corp" not in text.lower()


def test_an_approval_records_who_and_when(tmp_path: Path) -> None:
    store = _store(tmp_path)
    entry = store.approve(
        category=PIICategory.EMAIL,
        value=VALUE,
        reason="vendor sandbox address",
        approved_by="rbates8",
        now=datetime(2026, 8, 20, tzinfo=UTC),
    )
    assert entry.approved_by == "rbates8"
    assert entry.approved_on == "2026-08-20"


def test_fingerprints_are_case_and_whitespace_stable(tmp_path: Path) -> None:
    assert fingerprint(PIICategory.EMAIL, "  A@B.COM ") == fingerprint(PIICategory.EMAIL, "a@b.com")


def test_the_category_is_part_of_the_identity() -> None:
    # The same string under two categories is two decisions, not one.
    assert fingerprint(PIICategory.EMAIL, "x") != fingerprint(PIICategory.PHONE, "x")


def test_an_approval_without_a_reason_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="stated reason"):
        _store(tmp_path).approve(
            category=PIICategory.EMAIL, value=VALUE, reason="  ", approved_by="me"
        )


def test_an_approval_without_an_approver_is_refused(tmp_path: Path) -> None:
    # Self-approval is permitted; anonymous approval is not (FR-022a).
    with pytest.raises(ValueError, match="who made it"):
        _store(tmp_path).approve(
            category=PIICategory.EMAIL, value=VALUE, reason="fine", approved_by=""
        )


def test_a_reason_containing_an_identifier_is_refused(tmp_path: Path) -> None:
    # A free-text field that may hold a value defeats the fingerprinting it sits beside.
    store = _store(tmp_path)
    with pytest.raises(ReasonContainsIdentifierError, match="without reproducing it"):
        store.approve(
            category=PIICategory.EMAIL,
            value=VALUE,
            reason="approving jane.roe@acme-corp.co.uk because it is a test box",
            approved_by="me",
            scan_reason=lambda text: ["@" in text],
        )
    assert store.entries == []


def test_the_refusal_does_not_echo_the_offending_value(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ReasonContainsIdentifierError) as caught:
        store.approve(
            category=PIICategory.EMAIL,
            value=VALUE,
            reason="approving jane.roe@acme-corp.co.uk",
            approved_by="me",
            scan_reason=lambda text: [True],
        )
    assert "jane.roe" not in str(caught.value)


def test_approvals_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.approve(
        category=PIICategory.EMAIL, value=VALUE, reason="vendor sandbox", approved_by="me"
    )
    store.save()
    reloaded = ExceptionStore.load(store.path)
    assert reloaded.fingerprints == store.fingerprints


def test_suppression_survives_a_detector_swap(tmp_path: Path) -> None:
    # Approvals are keyed on category and value, not on which detector found it, so a value
    # approved once stays approved after the detector is replaced (research R9).
    store = _store(tmp_path)
    entry = store.approve(
        category=PIICategory.EMAIL, value=VALUE, reason="vendor sandbox", approved_by="me"
    )
    assert entry.fingerprint == fingerprint(PIICategory.EMAIL, VALUE)
