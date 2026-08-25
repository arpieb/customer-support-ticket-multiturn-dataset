"""Progress reporting (FR-012).

The requirement asks that progress be *observable* during a long run. Records reaching the
staging file satisfies that literally; an operator watching a slow model cannot tell a running
job from a hung one, which is what this is for.
"""

import io

import pytest

from ticket_dataset_generator.run.progress import Progress, ProgressReporter, render


def _progress(**overrides) -> Progress:
    base = {
        "written": 40,
        "generated": 44,
        "target": 200,
        "discarded": 4,
        "elapsed_seconds": 120.0,
    }
    return Progress(**{**base, **overrides})


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- what a line says -------------------------------------------------------------------------


def test_a_line_carries_position_rate_and_estimate() -> None:
    line = render(_progress())
    assert "40/200 records" in line
    assert "(20%)" in line
    assert "2m00s" in line
    assert "/min" in line
    assert "eta" in line


def test_discards_are_surfaced_live() -> None:
    # A run quietly discarding most of what it generates is exactly what an operator would want
    # to interrupt rather than wait out.
    assert "4 discarded" in render(_progress())
    assert "discarded" not in render(_progress(discarded=0))


def test_no_estimate_is_offered_from_too_few_records() -> None:
    # A confident wrong number is worse than no number.
    assert _progress(written=1, elapsed_seconds=10).eta_seconds is None
    assert _progress(written=5, elapsed_seconds=10).eta_seconds is not None


def test_the_estimate_falls_as_the_run_proceeds() -> None:
    early = _progress(written=10, elapsed_seconds=60).eta_seconds
    late = _progress(written=180, elapsed_seconds=1080).eta_seconds
    assert early > late


def test_a_finished_run_has_no_time_remaining() -> None:
    assert _progress(written=200, elapsed_seconds=600).eta_seconds == 0.0


# --- terminals get one rewritten line ----------------------------------------------------------


def test_a_terminal_rewrites_a_single_line() -> None:
    buffer = io.StringIO()
    clock = FakeClock()
    reporter = ProgressReporter(stream=buffer, force_tty=True, clock=clock, interval_seconds=1.0)
    for written in range(1, 6):
        clock.now += 1.0
        reporter.update(_progress(written=written))
    output = buffer.getvalue()
    assert output.count("\r") == 5
    assert output.count("\n") == 0  # nothing scrolls while the run is in flight


def test_a_terminal_is_throttled_by_time() -> None:
    buffer = io.StringIO()
    clock = FakeClock()
    reporter = ProgressReporter(stream=buffer, force_tty=True, clock=clock, interval_seconds=1.0)
    for written in range(1, 51):
        clock.now += 0.1
        reporter.update(_progress(written=written))
    # Fifty updates over five seconds at one per second.
    assert 4 <= buffer.getvalue().count("\r") <= 6


# --- logs get whole lines, bounded in number ---------------------------------------------------


def test_a_log_gets_whole_lines_not_carriage_returns() -> None:
    buffer = io.StringIO()
    reporter = ProgressReporter(stream=buffer, force_tty=False, target=200)
    for written in range(1, 201):
        reporter.update(_progress(written=written))
    output = buffer.getvalue()
    assert "\r" not in output
    assert output.count("\n") > 1


@pytest.mark.parametrize("target", [12, 200, 100_000])
def test_a_log_gets_a_bounded_number_of_lines_whatever_the_size(target: int) -> None:
    # A fixed record step gives a short run nothing and a release-scale run thousands of lines.
    buffer = io.StringIO()
    reporter = ProgressReporter(stream=buffer, force_tty=False, target=target)
    for written in range(1, target + 1):
        reporter.update(_progress(written=written, target=target))
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    assert 1 <= len(lines) <= ProgressReporter.LOG_LINES + 1, len(lines)


def test_a_short_run_still_reports_something() -> None:
    # The case that slipped through: a 12-record run against a step of 25 emitted nothing.
    buffer = io.StringIO()
    reporter = ProgressReporter(stream=buffer, force_tty=False, target=12)
    for written in range(1, 13):
        reporter.update(_progress(written=written, target=12))
    assert buffer.getvalue().strip()


def test_closing_emits_a_final_line_even_when_throttled() -> None:
    buffer = io.StringIO()
    reporter = ProgressReporter(stream=buffer, force_tty=False, every_records=10_000)
    reporter.update(_progress(written=3))
    assert buffer.getvalue() == ""
    reporter.close(_progress(written=3))
    assert "3/200 records" in buffer.getvalue()


def test_closing_a_terminal_line_leaves_the_cursor_on_its_own_row() -> None:
    buffer = io.StringIO()
    reporter = ProgressReporter(stream=buffer, force_tty=True, interval_seconds=0.0)
    reporter.update(_progress())
    reporter.close()
    assert buffer.getvalue().endswith("\n")


def test_closing_without_a_snapshot_is_harmless() -> None:
    buffer = io.StringIO()
    ProgressReporter(stream=buffer, force_tty=False).close()
    assert buffer.getvalue() == ""
