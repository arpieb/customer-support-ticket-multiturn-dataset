# Dataset cards

One card per released dataset version, named `v<MAJOR>.<MINOR>.<PATCH>.md`, following the
[Hugging Face dataset card template](https://github.com/huggingface/huggingface_hub/blob/main/src/huggingface_hub/templates/datasetcard_template.md)
and the [metadata spec](https://github.com/huggingface/hub-docs/blob/main/datasetcard.md).

- **`TEMPLATE.md`** — fill this in for a new release. It is domain-agnostic: any corpus this
  pipeline produces from any domain prompt.
- **`EXAMPLE.md`** — the template filled in against a real run of the consumer-electronics sample
  domain, so it can be read alongside. It is not a release: this repository commits no corpus, and
  no dataset version has been published from it.

These are documents, not automation. Releasing is a manual act: copy the card for the version
being released to the Hub dataset repository as its `README.md`, and upload the corpus alongside
it. Nothing in `src/` knows the Hub exists, and nothing here should teach it — the pipeline's job
ends when a run publishes to `data/release/`.

## Filling in a card

`TEMPLATE.md` opens with instructions in an HTML comment; strip that comment once the card is
written. It marks two kinds of placeholder, and the distinction is the point:

- `{{ FACT: ... }}` names the artifact and field a value must be read from. Never inferred, never
  carried across from a conversation, never rounded into something tidier.
- `{{ WRITE: ... }}` is prose to compose — judgement rather than lookup.

A card is worth something only because a reader can check it against the manifest, the report and
the corpus. One invented number costs the whole document its standing, so the template names a
source for every figure rather than trusting whoever fills it in to remember.

Two habits the template enforces, because both are easy to get wrong:

**Verify against the corpus, not the config.** A config states what was requested; the corpus is
what survived the gates. Turn ranges, field values and subdomain coverage are computed from the
records. `composition_achieved` in the manifest is the achieved distribution and may be quoted.

**State what is unflattering.** The template lists what to check — whether one model both generated
and judged, whether a composition dimension is constant and therefore useless as a signal, what
calibration found, how small the corpus is, what the privacy scan does not cover. A card that
only lists strengths is worth nothing to someone deciding whether to trust the data, and an
omission a reader discovers later discredits everything else in it.

## Versioning

`MAJOR.MINOR.PATCH`, with the meanings the constitution already fixes for dataset releases:
MAJOR for a breaking schema or semantic change, MINOR for added records or additive fields, PATCH
for corrections that neither add nor remove fields. This is the **dataset** version and moves
independently of the generator's version in `pyproject.toml` — the same generator can produce many
dataset versions, and a generator fix that leaves the corpus untouched is not a dataset release.

A version is marked in git with a `dataset-v<version>` tag on the commit whose card describes it.
That is also how the Hub versions a dataset: revisions are git refs, so a tag here and a tag there
mean the same thing without anything having to synchronise them.

## Defaults

**License: `cc-by-4.0`**, unless a domain calls for something else. Attribution-only suits a
corpus that is synthetic by construction: there is no underlying data whose terms could constrain
reuse, and requiring attribution keeps the provenance trail — which is the whole argument for
trusting the corpus — attached to it downstream.

**No test split.** The pipeline emits one corpus per run. Splitting is the consumer's decision and
depends on their task; a split baked into the card would be an arbitrary one.

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
