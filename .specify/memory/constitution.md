<!--
Sync Impact Report — 1.1.1 (2026-08-25)
=======================================
Version change: 1.1.0 → 1.1.1
Bump rationale: PATCH — wording only. The project was renamed; this document's title follows it.
No principle was added, removed, or redefined, and no obligation changed.

Modified sections:
  Title: "Customer Support Ticket Multi-Turn Dataset Constitution" → "Ticket Dataset Generator
  Constitution"

What changed and why: the repository name was the last artifact still describing this project as a
customer-support dataset rather than a domain-agnostic generator, which is what the 1.1.0 amendment
already established it to be. Renaming the constitution's title keeps governance consistent with
the thing it governs.

Templates updated in this change: none required. The propagation rule in Governance applies to
amendments that change obligations; this one changes none.

Superseded report (1.1.0)
=========================
Sync Impact Report — 1.1.0 (2026-08-24)
=======================================
Version change: 1.0.0 → 1.1.0
Bump rationale: MINOR — materially changes guidance in Technology & Data Constraints without
adding, removing, or redefining a principle.

Modified sections:
  Technology & Data Constraints: "Large artifacts" → "Corpora are not committed"

What changed and why: the previous rule assumed the repository would hold release evidence —
"the repository stores the generation config, manifest, and checksums instead" — which was never
true in practice, since `data/` is gitignored in its entirety. The framing it rested on has also
moved: this repository is a general-purpose generator, and the corpora it produces are published
manually elsewhere. Evidence now follows the artifact, carried by the dataset card, rather than
staying behind in the repository that produced it.

Templates updated in this change, per the propagation rule in Governance:
  ✅ .specify/templates/plan-template.md — Constraints check no longer asserts that large
     artifacts are represented in-repo by config + manifest + checksums
  ✅ .specify/templates/tasks-template.md — release-gate tasks reframed as obligations on
     whoever publishes a corpus, which a generator repository discharges by providing the means
  ✅ .specify/templates/spec-template.md — reviewed; encodes no gate touching this rule

Superseded report (1.0.0)
=========================
Version change: (unversioned template) → 1.0.0
Bump rationale: MAJOR/initial — first ratified constitution; all five principles newly
defined, replacing unfilled template placeholders.

Modified principles:
  [PRINCIPLE_1_NAME] → I. Schema-First Data Contracts
  [PRINCIPLE_2_NAME] → II. Reproducible Generation
  [PRINCIPLE_3_NAME] → III. Provenance & Traceability
  [PRINCIPLE_4_NAME] → IV. Privacy by Construction
  [PRINCIPLE_5_NAME] → V. Validation Gates Before Release

Added sections:
  Technology & Data Constraints (was [SECTION_2_NAME])
  Development Workflow & Quality Gates (was [SECTION_3_NAME])

Removed sections: none

Templates requiring updates:
  ✅ .specify/templates/plan-template.md — Constitution Check gates made concrete
  ✅ .specify/templates/tasks-template.md — added dataset-specific Polish gate tasks
  ✅ .specify/templates/spec-template.md — reviewed; no constitution-driven mandatory
     sections added or removed (Key Entities already covers dataset schema scope)
  ✅ .claude/skills/speckit-*/SKILL.md — reviewed; generic agent guidance, no
     outdated agent-specific references requiring change
  ✅ CLAUDE.md — reviewed; SPECKIT-managed block, no principle references to update
  ✅ README.md — rewritten to state project purpose, summarize the five principles, and link
     this constitution; datasheet reference documented as a per-release deliverable

Follow-up TODOs: none
-->

# Ticket Dataset Generator Constitution

## Core Principles

### I. Schema-First Data Contracts

Every dataset record MUST conform to an explicit, versioned schema that is committed to the
repository before any code that produces or consumes those records is written. The schema is
the contract: field names, types, cardinality, enumerations, and required/optional status are
declared in machine-readable form (JSON Schema or an equivalent typed model), not inferred
from example rows. Producers MUST validate their output against the schema; consumers MUST
validate their input. A schema change that removes a field, narrows a type, or tightens a
constraint is a breaking change and MUST bump the dataset MAJOR version.

**Rationale**: Multi-turn conversational records are deeply nested and easy to drift. Without
a declared contract, downstream training and evaluation code silently absorbs malformed turns,
and the defect surfaces only after the dataset has been consumed.

### II. Reproducible Generation

Any published dataset artifact MUST be regenerable from committed inputs. Every generation run
MUST accept an explicit random seed and a single serialized configuration object, and MUST
write both into the run's output manifest. Non-deterministic inputs — model sampling, wall-clock
time, network fetches, unpinned dependencies — MUST be captured in the manifest (model ID and
parameters, timestamps, source snapshot hashes) so a run can be replayed or, where exact replay
is impossible, audited. Generation code MUST NOT read hidden state from the developer's
environment; all inputs arrive via config or committed files.

**Rationale**: A dataset whose provenance cannot be reconstructed cannot be corrected, extended,
or defended. Seeds and manifests are what turn a one-off script output into a research artifact.

### III. Provenance & Traceability

