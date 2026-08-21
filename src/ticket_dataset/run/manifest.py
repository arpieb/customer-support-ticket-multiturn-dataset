"""The run manifest: how one run produced its output (FR-025–FR-029a).

Provenance cannot be retrofitted — a corpus produced without a manifest is permanently
unauditable — so this is written for every run, including one that failed.

Two properties are load-bearing:

**It is findable from a record alone.** The manifest is named ``<run_id>.manifest.json`` and sits
beside the artifact, so a record's own ``run_id`` locates it. Without a naming rule FR-029's claim
is unachievable: a record carries an identifier, not a path, and someone holding a single record
would have no way to reach the run that produced it (FR-029a).

**Its accounting closes.** ``records_generated - discards == records_written``, where records
generated is every response received from the generating model, counted once per attempt
(FR-026a). Validation checks the arithmetic, not only that fields are present: a manifest whose
fields are all there but whose counts do not balance is not valid, and presence checking alone
would pass exactly the manifests worth catching.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ticket_dataset.run.enums import DiscardReason
from ticket_dataset.run.revision import CodeRevision

MANIFEST_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class Segment:
    """One run or resume, with the code revision that produced its records (FR-015f).

    A changed revision does not refuse a resume; the corpus is described honestly instead.
    """

    code_revision: dict
    started_at: str
    completed_at: str
    first_record_index: int
    last_record_index: int


@dataclass(frozen=True, slots=True)
class ModelRecord:
    """What served one role, and under what settings (FR-027, FR-009j).

    Provider-neutral: ``model_id`` is a litellm model string and ``extra`` carries whatever
    provider-specific settings shaped the output. Both are recorded because anything that shapes
    output is provenance, whichever vendor's vocabulary it happens to be written in.

    ``connection_keys`` names the settings used to reach the provider **without their values**.
    An alternate endpoint has to be visible as provenance, or it is the hidden state FR-008
    prohibits — but its address is deployment infrastructure that auditing a corpus never needs,
    and publishing it in a manifest that ships with a release would disclose it to everyone who
    reads the dataset. Naming the setting satisfies the first without the second (FR-008c,
    FR-042). A digest was rejected: an internal hostname or address has too little entropy to
    survive being brute-forced, so hashing it would assure without protecting.
    """

    model_id: str
    max_tokens: int
    sampling_seed: int | None
    fallback_models: list[str]
    extra: dict
    connection_keys: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunManifest:
    run_id: str
    schema_version: str
    seed: int
    config: dict[str, Any]
    code_revision: CodeRevision
    input_hashes: dict[str, str]
    models: dict[str, ModelRecord]
    started_at: datetime
    completed_at: datetime
    records_generated: int
    records_written: int
    discards: dict[str, int]
    retry_counts: dict[str, int]
    resumed_count: int
    segments: list[Segment]
    duplicate_count: int
    composition_requested: dict[str, dict[str, float]]
    composition_assigned: dict[str, dict[str, float]]
    composition_achieved: dict[str, dict[str, float]]
    coherence_score_distribution: dict[str, int]
    output_filename: str
    output_sha256: str
    environment_overrides: dict[str, str] = field(default_factory=dict)
    fallbacks_used: dict[str, int] = field(default_factory=dict)
    budget: dict[str, Any] | None = None
    manifest_version: str = MANIFEST_VERSION

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "manifest_version": self.manifest_version,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "config": self.config,
            "code_revision": self.code_revision.as_dict(),
            "input_hashes": self.input_hashes,
            "models": {role: asdict(record) for role, record in self.models.items()},
            "environment_overrides": self.environment_overrides,
            "fallbacks_used": self.fallbacks_used,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "records_generated": self.records_generated,
            "records_written": self.records_written,
            "discards": [
                {"reason": reason, "count": count}
                for reason, count in sorted(self.discards.items())
            ],
            "retry_counts": self.retry_counts,
            "resumed_count": self.resumed_count,
            "segments": [asdict(segment) for segment in self.segments],
            "duplicate_count": self.duplicate_count,
            "composition_requested": self.composition_requested,
            "composition_assigned": self.composition_assigned,
            "composition_achieved": self.composition_achieved,
            "coherence_score_distribution": self.coherence_score_distribution,
            "output_filename": self.output_filename,
            "output_sha256": self.output_sha256,
        }
        if self.budget is not None:
            payload["budget"] = self.budget
        return payload

    def write(self, directory: Path) -> Path:
        """Write ``<run_id>.manifest.json`` beside the artifact (FR-029a)."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.run_id}.manifest.json"
        path.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n")
        return path


