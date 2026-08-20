"""The offline regex detector (FR-017, FR-024, research R7).

`datafog`'s core install is regex-only: no model downloads, no network, and identical findings
for identical input. Telemetry is disabled explicitly rather than trusted to stay off by default,
because FR-024 is not only about detection lookups — the gate must not be able to transmit the
content it examines.
"""

import os

# Set before the import: a library that reads this at import time would otherwise have already
# decided. FR-024 forbids the gate contacting a network service at all.
os.environ.setdefault("DATAFOG_TELEMETRY", "0")
os.environ["DATAFOG_TELEMETRY"] = "0"

import datafog  # noqa: E402

from ticket_dataset.privacy.registry import Detector, Match  # noqa: E402
from ticket_dataset.run.enums import PIICategory  # noqa: E402

#: The engine names its types slightly differently from the contract's enumeration. Mapping here
#: rather than renaming the enum keeps the contract independent of one library's vocabulary,
#: which is the point of the detector interface (FR-017).
_TYPE_MAP: dict[str, PIICategory] = {
    "EMAIL": PIICategory.EMAIL,
    "PHONE": PIICategory.PHONE,
    "CREDIT_CARD": PIICategory.CREDIT_CARD,
    "SSN": PIICategory.US_SSN,
    "IP_ADDRESS": PIICategory.IP_ADDRESS,
    # ZIP / ZIP_CODE and DATE are deliberately unmapped: both fire on ordinary support content —
    # an order number reads as a ZIP, and every record carries legitimate timestamps — and a
    # detector that fires on nearly every record trains maintainers to ignore the report
    # (research R8, FR-018b).
}


class DataFogDetector(Detector):
    """Wraps `datafog`'s regex engine behind the project's detector interface."""

    name = "datafog-regex"

    @property
    def categories(self) -> frozenset[PIICategory]:
        """What this detector *claims*. Coverage is established by probe, not by this (FR-018a)."""
        return frozenset(_TYPE_MAP.values())

    def scan(self, text: str) -> list[Match]:
        result = datafog.scan(text)
        matches: list[Match] = []
        for entity in result.entities:
            category = _TYPE_MAP.get(entity.type)
            if category is None:
                continue
            matches.append(Match(category=category, value=entity.text, detector=self.name))
        return matches
