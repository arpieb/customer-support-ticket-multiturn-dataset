# Pre-Implementation Requirements Checklist: Ticket Generation Pipeline

**Purpose**: Formal pre-implementation gate — interrogate the *requirements themselves* for completeness,
clarity, consistency, measurability, and coverage before `/speckit-tasks` decomposes them and code is
written against them. This validates what is written, not what the code will do.
**Created**: 2026-08-19
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [data-model.md](../data-model.md) |
[contracts/](../contracts/)
**Audience**: Spec author, before task generation
**Focus areas**: Model generation & judging · Reproducibility & determinism · Provenance & manifest ·
Privacy gate · Composition control · Interruption & resume · Thresholds & reporting · Cross-artifact
consistency

**Scope note**: Items reach into `plan.md`, `data-model.md`, and `contracts/` as well as the spec. A
constraint that exists only in a design document is not a requirement — an implementer working from the
spec alone would never learn it. Those items are marked `[Design-only]`.

---

## Model Generation & Judging Requirements

- [ ] CHK001 FR-008 requires that the generator "MUST NOT read hidden state from the operator's environment", yet generation authenticates against a hosted model using credentials resolved from that environment. Is the credential exception stated in the requirements, or does FR-008 contradict the way the feature must actually run? [Conflict, Spec §FR-008, §Assumptions]
- [ ] CHK002 Are requirements defined for what happens when the model **declines** a generation request on safety grounds — a case distinct from an unparseable response or a transport failure? [Gap, Spec §FR-009b, §FR-009c]
- [ ] CHK003 If a declined request is rescued by a fallback model, is it specified whether a record produced by a *different model than the one configured* is acceptable output, and how its provenance must be recorded? [Gap, Design-only, Plan §Technical Context]
- [ ] CHK004 FR-009 requires turns to "alternate between participants" but never states **which role speaks first**. Is the opening role specified, or is it left to the implementer? [Gap, Spec §FR-009]
- [ ] CHK005 FR-009e forbids a minimum turn count "below the smallest coherent exchange". Is that floor quantified, or is it a term an implementer must invent a number for? [Ambiguity, Measurability, Spec §FR-009e]
- [ ] CHK006 FR-009d requires each conversation's length to be "sampled from that range as a seeded choice". Is the **distribution** across the range specified (uniform or otherwise)? Two implementations could both satisfy FR-009d and produce materially different corpora. [Gap, Spec §FR-009d]
- [ ] CHK007 Is it specified whether the judging model may be the **same model** that generated the record, or whether self-judging is prohibited as a bias risk? [Gap, Spec §FR-009f, §FR-009j]
- [ ] CHK008 FR-009h sets a threshold on a "normalized 0–1 scale". Is the score's granularity or derivation specified — continuous, or aggregated from discrete rubric criteria — such that 0.8 means the same thing across rubric revisions? [Ambiguity, Spec §FR-009h, §FR-009f]
- [ ] CHK009 FR-009l discards a record that cannot be scored "after the configured retries", but no requirement names that retry setting or relates it to FR-009c's failure tolerance. Are these one knob or two? [Clarity, Spec §FR-009l, §FR-009c]
- [ ] CHK010 The judge is non-deterministic, so the same conversation may be admitted in one run and discarded in another. Is that variance stated as accepted behavior anywhere in the requirements, rather than only implied by the Assumptions? [Gap, Spec §Assumptions, §SC-003]
- [ ] CHK011 The spec is "English-first, not English-only", but no requirement gives the operator control over output language. Is language a configuration dimension, an emergent property of the prompt document, or undefined? [Gap, Spec §Assumptions]
- [ ] CHK012 Are requirements defined for the **content** of the domain prompt document and the rubric — what each must contain to be usable — or only that they exist, are committed, and are hashed? [Gap, Spec §FR-008a, §FR-009g]

## Reproducibility & Determinism Requirements

