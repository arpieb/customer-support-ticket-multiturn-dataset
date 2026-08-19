# Feature Specification: Dataset Validation Tool

> ## ⚠️ STATUS: SUPERSEDED SCOPE — REVISE BEFORE USE
>
> This specification was written on 2026-08-18 as feature **001**, under the mistaken framing that the
> validation harness was the primary deliverable and generation was a later consumer of it. That framing
> was corrected the same day: **the generator is the product; this validator is a complementary tool**,
> used chiefly to check datasets that an external tool has postprocessed after this app produced them.
>
> **Moved out of this feature, into feature 001 (generation pipeline)**:
>
> - The record schema, its enumerations, versioning, and JSON Schema export — the generator is the
>   producer and owns the contract it writes against (Constitution Principle I).
> - The run manifest (seed, config, code revision, input hashes, reconciliation) — Principle II binds
>   *generation runs*, so the manifest belongs with the generator, not with a checking tool. Was US4 here.
> - The blocking PII scan over pipeline output — Principle IV requires *every generation pipeline* to run
>   one, so the generator cannot be constitution-compliant without it. Was US2 here.
>
> **Retained for this feature** (to be re-specified against the new framing): schema-conformance reporting
> over an externally supplied file, conversation quality invariants, exact-duplicate detection, the
> consolidated report, and the CLI. Its user is someone holding a dataset of uncertain provenance, not the
> person running a release.
>
> Everything below is the original text, kept for reuse. Do not plan or implement from it as-is.

---

# Original Specification (feature 001, superseded framing)


**Feature Branch**: `bootstrap-speckit` *(no dedicated feature branch created; spec directory is `specs/001-record-schema-validation`)*

**Created**: 2026-08-18

**Status**: Draft

**Input**: User description: "Dataset record schema and validation harness. Define the versioned, machine-readable schema for a multi-turn customer support ticket record — conversation turns with speaker roles, ticket metadata, and the provenance fields required by Constitution Principle III (record ID, run ID, source/template, schema version). Ship a typed model bound to that schema, a validator that checks 100% of records in a dataset file and reports failures with record IDs, the run manifest format (seed, serialized config, code revision, input hashes, record counts, filter accounting by reason), quality invariant checks (turn ordering, role alternation, no empty or truncated turns, deduplication), and a blocking automated PII scan over pipeline output. This is the release-path machinery every later generation feature must pass through; it deliberately excludes any conversation generation logic."

## Clarifications

### Session 2026-08-18

- Q: What attributes must Ticket Metadata carry? → A: Core triage set — category, priority, channel, resolution status, and created/resolved timestamps
- Q: Which personal-identifier categories must the privacy scan detect? → A: Make the scan a registered callable (pluggable detector), initially backed by the offline `datafog` package
- Q: How do maintainers invoke the validator and release gate? → A: A programmatic API is the primary contract, with a thin command-line wrapper over it for maintainers and automation
- Q: How should truncated turns be detected? → A: Dropped from scope — the check is removed entirely and revisited once real generator output exists
- Q: How is the record schema versioned, and how many versions does the validator support? → A: MAJOR.MINOR.PATCH semantic versioning; the validator supports exactly one schema version at a time
- Q: The FR-013d floor exceeded what the chosen detector covers — narrow the floor or add a detector? → A: Narrow it — the floor is exactly what the datafog regex engine supports, no supplementary detector

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prove a dataset file conforms to the record contract (Priority: P1)

A dataset maintainer has a file of multi-turn support ticket records and needs to know, before anyone
trains on it, whether every record matches the agreed structure. They point the validator at the file
and receive a verdict: either the file conforms, or a report naming each offending record and what is
wrong with it. The maintainer fixes the producer, re-runs, and gets a clean pass.

**Why this priority**: This is the contract that every other gate and every future generation feature
depends on. Without a declared, enforceable record structure, no other check can be defined, and
Constitution Principle I forbids writing producer code before it exists. On its own it already delivers
value: a maintainer can validate hand-authored or externally supplied records today.

**Independent Test**: Can be fully tested by running the validator against a fixture file containing a
mix of conforming and malformed records, and confirming the verdict and per-record failure report match
the known defects — no generation, privacy, or manifest machinery required.

