"""A token bucket bounding the run's own request rate (FR-012e).

Distinct from the SDK's retry-on-429: that reacts to throttling after it happens, while this
stops a run throttling itself into failure in the first place. Shared across both model roles,
because the provider counts them together.
"""

import asyncio
import time
from collections.abc import Callable


class RateLimiter:
    """Bounds requests per minute across every caller sharing the instance."""

    def __init__(
        self,
        requests_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        if requests_per_minute < 1:
            raise ValueError("requests_per_minute must be at least 1")
        self._interval = 60.0 / requests_per_minute
        self._clock = clock
        self._sleep = sleep or asyncio.sleep
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        """Wait until this caller's turn, then return."""
        while True:
            async with self._lock:
                now = self._clock()
                if now >= self._next_allowed:
                    self._next_allowed = max(now, self._next_allowed) + self._interval
                    return
                wait = self._next_allowed - now
            # Sleeping outside the lock so waiting callers do not serialize on it.
            await self._sleep(wait)
