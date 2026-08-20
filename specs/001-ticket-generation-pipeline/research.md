# Phase 0 Research: Ticket Generation Pipeline

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-19

Each entry records a decision, why it was chosen, and what was rejected. Entries **R7–R10** are carried
forward from the superseded feature's research (`specs/002-dataset-validator/research.md`), which verified
the privacy engine's real coverage; they are restated here because the privacy gate now lives in this
feature and a plan should not depend on a superseded document to be readable.

---

## R1: Model access — SDK, model identity, and structured responses

**Decision**: Call Claude through the official **`anthropic` Python SDK** using **`AsyncAnthropic`** with the
`DefaultAioHttpClient` backend (`anthropic[aiohttp]`). Default model for both generation and judging is
**`claude-opus-5`**, configurable per role. Responses are constrained with
`output_config={"format": {"type": "json_schema", "schema": ...}}` on `client.messages.create`, where the
schema is `model_json_schema()` of the corresponding Pydantic wire model. Adaptive thinking
(`thinking={"type": "adaptive"}`) with `output_config.effort` configurable per role. Server-side refusal
fallback is enabled by default (`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`).

**Rationale**: The SDK is the supported surface, handles auth resolution (`ANTHROPIC_API_KEY`, then
`ANTHROPIC_AUTH_TOKEN`, then an `ant auth login` profile), and already retries 408/409/429/5xx with
exponential backoff — FR-012d gets a correct baseline for free, and the pipeline layers its own accounting
on top rather than reimplementing transport. The aiohttp backend is the documented choice for
high-concurrency async workloads, which FR-012a requires.

`output_config.format` is preferred over `client.messages.parse()` because **FR-009b makes structural
validation our own obligation**: every response must be validated and every failure accounted for under a
named discard reason. Owning the `json.loads` → Pydantic step keeps that accounting in one place and keeps
the code path identical whether the response was constrained or not, so a malformed response is a *discard*
rather than an exception from inside the SDK. Constraining the format still matters — it makes malformed
responses rare rather than routine.

Refusal fallback is enabled because a safety decline on a support-conversation prompt would otherwise be a
pure loss (a discarded slot and a wasted call). It has a provenance consequence, and the design absorbs it:
the model that actually served a record is recorded **on the record** (`generation.model_id`), not only in
the manifest, so a fallback cannot silently make the manifest's single "model identity" field a lie
(Principle II, FR-027).

**Alternatives considered**:
- *`client.messages.parse()` with `output_format=<PydanticModel>`*: less code, but moves validation failure
  into an SDK exception path and out of the discard-accounting path FR-009b requires.
- *Strict tool use as the output channel*: equivalent constraint strength, but a tool call is a worse fit
  than a response format for "return one document", and it is incompatible with some other options.
- *Assistant prefill to force JSON*: rejected outright — prefills return 400 on Claude Opus 5.
- *Raw HTTP via `httpx`*: no benefit; loses typed errors, retry policy, and auth resolution.

---

## R2: Deterministic per-record seeded choices

**Decision**: Derive every seeded choice for slot `p`, attempt `a` from a **counter-based key**, not a
shared stream: `Random(int.from_bytes(blake2b(f"{seed}/{p}/{a}".encode(), digest_size=8).digest()))`. Each
slot gets its own independent generator, constructed on demand before dispatch.

**Rationale**: FR-012b forbids drawing seeded choices from a shared sequential stream, because under
bounded concurrency the draw order is the completion order, which is not reproducible. Counter-based
derivation makes each slot's choices a pure function of `(seed, position, attempt)` — independent of
concurrency level, scheduling, retries, and resume. This is precisely what SC-013 measures: two runs at
different concurrency produce identical per-position choices. `blake2b` is in the standard library, is
fast, and gives well-distributed keys; the attempt component means a retried slot re-rolls its non-metadata
choices rather than repeating a draw that already failed. Ticket timestamps are drawn the same way (FR-006a), which is what
makes FR-012b's list of seeded choices exhaustive rather than illustrative — a per-record value outside that
list would be a hole in the reproducibility claim. The slot's **subdomain** is drawn with this
generator from the prompt document's declared list (FR-008d), which is what makes FR-012b's claim about
scenario selection true: the subdomain is seeded and comparable across runs, while the situation the model
elaborates within it is model output and is not.

**Alternatives considered**:
- *One `random.Random(seed)` advanced sequentially*: the obvious approach and explicitly prohibited by
  FR-012b — order-dependent under concurrency.