- [ ] CHK013 FR-012b names "scenario selection" as a seeded choice, but FR-008a has the **model** elaborating scenarios from the prompt document. Are these consistent, or does one requirement seed a choice the other assigns to the model? [Conflict, Spec §FR-012b, §FR-008a]
- [ ] CHK014 FR-010 and SC-003 both promise output "equivalent in structure and composition". Is "equivalent" defined operationally — which fields must match, at what granularity — so that two corpora can be objectively compared? [Measurability, Spec §FR-010, §SC-003]
- [ ] CHK015 SC-013 asserts "identical per-position seeded choices". Is the authoritative list of which choices are seeded (versus model-determined) stated in the requirements, or must it be inferred from the design? [Clarity, Spec §SC-013, §FR-012b]
- [ ] CHK016 FR-006 requires ticket creation and resolution times on every record, but no requirement says whether those timestamps are **seeded, model-chosen, or taken from the wall clock** — the distinction decides whether they are reproducible. [Gap, Spec §FR-006, §FR-012b]
- [ ] CHK017 Is it specified whether the same seed and configuration run against a **different code revision** must still be considered reproducible, or whether the code revision is part of the reproducibility contract? [Gap, Spec §FR-010, §FR-025]
- [ ] CHK018 SC-001 requires the run to complete "within an operator-acceptable window recorded in the configuration", but no functional requirement establishes such a field, and the configuration described in [data-model.md](../data-model.md) has none. Is this criterion satisfiable as written? [Conflict, Spec §SC-001, Design-only]
- [ ] CHK019 Are requirements defined for whether a corpus generated at one concurrency level and one generated at another must be **byte-comparable in record order**, or only comparable position by position? [Clarity, Spec §FR-012c, §SC-013]

## Provenance, Manifest & Traceability Requirements

- [ ] CHK020 FR-029 requires a record to be traceable to its manifest "using only the record's own fields", but no requirement establishes how the manifest is **located** — its path, filename convention, or co-location with the artifact. Is traceability achievable as specified? [Gap, Spec §FR-029, §FR-025]
- [ ] CHK021 FR-025 enumerates what the manifest records but omits **run start and end times**, which Principle II names explicitly as non-deterministic inputs to capture. Is the omission deliberate? [Gap, Spec §FR-025, Constitution §II]
- [ ] CHK022 Are requirements defined for what the manifest records when the **code revision cannot be determined** or the working tree is dirty, or is that decision left entirely to the design? [Gap, Design-only, Spec §FR-025]
- [ ] CHK023 FR-003 requires a stable record identifier but says nothing about its **derivation or uniqueness scope** — unique within an artifact, within a run, or globally across corpora? [Clarity, Spec §FR-003, §FR-015b]
- [ ] CHK024 FR-027 requires recording "any generation model identity". When a fallback causes different records in one corpus to come from different models, is a single run-level identity sufficient, or is per-record model identity required? [Gap, Spec §FR-027]
- [ ] CHK025 FR-026 requires that input count minus discards equals output count, but the term "input count" is never defined for a generator that creates its own inputs. Is it the requested corpus size, the number of model responses received, or the number of slots attempted? [Ambiguity, Measurability, Spec §FR-026, §SC-005]
- [ ] CHK026 Is the set of permitted **discard reasons** established by the requirements, or does the spec leave reasons open-ended while FR-026's reconciliation depends on them being enumerable? [Gap, Design-only, Spec §FR-026]
- [ ] CHK027 FR-028 requires the manifest to be "validatable" and to name missing elements. Is it specified whether validation also enforces the FR-026 reconciliation arithmetic, or only field presence? [Clarity, Spec §FR-028, §FR-026]
- [ ] CHK028 Is a requirement stated that the manifest bind to a **specific output file** (for example by checksum), so that a manifest cannot be read beside an artifact it does not describe? [Gap, Design-only, Spec §FR-025]

## Privacy Gate Requirements

- [ ] CHK029 FR-021 discards flagged records, while FR-022 lets a reviewer approve a finding as a legitimate synthetic value. If the flagged record was discarded and never written, and FR-020 forbids reporting the matched value, **what does the reviewer inspect in order to approve it**? Are the two requirements jointly satisfiable? [Conflict, Spec §FR-021, §FR-022, §FR-020]
- [ ] CHK030 Is the authoritative list of **scanned fields** stated in the requirements? The record carries model-generated free text in `scenario` as well as in turn content; the Edge Cases say "every field carrying free text" without naming them. [Gap, Spec §FR-023, §Edge Cases]
- [ ] CHK031 Does FR-018's term "government identifiers" match what an offline detector can actually cover (in practice, US SSN), or does it promise coverage of non-US identifiers that nothing detects — the exact overclaim FR-019 exists to prevent? [Conflict, Spec §FR-018, §FR-019]
- [ ] CHK032 The design places the privacy scan **last**, after coherence judging, so a record discarded for incoherence is never scanned. Is it specified whether privacy scanning must cover records that failed an earlier gate, and does the FR-021a discard rate become unrepresentative if it does not? [Consistency, Coverage, Spec §FR-016, §FR-021a, Design-only]
- [ ] CHK033 Are requirements defined for **who may approve** a privacy exception, and whether the person who ran the generator may approve findings on their own output? [Gap, Spec §FR-022]
- [ ] CHK034 Is there a requirement that an approved exception be re-reviewed or expire, or do approvals persist indefinitely once recorded? [Gap, Spec §FR-022]
- [ ] CHK035 Is it stated that the exception's free-text reason must not itself contain the matched value, given that keeping values out of the repository is the point? [Gap, Spec §FR-022, §FR-020]
- [ ] CHK036 The spec's privacy categories are all blocking; the design introduces **advisory, non-blocking** categories. Is the advisory tier a requirement, and is it unambiguous which categories block? [Gap, Design-only, Spec §FR-018]
- [ ] CHK037 Are requirements defined for what happens when a detector **raises an error** mid-scan — fail closed, skip the record, or abort the run? [Gap, Exception Flow, Spec §FR-017]
- [ ] CHK038 Can "a detector set that cannot cover this floor" be objectively evaluated — is the comparison against *declared* categories or against *demonstrated* detection capability? [Measurability, Spec §FR-018]
- [ ] CHK039 Does FR-024's "without contacting a network service" also cover **telemetry and usage reporting** by a detection library, or only detection lookups? [Clarity, Spec §FR-024]

