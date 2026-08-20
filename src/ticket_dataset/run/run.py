"""Run orchestration: config → slots → generate → judge → validate → ordered write.

This is where the per-record gate order lives: ``structural → privacy → judge → schema → write``.

The scan sits **before the judge** deliberately (FR-016a). Scanning is offline regex and costs
almost nothing next to a model call, so scanning every structurally valid response buys two
things: PII emission is measured across all usable output rather than only the part that survived
the coherence gate — which matters most exactly when the generator is worst — and no judging call
is spent on a record about to be discarded for privacy.

The corpus reaches ``data/release/`` only through :func:`ticket_dataset.run.writer.publish`, which
refuses unless the detector floor was demonstrated for this run.
"""

import asyncio
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.dedup import DuplicateCounter
from ticket_dataset.generation.domain_doc import DomainDocument, load_domain_document
from ticket_dataset.generation.generator import Candidate, StructuralFailure, validate_response
from ticket_dataset.generation.judge import JudgeFailure, meets_threshold, score_response
from ticket_dataset.generation.pipeline import PipelineStats, RunStopped, SlotOutcome, run_slots
from ticket_dataset.generation.prompts import (
    generator_system_prompt,
    generator_user_prompt,
    judge_system_prompt,
    judge_user_prompt,
)
from ticket_dataset.generation.rubric import Rubric, load_rubric
from ticket_dataset.model.client import ModelClient, ModelRefusal, ModelRole, ModelUnavailable
from ticket_dataset.model.wire import GeneratedConversation, JudgeVerdict, response_schema
from ticket_dataset.planning.slots import Slot, assign_subdomains, plan_slots
from ticket_dataset.planning.tolerance import attribute as attribute_drift
from ticket_dataset.planning.tolerance import check as tolerance_check
from ticket_dataset.privacy.canaries import FLOOR_CANARIES
from ticket_dataset.privacy.detectors.datafog_detector import DataFogDetector
from ticket_dataset.privacy.exceptions_store import ExceptionStore, fingerprint
from ticket_dataset.privacy.quarantine import Quarantine
from ticket_dataset.privacy.registry import DetectorError, DetectorRegistry, Finding, ScanReport
from ticket_dataset.run.budget import BudgetTracker
from ticket_dataset.run.checkpoint import Checkpoint, input_fingerprints, select_resumable
from ticket_dataset.run.enums import ADVISORY_CATEGORIES, BLOCKING_FLOOR, DiscardReason, RunOutcome
from ticket_dataset.run.ids import new_run_id, record_id
from ticket_dataset.run.manifest import ModelRecord, RunManifest, Segment, score_histogram
from ticket_dataset.run.report import RunReport
from ticket_dataset.run.retention import clean_after_success
from ticket_dataset.run.revision import capture_revision, environment_overrides, hash_inputs
from ticket_dataset.run.thresholds import discard_rate_breaches, should_stop_early
from ticket_dataset.run.writer import OrderedWriter, claim_destination, publish
from ticket_dataset.schema.record import TicketRecord
from ticket_dataset.schema.version import SCHEMA_VERSION

STAGING_ROOT = Path("data/interim")

#: Chunk size for hashing a corpus. Reading a 100,000-record artifact into memory to checksum it
#: would undo the streaming the writer does (FR-012).
_HASH_CHUNK = 1 << 20


def _digest_of(path: Path) -> str:
    """``sha256`` of a file, read in chunks rather than whole."""
    from hashlib import sha256

    digest = sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class RunResult:
    run_id: str
    outcome: RunOutcome
    staging_path: Path
    records_written: int
    stats: PipelineStats
    duplicates: int = 0
    slots_planned: int = 0
    scores: list[float] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    records_scanned: int = 0
    fields_scanned: int = 0
    detectors_run: tuple[str, ...] = ()
    quarantine_path: Path | None = None
    quarantine_count: int = 0
    artifact_path: Path | None = None
    manifest_path: Path | None = None
    report_path: Path | None = None
    report: RunReport | None = None
    resumed_count: int = 0
    failures: list[str] = field(default_factory=list)

    def scan_report(self) -> ScanReport:
        """What the scan examined and found, for the run report (FR-019, FR-023, FR-023a)."""
        return ScanReport(
            findings=self.findings,
            records_examined=self.records_scanned,
            fields_examined=self.fields_scanned,
            detectors_run=self.detectors_run,
            covered_types=tuple(sorted(c.value for c in BLOCKING_FLOOR | ADVISORY_CATEGORIES)),
        )


