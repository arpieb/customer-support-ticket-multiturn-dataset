"""Checkpointing and resume selection (FR-015a, FR-015e, FR-015f, FR-015g, FR-015h)."""

from pathlib import Path

import pytest

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.errors import (
    AmbiguousResumeError,
    CheckpointCorruptError,
    CheckpointMismatchError,
)
from ticket_dataset.run.checkpoint import (
    CHECKPOINT_NAME,
    Checkpoint,
    find_resumable,
    input_fingerprints,
    select_resumable,
)


def _config(tmp_path: Path, **overrides) -> GenerationConfig:
    prompt = tmp_path / "domain.md"
    rubric = tmp_path / "rubric.md"
    for path, text in ((prompt, "domain body"), (rubric, "rubric body")):
        if not path.exists():
            path.write_text(text)
    base = {
        "record_count": 100,
        "output_path": tmp_path / "release" / "corpus.jsonl",
        "prompt_document": prompt,
        "rubric": rubric,
    }
    return GenerationConfig(**{**base, **overrides})


def _checkpoint(run_id: str, fingerprints: dict[str, str], **overrides) -> Checkpoint:
    base = {
        "run_id": run_id,
        "next_position": 10,
        "bytes_written": 2048,
        "input_fingerprints": fingerprints,
    }
    return Checkpoint(**{**base, **overrides})


def test_a_checkpoint_round_trips(tmp_path: Path) -> None:
    fingerprints = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    original = _checkpoint("run-1", fingerprints, discards={"privacy_finding": 2}, resumes=1)
    path = original.write(tmp_path / "run-1")
    assert Checkpoint.read(path) == original


def test_the_write_is_atomic(tmp_path: Path) -> None:
    # Written via a temp file and a rename, so a checkpoint is never half-written.
    fingerprints = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    directory = tmp_path / "run-1"
    _checkpoint("run-1", fingerprints).write(directory)
    assert (directory / CHECKPOINT_NAME).exists()
    assert not (directory / f"{CHECKPOINT_NAME}.tmp").exists()


def test_an_unreadable_checkpoint_is_reported_not_swallowed(tmp_path: Path) -> None:
    path = tmp_path / CHECKPOINT_NAME
    path.write_text("{not json")
    with pytest.raises(CheckpointCorruptError, match="left in place"):
        Checkpoint.read(path)


def test_an_unreadable_checkpoint_leaves_partial_output_alone(tmp_path: Path) -> None:
    # The tool must not decide to throw away completed work at the moment its own state became
    # untrustworthy (FR-015g).
    staging = tmp_path / "records.partial.jsonl"
    staging.write_text('{"record_index": 0}\n')
    (tmp_path / CHECKPOINT_NAME).write_text("garbage")
    with pytest.raises(CheckpointCorruptError):
        Checkpoint.read(tmp_path / CHECKPOINT_NAME)
    assert staging.exists()


# --- applicability (FR-015e, FR-015f) -------------------------------------------------------


def test_matching_inputs_are_applicable(tmp_path: Path) -> None:
    fingerprints = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    _checkpoint("run-1", fingerprints).assert_applicable(fingerprints)


def test_a_changed_prompt_document_refuses_the_resume(tmp_path: Path) -> None:
    config = _config(tmp_path)
    before = input_fingerprints(config, 42, "1.0.0")
    (tmp_path / "domain.md").write_text("a different domain")
    after = input_fingerprints(config, 42, "1.0.0")
    with pytest.raises(CheckpointMismatchError, match="prompt_document"):
        _checkpoint("run-1", before).assert_applicable(after)


def test_a_changed_seed_refuses_the_resume(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(CheckpointMismatchError, match="seed"):
        _checkpoint("run-1", input_fingerprints(config, 42, "1.0.0")).assert_applicable(
            input_fingerprints(config, 43, "1.0.0")
        )


def test_a_changed_config_refuses_the_resume(tmp_path: Path) -> None:
    before = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    after = input_fingerprints(_config(tmp_path, record_count=200), 42, "1.0.0")
    with pytest.raises(CheckpointMismatchError, match="config"):
        _checkpoint("run-1", before).assert_applicable(after)


def test_the_code_revision_is_not_part_of_applicability(tmp_path: Path) -> None:
    # Deliberate: a changed revision is recorded as a manifest segment rather than refusing, so
    # an edit made while a run was interrupted does not discard hours of work (FR-015f).
    fingerprints = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    assert "code_revision" not in fingerprints
    assert "commit" not in fingerprints


# --- selection (FR-015h) ---------------------------------------------------------------------


def test_one_matching_run_resumes_without_being_named(tmp_path: Path) -> None:
    fingerprints = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    root = tmp_path / "interim"
    _checkpoint("run-1", fingerprints).write(root / "run-1")
    assert select_resumable(root, fingerprints).run_id == "run-1"


def test_several_matching_runs_refuse_and_name_the_candidates(tmp_path: Path) -> None:
    fingerprints = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    root = tmp_path / "interim"
    for run_id in ("run-a", "run-b"):
        _checkpoint(run_id, fingerprints).write(root / run_id)
    with pytest.raises(AmbiguousResumeError, match="run-a, run-b"):
        select_resumable(root, fingerprints)


def test_an_ambiguous_resume_can_be_disambiguated(tmp_path: Path) -> None:
    fingerprints = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    root = tmp_path / "interim"
    for run_id in ("run-a", "run-b"):
        _checkpoint(run_id, fingerprints).write(root / run_id)
    assert select_resumable(root, fingerprints, run_id="run-b").run_id == "run-b"


def test_nothing_to_resume_refuses_rather_than_starting_fresh(tmp_path: Path) -> None:
    # Starting a new run under the guise of resuming would be worse than refusing.
    fingerprints = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    with pytest.raises(CheckpointMismatchError, match="nothing to resume"):
        select_resumable(tmp_path / "interim", fingerprints)


def test_a_corrupt_checkpoint_does_not_hide_a_good_one(tmp_path: Path) -> None:
    fingerprints = input_fingerprints(_config(tmp_path), 42, "1.0.0")
    root = tmp_path / "interim"
    _checkpoint("run-good", fingerprints).write(root / "run-good")
    (root / "run-bad").mkdir(parents=True)
    (root / "run-bad" / CHECKPOINT_NAME).write_text("garbage")
    assert [c.run_id for c in find_resumable(root, fingerprints)] == ["run-good"]


def test_a_run_with_different_inputs_is_not_a_candidate(tmp_path: Path) -> None:
    config = _config(tmp_path)
    root = tmp_path / "interim"
    _checkpoint("run-1", input_fingerprints(config, 42, "1.0.0")).write(root / "run-1")
    assert find_resumable(root, input_fingerprints(config, 99, "1.0.0")) == []