## Composition Control Requirements

- [ ] CHK040 FR-031's ±2 percentage point tolerance is stated "per controlled dimension". Is it per **member** of a dimension or an aggregate over the dimension? The two readings can pass and fail the same corpus. [Ambiguity, Measurability, Spec §FR-031]
- [ ] CHK041 FR-030 treats the four dimensions independently. Are **cross-dimension** constraints required — combinations that should not co-occur, or joint distributions the operator can express — or is independence an accepted simplification? [Gap, Spec §FR-030]
- [ ] CHK042 FR-033 requires "a documented default distribution", but the spec never states its values; they exist only in [data-model.md](../data-model.md). Is the default itself a requirement, or an implementation choice that may change without a spec change? [Traceability, Design-only, Spec §FR-033]
- [ ] CHK043 The Assumptions concede that ±2pp "may be unreachable on very small corpora". Is a requirement defined for that case — refuse, warn, or silently exceed the tolerance and fail the run? [Gap, Spec §FR-031, §Assumptions]
- [ ] CHK044 FR-032 requires refusing an unsatisfiable request. Are the conditions that make a request unsatisfiable **enumerated** (proportions that do not sum, unknown members, a corpus too small to round), or left to the implementer to discover? [Clarity, Spec §FR-032]
- [ ] CHK045 When discards perturb the achieved composition past tolerance, is it specified whether the run fails for *composition* or for the underlying discard cause — and can an operator tell the two apart from the report? [Consistency, Spec §FR-031, §FR-009k, §FR-021a]

## Interruption, Resume & Output Path Requirements

- [ ] CHK046 FR-015e refuses a resume when the configuration, seed, prompt document, or rubric differ — but not when the **code revision** differs. Is resuming under changed code acceptable, given it produces exactly the mixed provenance FR-015e exists to prevent? [Gap, Spec §FR-015e]
- [ ] CHK047 FR-015b forbids reusing "a record identifier already issued", while a retried slot legitimately regenerates the same position. Is it unambiguous whether re-issuing an identifier for a **discarded** record counts as reuse? [Ambiguity, Spec §FR-015b, §FR-009c]
- [ ] CHK048 The Edge Cases require an unusable checkpoint to be "reported as such". Are requirements defined for what the operator may then do — what happens to partial output, and whether restarting must first clear it? [Gap, Recovery Flow, Spec §Edge Cases]
- [ ] CHK049 Are requirements defined for **two runs sharing a checkpoint** — the same configuration and seed started twice concurrently — or is that failure mode unaddressed? [Gap, Coverage]
- [ ] CHK050 FR-015 requires interrupted output to be distinguishable from finished output. Is the *mechanism* constrained by requirements (for instance, that incomplete output must not occupy the release path at all), or is the design free to satisfy it with a naming convention? [Clarity, Design-only, Spec §FR-015, §FR-013]
- [ ] CHK051 FR-014 forbids silently overwriting or appending to an existing artifact. Is a deliberate, explicit overwrite path required, or is overwriting prohibited outright? [Gap, Spec §FR-014]
- [ ] CHK052 Are requirements defined for the **retention or cleanup** of checkpoints and partial output after a successful or abandoned run, or do they accumulate indefinitely under `data/`? [Gap, Spec §FR-015a, Constitution §Technology & Data Constraints]

## Thresholds, Reporting & Run Outcome Requirements

