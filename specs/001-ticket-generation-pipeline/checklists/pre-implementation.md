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

- [x] CHK001 FR-008 requires that the generator "MUST NOT read hidden state from the operator's environment", yet generation authenticates against a hosted model using credentials resolved from that environment. Is the credential exception stated in the requirements, or does FR-008 contradict the way the feature must actually run? [Conflict, Spec §FR-008, §Assumptions]
  - **Resolved 2026-08-19** — FR-008 amended: model credentials are the **sole** permitted environment input, declared as an access mechanism that must not influence output and must never be written to any artifact. **FR-008c** (new) closes the real hole the conflict pointed at: an environment setting that could change model selection, routing, or parameters — endpoint, profile, inference region — is genuinely the hidden state FR-008 prohibits, so it must be recorded in the manifest as a non-deterministic input, and a setting that cannot be observed causes the run to refuse rather than proceed unrecorded.
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
  - **Partially resolved 2026-08-19** by the CHK013 amendment — FR-008d now imposes a content requirement on the domain prompt document: it must declare an enumerable subdomain list. The **rubric** half of this item is untouched: no requirement says what a rubric must contain to be usable, only that it exists, is committed, and is hashed.

## Reproducibility & Determinism Requirements

- [x] CHK013 FR-012b names "scenario selection" as a seeded choice, but FR-008a has the **model** elaborating scenarios from the prompt document. Are these consistent, or does one requirement seed a choice the other assigns to the model? [Conflict, Spec §FR-012b, §FR-008a]
  - **Resolved 2026-08-19** — neither requirement gave; scenario derivation is now two-level. **FR-008d** (new) requires the domain prompt document to declare an enumerable subdomain list; FR-012b's seeded choice selects the **subdomain** (so its claim is true and the corpus stratifies deterministically), and the model elaborates the specific situation within it (so FR-008a stands). FR-008b now requires both on the record: `subdomain` is reproducible from the seed, `scenario` is model text and is not. This changes the record contract — `subdomain` added to [record.schema.json](../contracts/record.schema.json) — and gives SC-013 a per-position field worth comparing.
- [ ] CHK014 FR-010 and SC-003 both promise output "equivalent in structure and composition". Is "equivalent" defined operationally — which fields must match, at what granularity — so that two corpora can be objectively compared? [Measurability, Spec §FR-010, §SC-003]
- [x] CHK015 SC-013 asserts "identical per-position seeded choices". Is the authoritative list of which choices are seeded (versus model-determined) stated in the requirements, or must it be inferred from the design? [Clarity, Spec §SC-013, §FR-012b]
  - **Resolved 2026-08-19** by the CHK013 amendment — FR-012b now names the list exhaustively ("its turn count, its composition assignment, its subdomain selection") and states explicitly that the scenario the model elaborates is model output rather than a seeded choice. **Caveat**: the list's authority depends on CHK016, which is still open — ticket timestamps are per-record values that appear nowhere in it, so until their origin is settled the list is exhaustive in wording but not demonstrably in fact.
- [ ] CHK016 FR-006 requires ticket creation and resolution times on every record, but no requirement says whether those timestamps are **seeded, model-chosen, or taken from the wall clock** — the distinction decides whether they are reproducible. [Gap, Spec §FR-006, §FR-012b]
- [ ] CHK017 Is it specified whether the same seed and configuration run against a **different code revision** must still be considered reproducible, or whether the code revision is part of the reproducibility contract? [Gap, Spec §FR-010, §FR-025]
- [x] CHK018 SC-001 requires the run to complete "within an operator-acceptable window recorded in the configuration", but no functional requirement establishes such a field, and the configuration described in [data-model.md](../data-model.md) has none. Is this criterion satisfiable as written? [Conflict, Spec §SC-001, Design-only]
  - **Resolved 2026-08-19**, together with CHK059 — **FR-012f** (new) lets the configuration declare a run budget: a maximum wall-clock duration, a maximum number of model calls, or both. Exhausting one **stops and checkpoints** rather than failing, so no completed work is lost and resuming stays the operator's decision; the manifest records the declared budget and the actual spend. SC-001 now refers to that budget, making the criterion literally satisfiable, and an unattended release-scale run finally has a ceiling on time and cost.
