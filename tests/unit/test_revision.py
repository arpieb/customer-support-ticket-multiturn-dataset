"""Code revision and environment provenance (FR-008, FR-008c, FR-025, FR-025a)."""

import subprocess
from pathlib import Path

from ticket_dataset.run.revision import (
    CREDENTIAL_VARIABLES,
    capture_revision,
    environment_overrides,
    hash_file,
    hash_inputs,
)


def _git(tmp_path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "file.txt").write_text("one\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "first")
    return tmp_path


def test_a_clean_tree_records_a_commit_and_no_modification(tmp_path: Path) -> None:
    revision = capture_revision(_repo(tmp_path))
    assert revision.commit and len(revision.commit) == 40
    assert revision.dirty is False
    assert revision.unavailable_reason is None


def test_a_modified_tree_is_recorded_rather_than_refused(tmp_path: Path) -> None:
    # A SHA from a modified tree misrepresents what produced the artifact; the flag makes the
    # condition reviewable instead of invisible. Refusing would block ordinary development.
    repo = _repo(tmp_path)
    (repo / "file.txt").write_text("changed\n")
    revision = capture_revision(repo)
    assert revision.commit is not None
    assert revision.dirty is True


def test_an_untracked_file_counts_as_modified(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "new.txt").write_text("appeared\n")
    assert capture_revision(repo).dirty is True


def test_a_missing_repository_records_why(tmp_path: Path) -> None:
    revision = capture_revision(tmp_path)
    assert revision.commit is None
    assert revision.unavailable_reason is not None
    assert "git" in revision.unavailable_reason


def test_the_revision_serializes_all_three_fields(tmp_path: Path) -> None:
    assert set(capture_revision(_repo(tmp_path)).as_dict()) == {
        "commit",
        "dirty",
        "unavailable_reason",
    }


# --- input hashing (FR-025) -----------------------------------------------------------------


def test_hashing_an_input_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "prompt.md"
    path.write_text("content")
    assert hash_file(path) == hash_file(path)


def test_editing_an_input_changes_its_hash(tmp_path: Path) -> None:
    # A change to the prompt document is a change in provenance (FR-008a).
    path = tmp_path / "prompt.md"
    path.write_text("content")
    before = hash_file(path)
    path.write_text("content, revised")
    assert hash_file(path) != before


def test_hash_inputs_labels_every_present_input(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "b.md").write_text("b")
    hashes = hash_inputs(
        {"prompt": tmp_path / "a.md", "rubric": tmp_path / "b.md", "absent": tmp_path / "c.md"}
    )
    assert set(hashes) == {"prompt", "rubric"}
    assert all(len(digest) == 64 for digest in hashes.values())


# --- environment provenance (FR-008, FR-008c) -----------------------------------------------


def test_a_routing_override_is_recorded() -> None:
    # An unrecorded setting that alters output is exactly the hidden state FR-008 prohibits;
    # recording it converts it into provenance.
    overrides = environment_overrides({"ANTHROPIC_BASE_URL": "https://gateway.internal"})
    assert overrides == {"ANTHROPIC_BASE_URL": "https://gateway.internal"}


def test_an_empty_environment_records_nothing() -> None:
    assert environment_overrides({}) == {}


def test_credentials_are_never_recorded() -> None:
    # Credentials are an access mechanism, not a generation input. They are excluded by name
    # rather than redacted: a value never read cannot be written by accident.
    environment = dict.fromkeys(CREDENTIAL_VARIABLES, "super-secret-value")
    environment["ANTHROPIC_PROFILE"] = "work"
    overrides = environment_overrides(environment)
    assert overrides == {"ANTHROPIC_PROFILE": "work"}
    assert "super-secret-value" not in str(overrides)


def test_several_routing_settings_are_all_recorded() -> None:
    overrides = environment_overrides(
        {"ANTHROPIC_BASE_URL": "https://gw", "AWS_REGION": "us-east-1", "ANTHROPIC_API_KEY": "sk-x"}
    )
    assert set(overrides) == {"ANTHROPIC_BASE_URL", "AWS_REGION"}
