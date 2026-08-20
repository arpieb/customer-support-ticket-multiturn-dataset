"""Throughput must not compromise reproducibility (SC-013).

Two runs with the same seed and configuration but different concurrency levels must produce
identical per-position seeded choices. This is the property the whole slot design exists for: if
seeded choices were drawn from a shared stream, the draw order would be the completion order and
this test would fail intermittently.
"""

import json
from pathlib import Path

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.model.fake import FakeModelClient
from ticket_dataset.run.run import GenerationRun

SEED = 42
RECORDS = 40


def _config(tmp_path: Path, concurrency: int) -> GenerationConfig:
    return GenerationConfig(
        record_count=RECORDS,
        output_path=tmp_path / "release" / f"c{concurrency}.jsonl",
        composition_tolerance_pp=10.0,
        max_concurrency=concurrency,
        composition={
            "category": {"billing": 0.5, "technical": 0.5},
            "priority": {"normal": 0.5, "high": 0.5},
            "channel": {"email": 0.5, "chat": 0.5},
            "resolution_status": {"resolved": 0.75, "escalated": 0.25},
        },
    )


async def _corpus(tmp_path: Path, concurrency: int) -> list[dict]:
    run = GenerationRun(
        config=_config(tmp_path, concurrency), seed=SEED, model_client=FakeModelClient()
    )
    result = await run.execute()
    return [json.loads(line) for line in result.staging_path.read_text().splitlines()]


def _seeded_choices(record: dict) -> tuple:
    """Exactly what FR-010a defines as equivalent — and nothing else."""
    return (
        record["record_index"],
        record["subdomain"],
        record["metadata"]["category"],
        record["metadata"]["priority"],
        record["metadata"]["channel"],
        record["metadata"]["resolution_status"],
        len(record["turns"]),
        record["metadata"]["created_at"],
        record["metadata"].get("resolved_at"),
    )


async def test_seeded_choices_are_identical_across_concurrency_levels(
    tmp_path: Path, staging_root: Path
) -> None:
    serial = await _corpus(tmp_path, 1)
    parallel = await _corpus(tmp_path, 16)
    assert [_seeded_choices(r) for r in serial] == [_seeded_choices(r) for r in parallel]


async def test_composition_is_identical_across_concurrency_levels(
    tmp_path: Path, staging_root: Path
) -> None:
    import collections

    serial = await _corpus(tmp_path, 1)
    parallel = await _corpus(tmp_path, 16)
    for dimension in ("category", "priority", "channel", "resolution_status"):
        assert collections.Counter(r["metadata"][dimension] for r in serial) == (
            collections.Counter(r["metadata"][dimension] for r in parallel)
        )


async def test_write_order_is_ascending_at_every_concurrency(
    tmp_path: Path, staging_root: Path
) -> None:
    # FR-012c: the write order is the position order, not the completion order.
    for concurrency in (1, 4, 16):
        corpus = await _corpus(tmp_path, concurrency)
        indices = [record["record_index"] for record in corpus]
        assert indices == list(range(RECORDS)), concurrency
