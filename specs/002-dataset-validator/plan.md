# Implementation Plan: Record Schema & Validation Harness

> ⚠️ **Superseded scope.** Written as feature 001 under the framing that validation was the primary
> deliverable. The generator is the product; this is a complementary tool. Schema, run manifest, and
> the blocking PII scan moved to feature 001. See the banner in `spec.md`. Kept for reuse; do not
> implement from it as-is.

**Branch**: `bootstrap-speckit` | **Date**: 2026-08-18 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-record-schema-validation/spec.md`

## Summary

Deliver the release-path machinery every later generation feature must pass through: a versioned record
schema for multi-turn support tickets, a streaming validator, conversation quality invariants, a blocking
privacy scan behind a pluggable detector registry, and a run manifest format — exposed as a programmatic
API with a thin CLI over it. No conversation generation is in scope.

The technical approach is a single Python package whose contract is a set of Pydantic v2 models. The
record model is authoritative and exports a committed JSON Schema; every gate reads JSONL line-by-line so
memory stays independent of file size; every gate emits findings into one structured report object from
which the JSON output, the human-readable text, and the CLI exit status are all derived. Privacy detection
sits behind a project-owned registry interface with a single registered detector — `datafog`'s offline
regex engine — whose high-precision categories define the blocking floor exactly.

## Technical Context

**Language/Version**: Python 3.14 (per `requires-python = ">=3.14"` in `pyproject.toml`)

**Primary Dependencies**: `pydantic` v2 (schema + typed models + report objects), `datafog` >=4.8,<5 core
install (offline regex PII engine), `typer` (CLI wrapper). Dev-only: `pytest`, `pytest-cov`.

**Storage**: Files only. JSONL artifacts under `data/`, JSON run manifests beside them, a committed JSON
Schema export, and a committed privacy-exception fingerprint file. No database.

**Testing**: `pytest`, with contract tests per public API surface, integration tests over fixture JSONL
files, and unit tests for individual rules. Fixtures are hand-authored (no generator exists).

**Target Platform**: Local developer machines (macOS, Linux) and CI. Fully offline — no network calls at
run time, enforced by `DATAFOG_TELEMETRY=0` and the no-extras `datafog` install.

**Project Type**: Library with a thin CLI wrapper. The programmatic API is the stable contract; the CLI
carries no checking logic of its own (FR-029–FR-032).

**Performance Goals**: A full gate run over a 100,000-record artifact completes in minutes, not hours, on a
single machine (SC-008). Single-threaded stdlib parsing is expected to meet this; `orjson` and
multiprocessing are the identified levers if it does not.

**Constraints**: Memory independent of file size — no whole-file loads (FR-012). Deterministic: identical
input yields identical findings (FR-013c). Offline: no network at run time. Exit status is the machine
verdict (FR-031).

**Scale/Scope**: ~100,000 records per release artifact; conversations of unbounded turn count; 43
functional requirements across five gate areas.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

*Source: `.specify/memory/constitution.md` v1.0.0. Mark each gate PASS / FAIL / N/A with a
one-line justification. Any FAIL must either be resolved or recorded in Complexity Tracking.*

| # | Gate | Status | Notes |
|---|------|--------|-------|
| I | **Schema-First Data Contracts** — is the record schema declared, versioned, and committed before producer/consumer code? Do both sides validate against it? Is any breaking schema change accompanied by a MAJOR bump? | **PASS** | This feature *is* the schema, and it lands before any generator exists. Semver per FR-002a; validator declares its version (FR-002b); mixed-version files rejected (FR-010a); JSON Schema export committed and diff-checked in CI so a breaking change is visible in review. |
| II | **Reproducible Generation** — does every run take an explicit seed and a single serialized config, and write a manifest capturing seed, config, code revision, and input hashes? Is all non-determinism captured? | **PASS** | No generation runs exist in this feature; it delivers and validates the manifest contract those runs must satisfy (FR-022–FR-024). Code revision is captured with an explicit dirty-tree flag (R8) so a misleading SHA cannot be recorded silently. |
| III | **Provenance & Traceability** — does every record carry record ID, run ID, source/template, and schema version? Do derived sets preserve upstream IDs? Are filtered-out records accounted for by count and reason? | **PASS** | Provenance fields are required by the schema, not optional (FR-003). Upstream IDs preserved on derived sets (FR-025). Manifest reconciles input − removals = output and fails validation otherwise (FR-023). |
| IV | **Privacy by Construction** — is all identifying content synthetic or verifiably de-identified before reaching `data/`? Is a blocking automated PII scan wired into the pipeline? | **PASS** | The scan blocks rather than advises (FR-015). The floor is scoped to what the offline regex engine actually covers — `EMAIL`, `PHONE`, `CREDIT_CARD`, `SSN` — with postal address and bank account recorded as known gaps that the report must state (FR-013e), so a clean verdict never overstates coverage. The registry asserts floor coverage at startup and fails closed. Exceptions are stored as fingerprints, never raw values (R4), so the exception file never becomes a PII store. |
| V | **Validation Gates Before Release** — do schema validation, PII scan, quality invariants, and sampled human review all gate the release? Do data-transforming modules have contract and edge-case tests? | **PASS** | The composite gate runs schema → privacy → invariants and fails if any fails (FR-026), treating an empty artifact as failure (FR-027). Contract and edge-case tests are required for every module. Sampled human review is a process step this feature enables by producing the report; it is not automatable here. |

**Constraints check**: dependencies managed via `uv` with `uv.lock` updated in the same change — **PASS**,
all three runtime dependencies added in one change. JSONL is the source of truth — **PASS**, all gates read
JSONL and no other format is produced. Release-path artifacts separated by directory from scratch work —
**PASS**, `data/raw/`, `data/interim/`, `data/release/` established by this feature. Large artifacts as
config + manifest + checksums rather than committed directly — **PASS**, `data/` is git-ignored and
manifests carry the checksums.

**Post-design re-check (after Phase 1)**: Re-evaluated against `data-model.md` and `contracts/`. All five
gates still hold. The design added no new dependency, no new persisted format beyond those listed, and no
whole-file load. Gate IV was re-evaluated after the blocking floor was narrowed to the detector's actual
regex coverage: it now passes without deviation, and the only entry remaining in Complexity Tracking is the
registry indirection.

## Project Structure

### Documentation (this feature)

```text
specs/001-record-schema-validation/
├── plan.md              # This file (/speckit-plan command output)
├── spec.md              # Feature specification
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── checklists/
│   └── requirements.md  # Spec quality checklist
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── python-api.md    # Programmatic contract (the stable surface)
│   ├── cli.md           # Command-line contract: commands, options, exit statuses
│   └── record.schema.json  # Generated JSON Schema export of the record contract
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/ticket_dataset/
├── __init__.py              # Public API re-exports — the stable surface (FR-029)
├── schema/
│   ├── record.py            # TicketRecord, ConversationTurn, TicketMetadata, Provenance models
│   ├── enums.py             # Role, Category, Priority, Channel, ResolutionStatus
│   ├── version.py           # SCHEMA_VERSION, semver parsing, supported-version check
│   └── export.py            # JSON Schema export + CI drift check
├── io/
│   └── jsonl.py             # Streaming line-by-line reader yielding (line_no, raw, parsed|error)
├── validation/
│   └── validator.py         # Per-record schema validation, version handling (FR-007–FR-012)
├── invariants/
│   ├── checks.py            # Ordering, role alternation, empty turns (FR-018)
│   └── dedup.py             # Exact-duplicate fingerprinting, duplicate record IDs (FR-018a–FR-020)
├── privacy/
│   ├── registry.py          # Detector registry + floor-coverage assertion (FR-013a, FR-013d)
│   ├── base.py              # Detector protocol: name, categories, scan(text) -> findings
│   ├── exceptions.py        # Fingerprint-based approved exceptions (FR-016)
│   └── detectors/
│       └── datafog_detector.py   # EMAIL, PHONE, CREDIT_CARD, SSN (+ optional advisory categories)
├── manifest/
│   ├── model.py             # RunManifest model + reconciliation rule (FR-022–FR-024)
│   └── capture.py           # git revision + dirty flag, input hashing (R8)
├── report/
│   ├── model.py             # Report, Finding, Verdict — one object, all surfaces (R9)
│   └── render.py            # JSON and human-readable text renderers
├── gate/
│   └── run.py               # Composite release gate orchestration (FR-026–FR-028)
└── cli/
    └── main.py              # Typer app — wiring only, no checking logic (FR-032)

