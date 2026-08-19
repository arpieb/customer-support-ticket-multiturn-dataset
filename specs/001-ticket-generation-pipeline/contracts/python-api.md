# Contract: Python API

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-08-19

The programmatic surface is the stable contract; the CLI is a wrapper over it. Everything re-exported from
`ticket_dataset/__init__.py` is public and covered by contract tests. Anything else is internal and may
change without a version bump.

---

## Record contract

```python
from ticket_dataset import (
    SCHEMA_VERSION,       # "1.0.0"
    TicketRecord,         # Pydantic v2 model — authoritative (Principle I)
    ConversationTurn,
    TicketMetadata,
    RecordQuality,
    GenerationInfo,
    Role, Category, Priority, Channel, ResolutionStatus,
    export_json_schema,   # () -> dict — must equal contracts/record.schema.json
)
```

`export_json_schema()` is what makes the committed contract a fact rather than documentation: CI compares
its output to `contracts/record.schema.json` and fails on drift.

---

## Configuration

```python
from ticket_dataset import GenerationConfig, Composition, load_config

config = load_config(Path("configs/smoke.toml"))   # raises ConfigError, naming the problem
```

`load_config` performs **total** validation (FR-011): shape, ranges, threshold bounds, turn range,
composition satisfiability, and output-path availability. It never partially accepts a configuration.
`ConfigError` carries a list of specific problems, not a single message — an operator fixing a config
should see all of them at once.

```python
composition.apportion(record_count: int) -> list[TicketMetadata]
composition.check(achieved: Composition, tolerance_pp: float) -> list[Breach]
```

Largest-remainder apportionment across slots (research R3). Raises `UnsatisfiableCompositionError` naming
the dimension and the reason when proportions do not sum, name an unknown member, cannot round to whole
records at the requested corpus size, or when the requested tolerance is below `100 / record_count` and is
therefore unachievable by arithmetic alone (FR-032, FR-031b) — the error states both the minimum corpus size
and the minimum tolerance that would work.

`check` returns one `Breach` per **member** exceeding the tolerance, carrying dimension, member, requested,
achieved, and drift. An empty list is the pass condition. Per-member rather than aggregate, because someone
slicing the corpus by one category cares about that category's drift and an average would let a badly-served
member hide behind well-served ones (FR-031).

---

## Generation

```python
from ticket_dataset import GenerationRun, RunResult

run = GenerationRun(config=config, seed=42, model_client=client)
result: RunResult = await run.execute()          # or run.resume()
```

`RunResult` exposes `manifest`, `report`, `artifact_path`, and `verdict`. `execute()`:

1. asserts the detector floor and refuses before generating if it is not covered (FR-018);
2. refuses if the output path exists (FR-014);
3. apportions composition and derives every slot's choices from `(seed, position, attempt)` (FR-012b);
4. runs bounded-concurrency generation → structural validation → judging → schema validation → privacy
   scan, writing accepted records in slot order to the staging path (FR-012, FR-012c);
5. checkpoints periodically (FR-015a);
6. writes the manifest and report, and moves the artifact into the release path **only** on success.

`resume()` reads the checkpoint, refuses when the input fingerprints differ (FR-015e), truncates the
staging file to its recorded length, and continues — without regenerating written records or reissuing a
record ID (FR-015b).

**Seeded choice derivation** is public because SC-013 must be testable directly:

```python
slot_random(seed: int, position: int, attempt: int) -> random.Random
```

The subdomain is drawn with that generator from the prompt document's declared list (FR-008d), so two runs
at any concurrency assign the same subdomain to the same position. The scenario the model elaborates within
it is model output and is not reproducible — the record carries both, and only the first is comparable.

---

## Model access

```python
from ticket_dataset import ModelClient, ModelRole, ModelResponse, AnthropicModelClient
```

The protocol in [model-io.md](./model-io.md). `AnthropicModelClient` is the only module that imports
`anthropic`; every other component depends on the protocol, so the pipeline is fully testable offline.

---

## Privacy

```python
from ticket_dataset import (
    Detector,             # Protocol: name, categories, scan(text) -> list[Match]
    DetectorRegistry,     # register / assert_floor_covered / scan_record
    PIICategory,
    PrivacyFinding,
    ExceptionStore,       # fingerprint-based; never stores raw values
)
```

`DetectorRegistry.assert_floor_covered()` raises `FloorNotCoveredError` when the registered detectors do
not cover `EMAIL`, `PHONE`, `CREDIT_CARD`, `GOVERNMENT_ID`. It is called at run start, so an inadequate
detector set fails **before** generation rather than after (FR-018).

`scan_record` returns findings carrying record ID, field, category, detector, and a masked rendering —
never the matched value (FR-020, FR-020a) — and reports the fields it examined so a clean result is
distinguishable from a scan that examined nothing (FR-023).

```python
mask(category: PIICategory, value: str) -> str
```

Deterministic and irreversible, preserving at most the non-identifying remainder: the domain for an email,
the issuer range for a payment card, shape and length otherwise. Public because it is what a reviewer
adjudicates from, so its behavior is a contract rather than a formatting detail.

Records discarded for a privacy finding are appended to the run's quarantine artifact (FR-021b), whose path
and count appear in the report. `ExceptionStore.approve_from_quarantine(path, record_id, field, category,
reason)` fingerprints the value in place, so approving never requires the reviewer to handle it.

Adding a detector requires only registering an object satisfying `Detector`; the record contract, the
finding format, and the gate are untouched (FR-017).

---

## Manifest and report

```python
from ticket_dataset import RunManifest, RunReport, Verdict, DiscardReason, validate_manifest

problems: list[str] = validate_manifest(manifest_dict)   # empty when valid
```

`validate_manifest` checks contract conformance **and** the reconciliation rule
`records_generated - sum(discards) == records_written`, naming any missing element or discrepancy (FR-026,
FR-028). Both checks are required: a manifest whose fields are all present but whose accounting does not
balance is invalid, and presence checking alone would pass exactly the manifests worth catching. `records_generated` counts every generator response, once per attempt (FR-026a) — the same
denominator every discard-rate threshold divides by, so a threshold cannot be computed two ways.

`RunReport` is the single object from which the JSON output, the human rendering, and the CLI exit status
are all derived (FR-035, FR-036) — disagreement between them is structurally impossible rather than a thing
to test for.

---

## Errors

| Exception | Raised when |
|-----------|-------------|
| `ConfigError` | Configuration is invalid or internally contradictory (FR-011) |
| `UnsatisfiableCompositionError` | A composition request cannot be satisfied (FR-032) |
| `FloorNotCoveredError` | Registered detectors do not cover the blocking floor (FR-018) |
| `OutputPathExistsError` | The destination artifact already exists (FR-014) |
| `CheckpointMismatchError` | Resume attempted with changed config, seed, prompt document, or rubric (FR-015e) |
| `CheckpointCorruptError` | The checkpoint is unreadable; the operator must restart deliberately (spec Edge Cases) |
| `UnobservableEnvironmentError` | An environment setting could alter model routing but cannot be observed and recorded, so the run refuses rather than proceed unrecorded (FR-008c) |
| `PromptDocumentError` | The domain prompt document declares no usable subdomain list (FR-008d) |

All inherit from `TicketDatasetError`. None of them carry a matched PII value.

---

## Stability

The public surface follows the record contract's version. Removing a name or narrowing a signature is a
breaking change requiring a MAJOR bump, in the same change as the schema, a migration note, and updated
validation tests (Principle I, Development Workflow).
