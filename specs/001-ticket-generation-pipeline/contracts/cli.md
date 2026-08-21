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
| `--config PATH` | path | — | The single serialized configuration (FR-008). Required unless `--from-manifest` is given |
| `--seed INT` | int | — | Explicit; there is no implicit or time-derived seed (Principle II). Required with `--config`; refused with `--from-manifest`, which carries the recorded seed |
| `--from-manifest PATH` | path | — | Reproduce the run a manifest describes, taking both its configuration and its seed (FR-040, FR-041). Naming it alongside `--config` or `--seed` refuses rather than choosing between them |
| `--allow-drift` | flag | off | Proceed with `--from-manifest` even though a recorded input has changed. The run is announced as not reproducing the recorded corpus (FR-041) |
| `--out PATH` | path | from config | Overrides `output_path`, and is applied **before** validation, so the occupied-path check tests the destination actually being written rather than the one the config names. Must be under `data/release/` and must not exist. There is deliberately **no** overwrite option — the run refuses and names the path, and removing a release artifact stays a manual act (FR-013, FR-014) |
| `--report PATH` | path | see below | Overrides the report location. By default the JSON report is `<run_id>.report.json` beside the artifact on success, and `data/interim/<run_id>/report.json` otherwise — locatable from a run identifier either way (FR-036a) |
| `--resume` | flag | off | Resume a checkpointed run. The candidate is found by matching input fingerprints; several matches refuse and list them (FR-015h) |
| `--run-id ID` | str | — | Names the run to resume when fingerprint matching is ambiguous (FR-015h) |
| `--dry-run` | flag | off | Validate config, apportion composition, assert the detector floor, and report the plan — no model calls |
| `--quiet` | flag | off | Suppress progress; the report is still written |

Progress is reported to stderr while records stream to the staging file (FR-012, FR-012g): records
completed against the target, elapsed time, rate, an estimate once enough records exist to make one
meaningful, and the discard count so far. A terminal gets one line rewritten in place; a pipe or a CI log
gets whole lines, bounded to roughly twenty for a run of any size. `--quiet` suppresses it. stdout carries
the machine-readable report and nothing else, so a piped invocation is never corrupted.

**Exit statuses**

| Code | Meaning |
|------|---------|
| `0` | Corpus written to the release path; every threshold satisfied |
| `1` | Run failed a threshold (privacy discard rate, coherence discard rate, composition tolerance — each computed over `records_generated` per FR-026a) or stopped short. Manifest and report are still written; the artifact is **not** moved into `data/release/` |
| `2` | Refused before generating: invalid config, unsatisfiable composition, a tolerance unachievable at the requested corpus size, existing output path, a floor type that failed its canary probe, or a resume whose inputs no longer match, an ambiguous or unreadable checkpoint, or a destination another run has already claimed, or a `--from-manifest` reproduction whose recorded inputs no longer match the working tree (FR-011, FR-018, FR-018a, FR-031b, FR-032, FR-015e, FR-015g, FR-015h, FR-014a, FR-041) |
| `3` | **Stopped**: interrupted, a declared budget exhausted (FR-012f), or a discard-rate threshold breached mid-run (FR-037). Progress checkpointed and resumable; completed work is never lost |

The four statuses map onto the four run outcomes FR-036b requires — completed, refused, failed, stopped —
because a binary cannot carry the distinction. `2` means nothing was generated and nothing was spent; `1`
means a corpus exists in staging and its accounting explains why it did not qualify; `3` means work is
preserved and resumable. The report's `outcome` field carries the same value for automation that should not
be reading exit codes.

---

## `ticket-dataset config-from-manifest PATH`

Recover the configuration a run used, from the manifest it wrote (FR-040).

| Option | Type | Default | Notes |
|--------|------|---------|-------|
| `--out PATH` | path | stdout | Write the recovered configuration here instead of to stdout |

What comes back is the **resolved** configuration — every default already materialised — so an unstated
default cannot change the recovered run's meaning. The rendered file is parsed back and compared against
the configuration it came from before anything is written; if it would load as a different run, nothing is
written at all. A subtly wrong configuration is worse than none, because it looks like it worked.

The configuration alone does not reproduce a run, so the conditions around it are reported on stderr: the
seed, each recorded input digest against the file on disk now, the code revision and whether it was dirty,
any routing environment variable that must be set to match, and the connection settings the run used, by
name (FR-041, FR-042). When every input still matches, the exact `generate` invocation is printed.

Connection settings are named but never recovered — their values were never recorded, so reproducing a run
means supplying them. That is the intended cost of not publishing an endpoint address in an artifact that
ships with the dataset.

**Exit statuses**

| Code | Meaning |
|------|---------|
| `0` | Configuration recovered; every recorded input still matches the working tree |
| `1` | Configuration recovered, but a recorded input has changed or is missing — the run will not reproduce as things stand. The file is still written, since deriving a new run from it is legitimate |
| `2` | Refused: the path does not exist, is not valid JSON, is not a manifest, carries no configuration, or would not round-trip |

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
re-checking an artifact after the exception file changes — re-running generation to verify an approval would
cost two model calls per record.

The path is deliberately unrestricted, which is **shared surface with feature 002** (spec Assumptions): 002
will need the same capability and is expected to reuse this implementation rather than grow a second one.
The boundary that holds is ownership — this feature owns the blocking gate over its own output; 002 owns
judging a dataset of uncertain provenance as a whole.

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
