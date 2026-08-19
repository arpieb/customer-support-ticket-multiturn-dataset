# Feature Specification: Ticket Generation Pipeline

**Feature Branch**: `bootstrap-speckit` *(no dedicated feature branch created; spec directory is `specs/001-ticket-generation-pipeline`)*

**Created**: 2026-08-18

**Status**: Draft

**Input**: User description: "Multi-turn customer support ticket generation pipeline. This is the product: it generates the dataset. Define the versioned record schema the generator writes against (conversation turns with speaker roles, ticket metadata, and provenance fields), then generate synthetic multi-turn customer/agent conversations from an explicit seed and a single serialized configuration, so any run is replayable or auditable. Every run writes a run manifest capturing seed, config, code revision, input hashes, schema version, record counts, and filter accounting by reason (Constitution Principle II and III). Every run passes its own output through a blocking automated PII scan before the output is written to the release path, because Constitution Principle IV requires every generation pipeline to run one. Output is JSON Lines under data/. The generator must be able to produce a corpus at release scale (~100,000 records) and let the operator control the mix of ticket categories, priorities, channels, and resolution outcomes. Out of scope: the standalone validation tool for datasets postprocessed by external tools, which is feature 002."

## Clarifications

### Session 2026-08-18

- Q: By what method is conversation text produced? → A: A language model generates it; exact reproducibility becomes best-effort with model identity and parameters captured in the manifest
- Q: What happens when the privacy scan flags generated records? → A: Discard the flagged records and account for them under a privacy discard reason; the rest of the corpus proceeds
- Q: Where do the support scenarios come from? → A: A committed domain prompt markdown file; the model elaborates plausible subdomain scenarios from it
- Q: How is conversation length determined? → A: A configurable min/max range, with each conversation's length sampled from it as a seeded choice
- Q: How is conversation coherence decided? → A: A model-as-judge scores every generated record against a rubric; records below a configured threshold are discarded and accounted for
- Q: What happens when a long run is interrupted? → A: Runs checkpoint progress and resume where they stopped, reconciling into a single manifest
- Q: How does the generator achieve throughput at release scale? → A: Bounded concurrency with retry and backoff, with per-record seeded choices assigned before dispatch so results stay order-independent
- Q: What default values should the run's thresholds and tolerances take? → A: Composition ±2 percentage points, privacy discard rate 0.5%, coherence discard rate 10%, coherence score threshold 0.8 — all configurable

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce a corpus of support conversations (Priority: P1)

A dataset author wants a corpus of multi-turn customer support conversations. They write a configuration
describing what they want, choose a seed, and run the generator. It produces a file of conversation records
— each a coherent exchange between a customer and a support agent about a plausible support issue — every
one of which conforms to the project's record contract.

**Why this priority**: This is the product. Everything else in the repository exists to make this output
trustworthy; without it there is no dataset. On its own it already delivers the core value: a usable corpus.

**Independent Test**: Run the generator with a small record count and a fixed seed, then confirm the output
file contains that many records, every record conforms to the schema, and each conversation reads as a
coherent multi-turn exchange — no manifest, privacy, or composition machinery required.

**Acceptance Scenarios**:

1. **Given** a valid configuration and a seed, **When** the author runs the generator, **Then** it produces
   the requested number of records, each conforming to the record contract, and reports how many it wrote.
2. **Given** a generated record, **When** the author inspects it, **Then** its turns alternate between a
   customer and a support agent, are ordered, and are non-empty, and the exchange concerns a single
   coherent support issue.
3. **Given** the same seed and the same configuration, **When** the author runs the generator twice,
   **Then** the two runs produce equivalent output, or — where exact reproduction is not achievable — the
   run records everything needed to explain the difference.
4. **Given** a configuration that is invalid or internally contradictory, **When** the author runs the
   generator, **Then** it refuses to run and names the specific problem rather than producing partial output.
5. **Given** a request for a corpus at release scale, **When** the generator runs, **Then** it writes
   records incrementally so that progress is observable and memory does not grow with corpus size.

