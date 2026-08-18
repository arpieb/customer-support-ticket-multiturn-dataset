# customer-support-ticket-multiturn-dataset

A generation pipeline for a synthetic, multi-turn customer support ticket dataset — and the
dataset artifacts it produces.

> **Status: bootstrapping.** The repository currently contains project governance and the
> Spec Kit scaffolding. The generation pipeline itself has not been implemented yet.

## What this is

The deliverable is a corpus of multi-turn conversations between customers and support agents,
suitable for training and evaluating models on support tasks. Records are synthetic by
construction — the project does not admit real personal data at any stage (see Principle IV
below).

Each released version ships with a manifest describing how it was generated and a datasheet
describing its composition, method, known limitations, and intended use.

## Governance

Development is bound by the [project constitution](.specify/memory/constitution.md) (v1.0.0).
Its five principles are non-negotiable for any change on a release path:

| # | Principle | In short |
|---|-----------|----------|
| I | Schema-First Data Contracts | The record schema is declared, versioned, and committed before the code that reads or writes it |
| II | Reproducible Generation | Every run takes an explicit seed and a serialized config, and writes a manifest that makes it replayable or auditable |
| III | Provenance & Traceability | Every record traces to its run, source, and schema version; filtered records are accounted for by reason |
| IV | Privacy by Construction | No real personal data enters `data/`, ever; a blocking automated PII scan gates the pipeline |
| V | Validation Gates Before Release | Schema validation, PII scan, quality invariants, and sampled human review all gate a release |

Read the constitution before contributing — it governs schema changes, release versioning, and
what must be true before a dataset version ships.

## Tech stack

- **Python** `>=3.14`
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment management — `uv.lock` is
  committed and must be updated in the same change as any dependency edit
- **JSON Lines** as the dataset source of truth; other formats are exports generated from it

## Getting started

```bash
uv sync          # create the environment from uv.lock
uv run main.py   # stub entry point
```

## Repository layout

```text
.specify/
  memory/constitution.md   # project constitution — the binding rules
  templates/               # spec / plan / tasks templates, with constitution gates wired in
.claude/skills/            # Spec Kit slash commands for coding agents
data/                      # dataset artifacts (empty; not yet populated)
main.py                    # stub entry point
```

Large dataset files are not committed directly. Where an artifact exceeds practical Git limits,
the repository stores its generation config, manifest, and checksums instead.

## Development workflow

Work proceeds through the Spec Kit flow, one feature at a time:

```text
/speckit-specify → /speckit-clarify → /speckit-plan → /speckit-tasks → /speckit-implement
```

The planning step evaluates a Constitution Check gate table before research and again after
design; the tasks step carries constitution gate tasks for any release-path change.
