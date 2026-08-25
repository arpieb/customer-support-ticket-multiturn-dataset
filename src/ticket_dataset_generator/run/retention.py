"""What survives a run, and what does not (FR-015i).

On success the staging copy and the checkpoint are redundant — the artifact in the release path
supersedes them, and keeping the staging copy would leave a second full copy of every corpus ever
generated under ``data/interim/``.

The report and any quarantine artifact survive. Quarantine is the input to FR-022's approval and
cannot be reconstructed without regenerating the corpus, so deleting it would leave a finding
approved after the fact with nothing to adjudicate against.

A run that failed or was interrupted retains everything, which is exactly when it is needed.
"""

from pathlib import Path

from ticket_dataset_generator.run.checkpoint import CHECKPOINT_NAME


def clean_after_success(staging_dir: Path, staging_file: Path) -> list[Path]:
    """Drop what the published artifact supersedes; return what was removed."""
    removed: list[Path] = []
    for path in (staging_file, Path(staging_dir) / CHECKPOINT_NAME):
        path = Path(path)
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def retained_after_failure(staging_dir: Path) -> list[Path]:
    """Everything a failed or interrupted run keeps, for the record."""
    directory = Path(staging_dir)
    if not directory.exists():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file())