---

### User Story 2 - No generated output reaches the release path carrying personal data (Priority: P2)

Before any generated output is treated as releasable, the pipeline scans it for content resembling real
personal identifiers. If anything is found, the output does not reach the release path. Findings a reviewer
has judged to be legitimately synthetic can be recorded as approved exceptions so they do not re-block
every subsequent run.

**Why this priority**: Constitution Principle IV requires every generation pipeline to run a blocking scan
over its output, and the consequence of failure is irreversible once published. It ranks below generation
only because there must be output before there is anything to scan.

**Independent Test**: Run the generator with a configuration deliberately seeded to emit identifier-shaped
content; confirm the run is blocked, nothing is written to the release path, and the findings name the
offending records.

**Acceptance Scenarios**:

1. **Given** generated output containing a value shaped like a real email address, phone number, payment
   card, or government identifier, **When** the pipeline scans it, **Then** each finding is reported with
   its record identifier, the field it appeared in, the category detected, and a masked rendering that
   never reproduces the matched value.
2. **Given** any unreviewed privacy finding, **When** the run completes its scan, **Then** the output does
   not reach the release path and the blocking reason is reported.
3. **Given** a finding a reviewer has adjudicated — from its masked rendering, or from the quarantined
   record when the mask is insufficient — and recorded as an approved synthetic value with a stated reason,
   **When** a later run produces the same content, **Then** it no longer blocks, but remains visible in the
   run's report as an approved exception.
4. **Given** output with no detectable identifiers, **When** the scan completes, **Then** it reports a clean
   result, states how many records and fields it examined, and names the detectors that ran.
5. **Given** a scan that cannot cover its mandatory categories, **When** the run starts, **Then** it fails
   before generating rather than producing output no one can vouch for.

---

### User Story 3 - Reconstruct how a corpus was produced (Priority: P3)

Months later, someone investigating a data quality complaint needs to know exactly how a corpus was made:
the seed, the full configuration, the code revision, what inputs were consumed, how many records were
produced, and why any were discarded. They open the run manifest beside the artifact and find all of it,
and can trace any single record back to that run.

**Why this priority**: Constitution Principles II and III require it, and provenance cannot be
retrofitted — a corpus produced without a manifest is permanently unauditable. It ranks below the privacy
gate because a missing manifest is recoverable by regenerating; published personal data is not.

**Independent Test**: Generate a small corpus, then confirm its manifest records seed, configuration, code
revision, input hashes, and counts, that the counts reconcile exactly, and that every record carries
identifiers resolving to that manifest.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** its manifest is written, **Then** the manifest records the seed, the
   full serialized configuration, the code revision, the identifying hashes of all inputs, the schema
   version, and the output record count.
2. **Given** a run that discarded records — because they failed the schema, failed the privacy scan, or were
   rejected as unusable — **When** the manifest is written, **Then** every discarded record is accounted for
   by count and by reason, and input count minus all discards equals output count.
3. **Given** any record in the corpus, **When** someone inspects it, **Then** it carries a record identifier,
   the run identifier, the source or template it derives from, and the schema version it was written against.
4. **Given** a run whose output cannot be reproduced exactly, **When** the manifest is written, **Then** it
   records the non-deterministic inputs that explain why, rather than implying reproducibility it cannot
   deliver.
5. **Given** a manifest missing any required element, **When** it is checked, **Then** the check fails and
   names the missing element.

---

### User Story 4 - Control the composition of the corpus (Priority: P4)

An author needs a corpus with a particular shape — weighted toward billing issues, mostly resolved, mostly
email and chat — rather than an arbitrary mix. They express the desired composition in the configuration and
the generator honors it, reporting the composition it actually achieved.

**Why this priority**: Composition control is what makes the corpus useful for a specific downstream task
rather than merely large. It ranks last because a corpus with an arbitrary but valid mix is still a usable
corpus, whereas one that fails the earlier gates is not.

