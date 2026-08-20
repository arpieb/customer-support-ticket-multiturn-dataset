"""Configuration validation refuses before anything is spent (FR-011, FR-031b, FR-032)."""

from pathlib import Path

import pytest

from ticket_dataset.config.loader import load_config, validate_config
from ticket_dataset.errors import ConfigError


def _payload(**overrides) -> dict:
    base = {
        "record_count": 100,
        "output_path": "data/release/does-not-exist-yet.jsonl",
        "prompt_document": "pyproject.toml",  # any existing file; content is not read here
        "rubric": "pyproject.toml",
    }
    return {**base, **overrides}


def test_a_valid_configuration_loads() -> None:
    assert validate_config(_payload()).record_count == 100


def test_zero_records_is_a_configuration_error() -> None:
    # Not an empty corpus — a refusal (spec Edge Cases).
    with pytest.raises(ConfigError, match="record_count"):
        validate_config(_payload(record_count=0))


def test_an_inverted_turn_range_is_refused() -> None:
    with pytest.raises(ConfigError, match="exceeds max"):
        validate_config(_payload(turns={"min": 10, "max": 4}))


def test_a_turn_minimum_below_two_is_refused() -> None:
    # One turn from each party is the smallest exchange that can be an exchange (FR-009e).
    with pytest.raises(ConfigError, match=r"turns\.min.*greater than or equal to 2"):
        validate_config(_payload(turns={"min": 1, "max": 8}))


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_a_threshold_outside_zero_to_one_is_refused(value: float) -> None:
    with pytest.raises(ConfigError, match="coherence"):
        validate_config(_payload(coherence={"threshold": value}))


def test_output_outside_the_release_directory_is_refused() -> None:
    with pytest.raises(ConfigError, match="not under data/release"):
        validate_config(_payload(output_path="data/interim/sneaky.jsonl"))


def test_an_existing_output_path_is_refused(tmp_path: Path) -> None:
    # No overwrite flag exists to catch: removing a corpus stays a deliberate manual act.
    existing = Path("data/release/occupied.jsonl")
    existing.write_text("")
    try:
        with pytest.raises(ConfigError, match="already exists"):
            validate_config(_payload(output_path=str(existing)))
    finally:
        existing.unlink()


def test_a_missing_prompt_document_is_refused() -> None:
    with pytest.raises(ConfigError, match="prompt_document"):
        validate_config(_payload(prompt_document="prompts/nope.md"))


def test_an_unachievable_tolerance_is_refused_before_generating() -> None:
    with pytest.raises(ConfigError, match="unachievable at 20 records"):
        validate_config(_payload(record_count=20, composition_tolerance_pp=2.0))


def test_every_semantic_problem_is_reported_at_once() -> None:
    # An operator fixing a config should see the whole list, not discover them one run at a
    # time — which is the point of FR-011's "total" validation.
    with pytest.raises(ConfigError) as caught:
        validate_config(
            _payload(
                record_count=20,
                composition_tolerance_pp=2.0,
                turns={"min": 9, "max": 4},
                output_path="data/interim/wrong.jsonl",
                prompt_document="prompts/nope.md",
            )
        )
    problems = caught.value.problems
    assert len(problems) >= 4, problems
    joined = " ".join(problems)
    for expected in ("turns", "output_path", "prompt_document", "unachievable"):
        assert expected in joined


def test_every_shape_problem_is_reported_at_once() -> None:
    with pytest.raises(ConfigError) as caught:
        validate_config(_payload(record_count=0, max_concurrency=0, checkpoint_interval=0))
    assert len(caught.value.problems) >= 3, caught.value.problems


def test_shape_failures_defer_the_semantic_layer() -> None:
    # The honest limitation: a payload that cannot become a config object cannot be checked for
    # an occupied output path or an unachievable tolerance. Fixing the shape surfaces those on
    # the next pass, rather than every semantic check being duplicated against raw dicts.
    with pytest.raises(ConfigError) as caught:
        validate_config(_payload(record_count="many", prompt_document="prompts/nope.md"))
    assert all("prompt_document" not in problem for problem in caught.value.problems)


def test_unknown_keys_are_rejected_rather_than_ignored() -> None:
    # A typo in a config should fail loudly, not silently take a default.
    with pytest.raises(ConfigError, match="[Ee]xtra inputs"):
        validate_config(_payload(recrod_count=100))


def test_a_missing_file_is_reported_as_such(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(tmp_path / "absent.toml")


def test_malformed_toml_is_reported_as_such(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("record_count = = 3")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(bad)


def test_loading_a_real_file_round_trips(tmp_path: Path) -> None:
    config_file = tmp_path / "run.toml"
    config_file.write_text(
        "record_count = 60\n"
        'output_path = "data/release/from-file.jsonl"\n'
        'prompt_document = "pyproject.toml"\n'
        'rubric = "pyproject.toml"\n'
        'language = "en"\n'
    )
    config = load_config(config_file)
    assert config.record_count == 60
    assert config.language == "en"