tests/
├── contract/                # Public API and CLI contract tests
├── integration/             # End-to-end gate runs over fixture artifacts
├── unit/                    # Individual rules, detectors, fingerprinting
└── fixtures/
    ├── clean.jsonl          # Conforming records — must produce zero findings
    ├── defects/             # One file per planted defect class (SC-003)
    └── manifests/           # Valid and invalid manifests

data/
├── raw/                     # Source material (git-ignored)
├── interim/                 # Scratch / intermediate stages (git-ignored)
└── release/                 # Release-path artifacts + manifests (git-ignored)
```

**Structure Decision**: Single Python project under `src/ticket_dataset/`, chosen because this feature is
one library with one CLI and no service or frontend boundary. Modules are split by *gate* rather than by
technical layer, so each of the spec's user stories maps onto one directory — `validation/` for US1,
`privacy/` for US2, `invariants/` for US3, `manifest/` for US4 — with `report/` and `io/` as the shared
spine and `gate/` composing them. The `data/` subdirectories implement the constitution's requirement that
release-path artifacts be distinguishable from scratch work by location alone.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| A registry indirection over PII detection rather than calling `datafog` directly | FR-013a requires detectors to be replaceable without touching the schema, finding format, or gate; the floor-coverage assertion and fingerprint-based suppression must apply uniformly across detectors. | *Direct calls to `datafog`*: couples the gate to one vendor's entity names and makes suppression detector-specific, so an approved exception would silently stop applying if the detector were swapped — the failure mode the registry exists to prevent. |
