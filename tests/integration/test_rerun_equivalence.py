"""Two runs of the same seed produce equivalent corpora (SC-003, FR-010a).

Two exclusions are the whole difficulty of this test, and both are deliberate:

* **Compare on ``record_index``, never on ``record_id``.** FR-003a gives each run a fresh
  ``run_id``, so identifiers differ by design. Comparing them would fail for correct behaviour,
  and the tempting fix would be to derive the run identifier from the inputs — which would make
  two legitimate reruns indistinguishable.
* **Do not assert equal record counts.** FR-009q makes survival through the coherence gate
  non-deterministic, so two equivalent runs may write different numbers of records.
"""

import json
from pathlib import Path

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.model.fake import FakeModelClient
from ticket_dataset.run.run import GenerationRun

SEED = 7


def _config(tmp_path: Path, label: str) -> GenerationConfig:
    return GenerationConfig(
        record_count=40,
        output_path=tmp_path / "release" / f"{label}.jsonl",
        composition_tolerance_pp=10.0,
        composition={
            "category": {"billing": 0.5, "technical": 0.5},
            "priority": {"normal": 0.5, "high": 0.5},
            "channel": {"email": 0.5, "chat": 0.5},
            "resolution_status": {"resolved": 0.75, "escalated": 0.25},
        },
    )


def _output(result) -> Path:
    """Where the corpus ended up: the published artifact on success, staging otherwise."""
    return result.artifact_path or result.staging_path


async def _corpus(tmp_path: Path, label: str) -> tuple[str, dict[int, dict]]:
    run = GenerationRun(config=_config(tmp_path, label), seed=SEED, model_client=FakeModelClient())
    result = await run.execute()
    records = [json.loads(line) for line in _output(result).read_text().splitlines()]
    return result.run_id, {record["record_index"]: record for record in records}


def _seeded_choices(record: dict) -> tuple:
    return (
        record["subdomain"],
        record["metadata"]["category"],
        record["metadata"]["priority"],
        record["metadata"]["channel"],
        record["metadata"]["resolution_status"],
        len(record["turns"]),
        record["metadata"]["created_at"],
        record["metadata"].get("resolved_at"),
    )


async def test_seeded_choices_match_at_every_shared_position(
    tmp_path: Path, staging_root: Path
) -> None:
    _, first = await _corpus(tmp_path, "first")
    _, second = await _corpus(tmp_path, "second")
    shared = set(first) & set(second)
    assert shared, "the two runs shared no positions at all"
    for index in sorted(shared):
        assert _seeded_choices(first[index]) == _seeded_choices(second[index]), index


async def test_a_rerun_gets_fresh_identifiers(tmp_path: Path, staging_root: Path) -> None:
    # Deliberate, and the reason the comparison above is by position: deriving the run
    # identifier from the inputs would make two legitimate reruns indistinguishable and give two
    # separate corpora the same record identifiers (FR-003a).
    first_run, first = await _corpus(tmp_path, "first")
    second_run, second = await _corpus(tmp_path, "second")
    assert first_run != second_run
    shared = set(first) & set(second)
    assert all(first[i]["record_id"] != second[i]["record_id"] for i in shared)


async def test_composition_matches_within_tolerance(tmp_path: Path, staging_root: Path) -> None:
    import collections

    _, first = await _corpus(tmp_path, "first")
    _, second = await _corpus(tmp_path, "second")
    tolerance = 10.0 / 100
    for dimension in ("category", "priority", "channel", "resolution_status"):
        a = collections.Counter(r["metadata"][dimension] for r in first.values())
        b = collections.Counter(r["metadata"][dimension] for r in second.values())
        for member in set(a) | set(b):
            share_a = a[member] / max(len(first), 1)
            share_b = b[member] / max(len(second), 1)
            assert abs(share_a - share_b) <= tolerance, f"{dimension}.{member}"