- *Pre-materializing all choices into a list before dispatch*: order-independent and correct, but holds
  per-record state for the whole corpus in memory, contradicting FR-012's memory requirement at 100k.
- *`numpy` `PCG64` with `jumped()` streams*: a well-established counter-like scheme, but adds a dependency
  for something eight lines of stdlib already do.

---

## R3: Composition control by assignment, not by rejection

**Decision**: Treat the run as **N ordered slots**. Before any model call, apportion the requested
distribution across those N slots by the **largest-remainder (Hamilton) method** per dimension, then
assign each slot's `(category, priority, channel, resolution_status)` by a seeded permutation of the
apportioned pools. The model is told what metadata to write a conversation *for*; it does not choose the
metadata. A discarded slot is **refilled by retrying the same slot** with its assignment intact.

**Rationale**: This makes composition correct by construction rather than by measurement and correction.
Largest-remainder is the standard apportionment method for turning proportions into integer counts and
bounds **per-member** error below one record — that is, below `1 / record_count` in proportion terms, far
inside the ±2 percentage point tolerance of FR-031 for any corpus of meaningful size, and the arithmetic
basis for FR-031b's refusal when a corpus is too small for the tolerance it asks for. The tolerance is
checked per member rather than in aggregate (FR-031), so a badly-served category cannot hide behind
well-served ones. The only thing that can perturb achieved composition is discards, and retrying
the *same slot* rather than appending a fresh one keeps the pools intact, so a discard costs calls and time
but not shape. The tolerance in FR-031 then covers the residue: slots that exhaust their attempts.

Assignment-first also resolves the tension in FR-032 cleanly — an unsatisfiable request (proportions that
do not sum to 1, a dimension with an unknown member, N too small for a requested proportion to round to a
whole record) is detectable at apportionment time, before a single call is made.

**Alternatives considered**:
- *Let the model choose metadata, then measure and fail on drift*: simplest prompt, but composition becomes
  a property to be discovered after paying for 100k calls, and FR-031's "exceeding the tolerance fails the
  run" turns into an expensive coin flip.
- *Rejection sampling toward the target distribution*: hits the target, but wastes calls proportionally to
  how skewed the request is, and the discard tallies would then mix "generator defect" with "sampling
  overhead" — corrupting the FR-009k/FR-021a defect signals.
- *Appending replacement slots at the end instead of retrying in place*: keeps the corpus count exact, but
  a replacement drawn from the remaining pool at the end distorts nothing while the run is healthy and
  distorts everything when discards cluster in one category.

---

## R4: Concurrency, rate limiting, and retry

**Decision**: **`asyncio`** with a bounded worker pool (`asyncio.Semaphore`, configurable
`max_concurrency`, default 8) fed from a slot iterator, plus a project-owned **token-bucket limiter** on
requests per minute (configurable, default 1000 rpm, applied across both model roles). Transport-level
retry stays with the SDK (`max_retries`, default 4 here); the pipeline adds **slot-level** retry with its
own attempt counter, and a **consecutive-failure circuit breaker** that stops the run and checkpoints.

**Rationale**: The workload is I/O-bound with two dependent calls per record, which is asyncio's core
competence; threads would add no throughput and would complicate the deterministic write path. A separate
token bucket is needed because the SDK's retry reacts to 429s *after* they happen, and FR-012e requires the
run to bound its own request rate so it cannot throttle itself into failure. Keeping transport retry
(429/5xx/connection) distinct from slot retry (refusal, unparseable output, judge failure) matters for
honesty in the report: FR-012d asks for retry counts so a degraded provider is visible, while FR-009c/FR-009l
ask for discard reasons — these are different facts and must not be summed into one number. The circuit
breaker implements the "sustained provider outage" edge case: exhausting retries across many consecutive
slots means stop and checkpoint, not burn the remaining corpus emitting discards.

**Alternatives considered**:
- *`concurrent.futures.ThreadPoolExecutor` with the sync client*: fewer async idioms to test, but no gain
  on I/O-bound work and a clumsier fit for a rate limiter shared across two call sites.
- *Relying on the SDK's retry alone*: violates FR-012e (no self-imposed bound) and leaves FR-012d's retry
  counts unobservable, since the SDK's internal retries are not surfaced per request.
- *Adaptive concurrency that tunes itself from 429 feedback*: attractive for throughput, but it makes the
  run's request pattern depend on provider state, and it is not needed to satisfy any requirement.

---

## R5: Deterministic write order, incremental output, and the staging path

