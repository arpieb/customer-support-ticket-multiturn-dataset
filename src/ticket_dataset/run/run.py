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
from dataclasses import dataclass, field
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
from ticket_dataset.privacy.canaries import FLOOR_CANARIES
from ticket_dataset.privacy.detectors.datafog_detector import DataFogDetector
from ticket_dataset.privacy.exceptions_store import ExceptionStore, fingerprint
from ticket_dataset.privacy.quarantine import Quarantine
from ticket_dataset.privacy.registry import DetectorError, DetectorRegistry, Finding, ScanReport
from ticket_dataset.run.enums import ADVISORY_CATEGORIES, BLOCKING_FLOOR, DiscardReason, RunOutcome
from ticket_dataset.run.ids import new_run_id, record_id
from ticket_dataset.run.writer import OrderedWriter, claim_destination, publish
from ticket_dataset.schema.record import TicketRecord
from ticket_dataset.schema.version import SCHEMA_VERSION

STAGING_ROOT = Path("data/interim")


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

    def __post_init__(self) -> None:
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

    async def execute(self) -> RunResult:
        """Generate the corpus, then publish it only if every threshold held."""
        slots = self.prepare()
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        writer = OrderedWriter(path=self.staging_path)
        writer.open()
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

        try:
            stats = await run_slots(
                slots,
                self._attempt,
                max_concurrency=self.config.max_concurrency,
                max_attempts=self.config.max_attempts_per_slot,
                consecutive_failure_limit=self.config.consecutive_failure_limit,
                on_outcome=on_outcome,
            )
        except RunStopped:
            outcome_state = RunOutcome.STOPPED
            stats = PipelineStats()
        finally:
            writer.close()
            quarantine.close()

        failures = self._threshold_failures(stats)
        if failures and outcome_state is RunOutcome.COMPLETED:
            outcome_state = RunOutcome.FAILED

        artifact: Path | None = None
        if outcome_state is RunOutcome.COMPLETED:
            # The only route to the release path, and it refuses without the gate.
            artifact = publish(
                self.staging_path, self.config.output_path, gate_passed=self.gate_passed
            )

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
            failures=failures,
        )

    def _threshold_failures(self, stats: PipelineStats) -> list[str]:
        """Run-level thresholds, evaluated over the FR-026a denominator.

        A generator emitting identifiers at volume is defective, and filtering around it would
        mask the defect — which is why these fail the run rather than merely being reported
        (FR-009k, FR-021a).
        """
        generated = stats.records_generated
        if generated == 0:
            return []
        failures: list[str] = []
        checks = (
            (
                DiscardReason.PRIVACY_FINDING,
                self.config.privacy.max_discard_rate,
                "privacy",
                "FR-021a",
            ),
            (
                DiscardReason.COHERENCE_BELOW_THRESHOLD,
                self.config.coherence.max_discard_rate,
                "coherence",
                "FR-009k",
            ),
        )
        for reason, limit, label, requirement in checks:
            rate = stats.discards.get(reason, 0) / generated
            if rate > limit:
                failures.append(
                    f"{label} discard rate {rate:.2%} exceeds the configured {limit:.2%} "
                    f"({stats.discards.get(reason, 0)} of {generated} responses, {requirement})"
                )
        return failures


def execute_run(config: GenerationConfig, seed: int, model_client: ModelClient) -> RunResult:
    """Synchronous entry point, for the CLI."""
    return asyncio.run(GenerationRun(config=config, seed=seed, model_client=model_client).execute())
