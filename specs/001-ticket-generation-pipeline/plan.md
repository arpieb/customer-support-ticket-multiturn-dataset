# Implementation Plan: Ticket Generation Pipeline

**Branch**: `bootstrap-speckit` | **Date**: 2026-08-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-ticket-generation-pipeline/spec.md`

## Summary

Ship the product: a pipeline that generates a corpus of multi-turn customer support conversations from an
explicit seed, a single serialized configuration, and a committed domain prompt document — writing JSON
Lines under `data/`, with a run manifest, a blocking offline privacy gate, and a model-as-judge coherence
gate.

The technical approach turns the run into **N ordered slots**. Composition is apportioned across those
slots by the largest-remainder method *before* any model call, and every seeded choice is derived from
`(seed, position, attempt)` rather than a shared stream — so composition is correct by construction and
reproducible regardless of concurrency. Slots are processed by a bounded `asyncio` worker pool behind a
token-bucket rate limiter; completed slots pass through structural validation, judging, schema validation,
and the privacy scan, then flow through a small reorder buffer so records are written in slot order
regardless of completion order. Output streams to a staging file under `data/interim/` and is moved into
`data/release/` atomically only after the run succeeds, which is what makes "an interrupted run leaves
nothing that looks complete" true rather than aspirational. A periodic checkpoint records the staging
file's length and the discard tallies, so a killed run resumes by truncation without regenerating or
reissuing an identifier.

The record contract is a set of Pydantic v2 models exporting a committed JSON Schema. Every model call goes
through one narrow `ModelClient` protocol, so the entire pipeline is testable offline against a fake.

## Technical Context

**Language/Version**: Python 3.14 (per `requires-python = ">=3.14"` in `pyproject.toml`)

**Primary Dependencies**: `anthropic` with the `aiohttp` extra (async model access — research R1),
`pydantic` v2 (record contract, config, manifest, report), `datafog >=4.8,<5` core install, no extras
(offline regex PII engine — research R7), `typer` (CLI). Dev-only: `pytest`, `pytest-asyncio`,
`pytest-cov`, `ruff`.

**Storage**: Files only. JSONL corpora under `data/release/`, staging and checkpoints under
`data/interim/`, JSON manifests and reports beside the artifact, a committed JSON Schema export, committed
prompt and rubric documents, and a committed privacy-exception fingerprint file. No database.

**Testing**: `pytest` with `pytest-asyncio`. Contract tests per public API surface, integration tests over
the full pipeline driven by `FakeModelClient`, unit tests for apportionment, slot derivation, reorder
buffering, and checkpoint truncation. **No test makes a network call** — the `ModelClient` seam exists for
this, and it is also what keeps CI free.

**Target Platform**: Local developer machines (macOS, Linux) and CI. Generation requires network access and
model credentials; the privacy gate is offline and deterministic by construction (FR-024).

**Project Type**: Single Python project — a library with a thin CLI wrapper. The programmatic API is the
stable contract; the CLI carries no logic of its own.

**Performance Goals**: 100,000 records in a single run without exhausting memory or requiring manual
intervention (SC-001). Memory is O(concurrency), not O(corpus): per-slot state, a reorder buffer bounded by
`max_concurrency`, and two digest sets (~3 MB each at 100k). Throughput is provider-bound; concurrency and
request rate are operator-facing knobs (FR-012a, FR-012e).

**Constraints**: Two model calls per record, so a release-scale run is ~200,000 calls before retries — cost
and time scale accordingly (spec Assumptions). Seeded choices must be order-independent (FR-012b). Records
must be written in deterministic order (FR-012c). The privacy gate must never depend on a remote service
(FR-024). Nothing incomplete may appear in the release path (FR-015).

**Scale/Scope**: ~100,000 records per release artifact; conversations of unbounded turn count; 60
functional requirements across four user stories.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

*Source: `.specify/memory/constitution.md` v1.0.0. Mark each gate PASS / FAIL / N/A with a
one-line justification. Any FAIL must either be resolved or recorded in Complexity Tracking.*

| # | Gate | Status | Notes |
|---|------|--------|-------|
| I | **Schema-First Data Contracts** — is the record schema declared, versioned, and committed before producer/consumer code? Do both sides validate against it? Is any breaking schema change accompanied by a MAJOR bump? | **PASS** | The contract lands as [contracts/record.schema.json](./contracts/record.schema.json) in this planning change, before any generator code (FR-001). `SCHEMA_VERSION = "1.0.0"`; every record declares it (FR-002). The generator validates every record before writing and discards non-conforming output (FR-007), and a CI check fails on any drift between the Pydantic model's export and the committed file, so a breaking change cannot land without the contract changing in the same commit. |
| II | **Reproducible Generation** — does every run take an explicit seed and a single serialized config, and write a manifest capturing seed, config, code revision, and input hashes? Is all non-determinism captured? | **PASS** | Seed and config are required, never implicit (FR-008; CLI has no default seed). The manifest records seed, verbatim config, code revision with an explicit dirty flag, and the sha256 of every input including the prompt document and rubric (FR-025, FR-008a, FR-009g). Non-determinism is captured rather than claimed away: both model identities and parameters (FR-009j, FR-027), a null sampling seed stated plainly, per-record `generation.model_id` so a refusal fallback cannot make the manifest lie, and any environment setting capable of changing model selection or routing recorded as a non-deterministic input (FR-008c) — credentials excepted, since they are an access mechanism that never influences output and are never written to an artifact (FR-008). The constitution's own text anticipates this — "where exact replay is impossible, audited" — and FR-010 scopes the guarantee to structure and composition, which *are* exactly reproducible via `(seed, position, attempt)` derivation (SC-013). |
| III | **Provenance & Traceability** — does every record carry record ID, run ID, source/template, and schema version? Do derived sets preserve upstream IDs? Are filtered-out records accounted for by count and reason? | **PASS** | All four fields are required by the schema, plus `record_index` and `scenario` so records are distinguishable and stratifiable (FR-003, FR-008b). Record IDs are UUIDv5 over `run_id/record_index`, so a resumed run cannot reissue one (FR-015b). Derived sets are out of scope here (nothing derives from this output within the feature). Every discard carries a closed-set reason and reconciles: `records_generated - discards == records_written`, across a resume (FR-026, FR-015c, SC-005). |
| IV | **Privacy by Construction** — is all identifying content synthetic or verifiably de-identified before reaching `data/`? Is a blocking automated PII scan wired into the pipeline? | **PASS** | Content is fabricated, never derived from real transcripts (spec Assumptions), and no real value is ever placed in a prompt. The scan is the last gate before a record is written, so nothing carrying an unreviewed finding reaches even the staging file, let alone the release path (FR-016, FR-021). It blocks rather than advises, and a discard rate above 0.5% fails the run (FR-021a). The floor is named at the identifier-type level the offline detector genuinely covers — `US_SSN`, not "government identifiers" — and every report enumerates covered types alongside gaps (research R8, FR-018, FR-019), so a clean verdict cannot read as broader coverage than the gate delivers. Findings carry a masked, irreversible rendering rather than the matched value, and exceptions are stored as fingerprints, so neither the report nor the exception file becomes a PII store (FR-020, FR-020a, FR-022). Records discarded for a finding are quarantined under `data/interim/` so a reviewer has something to adjudicate (FR-021b) — fabricated content a detector found identifier-shaped, never committed and never dataset output, which is why retaining it does not admit real personal data to `data/`. |
| V | **Validation Gates Before Release** — do schema validation, PII scan, quality invariants, and sampled human review all gate the release? Do data-transforming modules have contract and edge-case tests? | **PASS** | Four gates run per record — structural invariants (ordering, alternation, non-emptiness, turn count), schema validation, coherence judging, and the privacy scan — and any failure discards the record with an accounted reason (FR-007, FR-009b, FR-009h, FR-021). Run-level thresholds fail the run and keep the artifact out of the release path. Contract and edge-case tests are required for every data-transforming module before it produces a released artifact. Sampled human review is not automatable: this feature enables it with `sample-for-review` and reports the score distribution (SC-009, SC-011), but the judgment stays a human release act. |

**Constraints check**: dependencies managed via `uv` with `uv.lock` updated in the same change — **PASS**,
all four runtime dependencies land in one change. JSONL is the source of truth — **PASS**, the corpus is
JSONL and no alternative export exists. Release-path artifacts separated by directory from scratch work —
**PASS**, and load-bearing: `data/interim/` holds staging and checkpoints, `data/release/` receives an
atomic move only on success. Large artifacts as config + manifest + checksums rather than committed
directly — **PASS**, `data/` is git-ignored and the manifest carries `output_sha256`.

**Post-design re-check (after Phase 1)**: Re-evaluated against [data-model.md](./data-model.md) and
[contracts/](./contracts/), and again after the pre-implementation checklist resolved CHK029 and CHK053.
All five gates still hold. CHK029 exposed a genuine hole rather than a wording problem — FR-022's approval
had no input once FR-021 discarded the record and FR-020 withheld the value — closed by masked findings
plus a quarantine artifact; Gate IV was re-argued around it above rather than assumed. CHK053 fixed the
denominator for every discard-rate threshold (FR-026a), which was previously ambiguous enough that the
tests would have silently encoded whichever reading the implementer picked.

The four remaining conflicts were resolved the same day and are reflected above: credentials are carved out
of FR-008 as an access mechanism, while routing-capable environment settings become recorded provenance
(FR-008c); scenario derivation is two-level, so FR-012b's seeded claim holds for the subdomain while
FR-008a's model elaboration stands (FR-008d) — which adds `subdomain` to the record contract; a declared run
budget makes SC-001 literally satisfiable and gives an unattended release-scale run a ceiling (FR-012f); and
the blocking floor is named at identifier-type level so it stops promising coverage no offline detector
delivers (FR-018, FR-019).

The design added one dependency beyond the
superseded feature's set (`anthropic`), no new persisted format beyond those listed, and no whole-corpus
load. Two design decisions strengthened gates rather than straining them: recording the served model ID per
record closed a hole in Gate II that a refusal fallback would otherwise have opened, and ordering the
privacy scan last in the per-record pipeline made Gate IV's "before reaching `data/`" literal rather than
approximate. Complexity Tracking carries two entries, both indirection that a requirement names explicitly.

## Project Structure

### Documentation (this feature)

```text
specs/001-ticket-generation-pipeline/
├── plan.md              # This file (/speckit-plan command output)
├── spec.md              # Feature specification
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── checklists/
│   └── requirements.md  # Spec quality checklist
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── record.schema.json    # The committed record contract (Principle I)
│   ├── manifest.schema.json  # The run manifest contract
│   ├── model-io.md           # ModelClient protocol, request shapes, wire schemas
│   ├── python-api.md         # Programmatic contract — the stable surface
│   └── cli.md                # Commands, options, exit statuses
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/ticket_dataset/
├── __init__.py               # Public API re-exports — the stable surface
├── schema/
│   ├── record.py             # TicketRecord, ConversationTurn, TicketMetadata, RecordQuality, GenerationInfo
│   ├── enums.py              # Role, Category, Priority, Channel, ResolutionStatus
│   ├── version.py            # SCHEMA_VERSION, semver parsing
│   └── export.py             # JSON Schema export + CI drift check
├── config/
│   ├── models.py             # GenerationConfig, Composition, ModelSpec (Pydantic)
│   ├── loader.py             # Total validation; ConfigError with all problems at once (FR-011)
│   └── defaults.py           # Documented default distribution and turn range (FR-033)
├── planning/
│   ├── apportion.py          # Largest-remainder apportionment; achievability precondition (R3, FR-030–FR-032, FR-031b)
│   ├── tolerance.py          # Per-member tolerance check returning breaches (FR-031)
│   ├── slots.py              # Slot construction; assignment, turn count, scenario nonce
│   └── seeding.py            # slot_random(seed, position, attempt) — counter-based derivation (R2)
├── model/
│   ├── client.py             # ModelClient protocol, ModelRole, ModelResponse
│   ├── anthropic_client.py   # The ONLY module importing `anthropic`
│   ├── fake.py               # FakeModelClient — scripted responses for offline tests
│   ├── limiter.py            # Token-bucket rate limiter (FR-012e)
│   └── wire.py               # GeneratedConversation, JudgeVerdict wire models
├── generation/
│   ├── prompts.py            # System/user assembly from committed documents; cache-stable prefix
│   ├── domain_doc.py         # Parses the prompt document's declared subdomain list (FR-008d)
│   ├── generator.py          # Slot -> conversation, structural validation (FR-009, FR-009b)
│   ├── judge.py              # Coherence scoring against the committed rubric (FR-009f–FR-009l)
│   └── pipeline.py           # Bounded concurrency, retries, circuit breaker, reorder buffer
├── privacy/
│   ├── registry.py           # Detector registry, floor assertion, exception suppression (FR-017, FR-018)
│   ├── detectors/datafog.py  # Offline regex detector wrapper (DATAFOG_TELEMETRY=0)
│   ├── masking.py            # Deterministic, irreversible masked renderings (FR-020a)
│   ├── quarantine.py         # Appends privacy-discarded records outside the release path (FR-021b)
│   └── exceptions_store.py   # Fingerprint-based approved exceptions (FR-022, R9)
├── run/
│   ├── run.py                # GenerationRun.execute() / .resume() — orchestration
│   ├── writer.py             # Ordered streaming writer, staging -> atomic release move (R5)
│   ├── checkpoint.py         # Checkpoint write/read, truncation resume, fingerprint match (R6)
│   ├── manifest.py           # RunManifest build + validate_manifest reconciliation (FR-026, FR-028)
│   ├── revision.py           # Git SHA + dirty flag, input hashing, environment overrides (R10, FR-008c)
│   ├── budget.py             # Declared time and call ceilings; stop-and-checkpoint on exhaustion (FR-012f)
│   └── report.py             # RunReport; JSON, text, and exit status from one object (R9, FR-035)
├── dedup.py                  # Turn-sequence fingerprints; duplicate counting (FR-034, R13)
└── cli/
    └── main.py               # Typer app — thin wrapper, no logic of its own

