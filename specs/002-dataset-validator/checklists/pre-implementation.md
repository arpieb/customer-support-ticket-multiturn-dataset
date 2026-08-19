# Pre-Implementation Requirements Checklist: Record Schema & Validation Harness

**Purpose**: Formal pre-implementation gate — interrogate the *requirements themselves* for completeness,
clarity, consistency, measurability, and coverage before `/speckit-implement` executes 80 tasks against
them. This validates what is written, not what the code will do.
**Created**: 2026-08-18
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [data-model.md](../data-model.md)
**Audience**: Spec author, before implementation
**Focus areas**: Privacy & data protection · Data contract & schema · Provenance & reproducibility ·
Release-gate operability

---

## Privacy & Data Protection Requirements

- [ ] CHK001 Does FR-013d's term "government identifiers" match what the chosen engine actually covers (US SSN only), or does it promise coverage of non-US identifiers that nothing detects? [Conflict, Spec §FR-013d]
- [ ] CHK002 Is it specified **which fields** the privacy scan examines — turn content only, or also ticket metadata, record IDs, and source identifiers? [Gap, Spec §FR-013]
- [ ] CHK003 Is the authoritative list of declared gaps defined in the requirements, or only described narratively in Assumptions? [Clarity, Spec §FR-013e]
- [ ] CHK004 Are requirements defined for **who may approve** a privacy exception, and whether self-approval by the record's author is permitted? [Gap, Spec §FR-016]
- [ ] CHK005 Is there a requirement that an approved exception be re-reviewed or expire, or do approvals persist indefinitely once recorded? [Gap, Spec §FR-016]
- [ ] CHK006 Is it stated that the exception's free-text `reason` field must not itself contain the matched value, given the whole point of fingerprinting is to keep values out of the repository? [Gap, Spec §FR-016]
- [ ] CHK007 Is the normalization rule used to compute a fingerprint specified in the requirements, or only in research notes — and is it stable enough that an approval survives a detector change? [Ambiguity, Spec §FR-016]
- [ ] CHK008 Does FR-013f state whether the default detector set enables advisory categories, or is "MAY report" left to implementer discretion? [Ambiguity, Spec §FR-013f]
- [ ] CHK009 Are requirements defined for what happens when a detector raises an error mid-scan — does the gate fail closed, skip the record, or abort? [Gap, Exception Flow]
- [ ] CHK010 Is the residual privacy risk (uncovered postal address and bank account) recorded with an explicit acceptance owner, or only asserted in Assumptions? [Assumption, Spec §Assumptions]
- [ ] CHK011 Are requirements consistent between FR-015 ("unreviewed finding MUST block") and FR-013f ("advisory findings MUST NOT fail the gate") — is it unambiguous which categories are which? [Consistency, Spec §FR-015, §FR-013f]
- [ ] CHK012 Is it specified whether the scan must examine records that already failed schema validation, or whether structural failure exempts a record from privacy scanning? [Gap, Coverage]
- [ ] CHK013 Can "a detector set that cannot cover this floor" be objectively evaluated — is the comparison declared categories vs. floor, or actual detection capability? [Measurability, Spec §FR-013d]

## Data Contract & Schema Requirements

- [ ] CHK014 Is the uniqueness scope of `record_id` specified — unique within an artifact, within a run, or globally across all released versions? [Ambiguity, Spec §FR-003, §FR-020]
- [ ] CHK015 Are requirements defined for how a `record_id` is formed (opaque, deterministic, derived from content), given later features must generate them? [Gap, Spec §FR-003]
- [ ] CHK016 Is "insignificant whitespace" defined precisely enough that two implementations would normalize identically before fingerprinting? [Ambiguity, Spec §FR-018a]
- [ ] CHK017 Do the requirements state whether turn indices must be **contiguous from zero** or merely ascending — the spec says ordering, the data model says contiguous? [Conflict, Spec §FR-018 vs data-model.md]
- [ ] CHK018 Is a single-turn conversation specified as valid, and if so, how role alternation applies to it? [Edge Case, Gap, Spec §FR-018]
- [ ] CHK019 Are requirements defined for maximum turn content length or total record size, or is any size acceptable? [Gap, Coverage]
- [ ] CHK020 Is the requirement that timestamps be timezone-aware stated in the spec, or introduced only in the data model? [Consistency, Spec §FR-006a vs data-model.md]
- [ ] CHK021 Is the rule "`resolved_at` required when `resolution_status` is `resolved`" present in the functional requirements, or does it appear only in the design? [Consistency, Spec §FR-006c vs data-model.md]
- [ ] CHK022 Is the semantic meaning of `source_id` defined — a template name, a generator identifier, an upstream corpus — such that two implementers would populate it the same way? [Ambiguity, Spec §FR-003]
- [ ] CHK023 Are the enumerated value sets for category, priority, channel, and resolution status specified in the requirements, or delegated entirely to the schema file? [Completeness, Spec §FR-006b]
- [ ] CHK024 Is the policy for adding an enum member (additive MINOR) versus removing one (breaking MAJOR) stated as a requirement, or only as a data-model note? [Traceability, Spec §FR-002a]
- [ ] CHK025 Are requirements defined for whether unknown/extra fields in a record are rejected or ignored? [Gap, Spec §FR-006]
- [ ] CHK026 Is it specified whether the record schema and the manifest schema version independently or together? [Gap, Spec §FR-002, §FR-022]
- [ ] CHK027 Does FR-018a's exact-duplicate definition specify whether ticket metadata participates in the comparison, or is that inferable only from research? [Clarity, Spec §FR-018a]
- [ ] CHK028 Are requirements defined for what a consumer should do with a record whose `upstream_record_id` refers to a record not present in the artifact? [Gap, Edge Case, Spec §FR-025]

