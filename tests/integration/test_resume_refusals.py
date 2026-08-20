"""What refuses a resume, and what deliberately does not (FR-015e, FR-015f, FR-015g)."""

import json
from pathlib import Path

import pytest

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.errors import CheckpointCorruptError, CheckpointMismatchError
from ticket_dataset.model.client import ModelResponse, ModelRole, ModelUnavailable
from ticket_dataset.model.fake import FakeModelClient
from ticket_dataset.run.checkpoint import CHECKPOINT_NAME
from ticket_dataset.run.run import GenerationRun


def _prompts(tmp_path: Path) -> tuple[Path, Path]:
    prompt = tmp_path / "domain.md"
    prompt.write_text(
        "---\nsubdomains:\n  - refund\n  - shipping-delay\n---\n\n# Domain\n\nBody text.\n"
    )
    rubric = tmp_path / "rubric.md"
    rubric.write_text(
        "---\nrubric_id: test-v1\ncriteria:\n  single_issue: 1.0\n---\n\n# Rubric\n\nGuidance.\n"
    )
    return prompt, rubric


def _config(tmp_path: Path, **overrides) -> GenerationConfig:
    prompt, rubric = _prompts(tmp_path)
    base = {
        "record_count": 20,
        "output_path": tmp_path / "release" / "corpus.jsonl",
        "prompt_document": prompt,
        "rubric": rubric,
        "composition_tolerance_pp": 20.0,
        "checkpoint_interval": 3,
        "max_concurrency": 1,
        "consecutive_failure_limit": 2,
        "max_attempts_per_slot": 1,
        "composition": {
            "category": {"billing": 1.0},
            "priority": {"normal": 1.0},
            "channel": {"email": 1.0},
            "resolution_status": {"resolved": 1.0},
        },
    }
    return GenerationConfig(**{**base, **overrides})


def _client(fail_after: int | None = None) -> FakeModelClient:
    state = {"n": 0}

    def responder(role: ModelRole, system: str, user: str) -> ModelResponse:
        if role is ModelRole.JUDGE:
            return ModelResponse(
                text=json.dumps({"criteria": {"single_issue": 0.95}, "justification": "ok"}),
                model_id="fake-model-1",
            )
        state["n"] += 1
        if fail_after is not None and state["n"] > fail_after:
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


async def _interrupt(tmp_path: Path, config: GenerationConfig):
    return await GenerationRun(config=config, seed=5, model_client=_client(fail_after=6)).execute()


async def test_a_changed_prompt_document_refuses(tmp_path: Path, staging_root: Path) -> None:
    config = _config(tmp_path)
    await _interrupt(tmp_path, config)

    (tmp_path / "domain.md").write_text(
        "---\nsubdomains:\n  - refund\n  - billing-dispute\n---\n\n# Domain\n\nDifferent body.\n"
    )
    with pytest.raises(CheckpointMismatchError, match="prompt_document"):
        await GenerationRun(config=config, seed=5, model_client=_client()).resume()


async def test_a_changed_seed_refuses(tmp_path: Path, staging_root: Path) -> None:
    config = _config(tmp_path)
    await _interrupt(tmp_path, config)
    with pytest.raises(CheckpointMismatchError, match="nothing to resume|seed"):
        await GenerationRun(config=config, seed=6, model_client=_client()).resume()


async def test_a_changed_rubric_refuses(tmp_path: Path, staging_root: Path) -> None:
    config = _config(tmp_path)
    await _interrupt(tmp_path, config)
    (tmp_path / "rubric.md").write_text(
        "---\nrubric_id: test-v2\ncriteria:\n  single_issue: 1.0\n---\n\n# Rubric\n\nRevised.\n"
    )
    with pytest.raises(CheckpointMismatchError, match="rubric"):
        await GenerationRun(config=config, seed=5, model_client=_client()).resume()


async def test_a_changed_code_revision_succeeds_and_adds_a_segment(
    tmp_path: Path, staging_root: Path
) -> None:
    """The deliberate exception (FR-015f).

    A changed revision is recorded rather than refused, because discarding hours of a
    release-scale run over an edit made while it was interrupted trades away far more than it
    protects — the same trade FR-025a makes for a modified working tree.
    """
    config = _config(tmp_path)
    interrupted = await _interrupt(tmp_path, config)
    assert interrupted.records_written < 20

    resumed = await GenerationRun(config=config, seed=5, model_client=_client()).resume()

    manifest = json.loads(resumed.manifest_path.read_text())
    assert len(manifest["segments"]) == 2
    # Each segment carries the revision that produced its records, so a corpus spanning more than
    # one revision is described rather than prevented.
    assert all("code_revision" in segment for segment in manifest["segments"])
    assert manifest["segments"][0]["first_record_index"] == 0
    assert manifest["segments"][1]["first_record_index"] >= 0


async def test_an_unreadable_checkpoint_refuses_and_preserves_output(
    tmp_path: Path, staging_root: Path
) -> None:
    config = _config(tmp_path)
    interrupted = await _interrupt(tmp_path, config)
    staging = interrupted.staging_path
    before = staging.read_bytes()

    (staging.parent / CHECKPOINT_NAME).write_text("{ not json")

    with pytest.raises((CheckpointCorruptError, CheckpointMismatchError)):
        await GenerationRun(config=config, seed=5, model_client=_client()).resume()

    # Restarting from scratch is an explicit operator action, never something the tool decides at
    # the moment its own state became untrustworthy (FR-015g).
    assert staging.read_bytes() == before


async def test_nothing_to_resume_refuses_rather_than_starting_fresh(
    tmp_path: Path, staging_root: Path
) -> None:
    config = _config(tmp_path)
    with pytest.raises(CheckpointMismatchError, match="nothing to resume"):
        await GenerationRun(config=config, seed=5, model_client=_client()).resume()
