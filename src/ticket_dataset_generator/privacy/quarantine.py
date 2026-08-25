"""Records discarded for a privacy finding, retained for review (FR-021b).

Without this, FR-022's approval has no input: the record is discarded and FR-020 withholds the
value, leaving a reviewer asked to judge something no artifact contains. The masked rendering
settles the common cases; quarantine is the fallback for the ones it cannot.

A quarantined record is fabricated content that a pattern detector found identifier-shaped — not
a real identifier — which is why retaining it under intermediate output is compatible with the
constitution's requirement that no real personal data enter ``data/``. It is never committed
(``data/`` is git-ignored), never in the release path, and never dataset output.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ticket_dataset_generator.privacy.registry import Finding


@dataclass(slots=True)
class Quarantine:
    """Append-only store of privacy-discarded records."""

    path: Path
    count: int = 0
    _handle: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def add(self, record: dict, findings: list[Finding]) -> None:
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8")
        payload = {
            "record": record,
            "findings": [
                {
                    **asdict(finding),
                    "category": finding.category.value,
                    "status": finding.status.value,
                }
                for finding in findings
            ],
        }
        self._handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._handle.flush()
        self.count += 1

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def find(self, record_id: str, field_name: str) -> str | None:
        """The matched text for one finding, read back for an approval (FR-022, contracts/cli.md).

        This is the one place a matched value is handled, and it exists so a reviewer never has
        to retype or paste one: the CLI reads it here and fingerprints it in place.
        """
        if not self.path.exists():
            return None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            record = entry["record"]
            if record.get("record_id") != record_id:
                continue
            if field_name == "scenario":
                return record.get("scenario")
            if field_name.startswith("turns["):
                index = int(field_name.split("[")[1].split("]")[0])
                turns = record.get("turns", [])
                if 0 <= index < len(turns):
                    return turns[index]["content"]
        return None
