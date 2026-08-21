"""Recovering a run's inputs from its manifest (FR-040, FR-041)."""

import hashlib
import json
import tomllib
from pathlib import Path

import pytest

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.errors import TicketDatasetError
from ticket_dataset.run.reproduce import (
    InputStatus,
    check_reproduction,
    config_from_manifest,
    render_config_toml,
)


def _config(tmp_path: Path) -> GenerationConfig:
    prompt = tmp_path / "domain.md"
    prompt.write_text("---\ndomain_id: d\nsubdomains:\n  - a\n  - b\n---\n\n# d\n\nbody\n")
    rubric = tmp_path / "rubric.md"
    rubric.write_text("# rubric\n\n## single_issue (weight 1.0)\n\nscore it\n")
    return GenerationConfig(
        record_count=20,
        output_path=tmp_path / "out.jsonl",
        prompt_document=prompt,
        rubric=rubric,
        composition_tolerance_pp=10.0,
    )


def _manifest(config: GenerationConfig, *, seed: int = 42) -> dict:
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
    return {
        "run_id": "abc-123",
        "seed": seed,
        "config": config.model_dump(mode="json"),
        "code_revision": {"commit": "a" * 40, "dirty": False},
        "input_hashes": {
            "prompt_document": digest(config.prompt_document),
            "rubric": digest(config.rubric),
        },
        "environment_overrides": {},
    }


def test_the_recovered_config_equals_the_one_the_run_used(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert config_from_manifest(_manifest(config)) == config


def test_an_unchanged_tree_is_reported_reproducible(tmp_path: Path) -> None:
    report = check_reproduction(_manifest(_config(tmp_path)))
    assert report.reproducible
    assert report.seed == 42
    assert {c.status for c in report.checks} == {InputStatus.MATCH}


def test_an_edited_prompt_is_reported_as_drift(tmp_path: Path) -> None:
    config = _config(tmp_path)
    manifest = _manifest(config)
    config.prompt_document.write_text("---\ndomain_id: d\nsubdomains:\n  - a\n---\n\n# d\n\nx\n")

    report = check_reproduction(manifest)
    assert not report.reproducible
    assert [c.label for c in report.drifted] == ["prompt_document"]


def test_a_deleted_input_is_missing_rather_than_merely_different(tmp_path: Path) -> None:
    config = _config(tmp_path)
    manifest = _manifest(config)
    config.rubric.unlink()

    drifted = check_reproduction(manifest).drifted
    assert [(c.label, c.status) for c in drifted] == [("rubric", InputStatus.MISSING)]


def test_a_dirty_run_is_reported_without_being_called_irreproducible(tmp_path: Path) -> None:
    # The input digests are what bear on the corpus; the dirty flag is context, not a verdict.
    manifest = _manifest(_config(tmp_path))
    manifest["code_revision"]["dirty"] = True

    report = check_reproduction(manifest)
    assert report.dirty
    assert report.reproducible


def test_a_manifest_without_a_config_refuses(tmp_path: Path) -> None:
    with pytest.raises(TicketDatasetError, match="no 'config' object"):
        config_from_manifest({"run_id": "x", "seed": 1})


# --- serialisation ---------------------------------------------------------------------------


def test_the_rendered_toml_parses_back_to_the_same_config(tmp_path: Path) -> None:
    config = _config(tmp_path)
    reloaded = GenerationConfig.model_validate(tomllib.loads(render_config_toml(config)))
    assert reloaded == config


def test_unset_options_are_omitted_rather_than_written_as_null(tmp_path: Path) -> None:
    # TOML has no null. Writing one would produce a file the loader cannot read at all.
    text = render_config_toml(_config(tmp_path))
    assert "null" not in text
    assert "max_model_calls" not in text  # unset, therefore absent
    assert tomllib.loads(text)  # and the result is still parseable


def test_a_serialiser_that_lost_information_would_refuse_to_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The guarantee is that the file describes the recorded run. If it cannot, nothing is handed
    # over — a subtly wrong config is worse than none, because it looks like it worked.
    import ticket_dataset.run.reproduce as module

    monkeypatch.setattr(module.tomli_w, "dumps", lambda payload: "record_count = 999\n")
    with pytest.raises(TicketDatasetError, match="did not read back identically"):
        render_config_toml(_config(tmp_path))


def test_a_manifest_predating_the_connection_split_is_still_recoverable(tmp_path: Path) -> None:
    # Manifests written before FR-042 put the endpoint in extra, which the model now refuses.
    # Refusing to read them would make every already-published run unreproducible.
    config = _config(tmp_path)
    manifest = _manifest(config)
    manifest["config"]["models"]["generator"]["extra"] = {
        "api_base": "http://10.0.0.5:11434",
        "reasoning_effort": "high",
    }

    recovered = config_from_manifest(manifest)
    generator = recovered.models.generator
    assert generator.connection == {"api_base": "http://10.0.0.5:11434"}
    assert generator.extra == {"reasoning_effort": "high"}  # output-shaping settings stay


def test_a_recovered_legacy_config_no_longer_carries_the_endpoint(tmp_path: Path) -> None:
    # The point of relocating: the config written back out cannot leak it a second time.
    config = _config(tmp_path)
    manifest = _manifest(config)
    manifest["config"]["models"]["judge"]["extra"] = {"api_key": "sk-SECRET"}

    text = render_config_toml(config_from_manifest(manifest))
    assert "sk-SECRET" not in text


def test_a_real_local_manifest_round_trips() -> None:
    """Opportunistic: whatever manifest a local run happens to have left behind.

    Not a fixture shaped to pass, which is the point — but `data/` is not version controlled, so
    this cannot run in CI and must not name a particular run. It skips where there is nothing to
    check rather than pinning a run identifier that a routine clean-up would silently retire.
    """
    manifests = sorted(Path("data/release").glob("*.manifest.json"))
    if not manifests:
        pytest.skip("no local release manifest")
    manifest = json.loads(manifests[0].read_text())
    config = config_from_manifest(manifest)
    text = render_config_toml(config)

    # Everything the file carries reads back identically. Connection settings are the deliberate
    # exception: they are never written, so the operator supplies them and nothing is published.
    assert GenerationConfig.model_validate(tomllib.loads(text)).model_dump(
        mode="json"
    ) == config.model_dump(mode="json")
    for spec in manifest["config"]["models"].values():
        for value in spec.get("extra", {}).values():
            assert str(value) not in text or not str(value).startswith("http")
