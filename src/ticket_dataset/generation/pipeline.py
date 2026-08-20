"""Bounded-concurrency generation with slot-level retry (FR-012a, FR-009o, FR-012d).

Three kinds of failure are kept apart on purpose, because they mean different things:

* **transport** — the SDK retries these; the count is reported so a degraded provider is visible
  rather than merely slow (FR-012d)
* **slot-level** — a refusal, malformed output, or an unscorable record; retried under the
  single attempts knob and, when exhausted, discarded under a named reason (FR-009o)
* **sustained** — many consecutive slots failing means the run stops and checkpoints rather than
  burning the remaining corpus emitting discards (spec Edge Cases)

Summing them into one number would hide exactly the distinction the accounting exists to make.
"""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ticket_dataset.planning.slots import Slot
from ticket_dataset.run.enums import DiscardReason


class RunStopped(Exception):
    """The circuit breaker tripped: too many consecutive slots failed (spec Edge Cases)."""


@dataclass(slots=True)
class SlotOutcome:
    """What one slot produced, after however many attempts it took."""

    position: int
    record: dict | None = None
    discard_reason: DiscardReason | None = None
    detail: str = ""
    attempts: int = 0
    retries: int = 0
    model_id: str = ""
    judge_model_id: str = ""
    #: Set when a privacy finding blocked the record, so the run can quarantine it for review
    #: (FR-021b). Never written to the corpus.
    blocked_record: dict | None = None
    blocking_findings: list = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.record is not None


@dataclass(slots=True)
class PipelineStats:
    responses: int = 0
    discards: Counter[DiscardReason] = field(default_factory=Counter)
    retries: Counter[str] = field(default_factory=Counter)
    consecutive_failures: int = 0

    @property
    def records_generated(self) -> int:
        """Every response received from the generating model, counted once per attempt.

        The one denominator every discard-rate threshold divides by, so a threshold cannot be
        computed two ways (FR-026a).
        """
        return self.responses


async def run_slots(
    slots: list[Slot],
    attempt_slot: Callable[[Slot, int], Awaitable[SlotOutcome]],
    *,
    max_concurrency: int,
    max_attempts: int,
    consecutive_failure_limit: int,
    on_outcome: Callable[[SlotOutcome], None] | None = None,
    on_attempt: Callable[[SlotOutcome], None] | None = None,
    stats: PipelineStats | None = None,
    on_progress: Callable[[], str | None] | None = None,
) -> PipelineStats:
    """Process every slot with bounded concurrency, retrying at the slot level.

    ``attempt_slot`` performs one attempt and returns its outcome. Retry policy lives here so a
    single knob governs every retryable per-record failure — a decline, an unparseable response,
    an unscorable record alike — while transport retries stay the SDK's business (FR-009o).
    """
    stats = stats or PipelineStats()
    stop = asyncio.Event()
    stop_reason: list[str] = []
    lock = asyncio.Lock()

    async def work(slot: Slot) -> None:
        if stop.is_set():
            return
        outcome = SlotOutcome(position=slot.position)
        for attempt in range(max_attempts):
            outcome = await attempt_slot(slot, attempt)
            outcome.attempts = attempt + 1
            async with lock:
                stats.responses += 1
                if outcome.retries:
                    stats.retries["transport"] += outcome.retries
            if outcome.accepted:
                break
            async with lock:
                if outcome.discard_reason is not None:
                    stats.discards[outcome.discard_reason] += 1
                    # Deliberately adjacent to the count. Anything that must happen once per
                    # discarded attempt belongs here, not in `on_outcome` — that fires once per
                    # slot with the *final* attempt, so a side effect placed there silently
                    # skips every attempt a retry replaced.
                    if on_attempt is not None:
                        on_attempt(outcome)
            if stop.is_set():
                return

        async with lock:
            if outcome.accepted:
                stats.consecutive_failures = 0
            else:
                if outcome.discard_reason is None:
                    outcome.discard_reason = DiscardReason.ATTEMPTS_EXHAUSTED
                    stats.discards[DiscardReason.ATTEMPTS_EXHAUSTED] += 1
                    if on_attempt is not None:
                        on_attempt(outcome)
                stats.consecutive_failures += 1
                if stats.consecutive_failures >= consecutive_failure_limit:
                    # Stop and checkpoint rather than spend the rest of the corpus finding
                    # out the provider is still down.
                    stop.set()
            if on_outcome is not None:
                on_outcome(outcome)
            if on_progress is not None:
                reason = on_progress()
                if reason is not None:
                    # A budget ceiling or a sustained threshold breach: stop and keep what
                    # has been produced, rather than spending the rest of the corpus finding
                    # out (FR-012f, FR-037).
                    stop_reason.append(reason)
                    stop.set()

    # A fixed pool of workers pulling from a shared iterator, rather than one task per slot.
    # Spawning 100,000 coroutines would hold 100,000 frames whatever the semaphore allowed, which
    # is the same memory-scales-with-corpus problem the reorder buffer exists to avoid (FR-012).
    pending = iter(slots)
    iterator_lock = asyncio.Lock()

    async def worker() -> None:
        while not stop.is_set():
            async with iterator_lock:
                slot = next(pending, None)
            if slot is None:
                return
            await work(slot)

    await asyncio.gather(*(worker() for _ in range(min(max_concurrency, len(slots) or 1))))
    if stop.is_set():
        raise RunStopped(
            stop_reason[0]
            if stop_reason
            else (
                f"{stats.consecutive_failures} consecutive slots failed; stopping and "
                "checkpointing rather than continuing (spec Edge Cases)"
            )
        )
    return stats