@dataclass(slots=True)
class GenerationRun:
    """One generation run against a configuration, a seed, and a model client."""

    config: GenerationConfig
    seed: int
    model_client: ModelClient
    run_id: str = ""
    document: DomainDocument | None = None
    rubric: Rubric | None = None
    registry: DetectorRegistry | None = None
    #: Set by :meth:`prepare` once the floor is demonstrated. Publishing refuses without it.
    gate_passed: bool = False
    findings: list[Finding] = field(default_factory=list)
    records_scanned: int = 0
    fields_scanned: int = 0
    resumed_from: Checkpoint | None = None
    fallbacks_used: dict[str, int] = field(default_factory=dict)
    assigned_composition: dict = field(default_factory=dict)
    requested_run_id: str | None = None
    budget: BudgetTracker | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        # A run identifier supplied by the caller names a specific run to resume; one generated
        # here is a fresh run instance (FR-003a). Keeping the distinction matters: a resume that
        # searched for its own freshly minted identifier would never find anything.
        self.requested_run_id = self.run_id or None
        self.run_id = self.run_id or new_run_id()

    @property
    def staging_dir(self) -> Path:
        return STAGING_ROOT / self.run_id

    @property
    def staging_path(self) -> Path:
        return self.staging_dir / "records.partial.jsonl"

    def prepare(self) -> list[Slot]:
        """Validate inputs, prove the floor, and plan every slot — before any model call.

        The floor probe runs here rather than at first use so an inadequate detector set costs
        nothing: the run refuses before generating rather than after producing output no one can
        vouch for (FR-018, FR-018a).
        """
        claim_destination(self.config.output_path)
        self.document = load_domain_document(self.config.prompt_document)
        self.rubric = load_rubric(self.config.rubric)

        if self.registry is None:
            self.registry = DetectorRegistry()
            self.registry.register(DataFogDetector())
        store = ExceptionStore.load(self.config.privacy.exceptions)
        self.registry.approvals = store.fingerprints
        self.registry.fingerprinter = fingerprint
        self.registry.assert_floor_covered(FLOOR_CANARIES)
        self.gate_passed = True

        slots = plan_slots(self.config, self.seed)
        return assign_subdomains(slots, self.document.subdomains, self.seed)

    async def _attempt(self, slot: Slot, attempt: int) -> SlotOutcome:
        """One attempt at one slot: generate, structurally validate, judge, validate schema."""
        outcome = SlotOutcome(position=slot.position)
        assert self.document is not None and self.rubric is not None

        try:
            response = await self.model_client.complete_json(
                role=ModelRole.GENERATOR,
                system=generator_system_prompt(self.document),
                user=generator_user_prompt(slot, self.config),
                schema=response_schema(GeneratedConversation),
            )
        except ModelRefusal as refusal:
            # A safety decline is a distinct outcome from malformed output: conflating them
            # would hide a prompt domain that trips a classifier behind a flaky-provider
            # statistic (FR-009m).
            outcome.discard_reason = DiscardReason.MODEL_REFUSAL
            outcome.detail = str(refusal)
            return outcome
        except ModelUnavailable as unavailable:
            outcome.discard_reason = DiscardReason.ATTEMPTS_EXHAUSTED
            outcome.detail = str(unavailable)
            return outcome

        outcome.retries = response.retries
        outcome.model_id = response.model_id

        checked = validate_response(response.text, slot, stop_reason=response.stop_reason)
        if isinstance(checked, StructuralFailure):
            outcome.discard_reason = checked.reason
            outcome.detail = checked.detail
            return outcome

        # The privacy scan runs *before* the judge (FR-016a): it is offline regex and costs
        # almost nothing next to a model call, so scanning here measures PII emission across all
        # usable output and spends no judging call on a record about to be discarded.
        if not self._passes_privacy(checked, slot, outcome):
            return outcome

        judged = await self._judge(checked, slot, outcome)
        if judged is None:
            return outcome

        record = self._assemble(slot, checked, judged.value, judged.rubric_id, outcome)
        if record is None:
            return outcome

        outcome.record = record
        return outcome

    def _passes_privacy(self, candidate: Candidate, slot: Slot, outcome: SlotOutcome) -> bool:
        """Scan the candidate's model-derived text; record findings either way (FR-016, FR-021)."""
        assert self.registry is not None
        probe = {
            "record_id": record_id(self.run_id, slot.position),
            "scenario": candidate.scenario,
            "turns": candidate.turns,
        }
        try:
            findings = self.registry.scan_record(probe)
        except DetectorError as error:
            # Fail closed: a malfunction is neither a clean result nor a real identifier, so it
            # is neither passed through nor recorded as a finding (FR-017a).
            outcome.discard_reason = DiscardReason.DETECTOR_ERROR
            outcome.detail = str(error)
            return False

        self.records_scanned += 1
        self.fields_scanned += len(candidate.turns) + 1
        # Findings are reported whatever their status, so the report never looks cleaner than the
        # scan was (FR-019, FR-021c, FR-022).
        self.findings.extend(findings)

        blocking = [finding for finding in findings if finding.blocks]
        if blocking:
            outcome.discard_reason = DiscardReason.PRIVACY_FINDING
            outcome.detail = ", ".join(
                f"{finding.category.value} in {finding.field} ({finding.masked})"
                for finding in blocking
            )
            outcome.blocked_record = probe
            outcome.blocking_findings = blocking
            return False
        return True

    async def _judge(self, candidate: Candidate, slot: Slot, outcome: SlotOutcome):
        assert self.rubric is not None
        try:
            verdict = await self.model_client.complete_json(
                role=ModelRole.JUDGE,
                system=judge_system_prompt(self.rubric),
                user=judge_user_prompt(candidate.turns, slot),
                schema=response_schema(JudgeVerdict),
            )
        except (ModelRefusal, ModelUnavailable) as error:
            # A record that cannot be scored is discarded, never admitted unjudged (FR-009l).
            outcome.discard_reason = DiscardReason.UNJUDGEABLE
            outcome.detail = str(error)
            return None

        outcome.judge_model_id = verdict.model_id
        scored = score_response(verdict.text, self.rubric)
        if isinstance(scored, JudgeFailure):
            outcome.discard_reason = scored.reason
            outcome.detail = scored.detail
            return None
        if not meets_threshold(scored, self.config.coherence.threshold):
            outcome.discard_reason = DiscardReason.COHERENCE_BELOW_THRESHOLD
            outcome.detail = f"scored {scored.value:.3f} below {self.config.coherence.threshold}"
            return None
        return scored

    def _assemble(
        self,
        slot: Slot,
        candidate: Candidate,
        score: float,
        rubric_id: str,
        outcome: SlotOutcome,
    ) -> dict[str, Any] | None:
        """Build the record and validate it against the contract before it is written (FR-007)."""
        assert self.document is not None
        payload = {
            "schema_version": SCHEMA_VERSION,
            "record_id": record_id(self.run_id, slot.position),
            "run_id": self.run_id,
            "record_index": slot.position,
            "source_id": self.document.source_id,
            "subdomain": slot.subdomain,
            "scenario": candidate.scenario,
            "metadata": slot.metadata(),
            "turns": [
                {"index": index, "role": turn["role"], "content": turn["content"]}
                for index, turn in enumerate(candidate.turns)
            ],
            "quality": {"coherence_score": score, "rubric_id": rubric_id},
            "generation": {
                "model_id": outcome.model_id,
                "judge_model_id": outcome.judge_model_id,
            },
        }
        try:
            record = TicketRecord.model_validate(payload)
        except Exception as error:  # noqa: BLE001 - any contract failure is one discard reason
            outcome.discard_reason = DiscardReason.SCHEMA_INVALID
            outcome.detail = str(error).splitlines()[0]
            return None
        return record.model_dump(mode="json")

    def fingerprints(self) -> dict[str, str]:
        """What must match for a checkpoint to be applicable (FR-015e, FR-015h)."""
        return input_fingerprints(self.config, self.seed, SCHEMA_VERSION)

    async def resume(self) -> RunResult:
        """Continue a checkpointed run (FR-015b–FR-015i).

        Resuming truncates the staging file to its recorded length and continues from the next
        position. Because writes are in strict position order the file is always a prefix of the
        corpus, so no record is regenerated and — record identifiers being derived from
        ``(run_id, position)`` — none can be reissued.
        """
        checkpoint = select_resumable(STAGING_ROOT, self.fingerprints(), self.requested_run_id)
        checkpoint.assert_applicable(self.fingerprints())
        self.run_id = checkpoint.run_id
        self.resumed_from = checkpoint
        return await self.execute()

    async def execute(self) -> RunResult:
        """Generate the corpus, then publish it only if every threshold held."""
        slots = self.prepare()
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.budget = BudgetTracker(budget=self.config.budget)

        resumed = self.resumed_from
        start_position = resumed.next_position if resumed else 0
        writer = OrderedWriter(path=self.staging_path)
        writer.open(
            start_position=start_position,
            truncate_to=resumed.bytes_written if resumed else None,
        )
        if resumed:
            # Continue the tallies rather than restarting them, so one manifest describes the
            # whole corpus and its accounting reconciles across segments (FR-015c).
            writer.records_written = resumed.records_written
            slots = [slot for slot in slots if slot.position >= start_position]
        quarantine = Quarantine(path=self.staging_dir / "quarantine.jsonl")
        duplicates = DuplicateCounter()
        scores: list[float] = []
        outcome_state = RunOutcome.COMPLETED

        def on_outcome(outcome: SlotOutcome) -> None:
            if outcome.blocked_record is not None:
                # Retained outside the release path so a reviewer has something to adjudicate
                # when the masked rendering alone is insufficient (FR-021b).
                quarantine.add(outcome.blocked_record, outcome.blocking_findings)
            if outcome.record is not None:
                served = outcome.record["generation"]["model_id"]
                if served and served != self.config.models.generator.model_id:
                    # A record rescued by a fallback stays in the corpus and names its actual
                    # producer; the manifest reports how many each model served (FR-009n).
                    self.fallbacks_used[served] = self.fallbacks_used.get(served, 0) + 1
                duplicates.observe(
                    [
                        {"role": turn["role"], "content": turn["content"]}
                        for turn in outcome.record["turns"]
                    ]
                )
                scores.append(outcome.record["quality"]["coherence_score"])
                writer.submit(outcome.position, outcome.record)
            else:
                writer.skip(outcome.position)

        self.assigned_composition = self._assigned_composition(slots)

        stats = PipelineStats()
        if resumed:
            stats.responses = resumed.records_generated
            stats.discards.update(
                {DiscardReason(reason): count for reason, count in resumed.discards.items()}
            )
            stats.retries.update(resumed.retry_counts)

        def checkpoint_now() -> None:
            writer.flush()
            Checkpoint(
                run_id=self.run_id,
                # Just after the last record actually written, so an interrupted run retries the
                # slots its interruption killed rather than losing them (FR-009c, FR-015b).
                next_position=writer.resume_position,
                bytes_written=writer.bytes_written,
                input_fingerprints=self.fingerprints(),
                discards={reason.value: count for reason, count in stats.discards.items()},
                retry_counts=dict(stats.retries),
                duplicate_count=duplicates.duplicates,
                records_generated=stats.records_generated,
                records_written=writer.records_written,
                resumes=(resumed.resumes + 1) if resumed else 0,
                segments=list(resumed.segments) if resumed else [],
            ).write(self.staging_dir)

        try:
            stats = await run_slots(
                slots,
                self._attempt,
                max_concurrency=self.config.max_concurrency,
                max_attempts=self.config.max_attempts_per_slot,
                consecutive_failure_limit=self.config.consecutive_failure_limit,
                on_outcome=on_outcome,
                stats=stats,
                on_progress=self._progress_hook(checkpoint_now, stats),
            )
        except RunStopped:
            outcome_state = RunOutcome.STOPPED
        finally:
            writer.close()
            quarantine.close()
            checkpoint_now()

        completed_at = datetime.now(UTC)
        achieved = self._achieved_composition(writer.path)

        # The composition tolerance is only meaningful once every slot has been attempted, so a
        # stopped run is not judged on it (FR-037a).
        failures = self._threshold_failures(
            stats, achieved if outcome_state is RunOutcome.COMPLETED else None
        )
        if failures and outcome_state is RunOutcome.COMPLETED:
            outcome_state = RunOutcome.FAILED

        artifact: Path | None = None
        if outcome_state is RunOutcome.COMPLETED:
            # The only route to the release path, and it refuses without the gate.
            artifact = publish(
                self.staging_path, self.config.output_path, gate_passed=self.gate_passed
            )

        manifest = self._build_manifest(
            stats=stats,
            writer=writer,
            duplicates=duplicates.duplicates,
            scores=scores,
            achieved=achieved,
            completed_at=completed_at,
            artifact=artifact,
        )
        # Written for every run, failed ones included: a corpus produced without a manifest is
        # permanently unauditable, and a failed run's accounting is the point (FR-025).
        manifest_dir = artifact.parent if artifact else self.staging_dir
        manifest_path = manifest.write(manifest_dir)

        report = RunReport(
            run_id=self.run_id,
            schema_version=SCHEMA_VERSION,
            outcome=outcome_state,
            records_generated=stats.records_generated,
            records_written=writer.records_written,
            discards={reason.value: count for reason, count in stats.discards.items()},
            retry_counts=dict(stats.retries),
            duplicate_count=duplicates.duplicates,
            coherence_score_distribution=score_histogram(scores),
            composition_requested=self.config.effective_composition.as_dict(),
            composition_assigned=self.assigned_composition,
            composition_achieved=achieved,
            composition_drift_pp=attribute_drift(
                self.config.effective_composition.as_dict(), self.assigned_composition, achieved
            ),
            scan=self._scan_report(),
            quarantine_path=str(quarantine.path) if quarantine.count else None,
            quarantine_count=quarantine.count,
            artifact_path=str(artifact) if artifact else None,
            manifest_path=str(manifest_path),
            failures=failures,
            resumed_count=manifest.resumed_count,
            budget=self.budget.as_dict() if self.budget else None,
        )
        report_path = report.write(manifest_dir, published=artifact is not None)

        if outcome_state is RunOutcome.COMPLETED:
            # The published artifact supersedes the staging copy and the checkpoint; the report
            # and any quarantine survive, because quarantine cannot be reconstructed (FR-015i).
            clean_after_success(self.staging_dir, self.staging_path)
        else:
            # Carry this run's segment into the checkpoint, so a later resume can assemble one
            # manifest describing the whole corpus rather than only its final leg (FR-015c).
            Checkpoint(
                run_id=self.run_id,
                next_position=writer.resume_position,
                bytes_written=writer.bytes_written,
                input_fingerprints=self.fingerprints(),
                discards={reason.value: count for reason, count in stats.discards.items()},
                retry_counts=dict(stats.retries),
                duplicate_count=duplicates.duplicates,
                records_generated=stats.records_generated,
                records_written=writer.records_written,
                resumes=manifest.resumed_count,
                segments=[asdict(segment) for segment in manifest.segments],
            ).write(self.staging_dir)

        return RunResult(
            run_id=self.run_id,
            outcome=outcome_state,
            staging_path=self.staging_path,
            records_written=writer.records_written,
            stats=stats,
            duplicates=duplicates.duplicates,
            slots_planned=len(slots),
            scores=scores,
            findings=self.findings,
            records_scanned=self.records_scanned,
            fields_scanned=self.fields_scanned,
            detectors_run=self.registry.names if self.registry else (),
            quarantine_path=quarantine.path if quarantine.count else None,
            quarantine_count=quarantine.count,
            artifact_path=artifact,
            manifest_path=manifest_path,
            report_path=report_path,
            report=report,
            resumed_count=manifest.resumed_count,
            failures=failures,
        )

    def _scan_report(self) -> ScanReport:
        return ScanReport(
            findings=self.findings,
            records_examined=self.records_scanned,
            fields_examined=self.fields_scanned,
            detectors_run=self.registry.names if self.registry else (),
            covered_types=tuple(sorted(c.value for c in BLOCKING_FLOOR | ADVISORY_CATEGORIES)),
        )

    def _assigned_composition(self, slots: list[Slot]) -> dict[str, dict[str, float]]:
        """What apportionment planned, before any discard (FR-031a).

        Requested versus assigned exposes apportionment error; assigned versus achieved exposes
        drift caused by discards. Without the middle term a tolerance failure has no attributable
        cause.
        """
        if not slots:
            return {}
        return {
            dimension: {
                member: count / len(slots)
                for member, count in sorted(
                    Counter(getattr(slot, dimension) for slot in slots).items()
                )
            }
            for dimension in ("category", "priority", "channel", "resolution_status")
        }

    def _achieved_composition(self, path: Path) -> dict[str, dict[str, float]]:
        """What the written corpus actually contains.

        Streamed line by line and counted as it goes. Reading the corpus into a list would make
        peak memory scale with corpus size — the exact property FR-012 forbids, and one that only
        shows up at the scale where it matters.
        """
        import json as _json

        path = Path(path)
        if not path.exists():
            return {}
        dimensions = ("category", "priority", "channel", "resolution_status")
        counters: dict[str, Counter[str]] = {dimension: Counter() for dimension in dimensions}
        total = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                metadata = _json.loads(line)["metadata"]
                total += 1
                for dimension in dimensions:
                    counters[dimension][metadata[dimension]] += 1
        if total == 0:
            return {}
        return {
            dimension: {
                member: count / total for member, count in sorted(counters[dimension].items())
            }
            for dimension in dimensions
        }

    def _build_manifest(
        self,
        *,
        stats: PipelineStats,
        writer: OrderedWriter,
        duplicates: int,
        scores: list[float],
        achieved: dict[str, dict[str, float]],
        completed_at: datetime,
        artifact: Path | None,
    ) -> RunManifest:
        revision = capture_revision()
        corpus = artifact if artifact else self.staging_path
        digest = _digest_of(corpus) if corpus.exists() else ""

        segment = Segment(
            code_revision=revision.as_dict(),
            started_at=self.started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            first_record_index=self.resumed_from.next_position if self.resumed_from else 0,
            last_record_index=max(writer.records_written - 1, 0),
        )
        previous = (
            [Segment(**entry) for entry in self.resumed_from.segments] if self.resumed_from else []
        )

        def model_record(spec) -> ModelRecord:
            return ModelRecord(
                model_id=spec.model_id,
                effort=spec.effort,
                max_tokens=spec.max_tokens,
                thinking=spec.thinking,
                sampling_seed=spec.sampling_seed,
            )

        return RunManifest(
            run_id=self.run_id,
            schema_version=SCHEMA_VERSION,
            seed=self.seed,
            config=self.config.model_dump(mode="json"),
            code_revision=revision,
            input_hashes=hash_inputs(
                {
                    "prompt_document": self.config.prompt_document,
                    "rubric": self.config.rubric,
                }
            ),
            models={
                "generator": model_record(self.config.models.generator),
                "judge": model_record(self.config.models.judge),
            },
            environment_overrides=environment_overrides(),
            fallbacks_used=self.fallbacks_used,
            started_at=self.started_at,
            completed_at=completed_at,
            records_generated=stats.records_generated,
            records_written=writer.records_written,
            discards={reason.value: count for reason, count in stats.discards.items()},
            retry_counts=dict(stats.retries),
            resumed_count=(self.resumed_from.resumes + 1) if self.resumed_from else 0,
            segments=[*previous, segment],
            duplicate_count=duplicates,
            composition_requested=self.config.effective_composition.as_dict(),
            composition_assigned=self.assigned_composition,
            composition_achieved=achieved,
            coherence_score_distribution=score_histogram(scores),
            output_filename=corpus.name,
            output_sha256=digest,
            budget=self.budget.as_dict() if self.budget else None,
        )

    def _progress_hook(self, checkpoint_now, stats: PipelineStats):
        """Checkpoint periodically, and stop early on a sustained threshold breach or budget.

        Both stops preserve completed work: the run checkpoints and reports ``stopped`` rather
        than failing, so resuming stays the operator's decision (FR-012f, FR-037).
        """
        written_at_last_checkpoint = 0

        def hook() -> str | None:
            nonlocal written_at_last_checkpoint
            if self.budget is not None:
                self.budget.record_call()
                exhausted = self.budget.exhausted()
                if exhausted is not None:
                    checkpoint_now()
                    return exhausted

            if stats.responses - written_at_last_checkpoint >= self.config.checkpoint_interval:
                written_at_last_checkpoint = stats.responses
                checkpoint_now()

            breaches = should_stop_early(self.config, stats.discards, stats.records_generated)
            if breaches:
                checkpoint_now()
                return "; ".join(breach.describe() for breach in breaches)
            return None

        return hook

    def _threshold_failures(
        self, stats: PipelineStats, achieved: dict[str, dict[str, float]] | None = None
    ) -> list[str]:
        """Run-level thresholds, evaluated over the FR-026a denominator.

        A generator emitting identifiers at volume is defective, and filtering around it would
        mask the defect — which is why these fail the run rather than merely being reported
        (FR-009k, FR-021a).

        The composition tolerance is evaluated here and only here, at completion. A partial corpus
        has no achieved composition — apportionment is only satisfied once every slot has been
        attempted — so an early check would measure incompleteness rather than drift (FR-037a).
        """
        generated = stats.records_generated
        failures: list[str] = []
        if generated:
            failures.extend(
                breach.describe()
                for breach in discard_rate_breaches(self.config, stats.discards, generated)
            )
        if achieved:
            failures.extend(
                breach.describe()
                for breach in tolerance_check(
                    self.config.effective_composition.as_dict(),
                    achieved,
                    self.config.composition_tolerance_pp,
                )
            )
        return failures


def execute_run(config: GenerationConfig, seed: int, model_client: ModelClient) -> RunResult:
    """Synchronous entry point, for the CLI."""
    return asyncio.run(GenerationRun(config=config, seed=seed, model_client=model_client).execute())