**Independent Test**: Generate a corpus with a specified composition and confirm the achieved distribution
across categories, priorities, channels, and resolution outcomes matches what was requested within the
stated tolerance.

**Acceptance Scenarios**:

1. **Given** a configuration specifying a desired mix of ticket categories, priorities, channels, and
   resolution outcomes, **When** the generator runs, **Then** the achieved composition matches the request
   within the stated tolerance.
2. **Given** any completed run, **When** the author reads the run report, **Then** it states the composition
   actually achieved, not only the composition requested.
3. **Given** a composition request that cannot be satisfied — proportions that do not sum correctly, or a
   combination the generator cannot produce — **When** the run starts, **Then** it refuses and explains
   which part of the request is unsatisfiable.
4. **Given** a configuration that specifies no composition, **When** the generator runs, **Then** it uses a
   documented default distribution rather than an undefined one.

---

### Edge Cases

- **Interrupted run**: A run killed partway must not leave a partially written file in the release path that
  looks complete; incomplete output is distinguishable from finished output, and the run can be resumed from
  its checkpoint.
- **Resume attempted with changed inputs**: Resuming a checkpoint whose configuration, seed, prompt
  document, or rubric no longer matches is refused rather than silently producing a mixed-provenance corpus.
- **Checkpoint corrupted or unreadable**: An unusable checkpoint is reported as such, leaving the operator to
  restart deliberately rather than resuming from an unknown state.
- **Zero records requested**: A request for zero records is refused as a configuration error rather than
  silently producing an empty corpus.
- **Every record discarded**: If all generated records fail the schema or the privacy scan, the run fails
  with the discards fully accounted for, rather than writing an empty artifact.
- **Duplicate output**: Generation may produce identical conversations by chance; the run reports how many
  duplicates it produced so the author can judge corpus diversity.
- **Unicode and multilingual content**: Non-Latin scripts, emoji, and right-to-left text are valid turn
  content and must not be treated as malformed.
- **Very long conversations**: A conversation with an unusually large number of turns is valid; nothing may
  assume a small fixed maximum.
- **Repeated run into an existing path**: Re-running into a path that already holds an artifact must not
  silently overwrite it or, worse, append to it.
- **Judge unavailable while the generator is working**: A record that cannot be scored is discarded and
  accounted for, never admitted unjudged.
- **Judge rejects nearly everything**: A coherence discard rate above threshold fails the run rather than
  quietly producing a corpus far smaller than requested.
- **Model unavailable or rate-limited mid-run**: A long run must survive transient failures without losing
  completed work, and must not silently deliver a smaller corpus than requested.
- **Sustained provider outage**: When retries are exhausted across many consecutive records, the run stops
  and checkpoints rather than burning through the remaining corpus emitting discards.
- **Concurrency changed between runs**: Two runs with the same seed and configuration but different
  concurrency levels must still produce comparable corpora, since seeded choices are position-derived rather
  than order-derived.
- **Model returns unusable output**: A response that is unparseable or structurally invalid is discarded and
  accounted for, not coerced into a record.
- **Prompt document changed between runs**: Two corpora generated from different prompt document versions
  are distinguishable from their manifests, since the document's hash is recorded as a run input.
- **Privacy scan finds content in a field the author considers non-textual**: Every field carrying free text
  is scanned; the set of scanned fields is stated in the report rather than assumed.

## Requirements *(mandatory)*

### Functional Requirements

**Record contract**

- **FR-001**: The project MUST publish a machine-readable, versioned definition of a support ticket record
  covering its conversation turns, ticket metadata, and provenance fields, and the generator MUST write
  against that definition.
- **FR-002**: The definition MUST carry a `MAJOR.MINOR.PATCH` version, and every record MUST declare the
  version it was written against.
- **FR-003**: Each record MUST provide a stable record identifier, the run identifier that produced it, the
  source or template it derives from, and its schema version.
- **FR-004**: Each conversation turn MUST identify its speaker role, its position in the conversation, and
  its content.