- [ ] CHK019 Are requirements defined for whether a corpus generated at one concurrency level and one generated at another must be **byte-comparable in record order**, or only comparable position by position? [Clarity, Spec §FR-012c, §SC-013]

## Provenance, Manifest & Traceability Requirements

- [ ] CHK020 FR-029 requires a record to be traceable to its manifest "using only the record's own fields", but no requirement establishes how the manifest is **located** — its path, filename convention, or co-location with the artifact. Is traceability achievable as specified? [Gap, Spec §FR-029, §FR-025]
- [ ] CHK021 FR-025 enumerates what the manifest records but omits **run start and end times**, which Principle II names explicitly as non-deterministic inputs to capture. Is the omission deliberate? [Gap, Spec §FR-025, Constitution §II]
- [ ] CHK022 Are requirements defined for what the manifest records when the **code revision cannot be determined** or the working tree is dirty, or is that decision left entirely to the design? [Gap, Design-only, Spec §FR-025]
- [ ] CHK023 FR-003 requires a stable record identifier but says nothing about its **derivation or uniqueness scope** — unique within an artifact, within a run, or globally across corpora? [Clarity, Spec §FR-003, §FR-015b]
- [ ] CHK024 FR-027 requires recording "any generation model identity". When a fallback causes different records in one corpus to come from different models, is a single run-level identity sufficient, or is per-record model identity required? [Gap, Spec §FR-027]
- [x] CHK025 FR-026 requires that input count minus discards equals output count, but the term "input count" is never defined for a generator that creates its own inputs. Is it the requested corpus size, the number of model responses received, or the number of slots attempted? [Ambiguity, Measurability, Spec §FR-026, §SC-005]
  - **Resolved 2026-08-19** by the CHK053 amendment — FR-026a defines the term the reconciliation depends on: records generated is every response received from the generating model, counted once per attempt, and each is either written or discarded under exactly one reason. "Input count" for a generator that creates its own inputs now has one meaning.
- [ ] CHK026 Is the set of permitted **discard reasons** established by the requirements, or does the spec leave reasons open-ended while FR-026's reconciliation depends on them being enumerable? [Gap, Design-only, Spec §FR-026]
  - **Partially resolved 2026-08-19** — FR-026a establishes that every counted response is discarded under **exactly one** reason, which is what the reconciliation needs arithmetically. The **enumeration itself** remains design-only: the closed `DiscardReason` set lives in `data-model.md` and in the manifest contract, and no requirement lists the permitted reasons.
- [ ] CHK027 FR-028 requires the manifest to be "validatable" and to name missing elements. Is it specified whether validation also enforces the FR-026 reconciliation arithmetic, or only field presence? [Clarity, Spec §FR-028, §FR-026]
- [ ] CHK028 Is a requirement stated that the manifest bind to a **specific output file** (for example by checksum), so that a manifest cannot be read beside an artifact it does not describe? [Gap, Design-only, Spec §FR-025]

## Privacy Gate Requirements

- [x] CHK029 FR-021 discards flagged records, while FR-022 lets a reviewer approve a finding as a legitimate synthetic value. If the flagged record was discarded and never written, and FR-020 forbids reporting the matched value, **what does the reviewer inspect in order to approve it**? Are the two requirements jointly satisfiable? [Conflict, Spec §FR-021, §FR-022, §FR-020]
  - **Resolved 2026-08-19** — they were not jointly satisfiable as written. Spec amended: **FR-020a** adds a deterministic, irreversible **masked rendering** to every finding (domain for an email, issuer range for a card, shape and length otherwise), which settles the common synthetic cases without reproducing the value; **FR-021b** retains privacy-discarded records in a **quarantine artifact** under `data/interim/`, never committed and never dataset output, for findings a mask cannot settle. FR-022 now states that a reviewer must be able to decide from one or the other and need not have observed the original run. Assumptions record why quarantine is compatible with Principle IV: the content is fabricated and merely identifier-shaped, and the requirement is about the provenance of content, not its shape.