REQUIRED_KEYS = (
    "manifest_version",
    "run_id",
    "schema_version",
    "seed",
    "config",
    "code_revision",
    "input_hashes",
    "models",
    "environment_overrides",
    "started_at",
    "completed_at",
    "records_generated",
    "records_written",
    "discards",
    "retry_counts",
    "resumed_count",
    "segments",
    "duplicate_count",
    "composition_requested",
    "composition_assigned",
    "composition_achieved",
    "coherence_score_distribution",
    "output_filename",
    "output_sha256",
)


def validate_manifest(payload: dict[str, Any]) -> list[str]:
    """Every problem with a manifest; empty when valid (FR-026, FR-026b, FR-028)."""
    problems: list[str] = []

    for key in REQUIRED_KEYS:
        if key not in payload:
            problems.append(f"missing required element: {key}")
    if problems:
        return problems

    revision = payload["code_revision"]
    for key in ("commit", "dirty"):
        if key not in revision:
            problems.append(f"code_revision.{key} is missing")

    permitted = {reason.value for reason in DiscardReason}
    discards = payload["discards"]
    total_discarded = 0
    for entry in discards:
        reason = entry.get("reason")
        if reason not in permitted:
            problems.append(
                f"discard reason {reason!r} is outside the closed set; "
                f"the reconciliation would be a sum over free text (FR-026b)"
            )
        count = entry.get("count", 0)
        if not isinstance(count, int) or count < 0:
            problems.append(f"discard count for {reason!r} is not a non-negative integer")
        else:
            total_discarded += count

    generated = payload["records_generated"]
    written = payload["records_written"]
    if generated - total_discarded != written:
        # A manifest whose fields are all present but whose accounting does not balance is not
        # valid; presence checking alone would pass exactly the manifests worth catching.
        problems.append(
            f"counts do not reconcile: {generated} generated - {total_discarded} discarded "
            f"= {generated - total_discarded}, but {written} were written (FR-026)"
        )

    if not payload["segments"]:
        problems.append("segments is empty; every run produced at least one")

    return problems


def validate_manifest_file(path: Path) -> list[str]:
    """Validate a manifest on disk, including its binding to the artifact beside it (FR-025b)."""
    path = Path(path)
    if not path.exists():
        return [f"manifest not found: {path}"]
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        return [f"manifest is not valid JSON: {error}"]

    problems = validate_manifest(payload)
    if problems:
        return problems

    artifact = path.parent / payload["output_filename"]
    if artifact.exists():
        from hashlib import sha256

        digest = sha256(artifact.read_bytes()).hexdigest()
        if digest != payload["output_sha256"]:
            problems.append(
                f"checksum mismatch: {artifact.name} hashes to {digest[:12]}… but the manifest "
                f"records {payload['output_sha256'][:12]}… (FR-025b)"
            )
    return problems


def score_histogram(scores: list[float], *, bucket: float = 0.05) -> dict[str, int]:
    """Counts in fixed buckets, plus summary statistics (FR-038, SC-009).

    Fixed buckets are the point: a free choice would make every run's distribution incomparable
    with every other, which defeats what the requirement is for.
    """
    histogram: dict[str, int] = {}
    for score in scores:
        index = min(int(score / bucket), int(1 / bucket) - 1)
        low = index * bucket
        histogram[f"{low:.2f}-{low + bucket:.2f}"] = (
            histogram.get(f"{low:.2f}-{low + bucket:.2f}", 0) + 1
        )
    summary = {"count": len(scores)}
    if scores:
        ordered = sorted(scores)
        summary |= {
            "min": ordered[0],
            "max": ordered[-1],
            "mean": sum(ordered) / len(ordered),
            "median": ordered[len(ordered) // 2],
        }
    return {**dict(sorted(histogram.items())), **{f"_{k}": v for k, v in summary.items()}}
