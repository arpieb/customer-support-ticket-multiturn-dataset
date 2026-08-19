---
description: "Task list for Record Schema & Validation Harness"
---

# Tasks: Record Schema & Validation Harness

> ⚠️ **Superseded scope.** Written as feature 001 under the framing that validation was the primary
> deliverable. The generator is the product; this is a complementary tool. Schema, run manifest, and
> the blocking PII scan moved to feature 001. See the banner in `spec.md`. Kept for reuse; do not
> implement from it as-is.

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-18

**Input**: Design documents from `specs/001-record-schema-validation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Test tasks ARE included. Constitution Principle V requires contract and edge-case tests for
every data-transforming module before it produces a released artifact, and SC-003 requires a planted-defect
fixture set. Tests are written before or alongside implementation, but strict red-green ordering is not
mandated (constitution: "test-first ordering is encouraged but not mandated").

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story this serves (US1–US4)

## Path Conventions

Single Python project: source in `src/ticket_dataset/`, tests in `tests/`. Paths below are repo-relative
and match the structure in [plan.md](./plan.md).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency baseline

- [ ] T001 Create the package skeleton `src/ticket_dataset/` with `schema/`, `io/`, `validation/`, `invariants/`, `privacy/detectors/`, `manifest/`, `report/`, `gate/`, `cli/` subpackages, each with an `__init__.py`
- [ ] T002 Add runtime dependencies `pydantic>=2,<3`, `datafog>=4.8,<5` (core install, NO extras), and `typer` to `pyproject.toml`, then run `uv sync` and commit the updated `uv.lock` in the same change (Constitution constraints check)
- [ ] T003 [P] Add dev dependencies `pytest` and `pytest-cov` to `pyproject.toml` and configure `[tool.pytest.ini_options]` with `testpaths = ["tests"]`
- [ ] T004 [P] Configure `ruff` for lint and format in `pyproject.toml`
- [ ] T005 [P] Create the test tree `tests/contract/`, `tests/integration/`, `tests/unit/`, `tests/fixtures/defects/`, `tests/fixtures/manifests/`, `tests/fixtures/exceptions/` with `__init__.py` where needed
- [ ] T006 Register the CLI entry point `ticket-dataset = "ticket_dataset.cli.main:app"` under `[project.scripts]` in `pyproject.toml`
- [ ] T007 [P] Create the `data/raw/`, `data/interim/`, and `data/release/` directories with `.gitkeep` files, so release-path artifacts are distinguishable from scratch work by location alone (Constitution: Technology & Data Constraints)
- [ ] T008 [P] Add a `datafog` install guard test in `tests/contract/test_offline_install.py` asserting that `spacy` and `torch` are NOT importable, so the offline guarantee cannot regress via a stray extra (FR-013c, quickstart Setup)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The record contract and shared spine that every user story consumes. Principle I requires the
schema to exist before any producer or consumer code, so nothing in Phase 3+ may start until this completes.

**⚠️ BLOCKING**: No user story phase can begin until Phase 2 is done.

- [ ] T009 [P] Define `Role`, `Category`, `Priority`, `Channel`, and `ResolutionStatus` closed enumerations in `src/ticket_dataset/schema/enums.py` per data-model.md
- [ ] T010 [P] Define `PIICategory` (blocking floor `EMAIL`, `PHONE`, `CREDIT_CARD`, `GOVERNMENT_ID`; advisory `IP_ADDRESS`, `POSTAL_CODE`), `Verdict`, and `GateName` enumerations in `src/ticket_dataset/report/enums.py` (FR-013d, FR-013f)
- [ ] T011 Define `SCHEMA_VERSION = "1.0.0"`, semver parsing, and `is_supported_version()` enforcing the exactly-one-version rule in `src/ticket_dataset/schema/version.py` (FR-002a, FR-002b)
- [ ] T012 Define the `TicketRecord`, `ConversationTurn`, and `TicketMetadata` Pydantic models in `src/ticket_dataset/schema/record.py`, including the FR-006c cross-field validators (`resolved_at` not before `created_at`; `resolved_at` required when `resolution_status` is `resolved`; turn timestamps within ticket bounds)
- [ ] T013 Implement `export_json_schema()` and a `--check` drift comparison against `specs/001-record-schema-validation/contracts/record.schema.json` in `src/ticket_dataset/schema/export.py` (R1, Principle I)
- [ ] T014 [P] Implement the streaming line-by-line JSONL reader yielding `ParsedLine(line_no, parsed | error)` in `src/ticket_dataset/io/jsonl.py`, never loading the whole file and continuing past unparseable lines (FR-008, FR-012)
- [ ] T015 [P] Define the `Report`, `Finding`, and `PrivacyException` models in `src/ticket_dataset/report/model.py`, including `declared_gaps`, `detectors_run`, `records_examined`, and `counts_by_gate`, and enforcing that `Finding` has no field capable of holding a matched PII value (data-model.md, R4)
- [ ] T016 Implement `render_json()`, `render_text()`, and `exit_status()` over the single `Report` object in `src/ticket_dataset/report/render.py`, so JSON, text, and exit status cannot disagree (R9, FR-011, FR-031)
- [ ] T017 [P] Author the conforming fixture `tests/fixtures/clean.jsonl` (≥20 records spanning every enum value, multi-turn, including non-Latin and RTL content) — must produce zero findings from every gate (SC-003)
- [ ] T018 [P] Author the empty fixture `tests/fixtures/empty.jsonl` (zero records) for the FR-027 empty-artifact failure path
- [ ] T019 Re-export the public API surface from `src/ticket_dataset/__init__.py` exactly as listed in [contracts/python-api.md](./contracts/python-api.md) (FR-029)
- [ ] T020 [P] Add a contract test in `tests/contract/test_public_api.py` asserting every name in [contracts/python-api.md](./contracts/python-api.md) is importable from `ticket_dataset` with the documented signature

**Checkpoint**: The record contract exists, is committed, and is exported. User story phases may begin.

---

## Phase 3: User Story 1 - Prove a dataset file conforms to the record contract (Priority: P1) 🎯 MVP

**Goal**: A maintainer can point the validator at a JSONL artifact and get either a clean verdict or a
report naming every offending record, field, and reason.

**Independent Test**: Run `validate_records` against a fixture mixing conforming and malformed records and
confirm the verdict and per-record failure report match the known planted defects — no privacy, invariant,
or manifest machinery involved.

### Tests for User Story 1

- [ ] T021 [P] [US1] Author `tests/fixtures/defects/schema_violations.jsonl` planting one instance each of: missing required field, wrong field type, unrecognized speaker role, invalid enum value, and a line that is not valid JSON at all (US1 scenarios 2 and 3)
- [ ] T022 [P] [US1] Author `tests/fixtures/defects/unsupported_version.jsonl` and `tests/fixtures/defects/mixed_version.jsonl` for the FR-010 and FR-010a outcomes
- [ ] T023 [P] [US1] Write the contract test for `validate_records` in `tests/contract/test_validate_records.py` covering the return type, the pass/fail verdict, and `records_examined` reconciliation (FR-011, SC-001)
- [ ] T024 [P] [US1] Write integration tests in `tests/integration/test_us1_validation.py` for quickstart Scenarios 1 and 2, asserting every planted defect is reported by record ID and that no clean record produces a finding (SC-003)

### Implementation for User Story 1

- [ ] T025 [US1] Implement `validate_records()` in `src/ticket_dataset/validation/validator.py`: stream via `read_jsonl`, validate each record against `TicketRecord`, and emit one `Finding` per failure naming the field and reason (FR-007, FR-008, FR-009)
- [ ] T026 [US1] Report unparseable lines by line number with `record_id = None` and continue the run rather than stopping at the first error, in `src/ticket_dataset/validation/validator.py` (FR-009, spec Edge Cases)
- [ ] T027 [US1] Implement unsupported-version detection as a distinct outcome and mixed-version file rejection naming each version present, in `src/ticket_dataset/validation/validator.py` (FR-010, FR-010a)
- [ ] T028 [US1] Record `schema_version_validated` and `records_examined` on every `Report` so a clean result is never indistinguishable from a run that examined nothing (FR-002b, FR-007, SC-001)
- [ ] T029 [US1] Add the `validate` command to `src/ticket_dataset/cli/main.py`, wiring arguments to `validate_records` and returning `exit_status(report)` with no checking logic of its own (FR-030, FR-032)
- [ ] T030 [P] [US1] Add a unit test in `tests/unit/test_unicode_content.py` proving non-Latin, emoji, and RTL turn content validates cleanly and is never reported as malformed (spec Edge Cases)
- [ ] T031 [P] [US1] Add a test in `tests/contract/test_schema_export.py` asserting `export-schema --check` passes against the committed contract and fails on drift (R1)

**Checkpoint**: US1 is independently shippable — a maintainer can validate an artifact end to end.

---

## Phase 4: User Story 2 - Block release when disallowed personal data is present (Priority: P2)

**Goal**: An artifact containing an unreviewed potential identifier cannot pass the gate; reviewed findings
can be recorded as approved exceptions without hiding them.

**Independent Test**: Scan a fixture with planted identifiers alongside clean synthetic records; confirm
exactly the planted items are flagged, the run is blocked, and a recorded approval unblocks on re-run while
remaining visible in the report.

### Tests for User Story 2

- [ ] T032 [P] [US2] Author `tests/fixtures/defects/pii_planted.jsonl` planting one synthetic instance of each blocking-floor category — email, phone, payment card, government identifier — inside turn content (SC-003)
- [ ] T033 [P] [US2] Author `tests/fixtures/exceptions/approved.json` containing fingerprint-only exception entries (no raw values) for a subset of the planted findings (R4, FR-016)
- [ ] T034 [P] [US2] Write the contract test for the detector protocol and registry in `tests/contract/test_detector_registry.py`, including that a registry missing a floor category raises rather than scanning (FR-013d)
- [ ] T035 [P] [US2] Write integration tests in `tests/integration/test_us2_privacy.py` for quickstart Scenarios 3 and 4, asserting the block, the per-finding record ID/field/category/detector, and the exception behavior
- [ ] T036 [P] [US2] Write a test in `tests/unit/test_no_pii_in_report.py` asserting that no rendered report — JSON or text — contains any planted PII value (R4, Principle IV)

### Implementation for User Story 2

- [ ] T037 [P] [US2] Define the `Detector` protocol (`name`, `categories`, `scan`) in `src/ticket_dataset/privacy/base.py` (FR-013a)
- [ ] T038 [US2] Implement `DetectorRegistry` with `register`, `covered_categories`, `assert_floor_covered` (failing closed on an uncovered blocking floor), and `scan_text` in `src/ticket_dataset/privacy/registry.py` (FR-013a, FR-013d)
- [ ] T039 [US2] Implement the datafog detector in `src/ticket_dataset/privacy/detectors/datafog_detector.py`, setting `DATAFOG_TELEMETRY=0` before construction and mapping datafog entity names to `PIICategory` (R2, FR-013c)
- [ ] T040 [US2] Implement fingerprint-based exceptions — `fingerprint(category, value)` as `sha256(category + ":" + normalized)` and `load_exceptions()` — in `src/ticket_dataset/privacy/exceptions.py`, never persisting raw values (R4, FR-016)
- [ ] T041 [US2] Apply exception suppression in the registry layer after detectors run, setting `blocking = false` while keeping the finding in the report, so an approval survives a detector swap (R4, FR-016)
- [ ] T042 [US2] Implement `scan_privacy()` in `src/ticket_dataset/privacy/scan.py`: scan every text field of every record, populate `detectors_run`, and report the examined record and field counts (FR-013, FR-013b, FR-017)
- [ ] T043 [US2] Populate `Report.declared_gaps` with the categories the scan does not cover — full postal address and bank account number — on every scan (FR-013e)
- [ ] T044 [US2] Mark non-floor categories as advisory, non-blocking findings that appear in the report but never fail the gate, in `src/ticket_dataset/privacy/scan.py` (FR-013f)
- [ ] T045 [US2] Add the `scan` command with `--exceptions` to `src/ticket_dataset/cli/main.py`, returning exit status `3` distinctly when floor coverage fails (FR-030, contracts/cli.md)

**Checkpoint**: US2 is independently shippable — the privacy gate blocks and honors reviewed exceptions.

---

## Phase 5: User Story 3 - Enforce conversation quality invariants (Priority: P3)

**Goal**: Records that pass schema validation but are conversationally incoherent or duplicated are caught
and reported by record ID and invariant name.

**Independent Test**: Run the invariant checks against a fixture violating each invariant exactly once and
confirm one report entry per planted violation, with no false positives on the clean fixture.

### Tests for User Story 3

- [ ] T046 [P] [US3] Author `tests/fixtures/defects/invariant_violations.jsonl` planting one instance each of: out-of-order turns, consecutive same-speaker turns, a whitespace-only turn, a duplicated conversation pair, and a duplicated record ID (SC-003)
- [ ] T047 [P] [US3] Write the contract test for `check_invariants` in `tests/contract/test_check_invariants.py`
- [ ] T048 [P] [US3] Write integration tests in `tests/integration/test_us3_invariants.py` for quickstart Scenario 5, asserting all violations surface in a single pass (FR-021)
- [ ] T049 [P] [US3] Write a unit test in `tests/unit/test_long_conversation.py` proving a conversation with a very large turn count is valid and no invariant assumes a fixed maximum (spec Edge Cases)

### Implementation for User Story 3

- [ ] T050 [P] [US3] Implement turn-ordering, role-alternation, and empty/whitespace-only turn checks in `src/ticket_dataset/invariants/checks.py` (FR-018)
- [ ] T051 [US3] Implement exact-duplicate detection in `src/ticket_dataset/invariants/dedup.py` by fingerprinting the turn sequence only — role plus whitespace-normalized content — excluding provenance and metadata (FR-018a, R6)
- [ ] T052 [US3] Group duplicates and identify the retained record in the report output from `src/ticket_dataset/invariants/dedup.py` (FR-019)
- [ ] T053 [US3] Report duplicate record IDs as a violation distinct from duplicate content in `src/ticket_dataset/invariants/dedup.py` (FR-020)
- [ ] T054 [US3] Implement `check_invariants()` in `src/ticket_dataset/invariants/run.py` reporting all violations across a file in one pass, holding only digests and IDs in memory (FR-021, R5)
- [ ] T055 [US3] Add the `invariants` command to `src/ticket_dataset/cli/main.py` (FR-030)

**Checkpoint**: US3 is independently shippable — quality invariants are enforced.

---

## Phase 6: User Story 4 - Reconstruct how a dataset version was produced (Priority: P4)

**Goal**: A maintainer can determine the seed, config, code revision, and inputs behind any artifact from
its manifest alone, and trace any record to the run that produced it.

**Independent Test**: Write a manifest for a fixture run, validate it against its declared structure, and
confirm every record in the fixture carries identifiers resolving to that manifest — no generation needed.

### Tests for User Story 4

- [ ] T056 [P] [US4] Author `tests/fixtures/manifests/valid.json`, `tests/fixtures/manifests/unbalanced.json` (removal counts that do not reconcile), and `tests/fixtures/manifests/missing_field.json` (US4 scenarios 2 and 3)
- [ ] T057 [P] [US4] Write the contract test for `validate_manifest` in `tests/contract/test_validate_manifest.py`
- [ ] T058 [P] [US4] Write integration tests in `tests/integration/test_us4_manifest.py` for quickstart Scenario 6, asserting the reconciliation failure names the discrepancy and a missing element is named (FR-023, FR-024)
- [ ] T059 [P] [US4] Write a unit test in `tests/unit/test_provenance_trace.py` asserting every record in `tests/fixtures/clean.jsonl` carries record ID, run ID, source ID, and schema version, and that a derived record preserves its upstream ID (FR-003, FR-025, SC-007)

### Implementation for User Story 4

- [ ] T060 [P] [US4] Define the `RunManifest`, `CodeRevision`, and `RemovalAccount` models in `src/ticket_dataset/manifest/model.py`, enforcing `input_count - sum(removals) == output_count` (FR-022, FR-023)
- [ ] T061 [US4] Implement `capture_code_revision()` in `src/ticket_dataset/manifest/capture.py` recording the git SHA plus an explicit dirty-tree flag, or a stated reason when unavailable (R8)
- [ ] T062 [P] [US4] Implement `hash_input()` as sha256 over file contents in `src/ticket_dataset/manifest/capture.py` (FR-022)
- [ ] T063 [US4] Implement `write_manifest()` and `validate_manifest()` naming any missing required element in `src/ticket_dataset/manifest/io.py` (FR-024)
- [ ] T064 [US4] Add the `manifest-check` command to `src/ticket_dataset/cli/main.py` (FR-030)

**Checkpoint**: All four user stories are independently shippable.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: The composite gate, documentation, and the constitution gates that govern any release-path change

- [ ] T065 Implement `run_gate()` in `src/ticket_dataset/gate/run.py` running schema → privacy → invariants (plus manifest validation when given), continuing past a failed gate so the full picture appears in one pass, and consolidating into a single `Report` (FR-026, FR-028, spec Edge Cases)
- [ ] T066 Treat an empty artifact as a gate failure rather than a trivial pass in `src/ticket_dataset/gate/run.py` (FR-027)
- [ ] T067 Add the `gate` and `export-schema` commands to `src/ticket_dataset/cli/main.py` (contracts/cli.md)
- [ ] T068 [P] Write an integration test in `tests/integration/test_gate.py` for quickstart Scenario 7, including the empty-artifact failure and the JSON report shape
- [ ] T069 [P] Write a contract test in `tests/contract/test_cli_parity.py` asserting the CLI and API produce identical verdicts and findings for the same input (FR-032)
- [ ] T070 [P] Write a contract test in `tests/contract/test_exit_statuses.py` covering all four documented exit statuses, including `3` for uncovered floor (contracts/cli.md, FR-031)
- [ ] T071 [P] Benchmark a full gate run over a generated 100,000-record artifact and record the timing in `specs/001-record-schema-validation/quickstart.md`; if it exceeds minutes, pull the `orjson` lever recorded in R5 (SC-008)
- [ ] T072 [P] Add a memory-ceiling test in `tests/integration/test_streaming.py` proving peak memory does not scale with file size (FR-012, R5)
- [ ] T073 [P] Update `README.md` with harness usage and link [quickstart.md](./quickstart.md) so a new contributor can validate an artifact unaided (SC-009)
- [ ] T074 Run `uv run pytest` and confirm the whole suite passes with every planted defect detected and zero findings on the clean fixture (SC-003)

### Constitution Gates (required for any release-path change)

- [ ] T075 [P] Verify schema validation runs over 100% of records and the examined count reconciles against the artifact record count, asserted in `tests/contract/test_validate_records.py` (Constitution I, V; SC-001)
- [ ] T076 [P] Verify the automated PII scan is wired as a blocking check, not advisory, and fails closed on uncovered floor, asserted in `tests/contract/test_detector_registry.py` (Constitution IV, V; FR-015)
- [ ] T077 [P] Verify the run manifest emits seed, serialized config, code revision, input hashes, record counts, and filter accounting by reason, asserted in `tests/contract/test_validate_manifest.py` (Constitution II, III; FR-022)
- [ ] T078 [P] Verify quality invariants are enforced — turn ordering, role alternation, no empty turns, deduplication — asserted in `tests/contract/test_check_invariants.py` (Constitution V; FR-018)
- [ ] T079 [P] Verify contract and edge-case tests exist for every data-transforming module by auditing coverage of `src/ticket_dataset/` against `tests/contract/` (Constitution V)
- [ ] T080 Confirm no released artifact is produced by this feature, so the sampled human review and datasheet gates do not apply yet; record that determination in the Constitution Check section of `specs/001-record-schema-validation/plan.md` and in the PR description (Constitution V)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1. **BLOCKS all user stories** — Principle I forbids consumer code before the schema exists
- **Phase 3 (US1)**: Depends on Phase 2. Independent of US2–US4
- **Phase 4 (US2)**: Depends on Phase 2. Independent of US1, US3, US4
- **Phase 5 (US3)**: Depends on Phase 2. Independent of US1, US2, US4
- **Phase 6 (US4)**: Depends on Phase 2. Independent of US1–US3
- **Phase 7 (Polish)**: `run_gate` (T065) depends on US1, US2, and US3 being complete, since it composes them

### User Story Dependencies

All four stories depend only on Phase 2 and are mutually independent — each reads records and emits a
`Report`, sharing no state. After Phase 2, they can be built in parallel by different people, or in
priority order by one.

### Within Each User Story

Fixtures and contract tests come first (they define expected behavior), then implementation, then the CLI
wiring, then integration tests. The CLI task in each story is last because it wraps the completed API.

### Parallel Opportunities

- **Phase 1**: T003, T004, T005, T007, T008 all touch different files
- **Phase 2**: T009, T010, T014, T015, T017, T018, T020 are parallel; T011 → T012 → T013 is a chain
- **Phase 3**: T021–T024 in parallel, then T025–T029 sequential (same file), T030/T031 parallel
- **Phase 4**: T032–T037 in parallel, then T038–T045 largely sequential
- **Phase 5**: T046–T050 in parallel, then T051–T055
- **Phase 6**: T056–T060 and T062 in parallel, then T061, T063, T064
- **Phase 7**: T068–T073 and T075–T079 all parallel
- **Across stories**: once Phase 2 lands, Phases 3–6 run fully in parallel

---

## Parallel Example: Phase 2 Foundational

```text
# Launch the independent foundational tasks together:
T009  Define record enums in src/ticket_dataset/schema/enums.py
T010  Define report enums in src/ticket_dataset/report/enums.py
T014  Streaming JSONL reader in src/ticket_dataset/io/jsonl.py
T015  Report/Finding models in src/ticket_dataset/report/model.py
T017  Clean fixture tests/fixtures/clean.jsonl
T018  Empty fixture tests/fixtures/empty.jsonl
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

