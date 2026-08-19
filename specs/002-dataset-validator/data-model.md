# Phase 1 Data Model: Record Schema & Validation Harness

> ⚠️ **Superseded scope.** Written as feature 001 under the framing that validation was the primary
> deliverable. The generator is the product; this is a complementary tool. Schema, run manifest, and
> the blocking PII scan moved to feature 001. See the banner in `spec.md`. Kept for reuse; do not
> implement from it as-is.

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-18

Entities are drawn from the spec's Key Entities section; validation rules are traced to the functional
requirement that mandates them. All models are Pydantic v2; the record model is authoritative and exports
[contracts/record.schema.json](./contracts/record.schema.json).

---

## Enumerations

| Enum | Values | Source |
|------|--------|--------|
| `Role` | `customer`, `agent`, `system` | FR-005; `system` accommodates automated messages without relaxing alternation (spec Assumptions) |
| `Category` | `billing`, `technical`, `account`, `shipping`, `product`, `other` | FR-006b |
| `Priority` | `low`, `normal`, `high`, `urgent` | FR-006b |
| `Channel` | `email`, `chat`, `phone`, `web_form` | FR-006b |
| `ResolutionStatus` | `resolved`, `unresolved`, `escalated`, `abandoned` | FR-006b |
| `PIICategory` | Blocking floor: `EMAIL`, `PHONE`, `CREDIT_CARD`, `GOVERNMENT_ID`. Advisory: `IP_ADDRESS`, `POSTAL_CODE` | FR-013d floor; FR-013f advisory |
| `Verdict` | `pass`, `fail` | FR-011 |
| `GateName` | `schema`, `privacy`, `invariants`, `manifest` | FR-028 |

`Role`, `Category`, `Priority`, `Channel`, and `ResolutionStatus` are closed sets — any other value is a
validation failure (FR-005, FR-006b). Adding a member is an additive MINOR schema change; removing one is
breaking and requires a MAJOR bump (FR-002a).

---

## TicketRecord

The unit that is validated, scanned, counted, and deduplicated.

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `schema_version` | `str` | yes | `MAJOR.MINOR.PATCH` semver (FR-002, FR-002a). Must equal the validator's supported version or the record is an unsupported-version outcome (FR-010) |
| `record_id` | `str` | yes | Stable, unique within an artifact. Duplicates are a distinct violation from duplicate content (FR-020) |
| `run_id` | `str` | yes | Identifies the producing run; resolves to a `RunManifest` (FR-003, FR-022) |
| `source_id` | `str` | yes | Source or template the record derives from (FR-003) |
| `upstream_record_id` | `str \| None` | no | Present on derived records; preserves the originating ID (FR-025) |
| `metadata` | `TicketMetadata` | yes | See below (FR-006a) |
| `turns` | `list[ConversationTurn]` | yes | Non-empty; ordering and alternation enforced by invariants, not the schema (FR-018) |

**Relationships**: `TicketRecord` 1→N `ConversationTurn` (ordered); 1→1 `TicketMetadata`; N→1 `RunManifest`
via `run_id`; 0..1→1 self-reference via `upstream_record_id`.

**Note on layering**: the schema enforces *shape* (types, enums, presence); the invariant checks enforce
*coherence* (ordering, alternation, duplication). Keeping them separate is what lets a record fail
invariants while still being structurally parseable, which US3 depends on.

---

## ConversationTurn

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `index` | `int` | yes | ≥ 0; establishes order. Must ascend contiguously from 0 within a record (FR-018) |
| `role` | `Role` | yes | Closed set (FR-005) |
| `content` | `str` | yes | Must not be empty or whitespace-only (FR-018). Any Unicode, including non-Latin and RTL, is valid (spec Edge Cases) |
| `timestamp` | `datetime \| None` | no | If present, must fall within the ticket's created/resolved bounds (FR-006c) |

---

## TicketMetadata

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `category` | `Category` | yes | Closed set (FR-006b) |
| `priority` | `Priority` | yes | Closed set (FR-006b) |
| `channel` | `Channel` | yes | Closed set (FR-006b) |
| `resolution_status` | `ResolutionStatus` | yes | Closed set (FR-006b) |
| `created_at` | `datetime` | yes | Timezone-aware (FR-006a) |
| `resolved_at` | `datetime \| None` | no | If present, must not precede `created_at` (FR-006c). Required when `resolution_status` is `resolved` |

---

## RunManifest

Describes how one run produced its output.

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `run_id` | `str` | yes | Referenced by every record the run produced (FR-003) |
| `schema_version` | `str` | yes | The version records were written against (FR-022) |
| `seed` | `int` | yes | Explicit seed (FR-022, Principle II) |
| `config` | `dict` | yes | Full serialized configuration (FR-022) |
| `code_revision` | `CodeRevision` | yes | See below (FR-022, R8) |
| `input_hashes` | `dict[str, str]` | yes | Path → sha256 of each input (FR-022) |
| `input_count` | `int` | yes | Records entering the run |
| `output_count` | `int` | yes | Records written |
| `removals` | `list[RemovalAccount]` | yes | Every removed record accounted for by reason (FR-023) |

