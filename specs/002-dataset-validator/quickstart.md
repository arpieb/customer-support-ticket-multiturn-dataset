# Quickstart: Validating an Artifact

> ⚠️ **Superseded scope.** Written as feature 001 under the framing that validation was the primary
> deliverable. The generator is the product; this is a complementary tool. Schema, run manifest, and
> the blocking PII scan moved to feature 001. See the banner in `spec.md`. Kept for reuse; do not
> implement from it as-is.

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Contracts**:
[python-api.md](./contracts/python-api.md), [cli.md](./contracts/cli.md)

This guide is the end-to-end proof that the harness works. It is written to be runnable by a new
contributor with no assistance, which is what SC-009 measures. Field-level details live in
[data-model.md](./data-model.md) and are not repeated here.

## Prerequisites

- Python 3.14+ and [uv](https://docs.astral.sh/uv/)
- A clone of this repository

## Setup

```bash
uv sync                       # installs pydantic, datafog (core, no extras), typer, pytest
uv run ticket-dataset-generator --help  # confirms the CLI entry point resolves
```

The `datafog` install must be the **core** install — no extras. If `spacy` or `torch` appear in
`uv.lock`, the offline guarantee (FR-013c) is broken and the install is wrong.

## Scenario 1 — A clean artifact passes (US1)

```bash
uv run ticket-dataset-generator validate tests/fixtures/clean.jsonl
```

**Expected**: verdict `pass`, a reported count of records examined that matches the fixture's line count,
the schema version validated against, and exit status `0`.

## Scenario 2 — Malformed records are reported individually (US1)

```bash
uv run ticket-dataset-generator validate tests/fixtures/defects/schema_violations.jsonl
```

**Expected**: verdict `fail` and exit status `1`. Every planted defect appears as its own finding naming
the record ID, the field, and the reason. A record that is not parseable at all is reported by line number
instead, and the run continues past it rather than stopping (FR-008, FR-009).

## Scenario 3 — The privacy scan blocks a release (US2)

```bash
uv run ticket-dataset-generator scan tests/fixtures/defects/pii_planted.jsonl
```

**Expected**: verdict `fail`, exit status `1`, one finding per planted identifier with its record ID,
field, category, and the detector that reported it. The detectors that ran are named in the report, so a
clean result is attributable (FR-013b), and the report states which categories are **not** covered —
currently full postal address and bank account number (FR-013e).

**Confirm no PII is echoed**: the report must not contain the matched values themselves — only their
locations and categories (R4). This is what makes the output safe to paste into a CI log.

## Scenario 4 — An approved exception unblocks without hiding (US2)

```bash
uv run ticket-dataset-generator scan tests/fixtures/defects/pii_planted.jsonl \
  --exceptions tests/fixtures/exceptions/approved.json
```

**Expected**: the previously blocking finding is still listed, now with `blocking = false` and its recorded
reason; the verdict flips to `pass` and exit status to `0` (FR-016). The exceptions file contains
fingerprints, never raw values — open it and confirm.

## Scenario 5 — Invariant violations are caught in one pass (US3)

```bash
uv run ticket-dataset-generator invariants tests/fixtures/defects/invariant_violations.jsonl
```

**Expected**: verdict `fail`; one finding per planted violation — out-of-order turns, consecutive
same-speaker turns, empty turns, duplicate conversations (grouped, naming the retained record), and
duplicate record IDs reported distinctly from duplicate content. All appear in a single run (FR-021).

## Scenario 6 — A manifest reconciles (US4)

```bash
uv run ticket-dataset-generator manifest-check tests/fixtures/manifests/valid.json
uv run ticket-dataset-generator manifest-check tests/fixtures/manifests/unbalanced.json
```

**Expected**: the first passes. The second fails, naming the discrepancy — its removal counts do not
reconcile input to output (FR-023). A manifest missing a required element names the missing element
(FR-024).

## Scenario 7 — The composite release gate (FR-026)

```bash
uv run ticket-dataset-generator gate tests/fixtures/clean.jsonl \
  --manifest tests/fixtures/manifests/valid.json --format json
```

**Expected**: a single consolidated JSON `Report` covering every gate run, with `gates_run`,
`detectors_run`, `records_examined`, and per-gate counts. Exit status `0`. This JSON is the machine
contract — automation reads it rather than parsing prose (FR-011).

Then confirm the gate fails closed on an empty artifact:

```bash
uv run ticket-dataset-generator gate tests/fixtures/empty.jsonl   # expect verdict fail, exit 1 (FR-027)
```

## Scenario 8 — Floor coverage fails closed (FR-013d)

With a registry configured to omit one of the four blocking-floor categories — `EMAIL`, `PHONE`,
`CREDIT_CARD`, `GOVERNMENT_ID` — the gate must refuse to run rather than report clean. **Expected**: exit
status `3`, distinct from an ordinary data failure, with a message naming the uncovered categories.
Exercised as a contract test rather than by hand.

## Running the test suite

```bash
uv run pytest                      # all contract, integration, and unit tests
uv run pytest tests/contract       # public API and CLI contracts only
```

**Expected**: every planted defect in `tests/fixtures/defects/` is detected, and no record in
`tests/fixtures/clean.jsonl` produces a finding — the two halves of SC-003.

## Checking schema-export drift

```bash
uv run ticket-dataset-generator export-schema --check
```

**Expected**: exit `0` when the committed
[`specs/001-ticket-generation-pipeline/contracts/record.schema.json`](../001-ticket-generation-pipeline/contracts/record.schema.json)
matches what the models generate; non-zero
when they have drifted, so a breaking change cannot land without showing up as a schema diff in review
(R1, Principle I).