**Acceptance Scenarios**:

1. **Given** a dataset file in which every record matches the declared structure, **When** the maintainer
   validates the file, **Then** the result reports success, states the number of records checked, and
   confirms that 100% of records were examined.
2. **Given** a dataset file containing records with a missing required field, a wrong field type, and an
   unrecognized speaker role, **When** the maintainer validates the file, **Then** the result reports
   failure and names each offending record by its record ID together with the specific field and the
   reason it failed.
3. **Given** a dataset file where one line is not a well-formed record at all, **When** the maintainer
   validates the file, **Then** the result reports that line by position with a parse failure, and
   continues checking the remaining records rather than stopping at the first error.
4. **Given** a dataset file whose records declare a schema version the validator does not support,
   **When** the maintainer validates the file, **Then** the result reports the version mismatch
   explicitly rather than reporting field-level errors.
5. **Given** any validation run, **When** it completes, **Then** the outcome is expressed as an
   unambiguous pass/fail signal that an automated release gate can act on without parsing prose.

---

### User Story 2 - Block release when disallowed personal data is present (Priority: P2)

Before a dataset version can be released, a maintainer must be certain it contains no real personal
data. They run the privacy scan over the output; the scan examines every record and reports any content
resembling real-world identifiers. If anything is found, the release stops. Findings the maintainer has
reviewed and judged to be legitimately synthetic can be recorded as such, with a reason, so that the
same finding does not silently re-block every subsequent run.

**Why this priority**: Constitution Principle IV makes this non-negotiable and irreversible in
consequence — published personal data cannot be recalled. It ranks below the schema only because the
scan needs records whose structure is already known in order to know which content to examine.

**Independent Test**: Can be fully tested by running the scan against a fixture containing planted
identifier-shaped values alongside clean synthetic records, and confirming the scan flags exactly the
planted items, halts the run, and honors a recorded review decision on a re-run.

**Acceptance Scenarios**:

1. **Given** a dataset file containing a value shaped like a real email address, phone number, postal
   address, or account number, **When** the maintainer runs the privacy scan, **Then** the scan reports
   each finding with its record ID, the field it appeared in, and the category of identifier detected.
2. **Given** a dataset file with at least one unreviewed privacy finding, **When** the release gate runs,
   **Then** the release is blocked and the blocking reason is reported.
3. **Given** a finding a maintainer has reviewed and recorded as an approved synthetic value with a
   stated reason, **When** the scan runs again over the same content, **Then** that finding no longer
   blocks the release but remains visible in the scan report as an approved exception.
4. **Given** a dataset file with no detectable identifiers, **When** the privacy scan runs, **Then** it
   reports a clean result and states the number of records and fields examined.

---

### User Story 3 - Enforce conversation quality invariants (Priority: P3)

A maintainer needs assurance that records are not merely well-shaped but conversationally coherent:
turns in order, speakers alternating sensibly, no empty turns, and no duplicate conversations padding
the corpus. They run the invariant checks and receive a report of every violation
by record ID and invariant name.

**Why this priority**: These defects pass schema validation while still ruining downstream training
value. They rank below privacy because they degrade quality rather than causing irreversible harm.

**Independent Test**: Can be fully tested by running the invariant checks against a fixture in which
each invariant is deliberately violated exactly once, and confirming one report entry per planted
violation with no false positives on the clean records.

**Acceptance Scenarios**:

1. **Given** a record whose turns are not in ascending order, **When** invariant checks run, **Then** the
   record is reported as violating turn ordering.
2. **Given** a record in which the same speaker takes two consecutive turns, **When** invariant checks
   run, **Then** the record is reported as violating role alternation.
3. **Given** a record containing a turn with empty or whitespace-only content, **When** invariant checks
   run, **Then** the record is reported as containing an empty turn.
4. **Given** a file containing two conversations that are duplicates of one another, **When** invariant
   checks run, **Then** both records are reported as duplicates of a single group, and the report
   identifies which record is retained.
5. **Given** a file that violates several invariants across different records, **When** invariant checks
   run, **Then** all violations are reported in one pass rather than one violation per run.

