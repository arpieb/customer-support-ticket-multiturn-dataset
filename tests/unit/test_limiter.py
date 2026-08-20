"""The run must bound its own request rate (FR-012e)."""

import asyncio

import pytest

from ticket_dataset.model.limiter import RateLimiter


class FakeClock:
    """A clock that only advances when someone sleeps, so the test is fast and exact."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


async def test_requests_are_spaced_by_the_configured_interval() -> None:
    clock = FakeClock()
    limiter = RateLimiter(60, clock=clock, sleep=clock.sleep)  # one per second
    stamps = []
    for _ in range(5):
        await limiter.acquire()
        stamps.append(clock.now)
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert all(abs(gap - 1.0) < 1e-9 for gap in gaps), stamps


async def test_the_bound_holds_under_concurrency() -> None:
    # The property that matters: it is the *run* that is bounded, not each caller.
    clock = FakeClock()
    limiter = RateLimiter(120, clock=clock, sleep=clock.sleep)  # one per half-second
    await asyncio.gather(*(limiter.acquire() for _ in range(10)))
    assert clock.now >= 4.5


async def test_both_model_roles_share_one_budget() -> None:
    # Generation and judging draw on the same provider quota, so they share a limiter.
    clock = FakeClock()
    limiter = RateLimiter(60, clock=clock, sleep=clock.sleep)
    await asyncio.gather(*(limiter.acquire() for _ in range(4)))
    assert clock.now >= 3.0


def test_a_nonsense_rate_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        RateLimiter(0)