**Decision**: Completed slots land in a small **reorder buffer** keyed by position; the writer emits
records strictly in ascending slot order to a **staging file under `data/interim/<run_id>/`**, and the
finished artifact is **atomically moved** (`os.replace`) into `data/release/` only after the run completes
successfully. The buffer is bounded by `max_concurrency`, so memory does not grow with corpus size.

**Rationale**: FR-012c demands an output order independent of completion order, and a reorder buffer is the
minimal structure that provides it while still writing incrementally (FR-012). Because at most
`max_concurrency` slots are in flight, the buffer holds at most that many records regardless of N —
satisfying FR-012's memory requirement at 100k without buffering the corpus.

Two-phase staging is what makes FR-014 and FR-015 true rather than aspirational, and FR-015 now requires the
location rule rather than merely permitting it: an interrupted run leaves its partial file in
`data/interim/`, which is not the release path, so nothing in `data/release/` can ever be mistaken for a
complete artifact. Distinguishing by location cannot be defeated by a partial write or a naming mistake, as
a suffix convention can. The atomic rename is the moment an artifact exists. The constitution's
directory separation (`data/raw/`, `data/interim/`, `data/release/`) is doing real work here rather than
being a naming convention. The pre-flight check refuses to start when the destination path already exists.

**Alternatives considered**:
- *Write directly to the release path with a `.partial` suffix and rename in place*: fewer moving parts,
  but places incomplete data in the release directory, which the constitution separates by location
  precisely so that inspection by location alone is reliable.
- *Write in completion order and sort afterwards*: needs a full pass over the corpus and either holds it in
  memory or writes it twice; a bounded buffer gets the same guarantee for free.
- *One file per record, concatenated at the end*: trivially order-independent, but produces 100k files and
  makes the interrupted-run story worse, not better.

---

## R6: Checkpoint and resume

**Decision**: The checkpoint is a **JSON sidecar** at `data/interim/<run_id>/checkpoint.json` holding:
`next_position`, `bytes_written` for the staging file, discard tallies by reason, retry counts, the
duplicate-fingerprint count, the **input fingerprint set** (config hash, seed, prompt document hash, rubric
hash, schema version), and a `resumes` counter. It is written by the same single writer task that appends
records, after `flush()` + `os.fsync()`, every `checkpoint_interval` records (default 100) — written to a
temp file and `os.replace`d, so a checkpoint is never half-written. Resume **truncates the staging file to
`bytes_written`** and continues from `next_position`.

**Rationale**: Because writes are strictly in slot order (R5), the staging file is always a *prefix* of the
final corpus, which is what makes a single integer (`bytes_written`) a sufficient recovery point — truncate
and continue, with no scanning, no partial-line parsing, and no possibility of a duplicated record
(FR-015b). Record IDs are derived deterministically from `(run_id, position)` (R2, and the data model), so
resumption cannot reissue an identifier even if a slot is regenerated. Comparing the input fingerprint set
before resuming implements FR-015e: a changed config, seed, prompt document, or rubric makes the checkpoint
inapplicable, and resuming is refused rather than producing a corpus the manifest cannot honestly describe.
The same fingerprints identify *which* run to resume when the operator names none (FR-015h). The **code
revision is deliberately excluded** from that set: a changed revision is recorded as an additional manifest
segment rather than refused (FR-015f), because discarding hours of a release-scale run over an edit made
while it was interrupted trades away far more than it protects. The `resumes` counter satisfies FR-015d, and
carrying the tallies in the checkpoint is what lets FR-015c's single reconciled manifest survive an
interruption.

**Alternatives considered**:
- *Reconstruct state by re-reading the staging file on resume*: no sidecar to keep consistent, but discard
  tallies and retry counts are not recoverable from the surviving records — FR-015c's reconciliation would
  be lost at exactly the moment it matters.
- *SQLite as the checkpoint store*: durable and transactional, but introduces a second persisted format for
  a structure that is one small object, and the constitution names JSONL as the source of truth.
- *Checkpoint after every record*: maximal safety, two extra fsyncs per record; the interval is
  configurable so an operator can choose that trade explicitly.

---

## R7: PII detection engine *(carried forward from the superseded feature, R2)*

**Decision**: **`datafog >= 4.8, < 5`** with the **core (regex) install — no extras** — behind this
project's own detector interface, with `DATAFOG_TELEMETRY=0` set explicitly by the wrapper.