- **FR-005**: Permitted speaker roles MUST be enumerated in the definition; any other value is invalid.
- **FR-006**: Each record MUST carry ticket metadata comprising a topic category, a priority level, an
  originating channel, a resolution status, and the times the ticket was created and resolved, each
  constrained to an enumerated set where applicable.
- **FR-007**: The generator MUST validate every record it produces against the definition before writing it,
  and MUST discard and account for any record that does not conform.

**Generation**

- **FR-008**: The generator MUST accept a single serialized configuration, an explicit seed, and a committed
  domain prompt document as its only inputs, and MUST NOT read hidden state from the operator's environment.
- **FR-008a**: Support scenarios MUST derive from a committed domain prompt document, from which the
  generation model elaborates plausible subdomain scenarios. The prompt document is a run input: its
  identifying hash MUST be recorded in the manifest, so a change to it is visible as a change in provenance.
- **FR-008b**: Each record MUST record the subdomain scenario it was generated for, in addition to its
  `source_id`, so that records remain distinguishable and the corpus can be stratified by scenario — the
  prompt document alone is common to every record and cannot serve that purpose.
- **FR-009**: The generator MUST produce coherent multi-turn exchanges in which turns are ordered, are
  non-empty, alternate between participants, and concern a single support issue.
- **FR-009a**: Conversation text MUST be produced by a language model prompted from the domain prompt
  document and the run configuration.
- **FR-009d**: The configuration MUST accept a minimum and maximum turn count, and each conversation's
  length MUST be sampled from that range as a seeded choice, so the length distribution is reproducible even
  though the text is not.
- **FR-009e**: The generator MUST reject and account for any conversation whose turn count falls outside the
  configured range, and MUST refuse to start when the range is invalid (minimum exceeding maximum, or a
  minimum below the smallest coherent exchange).
- **FR-009b**: The generator MUST structurally validate every model response before accepting it as a
  record, and MUST discard and account for any response that is unparseable, structurally invalid, or
  violates the ordering, alternation, non-emptiness, or turn-count constraints in FR-009 and FR-009d.
- **FR-009f**: Every structurally valid record MUST additionally be scored for coherence by a model-based
  judge, against a committed, versioned rubric.
- **FR-009g**: The coherence rubric MUST be a committed artifact whose identifying hash is recorded in the
  manifest as a run input, so a change in judging standards is visible as a change in provenance.
- **FR-009h**: Records scoring below a configured coherence threshold MUST be discarded and accounted for
  under a distinct coherence discard reason. The threshold defaults to **0.8** on a normalized 0–1 scale.
- **FR-009i**: Each accepted record MUST carry the coherence score it received, so the corpus can be
  filtered or stratified by quality without re-judging it.
- **FR-009j**: The identity and parameters of the judging model MUST be recorded in the manifest alongside
  those of the generating model, because the judge is a non-deterministic input that shapes which records
  survive (Constitution Principle II).
- **FR-009k**: A coherence discard rate above a configured threshold MUST fail the run, because a generator
  whose output is mostly rejected is defective and filtering around it would mask the defect. The threshold
  defaults to **10%** of records generated, with "records generated" as defined in FR-026a.
- **FR-009l**: A judge failure MUST NOT silently admit an unjudged record. If a record cannot be scored
  after the configured retries, it MUST be discarded and accounted for under a distinct reason.
- **FR-009c**: The generator MUST tolerate transient model failures without losing completed work — a
  failed or rejected response MUST NOT abort a run that can still proceed, and repeated failure MUST be
  reported as a discard reason rather than silently reducing corpus size.
- **FR-010**: Given the same seed, configuration, and prompt document, the generator MUST produce output
  that is equivalent in structure and composition. Exact textual reproduction is NOT guaranteed, because
  model sampling is not reproducible in general; the manifest MUST therefore record the model identity, its
  parameters, and any sampling seed, so that a run that cannot be replayed can still be audited
  (Constitution Principle II).