prompts/
├── domain.md                 # Committed domain prompt document (FR-008a)
└── coherence-rubric.md       # Committed, versioned judging rubric (FR-009g)

privacy/
└── exceptions.json           # Approved-exception fingerprints — never raw values

configs/
├── smoke.toml                # 20 records, tolerance widened to 10pp per FR-031b
├── medium.toml               # Interrupt/resume scenario
└── release.toml              # 100,000 records — the release acceptance run

tests/
├── contract/                 # Public API surface, schema export drift, CLI exit statuses
├── integration/              # Full pipeline against FakeModelClient, incl. interrupt/resume
├── unit/                     # Apportionment, seeding, reorder buffer, checkpoint truncation, dedup
└── fixtures/
    ├── responses/            # Scripted model responses: valid, malformed, refusal, PII-bearing
    ├── configs/              # Valid and deliberately invalid configurations
    └── manifests/            # Valid and defective manifests

data/
├── raw/                      # Source material (unused by this feature)
├── interim/                  # Staging files and checkpoints — never a release path
└── release/                  # Completed artifacts, manifests, reports
```

**Structure Decision**: Single Python project (`src/ticket_dataset/` + `tests/`), extending the package the
superseded feature planned rather than starting a second one — the record schema, privacy gate, and
manifest moved into this feature, so one package now owns the whole release path. Subpackages follow the
pipeline's stages so the dependency direction is visible: `schema` and `config` depend on nothing;
`planning` and `model` depend on those; `generation` and `privacy` depend on `model`; `run` composes
everything; `cli` depends only on `run`. The `model/` boundary is the one that matters most — it is the
only place `anthropic` is imported, which is what makes the rest of the package testable offline.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No gate fails. Two pieces of indirection are recorded because they add structure a simpler design would not
have, and both are named by a requirement rather than chosen for taste.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Detector registry between the pipeline and the PII engine | FR-017 requires detectors to be addable or replaceable without changing the record definition or the pipeline, and FR-022's exception suppression must behave identically across detectors | Calling `datafog` directly is fewer moving parts, but ties the gate to one library's category names and makes approved exceptions detector-specific — a value approved once would stop being approved after a detector swap, which is exactly what FR-017's replaceability is for |
| `ModelClient` protocol between the pipeline and the SDK | Keeps `anthropic` in one module so every other component — and therefore the whole test suite — runs offline and deterministically, and lets the served model ID be surfaced per record for FR-027 | Calling the SDK inline is more direct, but then no integration test can run without credentials and a network, and CI would either skip the pipeline's most important paths or pay for them on every push |
