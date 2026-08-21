"""Recovering a run's inputs from the manifest it wrote (FR-010b, FR-040, FR-041).

A manifest records everything a run consumed, but until now nothing read it back, so repeating
a release meant transcribing its config by hand. That is the failure this module exists to
prevent: a mis-typed threshold produces a corpus that looks legitimate and is not the one the
manifest describes.

The config is only part of the answer. Four inputs sit outside it — the seed, the prompt
document and rubric, the code revision, and the routing environment — and a config file that
travelled alone would let someone rerun against a changed prompt and never notice. So recovering
the config and checking the conditions around it are one operation here, not two.
"""

import hashlib
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import ValidationError

from ticket_dataset.config.models import GenerationConfig, _is_connection_setting
from ticket_dataset.errors import TicketDatasetError


class InputStatus(StrEnum):
    """How a recorded input compares with what is on disk now."""

    MATCH = "match"
    DIFFERS = "differs"
    #: Recorded by the run, absent now — the same obstacle to reproduction as a changed file,
    #: reported separately because the remedy is different.
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class InputCheck:
    """One recorded input, compared against the working tree."""

    label: str
    path: Path
    recorded: str
    actual: str | None

    @property
    def status(self) -> InputStatus:
        if self.actual is None:
            return InputStatus.MISSING
        return InputStatus.MATCH if self.actual == self.recorded else InputStatus.DIFFERS


@dataclass(frozen=True, slots=True)
class ReproductionReport:
    """Whether the working tree can still produce the run this manifest describes."""

    run_id: str
    seed: int
    checks: tuple[InputCheck, ...]
    commit: str | None
    dirty: bool
    environment_overrides: dict[str, str]
    #: role → the connection settings that run used, by name. Their values were deliberately
    #: never recorded (FR-042), so reproducing means supplying them; naming them is what makes
    #: that actionable rather than a silent difference.
    connection_keys: dict[str, list[str]]

    @property
    def drifted(self) -> tuple[InputCheck, ...]:
        return tuple(c for c in self.checks if c.status is not InputStatus.MATCH)

    @property
    def reproducible(self) -> bool:
        """True only when every recorded input is present and unchanged.

        A run made from a dirty tree is reported as such but does not by itself make this false:
        the working tree may since have committed exactly those edits, and the input hashes are
        the evidence that actually bears on the corpus (FR-025a).
        """
        return not self.drifted


def config_from_manifest(manifest: dict[str, Any]) -> GenerationConfig:
    """The exact configuration the run used.

    The manifest stores the *resolved* config — every default already materialised — so this
    reconstructs what the run actually ran with rather than what its author happened to type.
    """
    payload = manifest.get("config")
    if not isinstance(payload, dict):
        raise TicketDatasetError("manifest has no 'config' object to recover")
    return GenerationConfig.model_validate(_relocate_connection_settings(payload))


def _relocate_connection_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Move connection settings out of ``extra`` in configs recorded before they were separated.

    Manifests written before FR-042 recorded an endpoint inside ``extra``, which the config model
    now refuses. Refusing to read them would make every already-published run unreproducible to
    punish an exposure that has already happened in a file this cannot reach. Relocating them
    keeps recovery working and means the config written back out no longer carries the setting
    where it would be published again.
    """
    models = payload.get("models")
    if not isinstance(models, dict):
        return payload

    migrated = {**payload, "models": {**models}}
    for role, spec in models.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("extra"), dict):
            continue
        moved = {k: v for k, v in spec["extra"].items() if _is_connection_setting(k)}
        if not moved:
            continue
        migrated["models"][role] = {
            **spec,
            "extra": {k: v for k, v in spec["extra"].items() if k not in moved},
            "connection": {**spec.get("connection", {}), **moved},
        }
    return migrated


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def check_reproduction(manifest: dict[str, Any], *, root: Path = Path()) -> ReproductionReport:
    """Compare every input the manifest records against the working tree."""
    config = config_from_manifest(manifest)
    paths = {"prompt_document": config.prompt_document, "rubric": config.rubric}
    recorded = manifest.get("input_hashes") or {}
    revision = manifest.get("code_revision") or {}

    checks = tuple(
        InputCheck(label=label, path=path, recorded=digest, actual=_digest(root / path))
        for label, path in paths.items()
        if (digest := recorded.get(label)) is not None
    )
    return ReproductionReport(
        run_id=str(manifest.get("run_id", "")),
        seed=int(manifest["seed"]),
        checks=checks,
        commit=revision.get("commit"),
        dirty=bool(revision.get("dirty")),
        environment_overrides=dict(manifest.get("environment_overrides") or {}),
        connection_keys={
            role: sorted(record.get("connection_keys") or [])
            for role, record in (manifest.get("models") or {}).items()
            if record.get("connection_keys")
        },
    )


def _tomlable(value: Any) -> Any:
    """Drop what TOML cannot express, and narrow what it would round-trip differently.

    TOML has no null, so an unset optional is represented by absence — which is exactly how the
    loader reads it back. Paths become strings; nested tables recurse.
    """
    if isinstance(value, dict):
        return {k: _tomlable(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_tomlable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def render_config_toml(config: GenerationConfig) -> str:
    """Serialise a config to TOML, and prove the result parses back to the same config.

    The verification is the point. A serialiser that silently mangled a float or an escape would
    hand over a file that loads as a *different* run — the precise error this module exists to
    remove — so the output is re-read and compared before any caller is allowed to see it.
    """
    payload = _tomlable(config.model_dump(mode="json"))
    text = tomli_w.dumps(payload)

    failure = ""
    try:
        reloaded = GenerationConfig.model_validate(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        # Unreadable and readable-but-wrong are the same failure to the caller: what came back
        # is not the recorded run. Letting the underlying error escape would report it as a
        # problem with their manifest rather than with this serialisation.
        failure = f": {error}"
    else:
        if reloaded.model_dump(mode="json") == config.model_dump(mode="json"):
            return text

    raise TicketDatasetError(
        "serialised config did not read back identically; refusing to write a file that does "
        f"not describe the recorded run{failure}"
    )