- **FR-011**: The generator MUST refuse to run on an invalid or internally contradictory configuration,
  naming the specific problem, rather than producing partial output.
- **FR-012**: The generator MUST write records incrementally so that memory does not grow with corpus size
  and progress is observable during a long run.
- **FR-012a**: The generator MUST process multiple conversations concurrently, with the level of concurrency
  configurable, so that a release-scale corpus is achievable in a single run.
- **FR-012b**: All seeded choices for a record — its turn count, its composition assignment, its scenario
  selection — MUST be derived deterministically from the run seed and the record's position, assigned before
  the record is dispatched. They MUST NOT be drawn from a shared sequential stream, so that output does not
  depend on the order in which concurrent work completes.
- **FR-012c**: Records MUST be written in a deterministic order independent of completion order, so that two
  runs with the same seed and configuration produce corpora comparable record by record.
- **FR-012d**: The generator MUST retry transient failures and rate-limit responses with backoff, and MUST
  report retry counts in the run report so that a degraded provider is visible rather than merely slow.
- **FR-012e**: The generator MUST bound its own request rate so a run cannot be throttled into failure by
  its own concurrency, and the bound MUST be configurable.
- **FR-013**: The generator MUST write output as JSON Lines beneath the project's data directory, placing
  release-path output in a location distinct from scratch and intermediate output.
- **FR-014**: The generator MUST NOT silently overwrite or append to an existing artifact at its output path.
- **FR-015**: An interrupted run MUST NOT leave output in the release path that is indistinguishable from a
  completed run.
- **FR-015a**: A run MUST checkpoint its progress periodically — records written, discard tallies by reason,
  and the state needed to continue seeded choices — so that an interrupted run can resume rather than
  restart.
- **FR-015b**: A resumed run MUST continue from its checkpoint without regenerating or duplicating records
  already written, and MUST NOT reuse a record identifier already issued.
- **FR-015c**: A resumed run MUST produce a single manifest describing the whole corpus, with counts and
  discard accounting reconciling across all segments, so provenance is not fragmented by an interruption.
- **FR-015d**: The manifest MUST record that a run was resumed and how many times, since an interrupted run
  is a material fact about how the corpus was produced.
- **FR-015e**: Resuming MUST be refused when the configuration, seed, prompt document, or rubric differs
  from the checkpointed run, because continuing under changed inputs would produce a corpus the manifest
  cannot honestly describe.

**Privacy gate**

- **FR-016**: Every run MUST scan its own generated output for content matching known categories of real
  personal identifier before that output reaches the release path.
- **FR-017**: Detection MUST be performed by one or more registered detectors behind a common interface, so
  a detector can be added or replaced without changing the record definition or the pipeline.
- **FR-018**: The scan MUST detect at minimum: email addresses, phone numbers, payment card numbers, and
  government identifiers. A detector set that cannot cover this floor MUST fail the run before generation
  rather than producing unvouched output.
- **FR-019**: Categories the scan does not cover MUST be stated in the run report, so a clean result is
  never mistaken for coverage the scan does not provide.
- **FR-020**: Every privacy finding MUST report the record identifier, the field, the category detected, and
  the detector that reported it — and MUST NOT reproduce the matched value itself.
- **FR-020a**: Every privacy finding MUST additionally carry a **masked rendering** of the matched value —
  enough context for a reviewer to recognize a deliberately synthetic value without reproducing the value
  itself. Masking MUST be deterministic, MUST preserve at most the non-identifying remainder of the value
  (for an email, the domain; for a payment card, the issuer range; for other categories, length and shape
  alone), and MUST NOT be reversible. A masked rendering is not the matched value and does not violate
  FR-020.
- **FR-021**: A record carrying an unreviewed privacy finding MUST NOT reach the release path. Such records
  MUST be discarded and accounted for under a distinct privacy discard reason, and the remainder of the
  corpus MUST proceed; the gate MUST NOT be advisory and MUST NOT pass a flagged record through.
