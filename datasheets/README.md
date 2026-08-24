# Dataset cards

One card per released dataset version, named `v<MAJOR>.<MINOR>.<PATCH>.md`, following the
[Hugging Face dataset card template](https://github.com/huggingface/huggingface_hub/blob/main/src/huggingface_hub/templates/datasetcard_template.md)
and the [metadata spec](https://github.com/huggingface/hub-docs/blob/main/datasetcard.md).

These are documents, not automation. Releasing is a manual act: copy the card for the version
being released to the Hub dataset repository as its `README.md`, and upload the corpus alongside
it. Nothing in `src/` knows the Hub exists, and nothing here should teach it — the pipeline's job
ends when a run publishes to `data/release/`.

## Versioning

`MAJOR.MINOR.PATCH`, with the meanings the constitution already fixes for dataset releases:
MAJOR for a breaking schema or semantic change, MINOR for added records or additive fields, PATCH
for corrections that neither add nor remove fields. This is the **dataset** version and moves
independently of the generator's version in `pyproject.toml` — the same generator can produce many
dataset versions, and a generator fix that leaves the corpus untouched is not a dataset release.

A version is marked in git with a `dataset-v<version>` tag on the commit whose card describes it.
That is also how the Hub versions a dataset: revisions are git refs, so a tag here and a tag there
mean the same thing without anything having to synchronise them.

## What a card must carry

Beyond the template's own sections, a release is not complete until the card states:

- the **run identifier, seed, and output SHA-256** of the corpus it describes, so the card is
  bound to one artifact rather than to a filename;
- the **model identity** that generated and judged it, since sampling is not reproducible and the
  model is the part of the provenance a rerun cannot recover (FR-010);
- **every active privacy exception** in `privacy/exceptions.json` at release time, or the fact
  that there were none (FR-022a);
- the **calibration record** for the rubric the corpus was judged against, and what it found —
  including when it found something unflattering.