---

### User Story 4 - Reconstruct how a dataset version was produced (Priority: P4)

Months after a release, a maintainer investigating a data quality complaint needs to know exactly how a
given file was produced: what seed and configuration were used, what code produced it, what inputs it
consumed, how many records went in and came out, and why any records were dropped. They open the run
manifest that accompanies the artifact and find all of it, and can trace any individual record back to
that run.

**Why this priority**: Required by Constitution Principles II and III, but its full value is only
realized once generation runs exist to describe. Defining and validating the format now prevents
retrofitting provenance onto artifacts that were produced without it.

**Independent Test**: Can be fully tested by writing a manifest for a fixture run, validating it against
its own declared structure, and confirming that every record in the fixture carries identifiers that
resolve to that manifest — no real generation pipeline required.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** its manifest is produced, **Then** the manifest records the seed,
   the full serialized configuration, the code revision, the identifying hashes of all inputs, the
   schema version, the output record count, and the filter accounting.
2. **Given** a run in which records were removed by filtering, **When** the manifest is produced,
   **Then** every removed record is accounted for by count and by reason, and the input count minus all
   removal counts equals the output count.
3. **Given** a manifest missing any required element, **When** it is validated, **Then** validation fails
   and names the missing element.
4. **Given** any record in a released artifact, **When** a maintainer inspects it, **Then** it carries a
   record ID, the run ID of the manifest that describes its production, its source or template
   identifier, and the schema version it was written against.
5. **Given** a derived dataset produced by filtering an earlier one, **When** its records are inspected,
   **Then** they retain their upstream record IDs rather than being assigned new ones.

---

### Edge Cases

- **Empty file**: A file with zero records validates as structurally clean but is reported as empty, and
  the release gate treats an empty release artifact as a failure rather than a trivial pass.
- **Very large file**: Files too large to hold in memory are validated without loading the whole file at
  once; progress remains observable so an operator can tell a slow run from a hung one.
- **Mixed-version file**: A file whose records declare differing schema versions is rejected outright as
  a mixed-version file, rather than validating each record against its own version.
- **Duplicate record IDs**: Two records sharing a record ID is itself a violation, reported distinctly
  from content duplication, because it breaks traceability.
- **Conflicting gate outcomes**: When schema validation fails, the later gates still run where possible
  so the maintainer sees the full picture in one pass, but the overall verdict remains failure.
- **Unicode and multilingual content**: Non-Latin scripts, emoji, and right-to-left text are valid turn
  content and must not be reported as malformed.
- **Legitimately identifier-shaped synthetic values**: A synthetic value that looks like a real
  identifier is expected and handled through the recorded-review path, not by weakening the scan.
- **Very long conversations**: A conversation with an unusually large number of turns is valid; no
  invariant may assume a small fixed maximum.
- **Partially written file**: A file whose last line was cut off by an interrupted write is reported as a
  parse failure at that position rather than silently ignored.

## Requirements *(mandatory)*

### Functional Requirements

**Schema and record contract**

- **FR-001**: The project MUST publish a machine-readable, versioned definition of a support ticket
  record, covering its conversation turns, ticket metadata, and provenance fields.
- **FR-002**: The record definition MUST carry an explicit version identifier, and every record MUST
  declare the version it was written against.
- **FR-002a**: Schema versions MUST use `MAJOR.MINOR.PATCH` semantic versioning, consistent with the
  constitution's rule that a breaking record change bumps MAJOR and an additive field bumps MINOR.
- **FR-002b**: The validator MUST support exactly one schema version per run and MUST declare which
  version it is validating against in its report.
- **FR-003**: Each record MUST provide a stable record ID, the run ID that produced it, the source or
  template it derives from, and its schema version.
- **FR-004**: Each conversation turn MUST identify its speaker role, its position in the conversation,
  and its content.
- **FR-005**: The set of permitted speaker roles MUST be enumerated in the definition, and any value
  outside that set MUST be rejected.
- **FR-006**: The definition MUST state, for every field, whether it is required and what values are
  permitted, so that conformance is decidable without consulting example records.