- **FR-021b**: A record discarded for a privacy finding MUST be retained in a **quarantine artifact**
  outside the release path, so that a reviewer has something to adjudicate when the masked rendering alone
  is insufficient. The quarantine artifact MUST be identified in the run report, MUST NOT be committed to
  the repository, and MUST NOT be treated as dataset output. Without it, FR-022's approval has no input:
  the record is gone and FR-020 withholds the value, leaving a reviewer asked to judge something no
  artifact contains.
- **FR-021a**: The run report MUST state how many records were discarded for privacy reasons. A discard rate
  above a configured threshold MUST fail the run, because a generator emitting identifiers at volume is
  defective and filtering around it would mask the defect. The threshold defaults to **0.5%** of records
  generated, as defined in FR-026a — synthetic content should almost never trip the scanner, so a higher
  rate signals a real defect rather than noise.
- **FR-022**: Reviewers MUST be able to record a reviewed finding as an approved exception with a stated
  reason; approved exceptions MUST remain visible in the run report and MUST NOT store the matched value.
  A reviewer MUST be able to reach that decision from the masked rendering (FR-020a) or from the quarantine
  artifact (FR-021b), and MUST NOT be required to have observed the original run.
- **FR-023**: The scan MUST report how many records and fields it examined and which detectors ran, so a
  clean result is distinguishable from a scan that examined nothing.
- **FR-024**: Every detector MUST operate without contacting a network service, so the gate is runnable
  offline and yields identical findings for identical input.

**Run manifest and provenance**

- **FR-025**: Every run MUST write a manifest recording the seed, the full serialized configuration, the
  code revision, the identifying hashes of all inputs, the schema version, and the output record count.
- **FR-026**: The manifest MUST account for every discarded record by count and by reason, such that input
  count minus all discards equals output count.
- **FR-026a**: **"Records generated" means every response received from the generating model, counted once
  per attempt.** A slot retried three times contributes three. Every counted response either becomes a
  written record or is discarded under exactly one reason, so FR-026's arithmetic closes as
  `records generated − all discards = records written`. This one definition governs every rate expressed
  as a proportion of records generated — FR-009k and FR-021a included — so that a threshold cannot be
  computed two ways. Note the consequence: a run with heavy retries has a larger denominator, so both
  discard rates are diluted rather than inflated by retrying.
- **FR-027**: The manifest MUST record non-deterministic inputs — including any generation model identity
  and parameters — so a run that cannot be replayed exactly can still be audited.
- **FR-028**: The manifest MUST be validatable, and validation MUST name any missing required element.
- **FR-029**: Every record MUST be traceable to the manifest of the run that produced it using only the
  record's own fields.

**Composition control**

- **FR-030**: The configuration MUST allow the operator to specify a desired distribution across ticket
  categories, priorities, channels, and resolution outcomes.
- **FR-031**: The generator MUST honor a requested distribution within a configurable tolerance, defaulting
  to **±2 percentage points** per controlled dimension, and MUST report the composition actually achieved
  alongside the composition requested. Exceeding the tolerance MUST fail the run.
- **FR-032**: The generator MUST refuse an unsatisfiable composition request and explain which part cannot
  be satisfied.
- **FR-033**: When no composition is specified, the generator MUST apply a documented default distribution,
  including a documented default turn-count range.
- **FR-034**: The run report MUST state how many duplicate conversations were produced, so corpus diversity
  is visible.

**Reporting**

- **FR-035**: Every run MUST produce a report covering records generated, records discarded by reason,
  privacy findings, detectors run, uncovered categories, and achieved composition.
- **FR-036**: The report MUST be available in a machine-readable form so automation can act on it without
  parsing prose, and the run MUST signal success or failure unambiguously.

### Key Entities

- **Ticket Record**: One complete multi-turn support interaction — its ordered turns, its ticket metadata,
  and its provenance fields. The unit generated, validated, scanned, and counted.
- **Conversation Turn**: A single utterance within a record, carrying a speaker role from the permitted set,
  a position establishing order, and its textual content.