- [ ] CHK053 FR-021a and FR-009k both express a threshold as a percentage "of records generated". Is the **denominator** defined — slots attempted, model responses received including retries, or records written? Each yields a different rate from the same run. [Ambiguity, Measurability, Spec §FR-021a, §FR-009k]
- [ ] CHK054 Is it specified **when** run-level thresholds are evaluated — continuously so a doomed run stops early, or only at completion? At release scale the difference is most of the cost of the run. [Gap, Spec §FR-009k, §FR-021a, §SC-001]
- [ ] CHK055 FR-036 requires the run to "signal success or failure unambiguously". Is the outcome taxonomy specified — refused before generating, failed a threshold, interrupted — or only a binary? These call for different operator responses. [Clarity, Spec §FR-036]
- [ ] CHK056 Is the report's **format and location** established by the requirements, or only that it be machine-readable? [Gap, Spec §FR-035, §FR-036]
- [ ] CHK057 SC-009 requires reporting the score distribution across the corpus. Is the distribution's form specified — bucketing, summary statistics — well enough to be objectively produced and compared? [Measurability, Spec §SC-009]
- [ ] CHK058 FR-034 requires reporting duplicate conversations. Is the **scope** of duplicate detection specified — within a single run only, or across previously generated corpora — and is the comparison basis (turn content, whole record) defined? [Clarity, Spec §FR-034]
- [ ] CHK059 Are requirements defined bounding a run's **cost or call volume** — a ceiling, an estimate before starting, or an abort condition? SC-001 asserts a 100,000-record run is achievable; nothing prevents an unattended run from spending far more than intended. [Gap, Spec §SC-001, §Assumptions]

## Cross-Artifact Consistency & Governance

- [ ] CHK060 [contracts/record.schema.json](../contracts/record.schema.json) requires `resolved_at` to be **absent unless** the resolution status is `resolved`. FR-006 requires only that the record carry creation and resolution times. Is the conditional a requirement, or a design decision that narrows the contract? [Consistency, Design-only, Spec §FR-006]
- [ ] CHK061 The record contract admits a minimum of two turns while the configured default range starts at four. Is the contract-level minimum a requirement in its own right, and is it consistent with FR-009e's "smallest coherent exchange"? [Consistency, Spec §FR-009e, Design-only]
- [ ] CHK062 The design records a coherence score and rubric identifier on every record. FR-009i requires the score; is the **rubric identifier on the record** a requirement, given a score is uninterpretable without it? [Gap, Spec §FR-009i, §FR-009g]
- [ ] CHK063 SC-011 requires the judge to be calibrated against human judgment "before a corpus is released". Is calibration a **gate** with an owner and a recorded artifact, or an advisory expectation no requirement enforces? [Ambiguity, Spec §SC-011, Constitution §V]
- [ ] CHK064 SC-010 claims a new contributor can generate their first corpus "using the project's documentation alone". Is the documentation in scope for that claim identified, and is any requirement responsible for producing it? [Measurability, Spec §SC-010]
- [ ] CHK065 Is the assumption "conversations are fabricated, not derived from real support transcripts" enforced by any requirement, given it is the stated basis for accepting the residual privacy risk that FR-019 declares? [Assumption, Spec §Assumptions, §FR-019]
- [ ] CHK066 Are the requirements internally consistent about scope — does anything still imply that this feature validates externally postprocessed datasets, which was explicitly moved to feature 002? [Consistency, Spec §Assumptions]

## Notes

- Check items off as resolved: `[x]`. An item may be resolved by **amending the spec** or by recording a
  deliberate decision that the gap is acceptable — but not by leaving it unexamined.
- The highest-value items are the `[Conflict]` ones — CHK001 (credentials versus "no hidden environment
  state"), CHK013 (who selects the scenario), CHK018 (a success criterion referencing a configuration field
  that does not exist), CHK029 (approving an exception for a record that was discarded and never written),
  and CHK031 (a floor promising more than any offline detector delivers). Each is two requirements
  disagreeing, not a gap, so no amount of careful implementation resolves them.
- `[Design-only]` items mark constraints that exist in `plan.md`, `data-model.md`, or `contracts/` but not
  in the spec. A design document is not a requirement: an implementer following the spec alone would never
  learn them, and a future revision could drop them without any requirement noticing.
- `[Ambiguity]` items concentrated on denominators and tolerances (CHK040, CHK053) are worth resolving
  before tasks are written — a threshold whose denominator is undefined cannot be tested, and the tests
  will encode whichever reading the implementer happened to pick.
- `[Gap]` items may be legitimate deferrals. The point is that the deferral becomes explicit and dated
  rather than discovered mid-implementation.
- This checklist tests the requirements, not the implementation. Nothing here should be resolved by
  writing code.
