"""Prompt assembly and the concurrent pipeline.

Both are exercised end to end by the integration tests; these cover the properties that are hard
to see from there — prompt-prefix stability, which decides whether a run pays for the domain
document once or 200,000 times, and the pipeline's retry and stop behaviour in isolation.
"""

import asyncio
from pathlib import Path

import pytest

from tests.helpers import make_slot
from ticket_dataset.config.models import GenerationConfig
from ticket_dataset.generation.domain_doc import load_domain_document
from ticket_dataset.generation.pipeline import (
    PipelineStats,
    RunStopped,
    SlotOutcome,
    run_slots,
)
from ticket_dataset.generation.prompts import (
    generator_system_prompt,
    generator_user_prompt,
    judge_system_prompt,
    judge_user_prompt,
)
from ticket_dataset.generation.rubric import load_rubric
from ticket_dataset.model.wire import GeneratedConversation, JudgeVerdict, response_schema
from ticket_dataset.run.enums import DiscardReason


@pytest.fixture(scope="module")
def document():
    return load_domain_document(Path("prompts/domain.md"))


@pytest.fixture(scope="module")
def rubric():
    return load_rubric(Path("prompts/coherence-rubric.md"))


def _config() -> GenerationConfig:
    return GenerationConfig(record_count=60, output_path=Path("data/release/x.jsonl"))


# --- prompt assembly ------------------------------------------------------------------------


def test_the_system_prefix_is_byte_stable(document) -> None:
    # A run makes two calls per record. A prefix that varied would pay for the domain document on
    # every one of them instead of caching it (contracts/model-io.md).
    assert generator_system_prompt(document) == generator_system_prompt(document)


def test_the_system_prefix_carries_no_per_slot_content(document) -> None:
    prompt = generator_system_prompt(document)
    for volatile in ("turn_count=", "subdomain=", "category="):
        assert volatile not in prompt


def test_the_user_message_carries_the_assignment(document) -> None:
    slot = make_slot(turn_count=7, subdomain="billing-duplicate-charge")
    prompt = generator_user_prompt(slot, _config())
    assert "turn_count=7" in prompt
    assert "subdomain=billing-duplicate-charge" in prompt
    assert "category=billing" in prompt
    assert "language=en" in prompt


def test_the_turn_count_is_written_in_a_parseable_form(document) -> None:
    # The structural check rejects any other length, so the model must be told unambiguously.
    prompt = generator_user_prompt(make_slot(turn_count=11), _config())
    assert "turn_count=11\n" in prompt


def test_the_judge_prompt_carries_the_rubric_and_the_candidate(rubric) -> None:
    system = judge_system_prompt(rubric)
    assert "single_issue" in system
    user = judge_user_prompt([{"role": "customer", "content": "charged twice"}], make_slot())
    assert "charged twice" in user
    assert "category=billing" in user


def test_the_judge_is_told_not_to_return_an_overall_score(rubric) -> None:
    # It would be ignored — the score is derived from the criteria (FR-009p).
    assert "Do not return an overall score" in judge_system_prompt(rubric)


def test_response_schemas_are_cached() -> None:
    # Rebuilt on every attempt, this is 200,000 regenerations of a constant at release scale.
    assert response_schema(GeneratedConversation) is response_schema(GeneratedConversation)
    assert response_schema(JudgeVerdict) is not response_schema(GeneratedConversation)


# --- the pipeline ---------------------------------------------------------------------------


async def test_every_slot_is_attempted() -> None:
    slots = [make_slot(position=i) for i in range(20)]
    seen: list[int] = []

    async def attempt(slot, attempt_index):
        seen.append(slot.position)
        return SlotOutcome(position=slot.position, record={"record_index": slot.position})

    await run_slots(slots, attempt, max_concurrency=4, max_attempts=3, consecutive_failure_limit=50)
    assert sorted(seen) == list(range(20))


async def test_concurrency_is_bounded() -> None:
    slots = [make_slot(position=i) for i in range(30)]
    in_flight = 0
    peak = 0

    async def attempt(slot, attempt_index):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.001)
        in_flight -= 1
        return SlotOutcome(position=slot.position, record={"record_index": slot.position})

    await run_slots(slots, attempt, max_concurrency=5, max_attempts=1, consecutive_failure_limit=50)
    assert peak <= 5


async def test_a_slot_is_retried_up_to_the_configured_attempts() -> None:
    attempts: list[int] = []

    async def attempt(slot, attempt_index):
        attempts.append(attempt_index)
        return SlotOutcome(position=slot.position, discard_reason=DiscardReason.STRUCTURAL_INVALID)

    stats = await run_slots(
        [make_slot()], attempt, max_concurrency=1, max_attempts=3, consecutive_failure_limit=50
    )
    assert attempts == [0, 1, 2]
    # Every response is counted once per attempt — the denominator every rate divides by.
    assert stats.records_generated == 3