- **Ticket Metadata**: The descriptive attributes of the interaction — topic category, priority, originating
  channel, resolution status, and creation and resolution times.
- **Provenance Fields**: The identifiers binding a record to its origin — record identifier, run identifier,
  source or template identifier, and schema version.
- **Record Schema**: The versioned, machine-readable contract the generator writes against.
- **Domain Prompt Document**: The committed markdown document describing the support domain, from which the
  model elaborates subdomain scenarios. A run input; its hash is recorded in the manifest.
- **Subdomain Scenario**: The specific support situation a record was generated for, elaborated by the model
  from the domain prompt and recorded on the record so the corpus can be stratified by scenario.
- **Generation Configuration**: The single serialized object describing what to generate — corpus size,
  desired composition, turn-count range, coherence threshold, concurrency and rate bounds, and model
  parameters. Recorded verbatim in the manifest.
- **Seed**: The explicit value governing the run's random choices.
- **Run Manifest**: The record of how one run produced its output — seed, configuration, code revision,
  input hashes, schema version, counts, discard accounting, model and judge identities, and resume history.
- **Checkpoint**: The persisted progress of an in-flight run — records written, discard tallies, and the
  state needed to continue seeded choices — enabling resumption without duplication.
- **Discard Account**: One reason records were dropped, with its count. Reasons include structural
  invalidity, coherence below threshold, privacy findings, and unjudgeable records.
- **Coherence Rubric**: The committed, versioned document the judging model scores against. A run input;
  its hash is recorded in the manifest.
- **Coherence Score**: The judge's rating of a single record, retained on the accepted record so the corpus
  can be filtered by quality without re-judging.
- **Privacy Finding**: One detected potential identifier, with its record identifier, field, category,
  reporting detector, and review status — never the matched value.
- **Approved Exception**: A reviewer's recorded decision that a specific finding is a legitimate synthetic
  value, with the stated reason.
- **Run Report**: The consolidated outcome of a run — counts, discards, privacy findings, detectors run,
  uncovered categories, and achieved composition.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An author can produce a corpus of 100,000 conversation records in a single run on one machine
  without the run exhausting memory or requiring manual intervention, with concurrency sufficient that the
  run completes within an operator-acceptable window recorded in the configuration.
- **SC-013**: Two runs with the same seed and configuration but different concurrency levels produce corpora
  with identical composition and identical per-position seeded choices, demonstrating that throughput does
  not compromise reproducibility.
- **SC-002**: 100% of records written to the release path conform to the record contract, verified by the
  generator's own pre-write check.
- **SC-003**: For a fixed seed and configuration, two runs produce equivalent corpora — or the manifest
  identifies precisely which inputs made them differ.
- **SC-004**: No corpus containing an unreviewed potential personal identifier can reach the release path,
  demonstrated by an end-to-end attempt that is blocked.
- **SC-005**: For any corpus, the counts reconcile exactly: records generated minus the sum of all discard
  reasons equals records written, with no unexplained difference — including across a run that was
  interrupted and resumed.
- **SC-012**: An interrupted run resumes and completes without regenerating already-written records or
  duplicating record identifiers, demonstrated end to end by killing and resuming a run.
- **SC-006**: Someone who did not run the generator can determine the seed, configuration, code revision,
  and inputs behind any corpus from its manifest alone, in under five minutes.
- **SC-007**: Any single record can be traced to the run that produced it and the source it derives from,
  using only the record's own fields.
- **SC-008**: A requested composition is achieved within ±2 percentage points across every controlled
  dimension, and the achieved composition is reported for every run.
- **SC-009**: Every record written to the release path carries a coherence score at or above the configured
  threshold, and the run reports the score distribution across the corpus so quality is visible rather than
  assumed.
- **SC-011**: The coherence judge is calibrated at least once against human judgment on a sample before a
  corpus is released, so the automated gate is known to track what a reviewer would conclude rather than
  being trusted on faith.
- **SC-010**: A new contributor can generate their first corpus using the project's documentation alone.

