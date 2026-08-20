"""Progress reporting for a long run (FR-012).

FR-012 asks that progress be *observable* during a run. Records reaching the staging file
incrementally satisfies that literally — you can tail the file — but not usefully: an operator
watching a terminal while a slow self-hosted model works through a corpus cannot tell a running
job from a hung one, which is the question progress reporting exists to answer.

Two rendering modes, because the two audiences want opposite things:

* **A terminal** gets one line rewritten in place, so a long run does not scroll away everything
  else. Throttled by time, not by record, so a fast run does not spend its budget on writes.
* **A pipe or a CI log** gets periodic complete lines, because carriage returns produce unreadable
  logs and a file cannot be watched in place.

Everything goes to **stderr**. stdout carries the machine-readable report and nothing else, so a
piped invocation is never corrupted by progress lines (contracts/cli.md).
"""

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True, slots=True)
class Progress:
    """What is worth telling an operator mid-run."""

    written: int
    generated: int
    target: int
    discarded: int
    elapsed_seconds: float

    @property
    def fraction(self) -> float:
        return self.written / self.target if self.target else 0.0

    @property
    def records_per_minute(self) -> float:
        return (self.written / self.elapsed_seconds * 60) if self.elapsed_seconds > 0 else 0.0

    @property
    def eta_seconds(self) -> float | None:
        """Seconds remaining at the current rate, or ``None`` when it cannot be estimated.

        Deliberately absent rather than wrong for the first records: an estimate drawn from one
        completion is noise, and a confident wrong number is worse than no number.
        """
        if self.written < 3 or self.elapsed_seconds <= 0:
            return None
        remaining = self.target - self.written
        if remaining <= 0:
            return 0.0
        return remaining * (self.elapsed_seconds / self.written)


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def render(progress: Progress) -> str:
    """One line describing where the run has got to."""
    parts = [
        f"{progress.written}/{progress.target} records",
        f"({progress.fraction:.0%})",
        _duration(progress.elapsed_seconds),
    ]
    if progress.records_per_minute:
        parts.append(f"{progress.records_per_minute:.1f}/min")
    eta = progress.eta_seconds
    if eta is not None and eta > 0:
        parts.append(f"eta {_duration(eta)}")
    if progress.discarded:
        # Surfaced live, because a run quietly discarding most of what it generates is exactly
        # what an operator would want to interrupt rather than wait out.
        parts.append(f"{progress.discarded} discarded")
    return "  ".join(parts)


class ProgressReporter:
    """Throttled progress on stderr, adapted to whether it is a terminal."""

    #: Roughly how many progress lines a non-terminal run should produce, whatever its size. A
    #: fixed record step gives a 12-record run nothing and a 100,000-record run four thousand
    #: lines; a fraction of the target gives both something readable.
    LOG_LINES = 20

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        interval_seconds: float = 0.25,
        target: int | None = None,
        every_records: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        force_tty: bool | None = None,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._interval = interval_seconds
        if every_records is not None:
            self._every = max(1, every_records)
        elif target:
            self._every = max(1, target // self.LOG_LINES)
        else:
            self._every = 25
        self._clock = clock
        self._tty = self._stream.isatty() if force_tty is None else force_tty
        self._last_emitted = 0.0
        self._last_written = 0
        self._line_open = False

    def _should_emit(self, progress: Progress) -> bool:
        if self._tty:
            return self._clock() - self._last_emitted >= self._interval
        # A log wants a bounded number of lines, not one per record.
        return progress.written - self._last_written >= self._every

    def update(self, progress: Progress, *, final: bool = False) -> None:
        if not final and not self._should_emit(progress):
            return
        self._last_emitted = self._clock()
        self._last_written = progress.written
        line = render(progress)
        if self._tty and not final:
            self._stream.write(f"\r\033[K  {line}")
            self._line_open = True
        else:
            if self._line_open:
                # Close the rewritten line before anything else is printed under it.
                self._stream.write("\r\033[K")
                self._line_open = False
            self._stream.write(f"  {line}\n")
        self._stream.flush()

    def close(self, progress: Progress | None = None) -> None:
        """Emit a closing line and leave the cursor somewhere sane.

        A final line is emitted even when the throttle would have skipped it, so a short run in a
        log still reports where it got to rather than silently producing nothing.
        """
        if progress is not None:
            self.update(progress, final=True)
        elif self._line_open:
            self._stream.write("\n")
            self._stream.flush()
        self._line_open = False