- [ ] CHK030 Is the authoritative list of **scanned fields** stated in the requirements? The record carries model-generated free text in `scenario` as well as in turn content; the Edge Cases say "every field carrying free text" without naming them. [Gap, Spec §FR-023, §Edge Cases]
- [x] CHK031 Does FR-018's term "government identifiers" match what an offline detector can actually cover (in practice, US SSN), or does it promise coverage of non-US identifiers that nothing detects — the exact overclaim FR-019 exists to prevent? [Conflict, Spec §FR-018, §FR-019]
  - **Resolved 2026-08-19** — FR-018 now names **US Social Security numbers** rather than "government identifiers", stating the floor at the level of the identifier type actually detected; naming the broad category promised coverage of non-US identifiers that no offline detector delivers, which is the same overclaim FR-019 exists to prevent, merely relocated into the requirement. FR-019 is strengthened in turn: every report enumerates the types the scan **covers** as well as those it does not, at that same specificity, so widening coverage later is visible as a change in what the report claims rather than a silent improvement.
- [ ] CHK032 The design places the privacy scan **last**, after coherence judging, so a record discarded for incoherence is never scanned. Is it specified whether privacy scanning must cover records that failed an earlier gate, and does the FR-021a discard rate become unrepresentative if it does not? [Consistency, Coverage, Spec §FR-016, §FR-021a, Design-only]
- [ ] CHK033 Are requirements defined for **who may approve** a privacy exception, and whether the person who ran the generator may approve findings on their own output? [Gap, Spec §FR-022]
- [ ] CHK034 Is there a requirement that an approved exception be re-reviewed or expire, or do approvals persist indefinitely once recorded? [Gap, Spec §FR-022]
- [ ] CHK035 Is it stated that the exception's free-text reason must not itself contain the matched value, given that keeping values out of the repository is the point? [Gap, Spec §FR-022, §FR-020]
- [ ] CHK036 The spec's privacy categories are all blocking; the design introduces **advisory, non-blocking** categories. Is the advisory tier a requirement, and is it unambiguous which categories block? [Gap, Design-only, Spec §FR-018]
- [ ] CHK037 Are requirements defined for what happens when a detector **raises an error** mid-scan — fail closed, skip the record, or abort the run? [Gap, Exception Flow, Spec §FR-017]
- [ ] CHK038 Can "a detector set that cannot cover this floor" be objectively evaluated — is the comparison against *declared* categories or against *demonstrated* detection capability? [Measurability, Spec §FR-018]
  - **Partially resolved 2026-08-19** by the CHK031 amendment — the floor is now stated at identifier-type level, so the comparison has something specific to be made against, and FR-019 requires the report to enumerate covered types. The item's actual question stands: whether floor coverage is asserted from a detector's **declared** categories or from **demonstrated** detection is still unspecified, and the two differ exactly when a detector's declaration is wrong.
- [ ] CHK039 Does FR-024's "without contacting a network service" also cover **telemetry and usage reporting** by a detection library, or only detection lookups? [Clarity, Spec §FR-024]

## Composition Control Requirements

- [x] CHK040 FR-031's ±2 percentage point tolerance is stated "per controlled dimension". Is it per **member** of a dimension or an aggregate over the dimension? The two readings can pass and fail the same corpus. [Ambiguity, Measurability, Spec §FR-031]
  - **Resolved 2026-08-19** — FR-031 now states the tolerance is evaluated **per member of each dimension**: every member's achieved proportion must sit within the tolerance of its request, a dimension passes only when its worst member passes, and a failure names the offending member and its drift rather than the dimension. Aggregate measures were rejected in the requirement itself, with the reason recorded: someone slicing the corpus by one category cares about that category, and an average lets a badly-served member hide behind well-served ones. SC-008 was reworded to match.