- **FR-006a**: Each record MUST carry ticket metadata comprising a topic category, a priority level, an
  originating channel, a resolution status, and the times the ticket was created and resolved.
- **FR-006b**: Topic category, priority, channel, and resolution status MUST each be constrained to an
  enumerated set declared in the schema; values outside those sets MUST be rejected.
- **FR-006c**: Ticket timestamps MUST be validated for internal consistency — a resolution time MUST NOT
  precede its creation time, and turn ordering MUST be consistent with the ticket's own time bounds.

**Validation**

- **FR-007**: The validator MUST examine 100% of records in a file — never a sample — and MUST report the
  number of records examined.
- **FR-008**: The validator MUST report every conforming failure it finds in a single pass rather than
  stopping at the first.
- **FR-009**: Each reported failure MUST identify the offending record by record ID, or by position when
  the record is unparseable, and MUST name the specific field and reason.
- **FR-010**: The validator MUST detect and report a schema version it does not support as a distinct
  outcome, separate from field-level failures.
- **FR-010a**: A file containing records declaring more than one schema version MUST be rejected as a
  mixed-version file rather than partially validated, and the report MUST name each version present.
- **FR-011**: The validator MUST emit an unambiguous machine-readable pass/fail verdict suitable for an
  automated gate, in addition to any human-readable report.
- **FR-012**: The validator MUST process files larger than available memory without loading the entire
  file at once.

**Privacy scanning**

- **FR-013**: The privacy scan MUST examine every record and report content matching known categories of
  real-world personal identifier.
- **FR-013a**: Detection MUST be performed by one or more registered detectors invoked through a common
  interface, so that a detector can be added, replaced, or supplemented without changing the record
  schema, the finding format, or the release gate.
- **FR-013b**: The registry MUST record which detectors ran for a given scan, and the scan report MUST
  name them, so that a clean result is attributable to a known detector set rather than to an empty one.
- **FR-013c**: Every registered detector MUST operate without contacting a network service, so that the
  gate is runnable offline and produces identical findings for identical input.
- **FR-013d**: Regardless of which detectors are registered, the scan MUST detect at minimum: email
  addresses, phone numbers, payment card numbers, and government identifiers. A detector set that cannot
  cover this floor MUST fail the gate rather than silently reporting clean.
- **FR-013e**: Full postal addresses and bank account numbers are explicitly OUT OF SCOPE for the blocking
  floor, because reliable offline detection of them is not available (see Assumptions). Their absence from
  the floor MUST be stated in the scan report, so a clean result is never mistaken for coverage the scan
  does not provide.
- **FR-013f**: A detector MAY report additional categories beyond the floor as advisory, non-blocking
  findings. Advisory findings MUST appear in the report but MUST NOT fail the gate.
- **FR-014**: Each privacy finding MUST report the record ID, the field, and the identifier category
  detected.
- **FR-015**: An unreviewed privacy finding MUST block the release gate; the gate MUST NOT be advisory.
- **FR-016**: Maintainers MUST be able to record a reviewed finding as an approved exception with a
  stated reason, and approved exceptions MUST remain visible in the scan report.
- **FR-017**: The scan MUST report the number of records and fields examined, so that a clean result is
  distinguishable from a scan that examined nothing.

**Quality invariants**

- **FR-018**: The invariant checks MUST detect and report out-of-order turns, consecutive turns by the
  same speaker, empty or whitespace-only turns, and duplicate conversations. Truncation detection is
  explicitly OUT OF SCOPE for this feature.
- **FR-018a**: Duplicate detection MUST identify exact duplicates — conversations whose turn sequences are
  identical after normalization of insignificant whitespace. Near-duplicate detection (conversations
  differing only in names, numbers, or minor rewording) is explicitly OUT OF SCOPE for this feature.
- **FR-019**: Duplicate detection MUST group duplicates together and identify which record is retained.
- **FR-020**: Duplicate record IDs MUST be reported as a distinct violation from duplicate content.
- **FR-021**: All invariant violations across a file MUST be reported in a single pass.

**Run manifest**

