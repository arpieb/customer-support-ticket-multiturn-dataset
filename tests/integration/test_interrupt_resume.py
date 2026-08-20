"""An interrupted run resumes without regenerating or reissuing (SC-005, SC-012, FR-015b–i)."""

import json
from pathlib import Path

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.model.client import ModelResponse, ModelRole
from ticket_dataset.model.fake import FakeModelClient
from ticket_dataset.run.checkpoint import CHECKPOINT_NAME, Checkpoint
from ticket_dataset.run.enums import RunOutcome
from ticket_dataset.run.manifest import validate_manifest_file
from ticket_dataset.run.run import GenerationRun


def _config(tmp_path: Path, **overrides) -> GenerationConfig:
    base = {
        "record_count": 40,
        "output_path": tmp_path / "release" / "corpus.jsonl",
        "composition_tolerance_pp": 10.0,
        "checkpoint_interval": 5,
        "max_concurrency": 1,
        "composition": {
            "category": {"billing": 0.5, "technical": 0.5},
            "priority": {"normal": 1.0},
            "channel": {"email": 1.0},
            "resolution_status": {"resolved": 1.0},
        },
    }
    return GenerationConfig(**{**base, **overrides})


def _client(fail_after: int | None = None) -> FakeModelClient:
    """A client that stops answering after ``fail_after`` generation calls, as a kill would."""
    state = {"generated": 0}

    def responder(role: ModelRole, system: str, user: str) -> ModelResponse:
        if role is ModelRole.JUDGE:
            criteria = ["single_issue", "role_consistency", "conversational_flow", "metadata_fit"]
            return ModelResponse(
                text=json.dumps({"criteria": dict.fromkeys(criteria, 0.95), "justification": "ok"}),
                model_id="fake-model-1",
            )
        state["generated"] += 1
        if fail_after is not None and state["generated"] > fail_after:
            from ticket_dataset.model.client import ModelUnavailable

            raise ModelUnavailable("provider went away")
        count = int(user.split("turn_count=")[1].split("\n")[0])
        turns = [
            {"role": "customer" if i % 2 == 0 else "agent", "content": f"turn {i}"}
            for i in range(count)
        ]
        return ModelResponse(
            text=json.dumps({"scenario": "a situation", "turns": turns}), model_id="fake-model-1"
        )

    return FakeModelClient(responder=responder)


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def test_an_interrupted_run_checkpoints(tmp_path: Path, staging_root: Path) -> None:
    config = _config(tmp_path, consecutive_failure_limit=3, max_attempts_per_slot=1)
    result = await GenerationRun(
        config=config, seed=11, model_client=_client(fail_after=12)
    ).execute()

    assert result.outcome is RunOutcome.STOPPED
    assert result.artifact_path is None
    assert not Path(config.output_path).exists()
    checkpoint = Checkpoint.read(result.staging_path.parent / CHECKPOINT_NAME)
    assert checkpoint.next_position > 0
    assert checkpoint.bytes_written == result.staging_path.stat().st_size


async def test_resuming_completes_without_regenerating(tmp_path: Path, staging_root: Path) -> None:
    config = _config(tmp_path, consecutive_failure_limit=3, max_attempts_per_slot=1)
    interrupted = await GenerationRun(
        config=config, seed=11, model_client=_client(fail_after=12)
    ).execute()
    partial = len(_records(interrupted.staging_path))
    assert partial > 0

    resumed = await GenerationRun(config=config, seed=11, model_client=_client()).resume()

    assert resumed.outcome is RunOutcome.COMPLETED
    assert resumed.run_id == interrupted.run_id  # a resume keeps its identifier (FR-003a)
    assert resumed.records_written == 40
    assert resumed.resumed_count == 1


async def test_no_record_is_duplicated_or_skipped(tmp_path: Path, staging_root: Path) -> None:
    config = _config(tmp_path, consecutive_failure_limit=3, max_attempts_per_slot=1)
    await GenerationRun(config=config, seed=11, model_client=_client(fail_after=12)).execute()
    resumed = await GenerationRun(config=config, seed=11, model_client=_client()).resume()

    records = _records(resumed.artifact_path)
    indices = [record["record_index"] for record in records]
    ids = [record["record_id"] for record in records]
    assert indices == sorted(indices), "write order is position order (FR-012c)"
    assert len(set(indices)) == len(indices), "no position may be written twice"
    assert len(set(ids)) == len(ids), "no identifier may be issued twice (FR-015b)"
    # The interruption was a provider outage, not defective content, so the slots it killed are
    # retried on resume rather than silently shrinking the corpus (FR-009c).
    assert indices == list(range(40))


async def test_one_manifest_describes_the_whole_corpus(tmp_path: Path, staging_root: Path) -> None:
    # Provenance must not be fragmented by an interruption (FR-015c).
    config = _config(tmp_path, consecutive_failure_limit=3, max_attempts_per_slot=1)
    await GenerationRun(config=config, seed=11, model_client=_client(fail_after=12)).execute()
    resumed = await GenerationRun(config=config, seed=11, model_client=_client()).resume()

    assert validate_manifest_file(resumed.manifest_path) == []
    manifest = json.loads(resumed.manifest_path.read_text())
    assert manifest["resumed_count"] == 1
    assert len(manifest["segments"]) == 2, "one segment per run or resume (FR-015f)"
    generated = manifest["records_generated"]
    discarded = sum(entry["count"] for entry in manifest["discards"])
    assert generated - discarded == manifest["records_written"], "SC-005: counts reconcile"


async def test_success_drops_the_staging_copy_and_checkpoint(
    tmp_path: Path, staging_root: Path
) -> None:
    # The published artifact supersedes them; keeping the staging copy would leave a second full
    # copy of every corpus ever generated (FR-015i).
    config = _config(tmp_path)
    result = await GenerationRun(config=config, seed=11, model_client=_client()).execute()
    assert result.outcome is RunOutcome.COMPLETED
    assert not result.staging_path.exists()
    assert not (result.staging_path.parent / CHECKPOINT_NAME).exists()
    # The report survives.
    assert result.report_path.exists()


async def test_a_failed_run_retains_everything(tmp_path: Path, staging_root: Path) -> None:
    config = _config(tmp_path, consecutive_failure_limit=3, max_attempts_per_slot=1)
    result = await GenerationRun(
        config=config, seed=11, model_client=_client(fail_after=12)
    ).execute()
    assert result.staging_path.exists()
    assert (result.staging_path.parent / CHECKPOINT_NAME).exists()