- [x] CHK041 FR-030 treats the four dimensions independently. Are **cross-dimension** constraints required — combinations that should not co-occur, or joint distributions the operator can express — or is independence an accepted simplification? [Gap, Spec §FR-030]
  - **Resolved 2026-08-19** — independence is now stated rather than implied. A new assumption records that the four dimensions are apportioned separately, that any combination may therefore occur, and that an implausible pairing is the generating model's problem to render coherently and the coherence judge's to catch — not a composition concern. The tradeoff is explicit: four simple distributions instead of a 384-cell cross-product, at the cost of not being able to forbid a specific pairing.
- [x] CHK042 FR-033 requires "a documented default distribution", but the spec never states its values; they exist only in [data-model.md](../data-model.md). Is the default itself a requirement, or an implementation choice that may change without a spec change? [Traceability, Design-only, Spec §FR-033]
  - **Resolved 2026-08-19** — the default distribution and the 4–12 turn range are now stated **in FR-033 itself**, as a table, with the requirement noting they are requirements rather than implementation choices: changing them changes the corpus every unconfigured run produces. `data-model.md` now restates them and says the spec is normative.
- [x] CHK043 The Assumptions concede that ±2pp "may be unreachable on very small corpora". Is a requirement defined for that case — refuse, warn, or silently exceed the tolerance and fail the run? [Gap, Spec §FR-031, §Assumptions]
  - **Resolved 2026-08-19** — **FR-031b** (new) makes achievability a precondition. Assigning whole records bounds per-member error at `1 / record_count` before any discard, so a tolerance below that is unsatisfiable by arithmetic; the run refuses before generating and states both the minimum corpus size and the minimum tolerance that would work. The requirement is explicit that this is a necessary condition, not a sufficient one — meeting it does not guarantee the tolerance survives discards. The Assumptions were rewritten accordingly, and `configs/smoke.toml` now declares a 10pp tolerance because 20 records cannot achieve 2pp.
- [x] CHK044 FR-032 requires refusing an unsatisfiable request. Are the conditions that make a request unsatisfiable **enumerated** (proportions that do not sum, unknown members, a corpus too small to round), or left to the implementer to discover? [Clarity, Spec §FR-032]
  - **Resolved 2026-08-19** — FR-032 now enumerates the four conditions that make a request unsatisfiable: proportions that do not sum to 1 within a stated epsilon, a value that is not a member of the dimension's enumeration, a proportion too small to round to a whole record at the requested corpus size, and a tolerance unachievable at that size (FR-031b).
- [x] CHK045 When discards perturb the achieved composition past tolerance, is it specified whether the run fails for *composition* or for the underlying discard cause — and can an operator tell the two apart from the report? [Consistency, Spec §FR-031, §FR-009k, §FR-021a]
  - **Resolved 2026-08-19** — **FR-031a** (new) requires **three** distributions per dimension rather than two: requested, assigned, and achieved. Requested → assigned exposes apportionment error; assigned → achieved exposes drift caused by discards. Without the middle term a tolerance failure has no attributable cause, and the two causes call for entirely different responses. The manifest and report carry all three, plus a per-member breach list.

## Interruption, Resume & Output Path Requirements