- **FR-022**: Every run MUST produce a manifest recording the seed, the serialized configuration, the
  code revision, the identifying hashes of all inputs, the schema version, and the output record count.
- **FR-023**: The manifest MUST account for every removed record by count and by reason, such that input
  count minus all removal counts equals output count.
- **FR-024**: The manifest format MUST itself be validatable, and validation MUST name any missing
  required element.
- **FR-025**: Derived datasets MUST preserve upstream record IDs rather than assigning new ones.

**Release gate**

- **FR-026**: The release gate MUST run schema validation, the privacy scan, and the invariant checks,
  and MUST fail if any of them fails.
- **FR-027**: The release gate MUST treat an empty artifact as a failure.
- **FR-028**: The release gate MUST produce a single consolidated report covering all gates run.

**Interfaces**

- **FR-029**: The harness MUST expose its capabilities — record validation, invariant checks, the privacy
  scan and its detector registry, manifest writing and validation, and the consolidated release gate — as
  a programmatic interface that other project code can call directly without spawning a subprocess.
- **FR-030**: The harness MUST provide a command-line entry point over that same interface, so a
  maintainer or an automated job can validate an artifact with a single command.
- **FR-031**: The command-line entry point MUST signal its verdict through a conventional success/failure
  exit status, so an automated gate can act on it without parsing output.
- **FR-032**: Both interfaces MUST produce the same verdict and the same findings for the same input; the
  command-line surface MUST NOT implement checking logic of its own.

### Key Entities

- **Ticket Record**: One complete multi-turn customer support interaction. Holds its ordered
  conversation turns, its ticket metadata, and its provenance fields. The unit that is validated,
  scanned, counted, and deduplicated.
- **Conversation Turn**: A single utterance within a record. Carries a speaker role drawn from the
  permitted set, a position establishing its order, and its textual content.
- **Ticket Metadata**: The descriptive attributes of the support interaction as a whole — the attributes
  by which a consumer would filter or stratify the corpus. Comprises a topic category, a priority level, an
  originating channel, a resolution status, and the times the ticket was created and resolved. Category,
  priority, channel, and resolution status are each drawn from an enumerated set declared in the schema.
- **Provenance Fields**: The identifiers binding a record to its origin — record ID, run ID, source or
  template identifier, and schema version.
- **Record Schema**: The versioned, machine-readable contract that decides whether a record conforms.
  Identified by a `MAJOR.MINOR.PATCH` version; exactly one version is authoritative for a given
  validation run.
- **Run Manifest**: The record of how one generation run produced its output — seed, configuration, code
  revision, input hashes, schema version, record counts, and filter accounting.
- **Validation Report**: The outcome of running the gates over a file — an overall verdict plus the
  individual findings, each tied to a record ID and a reason.
- **Privacy Finding**: One detected potential personal identifier, with its record ID, field, category,
  the detector that reported it, and its review status.
- **Detector Registry**: The set of registered detection callables available to the privacy scan, each
  addressable by name, together with the categories each one covers.
- **Approved Exception**: A maintainer's recorded decision that a specific privacy finding is a
  legitimate synthetic value, with the stated reason.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of records in a candidate artifact are examined by every gate on every run, with the
  examined count reported and reconcilable against the artifact's record count.
- **SC-002**: A maintainer given a failing artifact can locate every defective record from the report
  alone, without opening the data file to search for the problem.
- **SC-003**: Every defect planted in the validation fixture set — one per rule, covering every field
  constraint, invariant, and identifier category — is detected, and no clean record is reported as
  defective.
- **SC-004**: No artifact containing an unreviewed potential personal identifier can pass the release
  gate, demonstrated by an end-to-end attempt that is blocked.
- **SC-005**: A maintainer can determine the seed, configuration, code revision, and inputs behind any
  released artifact from its manifest alone, in under five minutes, without consulting the person who
  produced it.
- **SC-006**: For any released artifact, the record count reconciles exactly: input count minus the sum
  of all removal reasons equals output count, with no unexplained difference.
- **SC-007**: Any individual record can be traced to the run that produced it and the source it derives
  from, using only the record's own fields.
- **SC-008**: A full gate run over a 100,000-record artifact completes on a single maintainer machine
  within minutes, not hours, so that validation is never the reason a release is deferred.