**Reconciliation rule (FR-023)**: `input_count - sum(r.count for r in removals) == output_count`. A manifest
failing this is invalid, and validation names the discrepancy. This is the check that makes silent dropping
impossible (Principle III).

### CodeRevision

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `commit` | `str \| None` | yes | Git SHA, or `None` when unavailable |
| `dirty` | `bool` | yes | True when the working tree had uncommitted changes (R8) |
| `unavailable_reason` | `str \| None` | no | Set when `commit` is `None`, explaining why |

A `dirty` or `unavailable` revision does not fail manifest validation — it records the caveat truthfully
rather than misrepresenting provenance.

### RemovalAccount

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `reason` | `str` | yes | Why records were removed (FR-023) |
| `count` | `int` | yes | ≥ 0 |

---

## Report, Finding, and Verdict

One object drives the JSON output, the text rendering, and the CLI exit status (R9, FR-032).

### Report

| Field | Type | Rules |
|-------|------|-------|
| `verdict` | `Verdict` | `fail` if any gate failed, else `pass` (FR-011, FR-026) |
| `schema_version_validated` | `str` | Which version the run validated against (FR-002b) |
| `records_examined` | `int` | Must reconcile against the artifact's record count (FR-007, SC-001) |
| `gates_run` | `list[GateName]` | Which gates executed (FR-028) |
| `detectors_run` | `list[str]` | Named detectors, so a clean result is attributable (FR-013b) |
| `declared_gaps` | `list[str]` | Categories the scan does not cover, stated on every scan (FR-013e) |
| `findings` | `list[Finding]` | All findings from all gates, one pass (FR-008, FR-021) |
| `counts_by_gate` | `dict[GateName, int]` | Summary counts |

### Finding

| Field | Type | Rules |
|-------|------|-------|
| `gate` | `GateName` | Which gate produced it |
| `record_id` | `str \| None` | `None` only when the record was unparseable (FR-009) |
| `line_number` | `int \| None` | Set when `record_id` is unavailable, locating the bad line (FR-009) |
| `rule` | `str` | The specific rule or field that failed (FR-009) |
| `message` | `str` | Human-readable reason |
| `pii_category` | `PIICategory \| None` | Privacy findings only (FR-014) |
| `detector` | `str \| None` | Which detector reported it (FR-013b) |
| `fingerprint` | `str \| None` | Privacy findings only; keys the exception store (R4) |
| `blocking` | `bool` | False when an approved exception applies (FR-016), or when the category is advisory rather than part of the floor (FR-013f) |

**Never present**: the matched value itself. Findings locate PII; they do not reproduce it, so reports can
be shared and committed without becoming a PII store (Principle IV, R4).

---

## PrivacyException

| Field | Type | Rules |
|-------|------|-------|
| `fingerprint` | `str` | `sha256(category + ":" + normalized_value)` — never the raw value (R4) |
| `category` | `PIICategory` | The category the finding was reported under |
| `reason` | `str` | The reviewer's stated justification (FR-016) |
| `approved_on` | `date` | When the decision was recorded |

Suppression is applied in the registry layer after detectors run, so an approval survives a detector swap
(R4, FR-013a). An approved finding stays in the report with `blocking = false` (FR-016).

---

## Detector protocol

Not a persisted entity — the interface every registered detector satisfies (FR-013a).

| Member | Type | Rules |
|--------|------|-------|
| `name` | `str` | Unique within the registry; appears in `Report.detectors_run` (FR-013b) |
| `categories` | `frozenset[PIICategory]` | What this detector claims to cover; the registry unions these to assert the FR-013d floor |
| `scan(text)` | `-> Iterable[RawFinding]` | Must be deterministic and must make no network call (FR-013c) |

**Registry startup assertion (FR-013d)**: the union of registered detectors' `categories` must cover the
full blocking floor — `EMAIL`, `PHONE`, `CREDIT_CARD`, `GOVERNMENT_ID`. If it does not, the gate fails
closed rather than reporting clean. Categories outside the floor are advisory: they appear in the report
with `blocking = false` and never fail the gate (FR-013f).

**Declared gaps (FR-013e)**: `Report` carries the categories the scan does not cover — currently full
postal address and bank account number — so a clean verdict is never read as coverage the scan lacks.

---

## State transitions

Records have no lifecycle — they are immutable once written. The only state transition in the model is a
**Finding's blocking status**: a finding is created `blocking = true`, and becomes `blocking = false` when a
matching `PrivacyException` fingerprint is recorded. There is no reverse transition; withdrawing an
approval means deleting the exception entry, which restores the finding to blocking on the next run.