## Assumptions

- **Synthetic by construction**: Conversations are fabricated, not derived from real support transcripts.
  The privacy scan is a safety net confirming that held, not the primary control.
- **Line-delimited output**: Corpora are written one record per line, per the constitution's designation of
  JSON Lines as the dataset source of truth.
- **Two-party conversations by default**: Records represent a customer and a support agent. Additional roles
  are accommodated by enumerating them in the schema rather than by relaxing coherence expectations.
- **English-first, not English-only**: Initial content is expected to be English, but nothing may assume it;
  multilingual and non-Latin content must be valid.
- **Quarantined records are synthetic, not personal data**: A record held in quarantine (FR-021b) is
  fabricated content that a pattern detector found identifier-shaped — not a real identifier. That is why
  retaining it under the project's intermediate output is compatible with the constitution's requirement
  that no real personal data enter `data/` in any form: the requirement is about provenance of the content,
  not about its shape. The quarantine artifact is never committed and is never dataset output, and the
  approved-exception file continues to store fingerprints rather than values, so nothing identifier-shaped
  accumulates in the repository itself.
- **The blocking floor is bounded by what offline detection can do**: The mandatory categories are those an
  offline pattern detector covers with high precision. Full postal addresses, bank account numbers, and
  person names are NOT gated — reliable offline detection of them is unavailable — and this residual risk is
  accepted because records are synthetic by construction. FR-019 requires the gap be stated in every report.
- **Composition tolerance is proportional**: Requested distributions are honored within a tolerance rather
  than exactly, because integer record counts cannot hit arbitrary proportions precisely. The ±2 percentage
  point default is comfortably achievable at release scale but may be unreachable on very small corpora,
  where the operator is expected to widen it deliberately.
- **Thresholds are defaults, not constants**: The four documented thresholds — composition ±2pp, privacy
  discard 0.5%, coherence discard 10%, coherence score 0.8 — are starting values chosen to make the
  requirements testable from the first run. They are configurable, and the coherence values in particular
  should be revisited once the rubric has been calibrated against human judgment (SC-011).
- **Generation requires network access; the privacy gate does not**: Producing conversations calls a hosted
  model, so a run needs credentials and connectivity. The privacy scan is deliberately offline and
  deterministic (FR-024), so the gate that protects the release path never depends on a remote service.
- **Model cost and time scale with corpus size, and judging roughly doubles both**: Every record costs at
  least two model calls — one to generate, one to judge — so a 100,000-record corpus is on the order of
  200,000 calls before retries and discards. SC-001 asserts the pipeline can produce that in one run without
  exhausting memory or needing manual intervention; it does not assert the run is cheap or quick. Budgeting
  and rate-limit strategy are planning concerns, and generating a smaller corpus is the normal case.
- **The coherence gate is non-deterministic and must be treated as such**: Judging is a model call, so the
  set of records that survive is not perfectly reproducible. This is why the judge's identity, parameters,
  rubric hash, and each record's score are all recorded — the gate is auditable even though it is not
  deterministic. FR-024 keeps the *privacy* gate offline and deterministic precisely so the irreversible-risk
  control never inherits this property.
- **Exact textual reproducibility is not claimed**: Model sampling is not reproducible in general. The
  constitution anticipates this by requiring non-deterministic inputs to be captured, so runs are auditable
  rather than bit-identical. Structure and composition remain reproducible.
- **Scenario variety rests on the prompt document**: Corpus diversity depends on the model elaborating
  varied subdomains from one committed prompt. FR-034's duplicate reporting is the feedback signal for
  whether that is working; a high duplicate rate indicates the prompt needs broadening.
- **The validation tool is a separate feature**: Checking datasets that external tools have postprocessed is
  feature 002. This feature validates only its own output, before writing it.
- **No released corpus is a deliverable here**: This feature ships the pipeline. Deciding to publish a
  particular corpus — with its datasheet and sampled human review — is a separate act governed by the
  constitution's release rules.
