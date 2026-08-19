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
| `1` | Run failed a threshold (privacy discard rate, coherence discard rate, composition tolerance) or stopped short. Manifest and report are still written; the artifact is **not** moved into `data/release/` |
| `2` | Refused before generating: invalid config, unsatisfiable composition, existing output path, detector floor not covered, or a resume whose inputs no longer match (FR-011, FR-018, FR-032, FR-015e) |
| `3` | Interrupted; progress checkpointed and resumable (FR-015a) |

The distinction between `1` and `2` is the point: `2` means nothing was generated and nothing was spent;
`1` means a corpus exists in staging and its accounting explains why it did not qualify.

---

## `ticket-dataset validate-manifest PATH`

Check a manifest against the manifest contract and its reconciliation rule (FR-028).

Exit `0` when valid; `1` when invalid, naming every missing or inconsistent element — including a failed
`records_generated - discards == records_written` (FR-026).

---

## `ticket-dataset privacy scan PATH`

Run the offline privacy scan over an existing JSONL artifact, independently of a generation run. Useful for
re-checking an artifact after the exception file changes.

| Option | Type | Default | Notes |
|--------|------|---------|-------|
| `--exceptions PATH` | path | `privacy/exceptions.json` | Approved-exception fingerprints (FR-022) |
| `--report PATH` | path | stdout | Machine-readable findings |

Exit `0` when clean or fully excepted; `1` when unreviewed findings exist. Findings name record ID, field,
category, and detector, and **never** reproduce the matched value (FR-020). Every report states the
detectors that ran, the counts examined, and the declared gaps (FR-019, FR-023).

---

## `ticket-dataset privacy approve`

Record a reviewed finding as an approved exception.

| Option | Type | Notes |
|--------|------|-------|
| `--category` | enum | The PII category of the finding |
| `--value` | str | The value, read from stdin or a prompt — **fingerprinted immediately and never written** (research R9) |
| `--reason` | str | **Required.** The reviewer's stated justification (FR-022) |

Appends `{fingerprint, category, reason, approved_on}` to the exception file. The file is committed; it
never contains a raw value.

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
