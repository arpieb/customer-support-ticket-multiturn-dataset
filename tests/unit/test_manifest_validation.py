"""Manifest validation checks the arithmetic, not only the fields (FR-026, FR-026b, FR-028)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ticket_dataset_generator.run.manifest import (
    MANIFEST_VERSION,
    score_histogram,
    validate_manifest,
    validate_manifest_file,
)


def _manifest(**overrides) -> dict:
    base = {
        "manifest_version": MANIFEST_VERSION,
        "run_id": "run-1",
        "schema_version": "1.0.0",
        "seed": 42,
        "config": {"record_count": 10},
        "code_revision": {"commit": "abc123", "dirty": False, "unavailable_reason": None},
        "input_hashes": {"prompt_document": "a" * 64},
        "models": {"generator": {"model_id": "m"}, "judge": {"model_id": "m"}},
        "environment_overrides": {},
        "started_at": datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
        "completed_at": datetime(2026, 3, 1, 1, tzinfo=UTC).isoformat(),
        "records_generated": 12,
        "records_written": 10,
        "discards": [{"reason": "coherence_below_threshold", "count": 2}],
        "retry_counts": {"transport": 1},
        "resumed_count": 0,
        "segments": [
            {
                "code_revision": {"commit": "abc123", "dirty": False},
                "started_at": datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
                "completed_at": datetime(2026, 3, 1, 1, tzinfo=UTC).isoformat(),
                "first_record_index": 0,
                "last_record_index": 9,
            }
        ],
        "duplicate_count": 0,
        "composition_requested": {"category": {"billing": 1.0}},
        "composition_assigned": {"category": {"billing": 1.0}},
        "composition_achieved": {"category": {"billing": 1.0}},
        "coherence_score_distribution": {"0.90-0.95": 10},
        "output_filename": "corpus.jsonl",
        "output_sha256": "b" * 64,
    }
    return {**base, **overrides}


def test_a_complete_manifest_validates() -> None:
    assert validate_manifest(_manifest()) == []


@pytest.mark.parametrize(
    "missing",
    ["run_id", "seed", "code_revision", "input_hashes", "segments", "output_sha256"],
)
def test_a_missing_element_is_named(missing: str) -> None:
    payload = _manifest()
    del payload[missing]
    problems = validate_manifest(payload)
    assert any(missing in problem for problem in problems)


def test_counts_that_do_not_reconcile_fail_even_though_every_field_is_present() -> None:
    # The check worth having: presence alone would pass exactly the manifests worth catching.
    problems = validate_manifest(_manifest(records_written=9))
    assert any("do not reconcile" in problem for problem in problems)


def test_a_discard_reason_outside_the_closed_set_is_rejected() -> None:
    # An open-ended reason string makes the reconciliation a sum over free text (FR-026b).
    problems = validate_manifest(_manifest(discards=[{"reason": "felt_wrong", "count": 2}]))
    assert any("outside the closed set" in problem for problem in problems)


def test_a_negative_discard_count_is_rejected() -> None:
    problems = validate_manifest(
        _manifest(
            discards=[{"reason": "coherence_below_threshold", "count": -2}], records_written=14
        )
    )
    assert any("non-negative" in problem for problem in problems)


def test_an_empty_segment_list_is_rejected() -> None:
    assert any("segments is empty" in p for p in validate_manifest(_manifest(segments=[])))


def test_a_run_with_no_discards_reconciles() -> None:
    assert validate_manifest(_manifest(records_generated=10, discards=[])) == []


def test_a_resumed_run_reconciles_across_segments() -> None:
    # The tallies carried in the checkpoint are what let one manifest describe both segments.
    payload = _manifest(
        resumed_count=1,
        records_generated=24,
        records_written=20,
        discards=[{"reason": "coherence_below_threshold", "count": 4}],
        segments=[
            {
                "code_revision": {"commit": "abc", "dirty": False},
                "started_at": "2026-03-01T00:00:00+00:00",
                "completed_at": "2026-03-01T00:30:00+00:00",
                "first_record_index": 0,
                "last_record_index": 9,
            },
            {
                "code_revision": {"commit": "def", "dirty": True},
                "started_at": "2026-03-01T01:00:00+00:00",
                "completed_at": "2026-03-01T01:30:00+00:00",
                "first_record_index": 10,
                "last_record_index": 19,
            },
        ],
    )
    assert validate_manifest(payload) == []


# --- on-disk validation, including the binding to the artifact (FR-025b) --------------------


def test_a_manifest_binds_to_its_artifact_by_checksum(tmp_path: Path) -> None:
    from hashlib import sha256

    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text('{"record_index": 0}\n')
    payload = _manifest(output_sha256=sha256(corpus.read_bytes()).hexdigest())
    manifest = tmp_path / "run-1.manifest.json"
    manifest.write_text(json.dumps(payload))
    assert validate_manifest_file(manifest) == []


def test_an_altered_corpus_is_detected(tmp_path: Path) -> None:
    # A corpus altered after the fact is exactly what the checksum exists to reveal.
    from hashlib import sha256

    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text('{"record_index": 0}\n')
    payload = _manifest(output_sha256=sha256(corpus.read_bytes()).hexdigest())
    manifest = tmp_path / "run-1.manifest.json"
    manifest.write_text(json.dumps(payload))
    corpus.write_text('{"record_index": 0}\n{"record_index": 1}\n')
    assert any("checksum mismatch" in p for p in validate_manifest_file(manifest))


def test_a_missing_manifest_is_reported(tmp_path: Path) -> None:
    assert any("not found" in p for p in validate_manifest_file(tmp_path / "absent.json"))


def test_malformed_json_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "bad.manifest.json"
    path.write_text("{not json")
    assert any("not valid JSON" in p for p in validate_manifest_file(path))


# --- the score histogram (FR-038, SC-009) ---------------------------------------------------


def test_the_histogram_uses_fixed_buckets() -> None:
    # Fixed buckets make two runs comparable without re-deriving anything.
    first = score_histogram([0.81, 0.99])
    second = score_histogram([0.82, 0.98])
    assert set(k for k in first if not k.startswith("_")) == {"0.80-0.85", "0.95-1.00"}
    assert set(k for k in second if not k.startswith("_")) == {"0.80-0.85", "0.95-1.00"}


def test_a_perfect_score_lands_in_the_top_bucket() -> None:
    assert score_histogram([1.0])["0.95-1.00"] == 1


def test_the_histogram_carries_summary_statistics() -> None:
    summary = score_histogram([0.8, 0.9, 1.0])
    assert summary["_count"] == 3
    assert summary["_min"] == 0.8
    assert summary["_max"] == 1.0


def test_an_empty_corpus_has_an_empty_histogram() -> None:
    assert score_histogram([])["_count"] == 0