- **SC-009**: A new contributor can validate their first artifact using the project's documentation
  alone, without assistance.

## Assumptions

- **Synthetic by construction**: Records are generated rather than derived from real support transcripts.
  The privacy scan is a safety net confirming that assumption held, not the primary control.
- **Migration is a separate concern**: Because the validator supports one schema version at a time,
  moving an existing corpus onto a new schema version is an explicit migration step, not something the
  validator performs implicitly. Building that migration path is not part of this feature.
- **Line-delimited records**: Artifacts hold one record per line, per the constitution's designation of
  JSON Lines as the dataset source of truth. Gates operate over that form.
- **Two-party conversations by default**: Records represent an exchange between a customer and a support
  agent. Additional roles (for example, an automated system message or a supervisor) are accommodated by
  enumerating them in the schema rather than by relaxing role alternation.
- **English-first, not English-only**: Initial content is expected to be English, but no gate may assume
  it; multilingual and non-Latin content must validate cleanly.
- **Gates run locally**: Validation is expected to run on a maintainer's machine and in automation, with
  no dependency on network services or hosted detectors.
- **Initial detector is `datafog`**: The first registered detector wraps the offline `datafog` package,
  chosen because its base install is dependency-light and pattern-based (no model downloads, no network)
  and it declares support for this project's Python version. The registry exists so this choice is
  reversible; confirming the exact package version and category mapping belongs to `/speckit-plan`.
- **The blocking floor is bounded by what offline pattern detection can actually do**: FR-013d's floor is
  set to exactly the categories the chosen detector's regex engine covers with high precision — email
  address, phone number, payment card, and government identifier (US SSN). This is a deliberate decision to
  make the gate's promise honest rather than aspirational: a floor listing categories nothing can detect
  would produce "clean" results that overstate coverage.
- **Known gaps in the blocking floor**: full postal addresses and bank account numbers are NOT gated.
  Address detection requires statistical NER, which breaks the offline and determinism requirements;
  bank account detection is available in the chosen engine only as a country-specific (German) IBAN type,
  which does not fit an English-first corpus. Person names are likewise not gated — statistical name
  detection produces heavy false positives on synthetic data and would route most findings through the
  exception path, eroding the gate's credibility. The residual risk is accepted because records are
  synthetic by construction, making the scan a safety net rather than the primary control, and because the
  detector registry (FR-013a) lets any of these be added later without reopening the schema or the gate.
- **Advisory categories are available but not blocking**: the chosen engine also detects IP addresses and
  postal codes. These may be registered as advisory, non-blocking findings (FR-013f). Generic date
  detection is deliberately not enabled — every record carries legitimate ticket timestamps, so it would
  fire on nearly every record.
- **No generation logic in scope**: This feature deliberately excludes producing conversations. It
  defines and enforces the contract that generation features will later have to satisfy.
- **API is the primary contract**: Later generation features are expected to call the harness
  programmatically rather than through the command line, so the API is the surface that must stay stable.
  The command-line wrapper is for maintainers and automation and carries no logic of its own.
- **No dataset content in scope**: This feature ships machinery and fixtures, not a released corpus.
- **Fixtures are hand-authored**: The defect fixtures backing SC-003 are authored as part of this
  feature, since no generator exists to produce them.
- **Truncation detection is out of scope**: Deciding whether a final turn was cut off mid-utterance
  cannot be made reliably testable without real generator output to characterize how truncation actually
  manifests. Rather than ship a heuristic that would produce arbitrary acceptance tests, the check is
  removed from this feature and revisited once generation exists. This leaves truncation as a known
  ungated defect class in the interim.
- **Release scale is ~100,000 records**: Gates are designed against this target. It is large enough that
  whole-file in-memory processing is not assumed anywhere, and small enough that a full gate run is
  expected to finish in minutes on one machine without distributed processing.
- **Deduplication is exact-match only**: Near-duplicate detection is deferred. The deduplication step
  should be structured so a similarity-based strategy can replace it later without changing the record
  schema or the report format, but implementing that strategy is not part of this feature.
