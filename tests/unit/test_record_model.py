"""Edge cases of the record contract (FR-004, FR-006b, FR-009, spec Edge Cases)."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ticket_dataset_generator.schema.record import TicketRecord

CREATED = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _record(**overrides):
    base = {
        "schema_version": "1.0.0",
        "record_id": "rec-1",
        "run_id": "run-1",
        "record_index": 0,
        "source_id": "domain.md@0123456789ab",
        "subdomain": "refund-dispute",
        "scenario": "customer disputes a duplicate charge on an annual plan",
        "metadata": {
            "category": "billing",
            "priority": "normal",
            "channel": "email",
            "resolution_status": "resolved",
            "created_at": CREATED,
            "resolved_at": CREATED + timedelta(hours=6),
        },
        "turns": [
            {"index": 0, "role": "customer", "content": "I was charged twice."},
            {"index": 1, "role": "agent", "content": "Let me take a look."},
        ],
        "quality": {"coherence_score": 0.91, "rubric_id": "coherence-v1"},
        "generation": {
            "model_id": "anthropic/claude-opus-4-5",
            "judge_model_id": "anthropic/claude-opus-4-5",
        },
    }
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def test_a_conforming_record_validates() -> None:
    assert TicketRecord.model_validate(_record()).record_index == 0


# --- FR-006b: resolved_at present exactly when the status is resolved -----------------------


def test_resolved_status_requires_a_resolution_time() -> None:
    with pytest.raises(ValidationError, match="resolution time"):
        TicketRecord.model_validate(_record(metadata={"resolved_at": None}))


@pytest.mark.parametrize("status", ["unresolved", "escalated", "abandoned"])
def test_unresolved_statuses_must_not_carry_a_resolution_time(status: str) -> None:
    with pytest.raises(ValidationError, match="only valid when resolved"):
        TicketRecord.model_validate(_record(metadata={"resolution_status": status}))


@pytest.mark.parametrize("status", ["unresolved", "escalated", "abandoned"])
def test_unresolved_statuses_validate_without_one(status: str) -> None:
    record = TicketRecord.model_validate(
        _record(metadata={"resolution_status": status, "resolved_at": None})
    )
    assert record.metadata.resolved_at is None


def test_resolution_time_must_not_precede_creation() -> None:
    with pytest.raises(ValidationError, match="must not precede"):
        TicketRecord.model_validate(_record(metadata={"resolved_at": CREATED - timedelta(hours=1)}))


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        TicketRecord.model_validate(
            _record(
                metadata={
                    "created_at": datetime(2026, 3, 1, 9, 0),
                    "resolved_at": None,
                    "resolution_status": "unresolved",
                }
            )
        )


# --- FR-004 / FR-009: ordering, alternation, opening role, non-empty content ----------------


def test_turn_indices_must_ascend_contiguously() -> None:
    with pytest.raises(ValidationError, match="ascend contiguously"):
        TicketRecord.model_validate(
            _record(
                turns=[
                    {"index": 0, "role": "customer", "content": "Hello"},
                    {"index": 2, "role": "agent", "content": "Hi"},
                ]
            )
        )


def test_the_customer_speaks_first() -> None:
    with pytest.raises(ValidationError, match="customer speaks first"):
        TicketRecord.model_validate(
            _record(
                turns=[
                    {"index": 0, "role": "agent", "content": "How can I help?"},
                    {"index": 1, "role": "customer", "content": "I was charged twice."},
                ]
            )
        )


def test_roles_must_alternate() -> None:
    with pytest.raises(ValidationError, match="alternate"):
        TicketRecord.model_validate(
            _record(
                turns=[
                    {"index": 0, "role": "customer", "content": "I was charged twice."},
                    {"index": 1, "role": "customer", "content": "Twice!"},
                    {"index": 2, "role": "agent", "content": "Checking."},
                ]
            )
        )


@pytest.mark.parametrize("content", ["", "   ", "\t\n"])
def test_blank_turn_content_is_rejected(content: str) -> None:
    with pytest.raises(ValidationError):
        TicketRecord.model_validate(
            _record(
                turns=[
                    {"index": 0, "role": "customer", "content": content},
                    {"index": 1, "role": "agent", "content": "Hi"},
                ]
            )
        )


def test_a_single_turn_is_not_an_exchange() -> None:
    with pytest.raises(ValidationError):
        TicketRecord.model_validate(
            _record(turns=[{"index": 0, "role": "customer", "content": "Hello"}])
        )


@pytest.mark.parametrize(
    "content",
    [
        "Мой заказ не пришёл",  # Cyrillic
        "注文が届きませんでした",  # Japanese
        "لم يصل طلبي بعد",  # Arabic, right-to-left
        "my order never arrived 😤📦",  # emoji
    ],
)
def test_non_latin_and_emoji_content_is_valid(content: str) -> None:
    # English-first, not English-only: nothing may assume Latin script (spec Assumptions).
    record = TicketRecord.model_validate(
        _record(
            turns=[
                {"index": 0, "role": "customer", "content": content},
                {"index": 1, "role": "agent", "content": "Let me check."},
            ]
        )
    )
    assert record.turns[0].content == content


def test_a_very_long_conversation_is_valid() -> None:
    # Nothing may assume a small fixed maximum (spec Edge Cases).
    turns = [
        {"index": i, "role": "customer" if i % 2 == 0 else "agent", "content": f"turn {i}"}
        for i in range(200)
    ]
    assert len(TicketRecord.model_validate(_record(turns=turns)).turns) == 200


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TicketRecord.model_validate(_record(surprise="extra"))


def test_schema_version_is_required_not_defaulted() -> None:
    # FR-002: a record *declares* its version. A default would let a producer omit it.
    payload = _record()
    del payload["schema_version"]
    with pytest.raises(ValidationError, match="schema_version"):
        TicketRecord.model_validate(payload)
