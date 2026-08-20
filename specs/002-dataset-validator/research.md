# Phase 0 Research: Record Schema & Validation Harness

> ⚠️ **Superseded scope.** Written as feature 001 under the framing that validation was the primary
> deliverable. The generator is the product; this is a complementary tool. Schema, run manifest, and
> the blocking PII scan moved to feature 001. See the banner in `spec.md`. Kept for reuse; do not
> implement from it as-is.

**Feature**: [spec.md](./spec.md) | **Date**: 2026-08-18

All Technical Context unknowns are resolved below. No `NEEDS CLARIFICATION` items remain.

---

## R1: Schema source of truth — typed model vs. standalone JSON Schema

**Decision**: Define records as **Pydantic v2 models**, and commit a **generated JSON Schema** export as a
build artifact checked in alongside them. The Pydantic model is authoritative; the JSON Schema is the
language-neutral publication of the same contract, regenerated and diff-checked in CI.

**Rationale**: Constitution Principle I accepts "JSON Schema or an equivalent typed model" but demands the
contract be committed and machine-readable. Pydantic v2 gives runtime validation, static types for
FR-029's programmatic API, and `model_json_schema()` export in one definition — no drift between a
hand-written schema and the code enforcing it. Committing the export keeps the contract readable by
non-Python consumers and makes breaking changes visible in review as a schema diff, which is what
FR-002a's MAJOR-bump rule needs to be enforceable. Pydantic v2 is already a transitive dependency of
`datafog`, so it costs nothing new.

**Alternatives considered**:
- *JSON Schema as source of truth, models generated from it*: better for polyglot consumers, but code
  generation adds a build step and the generated models are awkward to extend with the validation logic
  FR-006c needs (timestamp consistency).
- *Dataclasses + hand-written validators*: no dependency, but re-implements parsing, coercion, and error
  reporting that Pydantic already does well, and produces worse per-field error messages than FR-009 wants.

---

## R2: PII detection engine

**Decision**: Use **`datafog >= 4.8, < 5`** with the **core (regex) install — no extras** — wrapped behind
the project's own detector interface. Force telemetry off via `DATAFOG_TELEMETRY=0` set by the wrapper.

**Rationale**: Verified against PyPI (v4.8.1): `requires_python >= 3.10` with an explicit 3.14 classifier,
matching this project's `>=3.14` pin. The core install's only runtime dependencies are `pydantic`,
`pydantic-settings`, and `typing-extensions` — no model downloads, no network, satisfying FR-013c.
Detection is regex-based and therefore deterministic: identical input yields identical findings, which
FR-013c also requires. The public API is stable and simple: `datafog.scan(text, engine="regex").entities`.
Telemetry is documented as disabled by default and can be forced off with `DATAFOG_TELEMETRY=0`; the
wrapper sets it explicitly rather than trusting the default, so the offline guarantee does not depend on
upstream defaults staying unchanged.

**Alternatives considered**:
- *Microsoft Presidio*: broader entity coverage, but pulls spaCy models, needs downloads (breaking the
  offline requirement), and is markedly slower — a poor fit for scanning every field of 100k records.
- *`datafog[nlp]` with spaCy*: would add address and name detection, but requires model downloads at
  install or first use, violating FR-013c, and introduces non-determinism across model versions.
- *Hand-rolled regexes only*: no dependency, full control, but re-implements well-tested detectors and
  puts the burden of correctness for card and SSN checksums on this project.

---

## R3: Blocking floor scoped to the detector's real regex coverage

**Decision**: Set the FR-013d blocking floor to exactly the four categories `datafog`'s regex engine covers
with high precision — `EMAIL`, `PHONE`, `CREDIT_CARD`, `SSN` (government identifier). **One detector, no
supplementary pattern detector.** Postal address and bank account are removed from the floor and recorded
as known gaps (FR-013e). `IP_ADDRESS` and `ZIP_CODE` are available and may be registered as advisory,
non-blocking categories (FR-013f).

**Rationale**: Verified coverage of the regex engine (no extras, offline): its default structured set is
`EMAIL`, `PHONE`, `SSN`, `CREDIT_CARD`, `IP_ADDRESS`, `DATE`, `ZIP_CODE`, of which the first four are the
documented *high-precision* set that blocks by default. Bank account exists only as the country-specific
`DE_IBAN` under an opt-in German locale, which does not fit an English-first corpus; full postal address is
not covered by the regex engine at all and would require the spaCy/GLiNER extras that R2 rejects for
breaking the offline and determinism guarantees.

Narrowing the floor to what can actually be detected makes the gate's promise honest. A floor naming
categories nothing detects would have produced "clean" verdicts that overstate coverage — the same silent
overclaim the floor exists to prevent, merely relocated from the detector to the specification. FR-013e
requires the report to state the excluded categories, so the gap is visible at the point of use rather than
buried in a spec. The residual risk is accepted because records are synthetic by construction (the scan is
a safety net, not the primary control) and the registry (FR-013a) admits an address or IBAN detector later
without reopening the schema, the finding format, or the gate.

**Not enabled**: generic `DATE` detection. Every record legitimately carries ticket timestamps, so it would
fire on nearly every record and train maintainers to ignore the report.

**Alternatives considered**:
- *Add a project-owned pattern detector for IBAN and street addresses*: keeps the wider floor, but puts the
  correctness of hand-rolled address regexes on this project, and address patterns are inherently
  low-precision — the false-positive load would push most findings through the exception path.
- *Enable the German locale entity types*: adds `DE_IBAN`, but only for German-formatted values in a corpus
  assumed English-first; misleading coverage for the effort.
- *`datafog[nlp]` for addresses*: rejected in R2 — model downloads break the offline requirement.

