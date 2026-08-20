"""The manifest contract must not drift from what the code writes (FR-028, Constitution II).

The record contract has this check; the manifest contract did not, which left the artifact that
carries all the provenance free to diverge silently from its published shape. Comparison is
structural for the same reason as the record contract: the committed file is hand-authored with
prose, and the shape is what matters.
"""

import json
from pathlib import Path

import pytest

CONTRACT_PATH = Path("specs/001-ticket-generation-pipeline/contracts/manifest.schema.json")


@pytest.fixture(scope="module")
def contract() -> dict:
    assert CONTRACT_PATH.exists(), f"committed manifest contract missing at {CONTRACT_PATH}"
    return json.loads(CONTRACT_PATH.read_text())


def _written_manifest() -> dict:
    """A manifest as the code actually writes one."""
    from datetime import UTC, datetime

    from ticket_dataset.run.manifest import ModelRecord, RunManifest, Segment
    from ticket_dataset.run.revision import CodeRevision

    now = datetime(2026, 3, 1, tzinfo=UTC)
    model = ModelRecord(
        model_id="anthropic/claude-opus-4-5",
        max_tokens=16000,
        sampling_seed=None,
        fallback_models=[],
        extra={},
    )
    manifest = RunManifest(
        run_id="run-1",
        schema_version="1.0.0",
        seed=42,
        config={},
        code_revision=CodeRevision(commit="abc", dirty=False),
        input_hashes={"prompt_document": "a" * 64},
        models={"generator": model, "judge": model},
        started_at=now,
        completed_at=now,
        records_generated=10,
        records_written=10,
        discards={},
        retry_counts={},
        resumed_count=0,
        segments=[
            Segment(
                code_revision={"commit": "abc", "dirty": False},
                started_at=now.isoformat(),
                completed_at=now.isoformat(),
                first_record_index=0,
                last_record_index=9,
            )
        ],
        duplicate_count=0,
        composition_requested={},
        composition_assigned={},
        composition_achieved={},
        coherence_score_distribution={},
        output_filename="corpus.jsonl",
        output_sha256="b" * 64,
    )
    return manifest.as_dict()


def test_every_required_key_in_the_contract_is_written(contract: dict) -> None:
    written = _written_manifest()
    missing = [key for key in contract["required"] if key not in written]
    assert missing == [], f"the code does not write required contract keys: {missing}"


def test_every_key_written_is_declared_in_the_contract(contract: dict) -> None:
    # The other direction matters too: a field the code writes and the contract does not declare
    # is provenance nobody downstream knows to read.
    written = _written_manifest()
    undeclared = [key for key in written if key not in contract["properties"]]
    assert undeclared == [], f"the code writes keys the contract does not declare: {undeclared}"


def test_the_discard_reasons_agree(contract: dict) -> None:
    from ticket_dataset.run.enums import DiscardReason

    declared = set(contract["$defs"]["DiscardAccount"]["properties"]["reason"]["enum"])
    implemented = {reason.value for reason in DiscardReason}
    assert declared == implemented, "the closed set of discard reasons has drifted"


def test_the_contract_requires_the_reconciliation_fields(contract: dict) -> None:
    for key in ("records_generated", "records_written", "discards"):
        assert key in contract["required"], key
