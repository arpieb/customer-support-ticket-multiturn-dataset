---
description: "Task list for Ticket Generation Pipeline"
---

# Tasks: Ticket Generation Pipeline

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-20

**Input**: Design documents from `specs/001-ticket-generation-pipeline/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Test tasks ARE included. Constitution Principle V requires contract and edge-case tests for every
data-transforming module before it produces a released artifact, and this feature is entirely
data-transforming. Tests are written before or alongside implementation; strict red-green ordering is
encouraged but not mandated (constitution: "test-first ordering is encouraged but not mandated").

**No test makes a network call.** The `ModelClient` seam (T028–T029) exists so the whole pipeline is
exercised against a fake. Only the real client (T041) touches `anthropic`, and nothing in `tests/` imports it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel — different files, no dependency on an incomplete task
- **[Story]**: Which user story this serves (US1–US4)

## Path Conventions

Single Python project: source in `src/ticket_dataset/`, tests in `tests/`. Paths are repo-relative and
match the structure in [plan.md](./plan.md).

> ⚠️ **Increment caveat.** User Story 1 completes before the privacy gate exists (US2). A corpus produced
> at the end of Phase 3 has passed no PII scan and **must not be treated as release output**, whatever
> directory it lands in. The constitution's blocking-scan requirement is satisfied only once Phase 4 is
> complete. Do not publish anything generated before then.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency baseline

- [ ] T001 Create the package skeleton `src/ticket_dataset/` with `schema/`, `config/`, `planning/`, `model/`, `generation/`, `privacy/detectors/`, `run/`, `cli/` subpackages, each with an `__init__.py`
- [ ] T002 Add runtime dependencies `anthropic[aiohttp]`, `pydantic>=2,<3`, `datafog>=4.8,<5` (core install, NO extras), and `typer` to `pyproject.toml`, then run `uv sync` and commit the updated `uv.lock` in the same change (Constitution: Technology & Data Constraints)
- [ ] T003 [P] Add dev dependencies `pytest`, `pytest-asyncio`, `pytest-cov` to `pyproject.toml` and configure `[tool.pytest.ini_options]` with `testpaths = ["tests"]` and `asyncio_mode = "auto"`
- [ ] T004 [P] Configure `ruff` for lint and format in `pyproject.toml`
- [ ] T005 [P] Create the test tree `tests/contract/`, `tests/integration/`, `tests/unit/`, `tests/fixtures/responses/`, `tests/fixtures/configs/`, `tests/fixtures/manifests/`, `tests/fixtures/canaries/` with `__init__.py` where needed
- [ ] T006 Register the CLI entry point `ticket-dataset = "ticket_dataset.cli.main:app"` under `[project.scripts]` in `pyproject.toml`
- [ ] T007 [P] Create `data/raw/`, `data/interim/`, and `data/release/` with `.gitkeep` files, so release-path artifacts are distinguishable from scratch work by location alone (FR-013, FR-015)
- [ ] T008 [P] Add a `datafog` install guard in `tests/contract/test_offline_install.py` asserting `spacy` and `torch` are NOT importable, so the offline guarantee cannot regress via a stray extra (FR-024, quickstart Setup)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The record contract and the shared spine every user story consumes. Principle I requires the
schema to exist before any producer code, so nothing in Phase 3+ may start until this completes.

**⚠️ BLOCKING**: No user story phase can begin until Phase 2 is done.

### Record contract

- [ ] T009 [P] Define `Role` (`customer`, `agent`), `Category`, `Priority`, `Channel`, and `ResolutionStatus` closed enumerations in `src/ticket_dataset/schema/enums.py` (FR-005, FR-006)
- [ ] T010 [P] Define `PIICategory` (blocking floor `EMAIL`, `PHONE`, `CREDIT_CARD`, `US_SSN`; advisory `IP_ADDRESS`, `POSTAL_CODE`), `DiscardReason` (the nine members FR-026b enumerates), `Verdict`, and `RunOutcome` (`completed`, `refused`, `failed`, `stopped`) in `src/ticket_dataset/run/enums.py` (FR-018, FR-018b, FR-026b, FR-036b)
- [ ] T011 Define `SCHEMA_VERSION = "1.0.0"` and semver parsing in `src/ticket_dataset/schema/version.py` (FR-002)
- [ ] T012 Define `TicketRecord`, `ConversationTurn`, `TicketMetadata`, `RecordQuality`, and `GenerationInfo` Pydantic models in `src/ticket_dataset/schema/record.py` per [data-model.md](./data-model.md), including the `subdomain` and `scenario` fields and a validator enforcing that `resolved_at` is present exactly when `resolution_status` is `resolved` (FR-003, FR-004, FR-006b, FR-008b, FR-009i)
- [ ] T013 Implement `export_json_schema()` in `src/ticket_dataset/schema/export.py` (FR-001)
- [ ] T014 Add a contract test in `tests/contract/test_schema_export.py` asserting `export_json_schema()` equals the committed `specs/001-ticket-generation-pipeline/contracts/record.schema.json`, so a schema change cannot land without the contract changing in the same commit (Constitution I)
- [ ] T015 [P] Add edge-case tests in `tests/unit/test_record_model.py` covering the `resolved_at` conditional in both directions, contiguous turn indices, customer-first alternation, whitespace-only turn content, and non-Latin/emoji/RTL content as valid (FR-004, FR-006b, FR-009, spec Edge Cases)

### Configuration

- [ ] T016 Define `GenerationConfig`, `Composition`, `ModelSpec`, `Budget`, and `TimeWindow` models in `src/ticket_dataset/config/models.py` per [data-model.md](./data-model.md) (FR-008, FR-009r, FR-012f)
- [ ] T017 [P] Define the documented defaults — distribution per dimension, 4–12 turn range, thresholds 0.8 / 10% / 0.5% / ±2pp, concurrency and rate bounds — in `src/ticket_dataset/config/defaults.py`, matching the normative table in FR-033
- [ ] T018 Implement `load_config()` in `src/ticket_dataset/config/loader.py` performing **total** validation and raising `ConfigError` carrying *every* problem rather than the first (FR-011)
- [ ] T019 [P] Add unit tests in `tests/unit/test_config_loader.py` for each refusal: zero records, inverted turn range, `turns.min` below 2, threshold outside `[0,1]`, output path outside `data/release/`, and multiple simultaneous problems reported together (FR-009e, FR-011, spec Edge Cases)

### Deterministic planning

- [ ] T020 Implement `slot_random(seed, position, attempt)` in `src/ticket_dataset/planning/seeding.py` using counter-based `blake2b` derivation (FR-012b, research R2)
- [ ] T021 [P] Add unit tests in `tests/unit/test_seeding.py` asserting draws are identical regardless of call order and that a different attempt re-rolls (FR-012b, SC-013)
- [ ] T022 Implement largest-remainder apportionment in `src/ticket_dataset/planning/apportion.py`, including the achievability precondition `tolerance >= 100 / record_count` and `UnsatisfiableCompositionError` naming the dimension and reason (FR-030, FR-031b, FR-032)
- [ ] T023 [P] Add unit tests in `tests/unit/test_apportion.py` asserting per-member error stays below one record, and covering each unsatisfiable condition FR-032 enumerates
- [ ] T024 Implement `Slot` construction in `src/ticket_dataset/planning/slots.py`: apportioned assignment, uniform turn count, seeded subdomain, and seeded `created_at`/`resolved_at` from the configured window and duration bounds (FR-006a, FR-008d, FR-009d, FR-012b)
- [ ] T025 [P] Add unit tests in `tests/unit/test_slots.py` asserting every slot field is a pure function of `(seed, position)`, that turn counts are uniformly distributed over the range, and that `resolved_at` is absent unless the assignment is `resolved` (FR-006a, FR-006b, FR-009d)

### Identity, model seam, and errors

- [ ] T026 Implement fresh-per-run `run_id` and UUIDv5 `record_id` derivation in `src/ticket_dataset/run/ids.py` (FR-003a, FR-003b)
- [ ] T027 [P] Add unit tests in `tests/unit/test_ids.py` asserting a rerun yields a different `run_id`, a resume reuses one, and identifiers are stable per `(run_id, position)` (FR-003a, FR-003b, FR-015b)
- [ ] T028 Define the `ModelClient` protocol, `ModelRole`, and `ModelResponse` (carrying the **served** model id, stop reason, usage, retries) in `src/ticket_dataset/model/client.py` per [contracts/model-io.md](./contracts/model-io.md)
- [ ] T029 Implement `FakeModelClient` in `src/ticket_dataset/model/fake.py` with scripted responses covering valid output, malformed JSON, refusal, rate-limit error, and PII-bearing content — the fixture every offline test depends on
- [ ] T030 [P] Implement the token-bucket rate limiter in `src/ticket_dataset/model/limiter.py`, shared across both model roles (FR-012e)
- [ ] T031 [P] Add unit tests in `tests/unit/test_limiter.py` asserting the configured requests-per-minute bound holds under concurrency
- [ ] T032 [P] Define the exception hierarchy in `src/ticket_dataset/errors.py`: `TicketDatasetError` plus the eight subclasses in [contracts/python-api.md](./contracts/python-api.md), none of which may carry a matched PII value
- [ ] T033 [P] Define the `GeneratedConversation` and `JudgeVerdict` wire models in `src/ticket_dataset/model/wire.py`, deliberately excluding provenance fields so the model cannot write them (contracts/model-io.md)

---

## Phase 3: User Story 1 — Produce a corpus of support conversations (Priority: P1) 🎯 MVP

**Goal**: Generate a file of coherent multi-turn support conversations from a seed and a config, every
record conforming to the contract.

**Independent test**: Run the generator with a small record count and a fixed seed; confirm the output
contains that many records, every record conforms to the schema, and each conversation reads as a coherent
exchange — no manifest, privacy, or composition machinery required.

### Committed prompt inputs

- [ ] T034 [P] [US1] Author `prompts/domain.md` declaring the support domain **and a machine-readable subdomain list** (FR-008a, FR-008d)
- [ ] T035 [P] [US1] Author `prompts/coherence-rubric.md` declaring `rubric_id`, version, criteria, and per-criterion weights summing to 1 (FR-009g, FR-009p)
- [ ] T036 [US1] Implement the domain document parser in `src/ticket_dataset/generation/domain_doc.py`, raising `PromptDocumentError` when no usable subdomain list is declared (FR-008d)
- [ ] T037 [P] [US1] Add unit tests in `tests/unit/test_domain_doc.py` for a valid document, an empty list, and a malformed declaration
- [ ] T038 [US1] Implement the rubric parser in `src/ticket_dataset/generation/rubric.py`, refusing a rubric whose weights do not sum to 1 (FR-009p)
- [ ] T039 [P] [US1] Add unit tests in `tests/unit/test_rubric.py` covering weight validation and `rubric_id` extraction

### Generation and judging

- [ ] T040 [US1] Implement prompt assembly in `src/ticket_dataset/generation/prompts.py` with a **byte-stable system prefix** (domain document, rubric) and per-slot user content (assignment, turn count, language, subdomain), so the prefix caches across a run (contracts/model-io.md)
- [ ] T041 [US1] Implement `AnthropicModelClient` in `src/ticket_dataset/model/anthropic_client.py` — the only module importing `anthropic` — with `output_config.format`, adaptive thinking, configured effort, refusal fallback, and the served model id surfaced on every response (FR-027a, research R1)
- [ ] T042 [US1] Implement generation and structural validation in `src/ticket_dataset/generation/generator.py`: parse, validate against `GeneratedConversation`, and check turn count, customer-first alternation, and non-empty content, discarding under the named reason rather than coercing (FR-009, FR-009b, FR-009d)
- [ ] T043 [P] [US1] Add unit tests in `tests/unit/test_structural_validation.py` for each rejection path — unparseable, wrong turn count, agent-first, non-alternating, empty turn, truncated response — each mapping to its own `DiscardReason` (FR-009b, FR-009m)
- [ ] T044 [US1] Implement coherence judging in `src/ticket_dataset/generation/judge.py`, computing the score as the **weighted mean of per-criterion scores** using the rubric's declared weights rather than any holistic number the model returns (FR-009f, FR-009p)
- [ ] T045 [P] [US1] Add unit tests in `tests/unit/test_judge.py` asserting the weighted mean is computed from criteria, that a below-threshold score discards under `coherence_below_threshold`, and that an unscorable record discards under `unjudgeable` after the configured attempts (FR-009h, FR-009l)
- [ ] T046 [US1] Implement the concurrent pipeline in `src/ticket_dataset/generation/pipeline.py`: bounded `asyncio` worker pool, slot-level retry with the single attempts knob, and the consecutive-failure circuit breaker (FR-012a, FR-009o, FR-012d, spec Edge Cases)

### Ordered output

- [ ] T047 [US1] Implement the ordered writer in `src/ticket_dataset/run/writer.py`: a reorder buffer bounded by `max_concurrency`, ascending-position writes with deterministic serialization, destination claim at start, re-verification before the move, and the atomic staging→release move (FR-012, FR-012c, FR-014, FR-014a, FR-015, research R5)
- [ ] T048 [P] [US1] Add unit tests in `tests/unit/test_writer.py` asserting output order is ascending by position regardless of completion order, that buffer size stays bounded, and that a claimed destination refuses a second run (FR-012c, FR-014a)
- [ ] T049 [P] [US1] Implement turn-sequence fingerprinting and duplicate counting in `src/ticket_dataset/dedup.py`, Unicode-normalized, metadata excluded, reported never discarded (FR-034, FR-039, research R13)
- [ ] T050 [P] [US1] Add unit tests in `tests/unit/test_dedup.py` asserting identical conversations with differing metadata count as duplicates, and that duplicates are never removed
- [ ] T051 [US1] Implement `GenerationRun.execute()` in `src/ticket_dataset/run/run.py` wiring config validation → slot planning → concurrent generation → judging → schema validation → ordered write (FR-007)
- [ ] T052 [US1] Implement the `generate` command in `src/ticket_dataset/cli/main.py` with `--config`, `--seed`, `--out`, `--dry-run`, `--quiet`, progress on stderr, and the four exit statuses (contracts/cli.md, FR-036b)
- [ ] T053 [P] [US1] Add `configs/smoke.toml`: 20 records, `composition_tolerance_pp = 10.0` (2pp is unachievable at 20 records per FR-031b), and a narrow time window

### US1 tests

- [ ] T054 [P] [US1] Add an integration test in `tests/integration/test_generate_smoke.py` driving the full pipeline against `FakeModelClient`: exact record count, 100% schema conformance, customer-first alternation, turn counts inside the range (SC-002)
- [ ] T055 [P] [US1] Add an integration test in `tests/integration/test_concurrency_invariance.py` asserting two runs at concurrency 1 and 16 produce identical per-position seeded choices — assignment, subdomain, turn count, and timestamps — exactly the equivalence FR-010a defines (SC-013)
- [ ] T056 [P] [US1] Add a contract test in `tests/contract/test_cli_generate.py` asserting exit `0` on success, `2` on a refused config, and that stdout carries machine-readable output only (contracts/cli.md)

**Checkpoint**: A corpus can be generated and validated. Not releasable — no privacy gate yet.

---

## Phase 4: User Story 2 — No output reaches the release path carrying personal data (Priority: P2)

**Goal**: A blocking, offline privacy gate over generated output, with reviewable exceptions.

**Independent test**: Run with a configuration seeded to emit identifier-shaped content; confirm the run is
blocked, nothing reaches the release path, and findings name the offending records without reproducing values.

- [ ] T057 [P] [US2] Implement the offline `datafog` detector wrapper in `src/ticket_dataset/privacy/detectors/datafog.py`, forcing `DATAFOG_TELEMETRY=0` explicitly rather than trusting the upstream default (FR-024, research R7)
- [ ] T058 [P] [US2] Add committed synthetic canary values — one per floor type — in `tests/fixtures/canaries/` and `src/ticket_dataset/privacy/canaries.py` (FR-018a)
- [ ] T059 [US2] Implement `DetectorRegistry` in `src/ticket_dataset/privacy/registry.py` with **demonstrated** floor coverage via canary probes at run start, the advisory/blocking tier, exception suppression, and fail-closed handling of a detector that raises (FR-017, FR-017a, FR-018, FR-018a, FR-018b)
- [ ] T060 [P] [US2] Add unit tests in `tests/unit/test_registry.py` including a detector that **declares** `US_SSN` but no longer matches it — the probe must fail the run, where a declaration check would have passed (FR-018a)
- [ ] T061 [P] [US2] Add a unit test in `tests/unit/test_detector_error.py` asserting a raising detector discards the record under `detector_error`, distinct from `privacy_finding`, and that repeated failures stop the run (FR-017a)
- [ ] T062 [US2] Implement deterministic, irreversible masking in `src/ticket_dataset/privacy/masking.py` — domain for an email, issuer range for a card, shape and length otherwise (FR-020a)
- [ ] T063 [P] [US2] Add unit tests in `tests/unit/test_masking.py` asserting determinism, that no mask contains the full value, and that masks are not reversible (FR-020, FR-020a)
- [ ] T064 [US2] Implement the fingerprint-based `ExceptionStore` in `src/ticket_dataset/privacy/exceptions_store.py`, recording approver and date, **running the detectors over the stated reason** and refusing one that trips them (FR-022, FR-022a, FR-022b, research R9)
- [ ] T065 [P] [US2] Add unit tests in `tests/unit/test_exceptions_store.py` asserting no raw value is ever written, that a reason containing an identifier is rejected, and that suppression survives a detector swap (FR-022b, research R9)
- [ ] T066 [US2] Implement the quarantine writer in `src/ticket_dataset/privacy/quarantine.py`, appending privacy-discarded records under `data/interim/<run_id>/` and never to the release path (FR-021b)
- [ ] T067 [US2] Wire the scan into `src/ticket_dataset/generation/pipeline.py` **before the judge call**, so every structurally valid response is scanned and no judging call is spent on a record about to be discarded for privacy (FR-016, FR-016a, FR-021)
- [ ] T068 [US2] Implement `privacy scan` and `privacy approve` in `src/ticket_dataset/cli/main.py`, including `--from-quarantine` and `--by`, and a report enumerating covered **and** uncovered identifier types (FR-019, FR-022a, contracts/cli.md)
- [ ] T069 [P] [US2] Add `configs/planted-pii.toml` and a seeded-defect prompt document under `tests/fixtures/` that deliberately elicits identifier-shaped content
- [ ] T070 [P] [US2] Add an integration test in `tests/integration/test_privacy_blocks.py`: flagged records discarded and quarantined, the 0.5% threshold breached, run fails, **nothing in `data/release/`**, findings carry masked renderings only (SC-004, FR-020, FR-021a)
- [ ] T071 [P] [US2] Add an integration test in `tests/integration/test_privacy_exception.py` asserting an approved finding stops blocking, stays visible in the report as an approved exception, and leaves only a fingerprint on disk (FR-022)

**Checkpoint**: US1 + US2 together satisfy the constitution's blocking-scan requirement. Output is releasable in principle.

---

## Phase 5: User Story 3 — Reconstruct how a corpus was produced (Priority: P3)

**Goal**: A run manifest and report that make a corpus auditable, and a run that survives interruption.

**Independent test**: Generate a small corpus, confirm its manifest records seed, config, code revision,
input hashes, and counts, that counts reconcile exactly, and that every record resolves to that manifest.

- [ ] T072 [US3] Implement code-revision capture and input hashing in `src/ticket_dataset/run/revision.py`: git SHA, explicit dirty flag, unavailable reason, `sha256` per input, and environment settings capable of altering routing (FR-008c, FR-025a, research R10)
- [ ] T073 [P] [US3] Add unit tests in `tests/unit/test_revision.py` covering a dirty tree, a missing repository, and an unobservable routing override refusing the run (FR-008c, FR-025a)
- [ ] T074 [US3] Implement manifest construction in `src/ticket_dataset/run/manifest.py`, written beside the artifact as `<run_id>.manifest.json`, carrying start/end times, both model identities, fallback tallies, per-segment code revisions, budget spend, output filename and checksum (FR-025, FR-025b, FR-027, FR-029a, FR-015f)
- [ ] T075 [US3] Implement `validate_manifest()` in `src/ticket_dataset/run/manifest.py` checking contract conformance **and** the reconciliation `records_generated - discards == records_written`, naming every discrepancy (FR-026, FR-026a, FR-028)
- [ ] T076 [P] [US3] Add unit tests in `tests/unit/test_manifest_validation.py` with fixture manifests: missing element, discard reason outside the closed set, and counts that do not reconcile though every field is present (FR-026b, FR-028)
- [ ] T077 [US3] Implement `RunReport` in `src/ticket_dataset/run/report.py` — one object driving the JSON output, the human rendering, the `RunOutcome`, and the exit status, with the score histogram in fixed 0.05 buckets (FR-035, FR-036, FR-036a, FR-036b, FR-038, research R9)
- [ ] T078 [US3] Implement mid-run threshold evaluation in `src/ticket_dataset/run/thresholds.py`, firing once `max(1000, 5% of record_count)` records exist and stopping-and-checkpointing on breach; composition stays end-only (FR-037, FR-037a)
- [ ] T079 [P] [US3] Add unit tests in `tests/unit/test_thresholds.py` asserting no evaluation before the minimum sample, that an early discard cluster does not fail a run that recovers, and that a sustained breach stops it (FR-037)
- [ ] T080 [US3] Implement checkpointing in `src/ticket_dataset/run/checkpoint.py`: periodic durable writes, `bytes_written` truncation resume, input-fingerprint comparison, candidate discovery, and `CheckpointCorruptError` preserving partial output (FR-015a, FR-015e, FR-015g, FR-015h, research R6)
- [ ] T081 [P] [US3] Add unit tests in `tests/unit/test_checkpoint.py` covering truncation recovery from a half-written line, fingerprint mismatch refusal, ambiguous candidates, and an unreadable checkpoint leaving staging intact (FR-015e, FR-015g, FR-015h)
- [ ] T082 [P] [US3] Implement run budgets in `src/ticket_dataset/run/budget.py` — wall-clock and model-call ceilings that stop and checkpoint rather than fail (FR-012f)
- [ ] T083 [P] [US3] Implement retention in `src/ticket_dataset/run/retention.py`: drop staging and checkpoint on success, keep report and quarantine, keep everything on failure or interruption (FR-015i)
- [ ] T084 [US3] Implement `GenerationRun.resume()` in `src/ticket_dataset/run/run.py`, adding a manifest segment per resume and reconciling tallies into one manifest (FR-015b, FR-015c, FR-015d, FR-015f)
- [ ] T085 [US3] Implement `validate-manifest` in `src/ticket_dataset/cli/main.py` (contracts/cli.md)
- [ ] T086 [P] [US3] Add an integration test in `tests/integration/test_interrupt_resume.py`: kill mid-run, resume, assert no regenerated records, no duplicate identifiers, dense positions, one reconciled manifest, and `resumed_count: 1` (SC-005, SC-012)
- [ ] T087 [P] [US3] Add an integration test in `tests/integration/test_resume_refusals.py`: a changed prompt document refuses, while a changed **code revision succeeds** and adds a segment (FR-015e, FR-015f)
- [ ] T088 [P] [US3] Add an integration test in `tests/integration/test_traceability.py` locating a manifest from a single record's `run_id` alone (FR-029, FR-029a, SC-006, SC-007)

---

## Phase 6: User Story 4 — Control the composition of the corpus (Priority: P4)

**Goal**: Operator-specified composition, honored within tolerance and reported honestly.

**Independent test**: Generate with a specified composition; confirm every member of every dimension lands
within ±2pp and that requested, assigned, and achieved distributions are all reported.

- [ ] T089 [US4] Implement per-member tolerance evaluation in `src/ticket_dataset/planning/tolerance.py`, returning one `Breach` per offending member with dimension, member, requested, achieved, and drift (FR-031)
- [ ] T090 [P] [US4] Add unit tests in `tests/unit/test_tolerance.py` asserting the worst member decides, that a failure names the member, and that an aggregate-passing but member-failing distribution fails (FR-031)
- [ ] T091 [US4] Record all three distributions — requested, assigned, achieved — in the manifest and report, so apportionment error and discard-induced drift are distinguishable (FR-031a)
- [ ] T092 [US4] Wire composition refusals into `load_config()`: proportions not summing, unknown member, a proportion too small to round, and a tolerance unachievable at the corpus size (FR-031b, FR-032)
- [ ] T093 [P] [US4] Add `configs/billing-heavy.toml` (500 records), `configs/bad-composition.toml` (proportions summing to 1.4), and `configs/tight-tolerance.toml` (20 records at 2pp)
- [ ] T094 [P] [US4] Add an integration test in `tests/integration/test_composition.py` asserting per-member drift within ±2pp, all three distributions reported, and both refusal configs exiting `2` before any model call (SC-008, FR-032)

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T095 [P] Implement `sample-for-review` in `src/ticket_dataset/cli/main.py` exporting a seeded random sample with scores, so SC-011 calibration is cheap (contracts/cli.md)
- [ ] T096 [P] Implement `schema export` in `src/ticket_dataset/cli/main.py` and wire the drift check from T014 into CI (Constitution I)
- [ ] T097 [P] Re-export the public surface from `src/ticket_dataset/__init__.py` exactly as [contracts/python-api.md](./contracts/python-api.md) specifies
- [ ] T098 [P] Add a contract test in `tests/contract/test_public_api.py` asserting every documented name is importable and no undocumented name is exported
- [ ] T099 [P] Add `configs/medium.toml`, `configs/smoke16.toml` (concurrency 16), and `configs/release.toml` (100,000 records with a declared budget)
- [ ] T100 [P] Add a memory-shape test in `tests/integration/test_memory_shape.py` generating 10,000 records against `FakeModelClient` and asserting peak memory does not scale with corpus size (SC-001, FR-012)
- [ ] T101 [P] Write `README.md` covering installation, credentials, writing a configuration, and one worked run — the documentation SC-010's claim rests on (SC-010)
- [ ] T102 Run every quickstart scenario end to end and reconcile any divergence between [quickstart.md](./quickstart.md) and actual behavior
- [ ] T103 [P] Add `ruff` lint/format and the full test suite to CI, including the offline-install guard and the schema drift check

### Constitution Gates (required for any release-path change)

- [ ] T104 Schema validation over 100% of produced records, verified by the generator's own pre-write check (Constitution I, V; FR-007, SC-002)
- [ ] T105 Blocking automated PII scan wired into the pipeline ahead of any write, with demonstrated floor coverage (Constitution IV, V; FR-016, FR-016a, FR-018a)
- [ ] T106 Run manifest emits seed, serialized config, code revision, input hashes, record counts, and discard accounting by reason, reconciling exactly (Constitution II, III; FR-025, FR-026)
- [ ] T107 Quality invariants enforced: turn ordering, customer-first alternation, no empty or truncated turns, duplicate reporting (Constitution V; FR-009, FR-034)
- [ ] T108 Contract and edge-case tests present for every data-transforming module before it produces a released artifact (Constitution V)
- [ ] T109 Documented random-sample human review recorded before any release, and the coherence judge calibrated at least once against human judgement (Constitution V; SC-011) — **not enforced by code**: no requirement obliges a calibration record to exist (checklist CHK063), so this gate is a human obligation at release time
- [ ] T110 Dataset version bump and datasheet update covering composition, generation method, model mix, known limitations, intended use, and **every active privacy exception** (Constitution: Development Workflow; FR-022a)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — **BLOCKS all user stories**
- **US1 (Phase 3)**: Depends on Foundational. No dependency on other stories
- **US2 (Phase 4)**: Depends on Foundational. Integrates into US1's pipeline at T067 but is independently testable
- **US3 (Phase 5)**: Depends on Foundational. Manifest and checkpointing wrap US1's run; independently testable
- **US4 (Phase 6)**: Depends on Foundational (apportionment lands in T022/T024). Adds operator control and tolerance on top
- **Polish (Phase 7)**: Depends on every story intended for the increment

### Critical Path

`T001 → T002 → T009–T012 → T016–T018 → T020–T024 → T028–T029 → T040–T047 → T051 → T052`

### Within Each User Story

- Committed prompt inputs before the code that parses them
- Wire models and parsers before the generator that produces them
- Generator before judge; judge before pipeline; pipeline before writer integration
- The privacy scan (T067) is inserted **before** judging, not after — ordering is a requirement, not a preference (FR-016a)

### Parallel Opportunities

- **Phase 1**: T003, T004, T005, T007, T008 all parallel after T001–T002
- **Phase 2**: T009, T010, T015, T017, T019, T021, T023, T025, T027, T030–T033 parallel within their groups
- **Phase 3**: T034 and T035 parallel; T037, T039, T043, T045, T048, T049, T050, T053 parallel; all four US1 tests (T054–T056) parallel
- **Phase 4**: T057, T058 parallel; every US2 unit test parallel with its neighbours; T070, T071 parallel
- **Phase 5**: T073, T076, T079, T081, T082, T083 parallel; T086, T087, T088 parallel
- **Phase 6**: T090, T093, T094 parallel
- **Phase 7**: T095–T101, T103 all parallel

### Cross-Story Parallelism

Once Phase 2 completes, US2's privacy modules (T057–T066), US3's provenance modules (T072–T077), and US4's
tolerance work (T089–T090) are independent of US1's generation path and of each other. Only their
integration points — T067, T084, T091 — need the pipeline to exist.

---

## Implementation Strategy

### MVP (User Story 1 only)

Phases 1–3, tasks T001–T056. Delivers a working generator producing conforming records with reproducible
structure. **Not releasable**: no privacy gate, no manifest. Useful for validating the generation approach
and the prompt document before investing in the surrounding machinery.

### Incremental delivery

1. **Phase 1–3** → a corpus exists and conforms (MVP)
2. **+ Phase 4** → output is gated; the constitution's blocking-scan requirement is met
3. **+ Phase 5** → the corpus is auditable and long runs survive interruption
4. **+ Phase 6** → composition is controllable and reported
5. **+ Phase 7** → documented, CI-enforced, release-ready

Stopping after any step leaves a coherent increment. Stopping after step 1 leaves output that must not be
published.

### Cost discipline while implementing

Every test in this plan runs against `FakeModelClient` and costs nothing. The first real model calls should
be a deliberate `configs/smoke.toml` run (~40 calls) after T052, not an accident of running the suite.
`configs/release.toml` is the release acceptance run — roughly 200,000 calls — and is never part of CI.