## Provenance & Reproducibility Requirements

- [ ] CHK029 Is the uniqueness and format of `run_id` specified, and how a record's `run_id` resolves to a manifest? [Gap, Spec §FR-003, §FR-022]
- [ ] CHK030 Does the reconciliation rule account for records **added** during a run (augmentation, splitting), or does it assume runs only remove? [Coverage, Spec §FR-023]
- [ ] CHK031 Is the location and naming convention of a manifest relative to its artifact specified, so a manifest can be found from the artifact alone? [Gap, Spec §FR-022]
- [ ] CHK032 Are requirements defined for what the manifest records when no git repository is available or the tree is dirty, or does that appear only in research? [Consistency, Spec §FR-022 vs research.md §R8]
- [ ] CHK033 Is there a requirement that the serialized configuration must not contain secrets or credentials, given manifests are committed alongside artifacts? [Gap, Security]
- [ ] CHK034 Is it specified which inputs must be hashed — every file read, only declared source files, or only files affecting output? [Ambiguity, Spec §FR-022]
- [ ] CHK035 Are requirements defined for whether a manifest is immutable once written, or may be amended after the fact? [Gap, Spec §FR-022]
- [ ] CHK036 Is a removal "reason" constrained to a defined vocabulary, or is free text acceptable — and can free text be aggregated across runs? [Ambiguity, Spec §FR-023]
- [ ] CHK037 Are requirements defined for a derived record produced by **merging** two upstream records, where a single `upstream_record_id` cannot express the lineage? [Gap, Edge Case, Spec §FR-025]
- [ ] CHK038 Can SC-005's "under five minutes, without consulting the person who produced it" be objectively evaluated, or is it a subjective target? [Measurability, Spec §SC-005]
- [ ] CHK039 Is it specified whether a manifest must exist for an artifact to pass the release gate, or whether manifest validation is optional? [Ambiguity, Spec §FR-026, contracts/cli.md]

## Release-Gate Operability Requirements

- [ ] CHK040 Is "minutes, not hours" quantified with a specific threshold that could fail a benchmark, or is it unfalsifiable as written? [Measurability, Spec §SC-008]
- [ ] CHK041 Does the requirement to continue running gates after a failure specify *which* gates can still run — the Edge Cases section says "where possible" without defining the boundary? [Ambiguity, Spec §Edge Cases, §FR-026]
- [ ] CHK042 Is the exit-status contract (including status 3 for uncovered floor) stated in the requirements, or only in the CLI contract document? [Traceability, Spec §FR-031 vs contracts/cli.md]
- [ ] CHK043 Is "release" defined as a process — who runs the gate, at what point, and what artifact state constitutes a release candidate? [Gap, Spec §FR-026]
- [ ] CHK044 Is an artifact whose records were **all** removed by filtering specified as empty for FR-027 purposes, or only a zero-byte file? [Edge Case, Spec §FR-027]
- [ ] CHK045 Are requirements defined for whether the consolidated report must be retained or published alongside a released artifact as evidence? [Gap, Spec §FR-028]
- [ ] CHK046 Does the machine-readable report carry its own format version, given automation is required to consume it without parsing prose? [Gap, Spec §FR-011]
- [ ] CHK047 Are requirements defined for concurrent gate runs over the same artifact, or for a gate run against a file being written? [Gap, Coverage]
- [ ] CHK048 Is the sampled human review required by Constitution Principle V represented anywhere in this feature's requirements, or is its absence explicitly justified? [Gap, Governance]
- [ ] CHK049 Is it specified whether gate results are reproducible across machines — i.e. that no gate outcome depends on locale, filesystem ordering, or environment? [Gap, Non-Functional]
- [ ] CHK050 Can SC-002 ("locate every defective record from the report alone") be objectively verified, or does it depend on reviewer judgment? [Measurability, Spec §SC-002]
- [ ] CHK051 Are requirements defined for how a maintainer resolves a failure — is remediation guidance in scope, or only detection? [Gap, Spec §FR-028]

## Cross-Cutting: Assumptions, Dependencies & Governance

- [ ] CHK052 Is the assumption "records are synthetic by construction" validated anywhere, given it is the stated basis for accepting the residual privacy risk? [Assumption, Spec §Assumptions]
- [ ] CHK053 Is the dependency on a specific third-party detection package reflected in the requirements as a constraint, or does the abstract detector interface fully insulate them? [Dependency, Spec §FR-013a]
- [ ] CHK054 Are the hand-authored fixtures backing SC-003 specified in enough detail — count, coverage per rule, provenance — to be reproducible by someone other than the author? [Completeness, Spec §SC-003]
- [ ] CHK055 Is SC-009 ("a new contributor validates unaided") measurable, and is it clear which documentation is in scope for that claim? [Measurability, Spec §SC-009]
- [ ] CHK056 Are the requirements internally consistent about scope — does anything still imply truncation detection, near-duplicate detection, or generation logic that was explicitly excluded? [Consistency, Spec §FR-018, §FR-018a, §Assumptions]

## Notes

- Check items off as resolved: `[x]`. An item may be resolved by **amending the spec** or by recording a
  deliberate decision that the gap is acceptable — but not by leaving it unexamined.
- Items marked `[Conflict]` (CHK001, CHK017) and `[Consistency]` (CHK020, CHK021, CHK032, CHK042) indicate
  requirements that disagree with each other or exist only in design documents. These are the highest-value
  items: a design document is not a requirement, and an implementer following the spec alone would miss them.
- `[Gap]` items may be legitimate deferrals. The point is that the deferral becomes explicit and dated
  rather than discovered mid-implementation.
- This checklist tests the requirements, not the implementation. Nothing here should be resolved by
  writing code.
