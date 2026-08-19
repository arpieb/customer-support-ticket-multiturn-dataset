# Contract: Command-Line Interface

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-08-19

Entry point `ticket-dataset`, built with Typer. The CLI is a **thin wrapper**: it parses arguments, calls
the programmatic API in [python-api.md](./python-api.md), renders a report, and exits with a status derived
from that report's verdict. It contains no generation, validation, or scanning logic of its own, so the
machine verdict and the human text cannot disagree (FR-036).

---

## `ticket-dataset generate`

Produce a corpus. The primary command.

| Option | Type | Default | Notes |
|--------|------|---------|-------|
| `--config PATH` | path | — | **Required.** The single serialized configuration (FR-008) |
| `--seed INT` | int | — | **Required.** Explicit; there is no implicit or time-derived seed (Principle II) |
| `--out PATH` | path | from config | Overrides `output_path`. Must be under `data/release/` and must not exist (FR-013, FR-014) |
| `--report PATH` | path | beside the artifact | Machine-readable run report (FR-036) |
| `--resume` | flag | off | Resume the checkpointed run for this config+seed (FR-015b) |
| `--dry-run` | flag | off | Validate config, apportion composition, assert the detector floor, and report the plan — no model calls |
| `--quiet` | flag | off | Suppress progress; the report is still written |

Progress is reported to stderr while records stream to the staging file (FR-012), so a long run is
observable without polluting stdout.

**Exit statuses**

| Code | Meaning |
|------|---------|
| `0` | Corpus written to the release path; every threshold satisfied |
| `1` | Run failed a threshold (privacy discard rate, coherence discard rate, composition tolerance — each computed over `records_generated` per FR-026a) or stopped short. Manifest and report are still written; the artifact is **not** moved into `data/release/` |
| `2` | Refused before generating: invalid config, unsatisfiable composition, a tolerance unachievable at the requested corpus size, existing output path, a floor type that failed its canary probe, or a resume whose inputs no longer match (FR-011, FR-018, FR-018a, FR-031b, FR-032, FR-015e) |
| `3` | Interrupted, **or a declared budget was exhausted** (FR-012f); progress checkpointed and resumable. Completed work is never lost to a ceiling |

The distinction between `1` and `2` is the point: `2` means nothing was generated and nothing was spent;
`1` means a corpus exists in staging and its accounting explains why it did not qualify.

---

## `ticket-dataset validate-manifest PATH`

Check a manifest against the manifest contract and its reconciliation rule (FR-028).

Exit `0` when valid; `1` when invalid, naming every missing or inconsistent element — including a failed
`records_generated - discards == records_written` (FR-026), a discard reason outside the closed set
(FR-026b), or a checksum that does not match the artifact beside it (FR-025b).

Manifests are named `<run_id>.manifest.json` and written beside the artifact (FR-029a), so a record's own
`run_id` finds its provenance without knowing which corpus it came from.

---

## `ticket-dataset privacy scan PATH`

Run the offline privacy scan over an existing JSONL artifact, independently of a generation run. Useful for
re-checking an artifact after the exception file changes.

| Option | Type | Default | Notes |
|--------|------|---------|-------|
| `--exceptions PATH` | path | `privacy/exceptions.json` | Approved-exception fingerprints (FR-022) |
| `--report PATH` | path | stdout | Machine-readable findings |

Exit `0` when clean or fully excepted; `1` when unreviewed findings exist. Findings name record ID, field,
category, detector, and a masked rendering, and **never** reproduce the matched value (FR-020, FR-020a).
Every report enumerates the identifier types the scan **covers** as well as those it does not — at the same
specificity as the floor, so `US_SSN` covered never reads as government identifiers covered — alongside the
detectors that ran, the counts examined, and the quarantine path and count when a generation run produced
one (FR-019, FR-021b, FR-023).

---

## `ticket-dataset privacy approve`

Record a reviewed finding as an approved exception.

| Option | Type | Notes |
|--------|------|-------|
| `--category` | enum | The PII category of the finding |
| `--value` | str | The value, read from stdin or a prompt — **fingerprinted immediately and never written** (research R9) |
| `--from-quarantine PATH --record-id ID --field F` | path/str | Alternative to `--value`: read the value straight out of the quarantine artifact, so the reviewer never has to retype or paste it (FR-021b) |
| `--reason` | str | **Required.** The reviewer's stated justification (FR-022). Scanned by the registered detectors and refused if it trips them (FR-022b) |
| `--by` | str | **Required.** Who is approving. Self-approval is permitted and recorded rather than prohibited (FR-022a) |

Appends `{fingerprint, category, reason, approved_by, approved_on}` to the exception file. The file is
committed; it never contains a raw value. Approvals do not expire — every active exception must instead be
listed in the datasheet of any release that relies on it, so review happens at the moment that matters
rather than on a timer (FR-022a).

**Where the reviewer's judgment comes from**: the masked rendering in the report settles the common cases
(a synthetic domain, a 555 number, a test card range). When it does not, the quarantined record is the
fallback — which is why FR-021b exists. Without one of the two, approval would be a judgment about
something no artifact contains.

---

## `ticket-dataset sample-for-review`

Export a seeded random sample of records with their coherence scores, for the human calibration SC-011
requires.

| Option | Type | Default | Notes |
|--------|------|---------|-------|
| `--corpus PATH` | path | — | **Required** |
| `--n INT` | int | `50` | Sample size |
| `--seed INT` | int | — | **Required** — the sample is itself reproducible |
| `--out PATH` | path | stdout | JSONL of sampled records plus scores |

The calibration judgment is a human act; this command exists so it is cheap rather than automated.

---

## `ticket-dataset schema export`

Write the JSON Schema export of the record contract to stdout or `--out`. CI runs this and fails on any
diff against `specs/001-ticket-generation-pipeline/contracts/record.schema.json`, so a schema change cannot
land without the committed contract changing in the same commit (Principle I).

---

## Conventions

- **stdout** carries machine-readable output only; **stderr** carries progress and human text. A piped
  invocation is never corrupted by progress lines.
- Every command that can fail names the specific problem rather than a generic message (FR-011, FR-032).
- No command reads hidden state from the operator's environment beyond model credentials (FR-008); every
  other input arrives as an explicit option or a committed file.
