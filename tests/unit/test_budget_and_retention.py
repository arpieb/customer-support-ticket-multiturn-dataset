"""Run budgets and what survives a run (FR-012f, FR-015i)."""

from datetime import timedelta
from pathlib import Path

from ticket_dataset_generator.config.models import Budget
from ticket_dataset_generator.run.budget import BudgetTracker
from ticket_dataset_generator.run.checkpoint import CHECKPOINT_NAME
from ticket_dataset_generator.run.retention import clean_after_success, retained_after_failure


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- budgets (FR-012f) -----------------------------------------------------------------------


def test_no_declared_budget_never_stops_a_run() -> None:
    tracker = BudgetTracker(budget=Budget())
    for _ in range(10_000):
        tracker.record_call()
    assert tracker.exhausted() is None


def test_a_call_ceiling_stops_the_run() -> None:
    tracker = BudgetTracker(budget=Budget(max_model_calls=5))
    for _ in range(4):
        tracker.record_call()
    assert tracker.exhausted() is None
    tracker.record_call()
    assert "model call ceiling" in tracker.exhausted()


def test_a_runtime_ceiling_stops_the_run() -> None:
    clock = FakeClock()
    tracker = BudgetTracker(budget=Budget(max_runtime=timedelta(seconds=60)), clock=clock)
    clock.now = 59
    assert tracker.exhausted() is None
    clock.now = 61
    assert "runtime ceiling" in tracker.exhausted()


def test_either_ceiling_is_enough() -> None:
    clock = FakeClock()
    tracker = BudgetTracker(
        budget=Budget(max_runtime=timedelta(hours=12), max_model_calls=3), clock=clock
    )
    for _ in range(3):
        tracker.record_call()
    assert tracker.exhausted() is not None


def test_the_manifest_records_the_budget_and_the_spend() -> None:
    clock = FakeClock()
    tracker = BudgetTracker(budget=Budget(max_model_calls=100), clock=clock)
    tracker.record_call(7)
    clock.now = 12.5
    recorded = tracker.as_dict()
    assert recorded["max_model_calls"] == 100
    assert recorded["spent_model_calls"] == 7
    assert recorded["spent_seconds"] == 12.5
    assert recorded["exhausted"] is False


# --- retention (FR-015i) ---------------------------------------------------------------------


def _staging(tmp_path: Path) -> Path:
    directory = tmp_path / "run-1"
    directory.mkdir()
    (directory / "records.partial.jsonl").write_text('{"record_index": 0}\n')
    (directory / CHECKPOINT_NAME).write_text("{}")
    (directory / "quarantine.jsonl").write_text('{"record": {}}\n')
    (directory / "report.json").write_text("{}")
    return directory


def test_success_drops_what_the_artifact_supersedes(tmp_path: Path) -> None:
    directory = _staging(tmp_path)
    removed = clean_after_success(directory, directory / "records.partial.jsonl")
    assert {path.name for path in removed} == {"records.partial.jsonl", CHECKPOINT_NAME}


def test_success_keeps_the_quarantine_and_the_report(tmp_path: Path) -> None:
    # Quarantine is the input to an approval and cannot be reconstructed without regenerating the
    # corpus, so deleting it would leave a later approval with nothing to adjudicate against.
    directory = _staging(tmp_path)
    clean_after_success(directory, directory / "records.partial.jsonl")
    assert (directory / "quarantine.jsonl").exists()
    assert (directory / "report.json").exists()


def test_cleaning_twice_is_harmless(tmp_path: Path) -> None:
    directory = _staging(tmp_path)
    clean_after_success(directory, directory / "records.partial.jsonl")
    assert clean_after_success(directory, directory / "records.partial.jsonl") == []


def test_a_failed_run_retains_everything(tmp_path: Path) -> None:
    directory = _staging(tmp_path)
    retained = {path.name for path in retained_after_failure(directory)}
    assert retained == {
        "records.partial.jsonl",
        CHECKPOINT_NAME,
        "quarantine.jsonl",
        "report.json",
    }


def test_retention_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert retained_after_failure(tmp_path / "absent") == []
