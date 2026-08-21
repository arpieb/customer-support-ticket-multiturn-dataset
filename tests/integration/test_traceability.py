"""A record locates its own provenance (FR-029, FR-029a, SC-006, SC-007)."""

import json
from pathlib import Path

from ticket_dataset.config.defaults import DEFAULT_PROMPT_DOCUMENT
from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.model.fake import FakeModelClient
from ticket_dataset.run.manifest import validate_manifest_file
from ticket_dataset.run.run import GenerationRun


def _config(tmp_path: Path) -> GenerationConfig:
    return GenerationConfig(
        record_count=20,
        output_path=tmp_path / "release" / "corpus.jsonl",
        composition_tolerance_pp=20.0,
        composition={
            "category": {"billing": 1.0},
            "priority": {"normal": 1.0},
            "channel": {"email": 1.0},
            "resolution_status": {"resolved": 1.0},
        },
    )


async def _run(tmp_path: Path):
    config = _config(tmp_path)
    return await GenerationRun(config=config, seed=3, model_client=FakeModelClient()).execute()


async def test_a_single_record_locates_its_manifest(tmp_path: Path, staging_root: Path) -> None:
    # The whole point of naming manifests by run identifier: someone holding one record, with no
    # other knowledge, can reach the run that produced it (FR-029a).
    result = await _run(tmp_path)
    record = json.loads(result.artifact_path.read_text().splitlines()[0])

    manifest_path = result.artifact_path.parent / f"{record['run_id']}.manifest.json"
    assert manifest_path.exists()
    assert validate_manifest_file(manifest_path) == []


async def test_the_manifest_names_the_artifact_it_describes(
    tmp_path: Path, staging_root: Path
) -> None:
    # And the other direction, so the mapping is navigable both ways (FR-025b).
    result = await _run(tmp_path)
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["output_filename"] == result.artifact_path.name
    assert len(manifest["output_sha256"]) == 64


async def test_every_record_carries_the_four_provenance_fields(
    tmp_path: Path, staging_root: Path
) -> None:
    result = await _run(tmp_path)
    for line in result.artifact_path.read_text().splitlines():
        record = json.loads(line)
        assert record["record_id"]
        assert record["run_id"] == result.run_id
        # Derived from the committed document rather than spelled out, so renaming it is not
        # a test edit. What matters is that the record names the document it came from.
        assert record["source_id"].startswith(f"{Path(DEFAULT_PROMPT_DOCUMENT).name}@")
        assert record["schema_version"] == "1.0.0"


async def test_the_manifest_answers_the_audit_questions(tmp_path: Path, staging_root: Path) -> None:
    # SC-006: seed, configuration, code revision, and inputs, from the manifest alone.
    result = await _run(tmp_path)
    manifest = json.loads(result.manifest_path.read_text())

    assert manifest["seed"] == 3
    assert manifest["config"]["record_count"] == 20
    assert "commit" in manifest["code_revision"]
    assert "dirty" in manifest["code_revision"]
    assert set(manifest["input_hashes"]) == {"prompt_document", "rubric"}
    assert manifest["models"]["generator"]["model_id"]
    assert manifest["models"]["judge"]["model_id"]
    assert manifest["started_at"] and manifest["completed_at"]


async def test_credentials_never_appear_in_the_manifest(
    tmp_path: Path, staging_root: Path, monkeypatch
) -> None:
    # Credentials are an access mechanism, not a generation input (FR-008).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-be-recorded")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.internal")
    result = await _run(tmp_path)
    text = result.manifest_path.read_text()

    assert "sk-should-never-be-recorded" not in text
    # A routing override is still recorded, because it can change output (FR-008c) — but as
    # having been set, not as where it pointed. A manifest ships with the release (FR-042).
    manifest = json.loads(text)
    assert manifest["environment_overrides"]["ANTHROPIC_BASE_URL"] == "<set>"
    assert "gateway.internal" not in text


async def test_the_report_is_findable_from_the_run_identifier(
    tmp_path: Path, staging_root: Path
) -> None:
    result = await _run(tmp_path)
    assert result.report_path.name == f"{result.run_id}.report.json"
    assert result.report_path.parent == result.artifact_path.parent


async def test_connection_settings_reach_no_artifact_a_release_ships_with(
    tmp_path: Path, staging_root: Path
) -> None:
    """The guarantee FR-042 makes, stated end to end.

    A manifest travels with a published dataset. Anything in it is disclosed to everyone who
    reads the corpus, so an endpoint address or a key must not be there at all — not redacted
    late, but never written.
    """
    config = _config(tmp_path)
    secrets = {"api_base": "http://10.11.12.13:9999", "api_key": "sk-never-published"}
    config = config.model_copy(
        update={
            "models": config.models.model_copy(
                update={
                    "generator": config.models.generator.model_copy(
                        update={"connection": dict(secrets)}
                    ),
                    "judge": config.models.judge.model_copy(update={"connection": dict(secrets)}),
                }
            )
        }
    )
    result = await GenerationRun(config=config, seed=3, model_client=FakeModelClient()).execute()

    for artifact in (result.manifest_path, result.report_path, result.artifact_path):
        text = artifact.read_text()
        for value in secrets.values():
            assert value not in text, f"{value} leaked into {artifact.name}"

    # Provenance is still served: the manifest says which settings were supplied, by name.
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["models"]["generator"]["connection_keys"] == ["api_base", "api_key"]