**Rationale**: Verified against PyPI (v4.8.1): `requires_python >= 3.10` with a 3.14 classifier, matching
this project's pin. The core install's only runtime dependencies are `pydantic`, `pydantic-settings`, and
`typing-extensions` — no model downloads and no network, satisfying FR-024. Regex detection is
deterministic, so identical input yields identical findings, which FR-024 also requires. The wrapper sets
telemetry off rather than trusting an upstream default to stay unchanged.

**Alternatives considered**: *Presidio* (pulls spaCy models, needs downloads, markedly slower);
*`datafog[nlp]`* (adds names and addresses but requires model downloads and varies across model versions);
*hand-rolled regexes* (re-implements card and government-ID checksums this project would then own).

---

## R8: Blocking floor scoped to real detector coverage *(carried forward, R3)*

**Decision**: The FR-018 blocking floor is exactly the four high-precision regex types: `EMAIL`, `PHONE`,
`CREDIT_CARD`, `US_SSN` — named at identifier-type level, because "government identifiers" would promise
coverage of non-US identifiers that nothing detects. `IP_ADDRESS` and `POSTAL_CODE` are registered as advisory,
non-blocking. Non-US government identifiers, full postal address, and bank account are **declared gaps**;
every run report enumerates covered and uncovered types alike, at the same specificity as the floor, so a
later detector widens coverage visibly rather than silently (FR-019). Generic `DATE` detection stays off — every record carries legitimate ticket timestamps, and a
detector that fires on nearly every record trains maintainers to ignore the report.

**Rationale**: A floor naming categories nothing detects produces "clean" verdicts that overstate coverage —
the exact silent overclaim the gate exists to prevent, merely relocated from the detector to the spec. The
registry (FR-017) admits an address or IBAN detector later without touching the record schema, the finding
format, or the gate. Residual risk is accepted because records are synthetic by construction; the scan is a
safety net, not the primary control. The registry asserts floor coverage at **startup** and fails closed,
which is what makes FR-018's "fail before generation" real.

**Alternatives considered**: a project-owned address/IBAN regex detector (low precision, would push most
findings through the exception path); enabling the German locale for `DE_IBAN` (misleading coverage for an
English-first corpus); `datafog[nlp]` (rejected in R7).

---

## R9: Approved exceptions without creating a PII store *(carried forward, R4)*

**Decision**: Approved exceptions are stored in a committed file as **fingerprints, never raw values**:
`sha256(category + ":" + normalized_value)`, with the category, the reviewer's stated reason, and the date.
Suppression is applied in the **registry layer**, after detectors run.

**Rationale**: A file listing the literal strings that tripped the scanner would itself be a file of
identifier-shaped values in the repository — precisely what Principle IV forbids accumulating. Applying
suppression in the registry rather than through a detector's own allowlist keeps behavior identical across
detectors, so a value approved once stays approved after a detector swap. Suppression changes a finding's
*blocking status*, not its presence: FR-022 requires approved exceptions to stay visible in the report.

**Alternatives considered**: `datafog`'s native `allowlist` (requires the literal value, detector-specific);
storing raw values behind an ignore-file convention (creates the PII store described above).

---

## R10: Code revision and input hashes *(carried forward, R8)*

**Decision**: Record the git commit SHA from `git rev-parse HEAD` **plus an explicit dirty-tree flag** from
`git status --porcelain`; hash every input file with `sha256` over its contents. When the tree is dirty or
the repository is unavailable, record that fact rather than omitting the field. This is now required rather
than merely chosen: FR-025a promotes it, so a future revision cannot drop it silently.

**Rationale**: Principle II requires runs to be replayable or auditable. A SHA recorded from a dirty tree
silently misrepresents what produced the artifact; the flag makes the condition reviewable. Refusing to
write a manifest at all on a dirty tree would block ordinary development, so recording the caveat is the
right trade.

**Alternatives considered**: SHA only (fails silently in the common case of an uncommitted change); a full
source snapshot in the manifest (complete, but bloats every manifest and duplicates version control).

---

## R11: Judging — rubric, scoring, and the calibration gap

**Decision**: A **committed, versioned rubric** at `prompts/coherence-rubric.md` declaring its `rubric_id`,
version, criteria, and per-criterion weights (FR-009p); its `sha256` is a manifest input hash (FR-009g). The
judge receives the record's turns and the rubric and returns a **constrained JSON object** of per-criterion
scores plus a short justification, and the pipeline computes the coherence score as their **weighted mean**
rather than trusting a holistic number the model reports alongside them. The judge defaults to the same
model as the generator. The record retains only `coherence_score` and
`rubric_id` plus the judging model's identity (FR-009i). SC-011 calibration is supported by a
`sample-for-review` CLI command that exports a seeded random sample with scores for human comparison; the
calibration itself is a documented human procedure, not an automated gate.