async def test_a_slot_that_succeeds_stops_retrying() -> None:
    calls = {"n": 0}

    async def attempt(slot, attempt_index):
        calls["n"] += 1
        if attempt_index == 0:
            return SlotOutcome(position=slot.position, discard_reason=DiscardReason.MODEL_REFUSAL)
        return SlotOutcome(position=slot.position, record={"record_index": slot.position})

    await run_slots(
        [make_slot()], attempt, max_concurrency=1, max_attempts=5, consecutive_failure_limit=50
    )
    assert calls["n"] == 2


async def test_sustained_failure_stops_the_run() -> None:
    async def attempt(slot, attempt_index):
        return SlotOutcome(position=slot.position, discard_reason=DiscardReason.MODEL_REFUSAL)

    with pytest.raises(RunStopped, match="consecutive"):
        await run_slots(
            [make_slot(position=i) for i in range(100)],
            attempt,
            max_concurrency=1,
            max_attempts=1,
            consecutive_failure_limit=3,
        )


async def test_a_progress_hook_can_stop_the_run() -> None:
    # How a budget ceiling and a mid-run threshold breach both stop: preserve what exists rather
    # than spending the rest of the corpus finding out (FR-012f, FR-037).
    async def attempt(slot, attempt_index):
        return SlotOutcome(position=slot.position, record={"record_index": slot.position})

    calls = {"n": 0}

    def progress():
        calls["n"] += 1
        return "budget exhausted" if calls["n"] >= 5 else None

    with pytest.raises(RunStopped, match="budget exhausted"):
        await run_slots(
            [make_slot(position=i) for i in range(50)],
            attempt,
            max_concurrency=1,
            max_attempts=1,
            consecutive_failure_limit=100,
            on_progress=progress,
        )


async def test_retries_are_counted_separately_from_discards() -> None:
    # A degraded provider and a defective generator are different facts (FR-012d).
    async def attempt(slot, attempt_index):
        return SlotOutcome(position=slot.position, record={"record_index": 0}, retries=2)

    stats = await run_slots(
        [make_slot()], attempt, max_concurrency=1, max_attempts=1, consecutive_failure_limit=50
    )
    assert stats.retries["transport"] == 2
    assert stats.discards == {}


async def test_existing_stats_are_continued_not_reset() -> None:
    # What lets a resumed run reconcile across segments (FR-015c).
    async def attempt(slot, attempt_index):
        return SlotOutcome(position=slot.position, record={"record_index": slot.position})

    carried = PipelineStats()
    carried.responses = 40
    stats = await run_slots(
        [make_slot()],
        attempt,
        max_concurrency=1,
        max_attempts=1,
        consecutive_failure_limit=50,
        stats=carried,
    )
    assert stats.records_generated == 41


# --- provider capability, checked before generating (research R1, FR-009b) -------------------


def test_a_model_that_cannot_be_constrained_refuses_the_run(tmp_path) -> None:
    """A model that cannot honour a JSON schema would make every record a structural discard.

    Discovering that after paying for a corpus is the wrong moment, so it is checked beside the
    detector floor — before the first call rather than after the last one.
    """
    from ticket_dataset.errors import ConfigError
    from ticket_dataset.model.fake import FakeModelClient
    from ticket_dataset.run.run import GenerationRun

    class PickyClient(FakeModelClient):
        @staticmethod
        def supports_structured_output(model_id: str) -> bool:
            return "good" in model_id

    config = GenerationConfig(
        record_count=60,
        output_path=tmp_path / "release" / "corpus.jsonl",
        models={"generator": {"model_id": "vendor/bad"}, "judge": {"model_id": "vendor/good"}},
    )
    with pytest.raises(ConfigError, match="cannot be constrained"):
        GenerationRun(config=config, seed=1, model_client=PickyClient()).prepare()


def test_a_client_that_does_not_advertise_capability_is_not_second_guessed(tmp_path) -> None:
    # The fake has no opinion about schemas; the check must not invent one for it.
    from ticket_dataset.model.fake import FakeModelClient
    from ticket_dataset.run.run import GenerationRun

    config = GenerationConfig(record_count=60, output_path=tmp_path / "release" / "corpus.jsonl")
    slots = GenerationRun(config=config, seed=1, model_client=FakeModelClient()).prepare()
    assert len(slots) == 60
