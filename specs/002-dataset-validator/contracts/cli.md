# Contract: Command-Line Interface

A thin wrapper over [python-api.md](./python-api.md). Every command parses arguments, calls exactly one API
function, renders the returned `Report`, and exits with its status. **No command implements checking logic**
(FR-032).

## Commands

| Command | Calls | Purpose |
|---------|-------|---------|
| `ticket-dataset-generator validate <path>` | `validate_records` | Schema conformance (US1) |
| `ticket-dataset-generator scan <path>` | `scan_privacy` | Privacy scan (US2) |
| `ticket-dataset-generator invariants <path>` | `check_invariants` | Quality invariants (US3) |
| `ticket-dataset-generator manifest-check <path>` | `validate_manifest` | Manifest validity (US4) |
| `ticket-dataset-generator gate <path>` | `run_gate` | Composite release gate (FR-026) |
| `ticket-dataset-generator export-schema` | `export_json_schema` | Write the JSON Schema export (R1) |

## Shared options

| Option | Default | Meaning |
|--------|---------|---------|
| `--format {text,json}` | `text` | Report rendering. `json` emits the `Report` verbatim (FR-011) |
| `--exceptions PATH` | none | Approved privacy exceptions file (FR-016) |
| `--manifest PATH` | none | Manifest to validate alongside the artifact (`gate` only) |
| `--schema-version VER` | `SCHEMA_VERSION` | Version to validate against (`validate` only) |

## Exit statuses (FR-031)

| Status | Meaning |
|--------|---------|
| `0` | Verdict `pass` — no blocking findings |
| `1` | Verdict `fail` — one or more blocking findings |
| `2` | Usage error: unreadable path, bad option, unparseable exceptions file |
| `3` | Configuration error: detector registry does not cover the FR-013d blocking floor (fails closed) |

Status `3` is deliberately distinct from `1`: a floor-coverage failure means the gate could not be trusted
to run, which is a different condition from an artifact that was checked and found wanting. Collapsing them
would let a misconfigured environment read as ordinary data failure.

## Guarantees

- Identical verdict and findings to the equivalent API call for the same input (FR-032).
- Fully offline; no network access at run time (FR-013c).
- `--format json` output is the serialized `Report`, so automation never parses prose (FR-011).
- Reports never contain matched PII values, so CLI output is safe to paste into CI logs (R4).
- `scan` and `gate` output names the categories the scan does not cover (FR-013e), so a `pass` verdict is
  never mistaken for coverage the detector set does not provide.