Complete Phase 1 → Phase 2 → Phase 3, then stop and validate. That yields a working schema contract and a
validator a maintainer can run against a real artifact — the deliverable Principle I requires before any
generation feature may begin. 31 tasks.

### Incremental Delivery

1. Phases 1–2 → the record contract exists and is committed
2. Phase 3 → **MVP**: schema validation shippable
3. Phase 4 → the privacy gate blocks releases (the highest-consequence gate)
4. Phase 5 → quality invariants
5. Phase 6 → provenance and manifests
6. Phase 7 → the composite gate ties them together

Each phase is independently testable and leaves the harness in a working state.

### Parallel Team Strategy

With multiple developers: complete Phases 1–2 together, then split — one developer per user story phase.
The stories share only the `Report` model and the JSONL reader, both frozen in Phase 2, so merge conflicts
are confined to `src/ticket_dataset/cli/main.py`, where each story appends one command.

---

## Notes

- **US1 is the true MVP**; Phase 2 is deliberately large because Principle I forbids writing consumer code
  before the schema is committed.
- **`run_gate` (T065) is the one cross-story dependency** — it composes US1, US2, and US3, which is why it
  sits in Polish rather than in any single story.
- **T071 is a measurement task, not an optimization task.** If the 100k target is missed, R5 records
  `orjson` as the first lever; do not optimize before measuring.
- **No released dataset artifact is produced by this feature**, so the constitution's sampled-human-review
  and datasheet release gates are recorded as not-yet-applicable (T080) rather than silently skipped.