## R4: Approved-exception storage without creating a PII store

**Decision**: Store approved exceptions in a committed file as **fingerprints, never raw values**. A
fingerprint is `sha256(category + ":" + normalized_matched_value)`, recorded with the category, the
reviewer's stated reason, and the date. Suppression is applied **in the registry layer** after detectors
run — not by passing values to a detector's own allowlist.

**Rationale**: An exception file listing the literal strings that tripped the scanner would itself become a
file of identifier-shaped values inside the repository, which is precisely what Principle IV forbids
letting accumulate. Fingerprints give stable, reviewable suppression with no recoverable value. Applying
suppression in the registry rather than via `datafog`'s `allowlist=` parameter keeps the behavior identical
across detectors — a value approved once stays approved even if the detector that found it is swapped,
which is the whole point of FR-013a's replaceable-detector design. Findings remain visible in the report as
approved exceptions (FR-016) because suppression changes their blocking status, not their presence.

**Alternatives considered**:
- *`datafog`'s native `allowlist` / `allowlist_patterns`*: convenient and upstream-supported, but requires
  the literal value, is detector-specific, and would not carry across a detector swap.
- *Storing raw values with an ignore-file convention*: simplest, but creates the PII store described above.

---

## R5: Streaming, memory, and the 100k-record target

**Decision**: Process JSONL **line-by-line with the standard library's `json`**, holding only per-record
state plus two accumulators: a `set` of seen record IDs, and a `dict` mapping content fingerprints to the
first record ID that carried them. Report findings incrementally rather than accumulating whole records.

**Rationale**: SC-008 targets minutes for 100k records on one machine, and FR-012 forbids whole-file loads.
Line-oriented reading makes memory independent of file size. The two accumulators are the only unavoidable
O(n) structures: at 100k records, ~100k 32-byte digests plus IDs is single-digit MB — negligible. Standard
`json` parses well within budget at this scale; introducing `orjson` would be premature optimization
against an unmeasured target.

**Alternatives considered**:
- *`orjson` / `msgspec`*: measurably faster parsing, but an added dependency for a target the stdlib is
  expected to meet. Recorded as the first lever to pull if SC-008 is missed.
- *Load-all-then-validate*: simplest code, directly violates FR-012.
- *Multiprocessing*: real speedup available, but adds ordering and error-aggregation complexity for a
  target that should be met single-threaded. Deferred until measurement justifies it.

---

## R6: Exact-duplicate detection method

**Decision**: Fingerprint each record as `sha256` over its **turn sequence only** — each turn's role and
its whitespace-normalized content, joined with a separator — excluding provenance and metadata fields.
First record wins; later matches are reported as duplicates of that group.

**Rationale**: FR-018a defines duplicates as identical turn sequences after insignificant-whitespace
normalization. Excluding provenance is essential: record IDs and run IDs differ by construction, so
including them would make every record unique and the check useless. Excluding ticket metadata is the
narrower call — two identical conversations filed under different categories are still duplicated
conversational content, which is what damages training value. A digest keeps memory flat per R5.

**Alternatives considered**:
- *Fingerprint the whole record*: trivially defeated by differing provenance; catches nothing.
- *Include metadata in the fingerprint*: would let an identical conversation reappear under each category,
  padding the corpus in exactly the way the check exists to prevent.

---

## R7: CLI framework

**Decision**: **Typer** for the command-line wrapper, one subcommand per gate plus a composite `gate`
command.

**Rationale**: The CLI has roughly five subcommands sharing common options (input path, schema version,
report format, exceptions file). Typer derives parsing from type hints, so the wrapper stays declarative
and holds no logic of its own — directly serving FR-032's requirement that the CLI not implement checking
behavior. It is pure-Python and small (`click` + `typer`), and it makes exit-status conventions (FR-031)
straightforward.

**Alternatives considered**:
- *`argparse`*: zero dependencies, but manual parser wiring for five subcommands with shared options is
  exactly the hand-written glue that tends to accrete logic, working against FR-032.
- *`click` directly*: equivalent capability; Typer's type-hint derivation is the deciding ergonomic edge.

---

## R8: Capturing code revision and input hashes for the manifest

**Decision**: Record the git commit SHA via `git rev-parse HEAD` plus an explicit **dirty-tree flag** from
`git status --porcelain`; hash inputs with `sha256` over file contents. If the tree is dirty or the
repository is unavailable, record that fact rather than omitting the field.

**Rationale**: Principle II requires runs to be replayable or *auditable*. A commit SHA recorded from a
dirty working tree silently misrepresents what produced the artifact; the dirty flag makes that condition
explicit and reviewable instead of invisible. Refusing to write a manifest at all when the tree is dirty
would block ordinary development, so recording the caveat is the right trade.

**Alternatives considered**:
- *Commit SHA only*: fails silently in the common case of an uncommitted local change.
- *Full source snapshot in the manifest*: complete provenance, but bloats every manifest and duplicates
  what version control already stores.

---

## R9: Report format

**Decision**: One **structured report object** (Pydantic model) serialized to JSON as the machine-readable
verdict, with a separate human-readable text renderer over the same object. The CLI exit status derives
from the object's verdict field.

**Rationale**: FR-011 requires both a machine verdict and a human report, and FR-032 requires both
interfaces to agree. Deriving every surface — JSON, text, exit status — from one object makes disagreement
structurally impossible rather than a thing to test for. Findings carry record ID, gate, category, and
detector, satisfying FR-009, FR-014, and FR-013b.

**Alternatives considered**:
- *Text output parsed by CI*: explicitly rejected by FR-031's exit-status requirement and fragile.
- *SARIF*: strong tooling story, but designed for static analysis of code and awkward for per-record data
  findings.
