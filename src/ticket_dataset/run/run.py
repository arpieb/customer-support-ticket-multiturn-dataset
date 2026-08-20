"""Run orchestration: config → slots → generate → judge → validate → ordered write.

This is where the per-record gate order lives. In this phase it is
``structural → judge → schema → write``; the privacy scan is inserted **before the judge** when
the gate lands (FR-016a), and the move into the release path arrives with it. Until then output
stops at the staging file, so there is no code path by which unscanned output can reach
``data/release/`` — the constitution's blocking-scan requirement enforced structurally rather
than remembered.
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
from ticket_dataset.run.enums import DiscardReason, RunOutcome
from ticket_dataset.run.ids import new_run_id, record_id
from ticket_dataset.run.writer import OrderedWriter, claim_destination
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


@dataclass(slots=True)
class GenerationRun:
    """One generation run against a configuration, a seed, and a model client."""

    config: GenerationConfig
    seed: int
    model_client: ModelClient
    run_id: str = ""
    document: DomainDocument | None = None
    rubric: Rubric | None = None

    def __post_init__(self) -> None:
        self.run_id = self.run_id or new_run_id()

    @property
    def staging_dir(self) -> Path:
        return STAGING_ROOT / self.run_id

    @property
    def staging_path(self) -> Path:
        return self.staging_dir / "records.partial.jsonl"

    def prepare(self) -> list[Slot]:
        """Validate inputs and plan every slot before a single model call is made."""
        claim_destination(self.config.output_path)
        self.document = load_domain_document(self.config.prompt_document)
        self.rubric = load_rubric(self.config.rubric)
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

        judged = await self._judge(checked, slot, outcome)
        if judged is None:
            return outcome

        record = self._assemble(slot, checked, judged.value, judged.rubric_id, outcome)
        if record is None:
            return outcome

        outcome.record = record
        return outcome

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
        """Generate the corpus into staging. Nothing here reaches the release path."""
        slots = self.prepare()
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        writer = OrderedWriter(path=self.staging_path)
        writer.open()
        duplicates = DuplicateCounter()
        scores: list[float] = []
        outcome_state = RunOutcome.COMPLETED

        def on_outcome(outcome: SlotOutcome) -> None:
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

        return RunResult(
            run_id=self.run_id,
            outcome=outcome_state,
            staging_path=self.staging_path,
            records_written=writer.records_written,
            stats=stats,
            duplicates=duplicates.duplicates,
            slots_planned=len(slots),
            scores=scores,
        )


def execute_run(config: GenerationConfig, seed: int, model_client: ModelClient) -> RunResult:
    """Synchronous entry point, for the CLI."""
    return asyncio.run(GenerationRun(config=config, seed=seed, model_client=model_client).execute())