- [ ] CHK046 FR-015e refuses a resume when the configuration, seed, prompt document, or rubric differ — but not when the **code revision** differs. Is resuming under changed code acceptable, given it produces exactly the mixed provenance FR-015e exists to prevent? [Gap, Spec §FR-015e]
- [ ] CHK047 FR-015b forbids reusing "a record identifier already issued", while a retried slot legitimately regenerates the same position. Is it unambiguous whether re-issuing an identifier for a **discarded** record counts as reuse? [Ambiguity, Spec §FR-015b, §FR-009c]
- [ ] CHK048 The Edge Cases require an unusable checkpoint to be "reported as such". Are requirements defined for what the operator may then do — what happens to partial output, and whether restarting must first clear it? [Gap, Recovery Flow, Spec §Edge Cases]
- [ ] CHK049 Are requirements defined for **two runs sharing a checkpoint** — the same configuration and seed started twice concurrently — or is that failure mode unaddressed? [Gap, Coverage]
- [ ] CHK050 FR-015 requires interrupted output to be distinguishable from finished output. Is the *mechanism* constrained by requirements (for instance, that incomplete output must not occupy the release path at all), or is the design free to satisfy it with a naming convention? [Clarity, Design-only, Spec §FR-015, §FR-013]
- [ ] CHK051 FR-014 forbids silently overwriting or appending to an existing artifact. Is a deliberate, explicit overwrite path required, or is overwriting prohibited outright? [Gap, Spec §FR-014]
- [ ] CHK052 Are requirements defined for the **retention or cleanup** of checkpoints and partial output after a successful or abandoned run, or do they accumulate indefinitely under `data/`? [Gap, Spec §FR-015a, Constitution §Technology & Data Constraints]

## Thresholds, Reporting & Run Outcome Requirements

- [x] CHK053 FR-021a and FR-009k both express a threshold as a percentage "of records generated". Is the **denominator** defined — slots attempted, model responses received including retries, or records written? Each yields a different rate from the same run. [Ambiguity, Measurability, Spec §FR-021a, §FR-009k]
  - **Resolved 2026-08-19** — spec amended with **FR-026a**, one definition governing every rate expressed as a proportion of records generated: *every response received from the generating model, counted once per attempt*. A slot retried three times contributes three. This is the only reading under which FR-026's reconciliation closes, since every counted response either becomes a written record or is discarded under exactly one reason. The consequence is recorded in the requirement rather than left to be discovered: heavy retries enlarge the denominator and therefore **dilute** both discard rates.
- [ ] CHK054 Is it specified **when** run-level thresholds are evaluated — continuously so a doomed run stops early, or only at completion? At release scale the difference is most of the cost of the run. [Gap, Spec §FR-009k, §FR-021a, §SC-001]
- [ ] CHK055 FR-036 requires the run to "signal success or failure unambiguously". Is the outcome taxonomy specified — refused before generating, failed a threshold, interrupted — or only a binary? These call for different operator responses. [Clarity, Spec §FR-036]
- [ ] CHK056 Is the report's **format and location** established by the requirements, or only that it be machine-readable? [Gap, Spec §FR-035, §FR-036]
- [ ] CHK057 SC-009 requires reporting the score distribution across the corpus. Is the distribution's form specified — bucketing, summary statistics — well enough to be objectively produced and compared? [Measurability, Spec §SC-009]
- [ ] CHK058 FR-034 requires reporting duplicate conversations. Is the **scope** of duplicate detection specified — within a single run only, or across previously generated corpora — and is the comparison basis (turn content, whole record) defined? [Clarity, Spec §FR-034]
- [x] CHK059 Are requirements defined bounding a run's **cost or call volume** — a ceiling, an estimate before starting, or an abort condition? SC-001 asserts a 100,000-record run is achievable; nothing prevents an unattended run from spending far more than intended. [Gap, Spec §SC-001, §Assumptions]
  - **Resolved 2026-08-19** — closed by FR-012f alongside CHK018: a declared budget of wall-clock time, model calls, or both, with exhaustion stopping and checkpointing the run.

## Cross-Artifact Consistency & Governance

- [ ] CHK060 [contracts/record.schema.json](../contracts/record.schema.json) requires `resolved_at` to be **absent unless** the resolution status is `resolved`. FR-006 requires only that the record carry creation and resolution times. Is the conditional a requirement, or a design decision that narrows the contract? [Consistency, Design-only, Spec §FR-006]
- [ ] CHK061 The record contract admits a minimum of two turns while the configured default range starts at four. Is the contract-level minimum a requirement in its own right, and is it consistent with FR-009e's "smallest coherent exchange"? [Consistency, Spec §FR-009e, Design-only]
  - **Partially resolved 2026-08-19** by the CHK042 amendment — the 4–12 default turn range is now normative in FR-033 rather than living only in the data model. The inconsistency this item names is unchanged: the record contract still admits two turns, and FR-009e's "smallest coherent exchange" is still unquantified (CHK005).