**Rationale**: A rubric that lives in a prompt string is a rubric that changes invisibly; committing it and
hashing it into the manifest makes a change in judging standards a change in provenance, which is what
FR-009g asks for. Declaring criteria and weights rather than prose is what gives the 0.8 threshold a stable
meaning — a holistic score means whatever the model reads the prose to mean and drifts with the model —
and it lets a low score be attributed to a criterion during calibration. Sharing the generator's model is
the accepted default: self-preference bias is real, but the judge scores declared criteria rather than
choosing between candidates, and SC-011's calibration is what would expose it. Pointing the roles at
different models is then a configuration change, not a code change. Constraining the judge's response makes an unparseable score impossible in the normal
case and a clean discard (FR-009l) in the abnormal one. Sub-scores and justification are useful during
calibration but are deliberately **not** persisted on the record — they would multiply corpus size for
information that is only meaningful next to the rubric version that produced it.

SC-011 cannot be satisfied by code: it asserts that a human has compared the judge against their own
judgment. What the pipeline owes is the sampling and export that makes the comparison cheap, plus honest
labeling that an uncalibrated threshold is a default rather than a validated one.

**Alternatives considered**:
- *Self-consistency judging (N judges, majority vote)*: better signal, N× the cost on a workload that is
  already two calls per record; revisit after calibration shows single-judge variance.
- *Embedding-based or heuristic coherence scoring*: cheap and deterministic, but does not measure what the
  rubric describes, and would require a model dependency the offline privacy gate deliberately avoids.
- *Persisting the full judge response per record*: maximal auditability, materially larger corpus; the
  score plus rubric ID is enough to re-derive by re-judging.

---

## R12: Online concurrent requests vs. the Batch API

**Decision**: **Online concurrent requests** (R4) for the shipped pipeline. The Message Batches API is
recorded as the identified cost lever for release-scale runs and is **not** implemented in this feature.

**Rationale**: Batches cost 50% less, which is material at ~200,000 calls, but the requirements pull the
other way: FR-012 wants incremental writes with observable progress, FR-015a wants periodic checkpoints,
and the pipeline is a two-stage dependency (judge the generated record) that a single batch cannot express
without a second batch keyed off the first's results. Batch results also arrive in arbitrary order and must
be keyed by `custom_id`, which is compatible with the slot design but adds a second, differently-shaped
execution path. Shipping one correct path first, with the slot model already keyed by position, leaves the
batch path as an additive change rather than a rewrite.

**Alternatives considered**:
- *Batch-only pipeline*: cheapest per record, but a 24-hour completion window and no incremental progress
  contradict FR-012 and make the interrupted-run story worse.
- *Hybrid — batch generation, online judging*: plausible and probably the right eventual answer; deferred
  because it doubles the execution paths to test before the first corpus exists.

---

## R13: Duplicate reporting

**Decision**: Fingerprint each accepted record as `sha256` over its **turn sequence only** — each turn's
role and content, in order, with no metadata and no identifiers. Hold a `set` of fingerprints for the run;
count collisions and report the total (FR-034). Duplicates are **reported, not discarded**.

**Scope**: within a single run only (FR-039). Comparing against previously generated corpora would need a
persistent cross-run registry the feature does not otherwise require, and FR-034's purpose is a diversity
signal for the run in hand.

**Rationale**: FR-034 asks for duplicate visibility as a diversity signal, not a filter — and the spec's
assumption is explicit that a high duplicate rate means the prompt document needs broadening. Discarding
duplicates would suppress the very signal the requirement exists to surface, and would inflate the discard
tallies that FR-009k uses to detect a defective generator. Fingerprinting the turn sequence alone means two
records with identical conversations but different assigned metadata still register as duplicate *content*,
which is the thing an author cares about. A 32-byte digest per record is ~3.2 MB at 100k — bounded and
acceptable, unlike holding records themselves.

**Alternatives considered**:
- *Near-duplicate detection (MinHash/SimHash)*: catches paraphrase-level repetition, which is the more
  likely failure at scale, but introduces thresholds requiring their own calibration; exact duplicates are
  what FR-034 specifies and are unambiguous.
- *Hashing the whole record including metadata*: no collisions ever, and no signal either — assigned
  metadata varies by construction (R3), so identical conversations would rarely fingerprint identically.
