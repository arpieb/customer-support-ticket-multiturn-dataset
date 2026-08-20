"""A detector that fails must fail closed, under its own reason (FR-017a)."""

import pytest

from ticket_dataset.privacy.registry import DetectorError, DetectorRegistry, Match
from ticket_dataset.run.enums import BLOCKING_FLOOR, DiscardReason


class ExplodingDetector:
    name = "exploding"

    @property
    def categories(self):
        return frozenset(BLOCKING_FLOOR)

    def scan(self, text: str):
        raise RuntimeError("regex engine fell over")


class FlakyDetector:
    """Fails only on particular content, as a real malfunction would."""

    name = "flaky"

    def __init__(self, trigger: str) -> None:
        self.trigger = trigger

    @property
    def categories(self):
        return frozenset(BLOCKING_FLOOR)

    def scan(self, text: str):
        if self.trigger in text:
            raise ValueError("cannot handle this input")
        return [Match(category=next(iter(BLOCKING_FLOOR)), value="x", detector=self.name)]


def test_a_raising_detector_raises_rather_than_returning_clean() -> None:
    # Returning an empty finding list would record a malfunction as a clean result, which is the
    # one outcome that must be impossible.
    registry = DetectorRegistry()
    registry.register(ExplodingDetector())
    with pytest.raises(DetectorError, match="exploding failed"):
        registry.scan_text("anything", record_id="r", field_name="turns[0].content")


def test_the_failure_names_the_detector() -> None:
    registry = DetectorRegistry()
    registry.register(FlakyDetector(trigger="bad input"))
    registry.scan_text("fine input", record_id="r", field_name="turns[0].content")
    with pytest.raises(DetectorError, match="flaky"):
        registry.scan_text("bad input here", record_id="r", field_name="turns[0].content")


def test_detector_error_is_a_distinct_discard_reason() -> None:
    # A malfunction is neither a clean result nor a real identifier, so it must not be recorded
    # as either (FR-017a, FR-026b).
    assert DiscardReason.DETECTOR_ERROR is not DiscardReason.PRIVACY_FINDING
    assert DiscardReason.DETECTOR_ERROR.value == "detector_error"
