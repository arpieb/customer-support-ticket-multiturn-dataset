"""Retained memory must not grow with corpus size (SC-001, FR-012).

The release acceptance run is 100,000 records and is never part of CI. What CI can check is the
*shape*: only per-slot state, a reorder buffer bounded by the concurrency level, and two digest
sets are held, so what the run still holds at the end is flat in the corpus size.

**Retained, not peak.** ``tracemalloc``'s peak conflates two different things: memory the run is
holding, and allocation churn that has already been freed but not yet collected. Churn is
proportional to work done and always will be — a run that produces ten times the records encodes
ten times the JSON. What FR-012 forbids is the pipeline *accumulating* the corpus, and that is
what a post-run snapshot measures.
"""

import json
import tracemalloc
from pathlib import Path

from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.model.fake import FakeModelClient
from ticket_dataset_generator.run.enums import RunOutcome
from ticket_dataset_generator.run.run import GenerationRun


def _config(tmp_path: Path, records: int) -> GenerationConfig:
    return GenerationConfig(
        record_count=records,
        output_path=tmp_path / "release" / f"corpus-{records}.jsonl",
        composition_tolerance_pp=10.0,
        max_concurrency=8,
        composition={
            "category": {"billing": 0.5, "technical": 0.5},
            "priority": {"normal": 1.0},
            "channel": {"email": 1.0},
            "resolution_status": {"resolved": 1.0},
        },
    )


async def _retained_kib(tmp_path: Path, records: int) -> tuple[float, int]:
    """Memory still held once the run has finished."""
    tracemalloc.start()
    try:
        result = await GenerationRun(
            config=_config(tmp_path, records), seed=1, model_client=FakeModelClient()
        ).execute()
        snapshot = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()
    assert result.outcome is RunOutcome.COMPLETED
    retained = sum(stat.size for stat in snapshot.statistics("filename"))
    return retained / 1024, result.records_written


async def test_retained_memory_does_not_scale_with_corpus_size(
    tmp_path: Path, staging_root: Path
) -> None:
    small, small_count = await _retained_kib(tmp_path, 500)
    large, large_count = await _retained_kib(tmp_path, 5_000)

    assert small_count == 500
    assert large_count == 5_000

    # Measured per record rather than as a ratio. Some growth is expected and bounded — the
    # duplicate-detection digest and the coherence score are one small entry per accepted record —
    # so the question is not "does it grow" but "does it grow by anything like a record's size".
    # A record serializes to roughly 500 bytes; retaining a fraction of that per record means the
    # pipeline is holding summaries, not the corpus.
    per_record_bytes = (large - small) * 1024 / (large_count - small_count)
    assert per_record_bytes < 250, (
        f"retained memory grew by {per_record_bytes:.0f} bytes per record "
        f"({small:.0f} KiB at 500 records, {large:.0f} KiB at 5,000). The pipeline must hold only "
        "per-slot state, a bounded reorder buffer, and the digest sets — not the corpus (FR-012)."
    )


async def test_nothing_holds_the_corpus_after_the_run(tmp_path: Path, staging_root: Path) -> None:
    # The concrete form of the same property: 5,000 records at roughly 500 bytes each is ~2.5 MB
    # of corpus, so anything close to that in retained memory means the run kept a copy.
    retained, count = await _retained_kib(tmp_path, 5_000)
    corpus_kib = count * 500 / 1024
    assert retained < corpus_kib / 2, (
        f"{retained:.0f} KiB retained against a ~{corpus_kib:.0f} KiB corpus — the run appears to "
        "be holding the records it wrote"
    )


async def test_the_corpus_is_written_incrementally(tmp_path: Path, staging_root: Path) -> None:
    # Progress must be observable during a long run, which means records reach disk as they are
    # produced rather than at the end (FR-012). The writer's ordering guarantees are unit-tested;
    # this checks the end-to-end result is complete and ordered.
    config = _config(tmp_path, 200)
    result = await GenerationRun(config=config, seed=1, model_client=FakeModelClient()).execute()

    records = [json.loads(line) for line in result.artifact_path.read_text().splitlines()]
    assert len(records) == 200
    assert [record["record_index"] for record in records] == list(range(200))
