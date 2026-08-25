"""Declared ceilings on time and model calls (FR-012f).

Exhausting a budget **stops and checkpoints** rather than failing: no completed work is lost, and
resuming stays the operator's decision. An unattended run at release scale otherwise has no
ceiling on time or cost.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ticket_dataset_generator.config.models import Budget


@dataclass(slots=True)
class BudgetTracker:
    """Tracks spend against a declared budget."""

    budget: Budget
    clock: Callable[[], float] = time.monotonic
    started_at: float = field(default=0.0)
    model_calls: int = 0

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    def record_call(self, count: int = 1) -> None:
        self.model_calls += count

    @property
    def elapsed_seconds(self) -> float:
        return self.clock() - self.started_at

    def exhausted(self) -> str | None:
        """Which ceiling was reached, or ``None`` while there is room left."""
        if not self.budget.is_declared:
            return None
        if (
            self.budget.max_model_calls is not None
            and self.model_calls >= self.budget.max_model_calls
        ):
            return (
                f"model call ceiling reached: {self.model_calls} of "
                f"{self.budget.max_model_calls} declared"
            )
        if self.budget.max_runtime is not None:
            limit = self.budget.max_runtime.total_seconds()
            if self.elapsed_seconds >= limit:
                return (
                    f"runtime ceiling reached: {self.elapsed_seconds:.0f}s of {limit:.0f}s declared"
                )
        return None

    def as_dict(self) -> dict:
        """What the manifest records: the declared budget and the actual spend (FR-012f)."""
        return {
            "max_runtime_seconds": (
                int(self.budget.max_runtime.total_seconds())
                if self.budget.max_runtime is not None
                else None
            ),
            "max_model_calls": self.budget.max_model_calls,
            "spent_seconds": round(self.elapsed_seconds, 3),
            "spent_model_calls": self.model_calls,
            "exhausted": self.exhausted() is not None,
        }
