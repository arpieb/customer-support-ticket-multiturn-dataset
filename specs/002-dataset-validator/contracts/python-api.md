# Contract: Programmatic API

**Stability**: This is the primary contract (FR-029). Later generation features call it directly rather
than shelling out, so it is the surface that must stay stable. The CLI is a wrapper over exactly these
calls and adds no behavior of its own (FR-032).

All names below are re-exported from `ticket_dataset`.

---

## Schema

```python
SCHEMA_VERSION: str                      # e.g. "1.0.0" — the one version this build validates (FR-002b)

class TicketRecord(BaseModel): ...       # see data-model.md
class ConversationTurn(BaseModel): ...
class TicketMetadata(BaseModel): ...

def export_json_schema() -> dict         # the committed JSON Schema export (R1)
def is_supported_version(v: str) -> bool # exactly-one-version rule (FR-002b, FR-010)
```

## Reading artifacts

```python
def read_jsonl(path: Path) -> Iterator[ParsedLine]
```

Streams line-by-line; never loads the whole file (FR-012). Each `ParsedLine` carries the line number and
either a parsed object or a parse error — a malformed line yields an error entry and iteration continues
(FR-008, spec Edge Cases).

## Gates

Every gate takes a path and returns a `Report`. Each is independently callable, which is what makes the
spec's user stories independently testable.

```python
def validate_records(path: Path, *, schema_version: str = SCHEMA_VERSION) -> Report   # US1, FR-007–FR-012
def check_invariants(path: Path) -> Report                                            # US3, FR-018–FR-021
def scan_privacy(path: Path, *, registry: DetectorRegistry | None = None,
                 exceptions: Path | None = None) -> Report                            # US2, FR-013–FR-017
def validate_manifest(path: Path) -> Report                                           # US4, FR-024
def run_gate(path: Path, *, manifest: Path | None = None,
             exceptions: Path | None = None) -> Report                                # FR-026–FR-028
```

`run_gate` runs schema → privacy → invariants, plus manifest validation when a manifest is given. It runs
every gate it can even after one fails, so the caller sees the full picture in one pass, and returns a
single consolidated `Report` whose verdict is `fail` if any gate failed (spec Edge Cases, FR-026, FR-028).
An empty artifact is a failure, not a trivial pass (FR-027).

## Privacy detection

```python
class Detector(Protocol):
    name: str
    categories: frozenset[PIICategory]
    def scan(self, text: str) -> Iterable[RawFinding]: ...

class DetectorRegistry:
    def register(self, detector: Detector) -> None
    def covered_categories(self) -> frozenset[PIICategory]
    def assert_floor_covered(self) -> None      # raises if the FR-013d floor is unmet — fails closed
    def scan_text(self, text: str) -> list[RawFinding]

def default_registry() -> DetectorRegistry      # the datafog regex detector
```

**Guarantees**: detectors make no network calls and are deterministic (FR-013c). `default_registry()` sets
`DATAFOG_TELEMETRY=0` before constructing the datafog detector rather than relying on the upstream default.
A registry whose union of categories misses the blocking floor — `EMAIL`, `PHONE`, `CREDIT_CARD`,
`GOVERNMENT_ID` — raises rather than scanning (FR-013d). Categories outside the floor are advisory: they
appear in the report but never fail the gate (FR-013f). `Report.declared_gaps` names the categories the
scan does not cover, so a clean verdict cannot be read as coverage it lacks (FR-013e).

## Approved exceptions

```python
def load_exceptions(path: Path) -> list[PrivacyException]
def fingerprint(category: PIICategory, value: str) -> str    # sha256(category + ":" + normalized)
```

Exceptions are matched by fingerprint in the registry layer after detectors run, so an approval survives a
detector swap (R4). Raw matched values are never stored or returned.

## Manifests

```python
class RunManifest(BaseModel): ...
def capture_code_revision() -> CodeRevision      # git SHA + dirty flag, or a recorded reason (R8)
def hash_input(path: Path) -> str                # sha256 of file contents
def write_manifest(m: RunManifest, path: Path) -> None
```

`RunManifest` validation enforces `input_count - sum(removals) == output_count` (FR-023).

## Reports

```python
class Report(BaseModel):
    verdict: Verdict
    findings: list[Finding]
    # ... see data-model.md

def render_json(r: Report) -> str
def render_text(r: Report) -> str
def exit_status(r: Report) -> int      # 0 on pass, 1 on fail (FR-031)
```

`Report` is the single source for every surface — JSON, text, and exit status all derive from it, so they
cannot disagree (R9, FR-032). Findings never contain the matched PII value.
