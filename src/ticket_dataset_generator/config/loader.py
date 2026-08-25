"""Total configuration validation (FR-011).

Total means two things. Every problem is reported at once, so an operator fixing a config sees
the whole list rather than discovering them one run at a time. And validation happens before
any model call, so an unsatisfiable request costs nothing — which is the difference between
exit 2 and exit 1.

One honest limitation: problems come in two layers, and the second cannot run if the first
fails. *Shape* problems — a missing field, a wrong type, a value out of range — are all
reported together, but a payload that fails them cannot be turned into a config object, so the
*semantic* checks that need one (an occupied output path, an unachievable tolerance, a missing
prompt document) are not reached on that pass. Fixing the shape and re-running surfaces them
together in turn. Merging the two layers would mean duplicating every semantic check against
raw dictionaries, which is a worse trade than one extra iteration.
"""

import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ticket_dataset_generator.config.defaults import RELEASE_DIR
from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.errors import ConfigError
from ticket_dataset_generator.planning.apportion import achievability_problems


def _shape_problems(payload: dict[str, Any]) -> tuple[GenerationConfig | None, list[str]]:
    try:
        return GenerationConfig.model_validate(payload), []
    except ValidationError as error:
        problems = []
        for item in error.errors():
            location = ".".join(str(part) for part in item["loc"]) or "(root)"
            problems.append(f"{location}: {item['msg']}")
        return None, problems


def semantic_problems(config: GenerationConfig, *, require_absent_output: bool = True) -> list[str]:
    """Problems the shape alone cannot express."""
    problems: list[str] = []

    if config.turns.min > config.turns.max:
        problems.append(f"turns: min {config.turns.min} exceeds max {config.turns.max}")
    # The floor of MINIMUM_TURNS is enforced on the model itself, so an invalid minimum is
    # caught during shape validation and never reaches here (FR-009e).

    if config.time_window is not None and config.time_window.start >= config.time_window.end:
        problems.append("time_window: start must precede end")
    if config.resolution_duration.min > config.resolution_duration.max:
        problems.append("resolution_duration: min exceeds max")

    output = Path(config.output_path)
    release_root = Path(RELEASE_DIR)
    if release_root not in output.parents:
        problems.append(
            f"output_path: {output} is not under {RELEASE_DIR}/ — release-path artifacts are "
            "distinguishable from scratch work by location alone (FR-013)"
        )
    if require_absent_output and output.exists():
        # There is deliberately no overwrite option: the data directory is outside version
        # control, so an overwritten corpus and its manifest are unrecoverable (FR-014).
        problems.append(
            f"output_path: {output} already exists. Remove it deliberately or choose another "
            "path; there is no overwrite flag (FR-014)"
        )

    for label, path in (
        ("prompt_document", config.prompt_document),
        ("rubric", config.rubric),
    ):
        if not Path(path).exists():
            problems.append(f"{label}: {path} does not exist")

    problems.extend(config.effective_composition.problems())
    problems.extend(achievability_problems(config))
    return problems


def validate_config(
    payload: dict[str, Any],
    *,
    require_absent_output: bool = True,
    output_override: Path | None = None,
) -> GenerationConfig:
    """Validate a parsed configuration, raising ``ConfigError`` with *every* problem.

    ``output_override`` is applied before validation rather than after. Checking the configured
    path and then writing somewhere else would refuse runs over a destination they never touch —
    which is what a recovered config always looks like, since the run it describes already
    published to that path (FR-014, FR-040).
    """
    if output_override is not None:
        payload = {**payload, "output_path": str(output_override)}
    config, problems = _shape_problems(payload)
    if config is None:
        raise ConfigError(problems)
    problems = semantic_problems(config, require_absent_output=require_absent_output)
    if problems:
        raise ConfigError(problems)
    return config


def load_config(
    path: Path, *, require_absent_output: bool = True, output_override: Path | None = None
) -> GenerationConfig:
    """Read and validate a TOML configuration file (FR-008, FR-011)."""
    path = Path(path)
    if not path.exists():
        raise ConfigError([f"config: {path} does not exist"])
    try:
        payload = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError([f"config: {path} is not valid TOML: {error}"]) from error
    return validate_config(
        payload,
        require_absent_output=require_absent_output,
        output_override=output_override,
    )