- [ ] CHK062 The design records a coherence score and rubric identifier on every record. FR-009i requires the score; is the **rubric identifier on the record** a requirement, given a score is uninterpretable without it? [Gap, Spec §FR-009i, §FR-009g]
- [ ] CHK063 SC-011 requires the judge to be calibrated against human judgment "before a corpus is released". Is calibration a **gate** with an owner and a recorded artifact, or an advisory expectation no requirement enforces? [Ambiguity, Spec §SC-011, Constitution §V]
- [ ] CHK064 SC-010 claims a new contributor can generate their first corpus "using the project's documentation alone". Is the documentation in scope for that claim identified, and is any requirement responsible for producing it? [Measurability, Spec §SC-010]
- [ ] CHK065 Is the assumption "conversations are fabricated, not derived from real support transcripts" enforced by any requirement, given it is the stated basis for accepting the residual privacy risk that FR-019 declares? [Assumption, Spec §Assumptions, §FR-019]
  - **Partially resolved 2026-08-19** — the CHK029 amendment added an assumption stating that quarantined records are fabricated content rather than personal data, and the model contract states no real transcript or customer record is ever placed in a prompt. Both are still **assumptions and design text**: no requirement enforces synthetic-by-construction, which remains the stated basis for accepting the residual privacy risk.
- [ ] CHK066 Are the requirements internally consistent about scope — does anything still imply that this feature validates externally postprocessed datasets, which was explicitly moved to feature 002? [Consistency, Spec §Assumptions]
  - **Swept 2026-08-19, still open** — the spec itself is clean: the only mentions of externally postprocessed datasets are scope *exclusions* (the Input description and the Assumptions), and FR-016 scopes the scan to "its own generated output". The leak is in the design: [cli.md](../contracts/cli.md) defines `ticket-dataset privacy scan PATH` over an arbitrary existing artifact, which is a scan of a file this feature did not necessarily produce. It is needed by the approval loop (re-checking after the exception file changes), so the question is whether to scope it to this project's own artifacts or accept it as a deliberate overlap with feature 002. [Design-only]

## Notes

- Check items off as resolved: `[x]`. An item may be resolved by **amending the spec** or by recording a
  deliberate decision that the gap is acceptable — but not by leaving it unexamined.
- **All five `[Conflict]` items are resolved** — CHK001, CHK013, CHK018, CHK029, CHK031 — each by amending
  the requirements rather than by deciding how to implement around them. Each was two requirements
  disagreeing, so no amount of careful implementation would have resolved any of them; an implementer would
  simply have picked a side without noticing there was one.
- **Resolved on 2026-08-19**: CHK001, CHK013, CHK018, CHK029, CHK031, CHK053, CHK059 (as part of CHK018),
  and the whole composition cluster — CHK040 through CHK045. A sweep of the remaining items then closed
  **CHK015** and **CHK025**, which the CHK013 and CHK053 amendments had already resolved without anyone
  noticing, and annotated five more as partially resolved (CHK012, CHK026, CHK038, CHK061, CHK065) — a
  partially resolved item is not resolved, and stays open. The sweep also found one thing the checklist had
  not: `privacy scan PATH` in the CLI contract scans an arbitrary artifact, which is the only place this
  feature's scope leaks toward feature 002 (see CHK066). Spec amendments: FR-008 (credential carve-out), FR-008c, FR-008d, FR-012f, FR-018, FR-019,
  FR-020a, FR-021b, FR-022, FR-026a, SC-001, plus Assumptions and Edge Cases. `subdomain` was added to the
  record contract, and FR-031, FR-031a, FR-031b, FR-032, FR-033, and SC-008 were rewritten for the
  composition cluster. Every change is propagated through `research.md`, `plan.md`, `data-model.md`,
  `contracts/`, and `quickstart.md`.
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