Every record MUST carry the identifiers needed to trace it back to its origin: a stable record
ID, the generation run ID, the source or template it derives from, and the schema version it
was written against. Derived or filtered datasets MUST preserve the upstream record ID rather
than reassigning fresh identifiers. Records removed by a filter MUST be accounted for in the run
manifest by count and by reason; silent dropping is prohibited.

**Rationale**: When a quality problem is found in one record, provenance is what lets us find
every sibling record produced the same way, instead of re-reviewing the whole corpus.

### IV. Privacy by Construction

The dataset MUST contain no real personal data. Customer names, emails, phone numbers, addresses,
account numbers, and ticket identifiers MUST be synthetic or verifiably de-identified before they
enter `data/` in any form, including intermediate and scratch outputs. Real support transcripts,
if ever used as source material, MUST NOT be committed to the repository and MUST pass a
documented de-identification step before influencing any committed artifact. Every generation
pipeline MUST run an automated PII scan over its output, and the scan MUST be a blocking check,
not an advisory report.

**Rationale**: Support tickets are among the densest sources of personal data that exist.
Scrubbing after the fact is unreliable and irreversible once published; the only durable control
is to never admit real identifiers in the first place.

### V. Validation Gates Before Release

No dataset version is released until it passes, in order: schema validation over 100% of records;
the automated PII scan; declared quality invariants (turn ordering, role alternation, no empty
turns, no truncated conversations, deduplication); and human review of a documented random sample.
Code that transforms data — generators, filters, formatters, splitters — MUST have automated tests
covering its contract and its known edge cases before it is used to produce a released artifact.
Tests are required for data-transforming code; test-first ordering is encouraged but not mandated.
Exploratory notebooks and analysis scripts are exempt from the test requirement but MUST NOT be
part of a release path.

**Rationale**: Dataset defects are discovered by whoever trains on the data, long after the fact,
and cost far more to remediate than to prevent. Gates are cheap; a recalled dataset version is not.

## Technology & Data Constraints

- **Language and runtime**: Python, at the version pinned in `pyproject.toml` (currently `>=3.14`).
  Dependencies are managed exclusively with `uv`; `uv.lock` MUST be committed and MUST be updated
  in the same change as any dependency edit.
- **Data layout**: Generated artifacts live under `data/`. Raw or source material, intermediate
  stages, and released artifacts MUST occupy distinct subdirectories so that a release path is
  distinguishable from scratch work by location alone.
- **Interchange format**: Records are serialized as JSON Lines (one record per line, UTF-8).
  Alternative formats MAY be added as additional exports but MUST be generated from the JSONL
  source of truth, never authored independently.
- **Corpora are not committed**: This repository is a generator, not a dataset. No corpus, and no
  manifest or report describing one, is committed — `data/` is outside version control in its
  entirety, including artifacts small enough that Git would tolerate them. The **dataset card**
  carries what a reader needs to bind a corpus to its origin — run identifier, seed, output digest,
  model identity, and filter accounting — and travels with the corpus to wherever it is published.
  Evidence follows the artifact rather than staying behind in the repository that produced it,
  because a corpus is consumed by people who will never see this repository.
- **Manifests**: Every run writes a manifest recording seed, config, code revision, input hashes,
  output record count, filter accounting, and schema version.

## Development Workflow & Quality Gates

- Work proceeds through the Spec Kit flow: specify → clarify → plan → tasks → implement. The
  Constitution Check in `plan-template.md` MUST be evaluated before Phase 0 research and re-evaluated
  after Phase 1 design.
- Every change that touches generation, filtering, or schema MUST state in its plan which principles
  it engages and how it satisfies them. Violations MUST be recorded in the plan's Complexity Tracking
  table with a justification and the rejected simpler alternative.
- Schema changes require: the updated schema file, a version bump, a migration note for existing
  artifacts, and updated validation tests, all in the same change.
- Released dataset versions follow `MAJOR.MINOR.PATCH`: MAJOR for breaking schema or semantic
  changes, MINOR for added records or additive fields, PATCH for corrections that neither add nor
  remove fields. Each release ships a datasheet describing composition, generation method, known
  limitations, and intended use.

## Governance

This constitution supersedes other development practices in this repository. Where a tool default,
template, or habit conflicts with a principle here, the principle wins.

Amendments MUST be made by editing this file, with a version bump and an updated Sync Impact Report
recorded in the comment block at the top. Versioning of this constitution follows semantic
versioning: MAJOR for removing or redefining a principle in a backward-incompatible way, MINOR for
adding a principle or materially expanding guidance, PATCH for clarifications and wording that do
not change obligations. Any amendment that changes obligations MUST be propagated in the same change
to `.specify/templates/plan-template.md`, `.specify/templates/spec-template.md`, and
`.specify/templates/tasks-template.md` where those templates encode principle-driven gates.

Compliance is verified at review time: reviewers MUST confirm that the Constitution Check was
completed, that validation gates ran, and that any complexity is justified rather than assumed.
Runtime development guidance for coding agents lives in `CLAUDE.md` and in the active feature plan;
those documents elaborate on this constitution but never override it.

**Version**: 1.1.1 | **Ratified**: 2026-08-18 | **Last Amended**: 2026-08-25
