<!--
FILLING THIS IN
===============

This is the Hugging Face dataset card template, adapted for a corpus this pipeline generated.
Copy it to `datasheets/v<version>.md` and replace every {{ ... }} placeholder.

Two kinds of placeholder, and the difference matters:

  {{ FACT: <where it lives> }}   Read it from the named artifact. Never infer it, never carry it
                                 from a conversation, never round it into something tidier. The
                                 card's whole value is that a reader can check it.

  {{ WRITE: <what to say> }}     Prose you compose. Judgement, not lookup.

Follow the Hub convention of leaving `[More Information Needed]` where something genuinely is not
known, rather than deleting the section or guessing.

Sources, given a run id R:

  MANIFEST  data/release/<R>.manifest.json
  REPORT    data/release/<R>.report.json
  CORPUS    the .jsonl the manifest's `output_filename` names
  PROMPT    the file at MANIFEST.config.prompt_document
  RUBRIC    the file at MANIFEST.config.rubric
  CALIB     calibration/<rubric_id>.calibration.json, if one exists

Verify against the CORPUS, not the config
-----------------------------------------
A config states what was requested; the corpus is what was produced, after discards. Claims about
turn ranges, field values, subdomain coverage, and alternation must be computed from the records.
`MANIFEST.composition_achieved` is the achieved distribution and may be quoted directly.

Say the unflattering things
---------------------------
A dataset card that only lists strengths is worth nothing to the person deciding whether to trust
the data. Before writing "Bias, Risks, and Limitations", check each of these and state the ones
that hold:

  - Did one model both generate and judge? Compare MANIFEST.models.generator.model_id against
    MANIFEST.models.judge.model_id. A model scoring its own output inflates agreement.
  - Is any composition dimension constant? A field with one value across the corpus is present and
    useless as a training signal, and a reader will not discover that from the schema.
  - What did calibration find? If CALIB exists, report it as it reads. A high gate-agreement rate
    is an artifact when neither side rejected anything — check the spreads before quoting it. A
    near-zero rank correlation means the scores should not be used to rank quality, and that is
    worth more to a reader than the headline number.
  - How large is the corpus, and is that enough for the uses being claimed?
  - How many models, prompts, seeds? One of each means stylistic tics run through everything.
  - What does the privacy scan not cover? REPORT names its declared gaps; restate them so a clean
    scan is not mistaken for coverage it does not provide.

Reproducibility is structural unless a sampling seed was set
------------------------------------------------------------
Check MANIFEST.models.generator.sampling_seed. Null means the conversation text differs on every
run and only the seeded choices repeat. Say so; do not claim textual reproduction.
-->
---
# For reference on dataset card metadata, see the spec: https://github.com/huggingface/hub-docs/blob/main/datasetcard.md?plain=1
# Doc / guide: https://huggingface.co/docs/hub/datasets-cards
pretty_name: {{ WRITE: a human-readable name naming the domain }}
language:
  - {{ FACT: MANIFEST.config.language }}
license: cc-by-4.0
task_categories:
  - text-generation
tags:
  - synthetic
  - customer-support
  - multi-turn
  - conversational
  - dialogue
size_categories:
  - {{ FACT: bucket MANIFEST.records_written — n<1K, 1K<n<10K, 10K<n<100K, 100K<n<1M }}
annotations_creators:
  - machine-generated
language_creators:
  - machine-generated
source_datasets:
  - original
configs:
  - config_name: default
    data_files:
      - split: train
        path: {{ FACT: MANIFEST.output_filename }}
---

# Dataset Card for {{ WRITE: the same name as pretty_name }}

{{ FACT: MANIFEST.records_written }} wholly synthetic multi-turn customer-support conversations in
{{ WRITE: the domain, from PROMPT }}, each with assigned ticket metadata, a machine coherence
score, and provenance linking it to the run that produced it.

## Dataset Details

### Dataset Description

{{ WRITE: what these conversations are and what they are for. Every conversation is fabricated by
a language model from a committed domain prompt; no real transcript, customer or agent is involved
and none was used as source material. Say what need the domain serves. }}

Each record is one complete ticket: an ordered sequence of turns alternating customer and agent,
starting with the customer, plus the metadata the conversation was generated to fit.

Composition is **assigned before generation rather than measured after it**. Each record's
category, priority, channel, resolution status, turn count, subdomain and timestamps are seeded
choices made from the run seed and the record's position, so the distribution is a property of the
request rather than an accident of what the model happened to produce.

- **Curated by:** {{ WRITE: who ran it }}
- **Funded by [optional]:** {{ WRITE: or [More Information Needed] }}
- **Shared by [optional]:** {{ WRITE: who publishes it }}
- **Language(s) (NLP):** {{ FACT: MANIFEST.config.language }}
- **License:** cc-by-4.0

### Dataset Sources [optional]

- **Repository:** {{ WRITE: the generator repository URL }}
- **Paper [optional]:** {{ WRITE: or None }}
- **Demo [optional]:** {{ WRITE: or None }}

## Uses

### Direct Use

{{ WRITE: what this corpus is genuinely suitable for, given its size and domain. Be specific to
the domain rather than generic. If the corpus is small, say what it is too small for here rather
than only in Limitations. }}

### Out-of-Scope Use

{{ WRITE: at minimum — it is not a sample of real traffic, so no frequency or distributional claim
about the world can rest on it; the coherence scores are machine-generated and are a filtering
artifact rather than ground truth; synthetic-by-construction is a different problem from
de-identified-after-the-fact, so it cannot validate a de-identification method. Add domain-specific
misuses: a medical or financial domain carries risks a consumer-electronics one does not. }}

## Dataset Structure

One JSON object per line (JSONL, UTF-8). {{ FACT: MANIFEST.records_written }} records,
{{ FACT: byte size of CORPUS }} bytes. A single `train` split.
{{ WRITE: why there is no test split, if there is not }}

| Field | Type | Notes |
|---|---|---|
| `record_id` | string (UUIDv5) | Stable, derived from the run and position |
| `record_index` | int | Position in the run, ascending |
| `run_id` | string (UUID) | The generation run; matches the manifest |
| `schema_version` | string | {{ FACT: MANIFEST.schema_version }} |
| `source_id` | string | Domain prompt identity: `name@sha256[:12]` |
| `subdomain` | string | Seeded choice from the prompt's declared list |
| `scenario` | string | The specific situation the model elaborated |
| `metadata` | object | `category`, `priority`, `channel`, `resolution_status`, `created_at`, `resolved_at` |
| `turns` | array | `{role: "customer"｜"agent", content: string}`, customer first, strictly alternating |
| `quality` | object | `coherence_score` (0–1), `rubric_id` |
| `generation` | object | `model_id`, `judge_model_id` |

`resolved_at` is present when and only when `resolution_status` is `resolved`.

**Achieved composition** {{ FACT: MANIFEST.composition_achieved, with the worst-member drift from
REPORT.composition_drift_pp }}:

| Dimension | Distribution |
|---|---|
| category | {{ FACT }} |
| priority | {{ FACT }} |
| channel | {{ FACT }} |
| resolution_status | {{ FACT }} |

Turn counts range {{ FACT: computed from CORPUS }}.
{{ FACT: distinct subdomains in CORPUS }} of the domain's {{ FACT: subdomains declared in PROMPT }}
declared subdomains appear.

## Dataset Creation

### Curation Rationale

{{ WRITE: why this dataset exists rather than a real one. The general argument — real support
tickets are dense with personal data, scrubbing afterwards is unreliable and irreversible once
published, so admit no real identifiers at any point — plus whatever is specific to this domain. }}

### Source Data

#### Data Collection and Processing

Generated by {{ FACT: MANIFEST.models.generator.model_id }} from a committed domain prompt document
({{ FACT: a record's source_id }}) declaring {{ FACT: count from PROMPT }} subdomains.

Per record: the pipeline assigns metadata from the seed, prompts the model for a conversation
fitting that assignment, then applies four gates in order — structural validation, a blocking
privacy scan, coherence judging, and schema validation. A record failing any gate is discarded and
counted by reason; the slot is retried up to {{ FACT: MANIFEST.config.max_attempts_per_slot }}
times. Output is written to staging and moved to the release path only after the privacy floor is
demonstrated against known canaries.

**This run:** {{ FACT: MANIFEST.records_generated }} generated,
{{ FACT: MANIFEST.records_written }} written. Discards: {{ FACT: MANIFEST.discards, by reason }}.
{{ FACT: MANIFEST.duplicate_count }} duplicates, {{ FACT: REPORT.privacy.blocking }} privacy
blocks.

Reproduction inputs: run `{{ FACT: MANIFEST.run_id }}`, seed `{{ FACT: MANIFEST.seed }}`, code
revision `{{ FACT: MANIFEST.code_revision.commit, first 12 }}`
{{ FACT: say so if code_revision.dirty is true — a corpus generated from an uncommitted tree
cannot be reproduced from any commit, and that belongs in the card }}, corpus SHA-256
`{{ FACT: MANIFEST.output_sha256 }}`.

{{ WRITE: state whether reproduction is structural or textual — see the note at the top of this
template. }}

#### Who are the source data producers?

A language model, prompted by an automated pipeline. No humans produced any conversational
content, and no human-authored text was used as source material.

### Annotations [optional]

#### Annotation process

Each conversation is scored 0–1 for coherence by a second model call against a committed, versioned
rubric ({{ FACT: rubric_id from RUBRIC }}) with {{ FACT: criteria and weights from RUBRIC front
matter }}. The record's score is the weighted mean. Records below
{{ FACT: MANIFEST.config.coherence.threshold }} are discarded before release; the score of every
surviving record is retained.

Score distribution: {{ FACT: MANIFEST.coherence_score_distribution }}.

#### Who are the annotators?

{{ FACT: MANIFEST.models.judge.model_id }}{{ WRITE: if it equals the generator model, say so here
and carry it into Limitations }}.

{{ WRITE: whether a human calibration exists. If CALIB exists, name the reviewer, sample size and
seed, and the path. If none exists, say that plainly — an uncalibrated judge is a fact a reader
needs. }}

#### Personal and Sensitive Information

The dataset contains no real personal data by construction. Identifier-shaped values are drawn
from ranges reserved for fiction — RFC 2606 domains (`example.com`, `.test`, `.invalid`), NANP
`555-0100`–`555-0199` phone numbers, published payment-card test numbers — so they cannot refer to
anyone.

Every record was scanned before admission: {{ FACT: REPORT.privacy.records_examined }} records,
{{ FACT: REPORT.privacy.fields_examined }} fields,
{{ FACT: REPORT.privacy.findings_by_status }}. {{ FACT: the state of privacy/exceptions.json —
every active exception, or that none has ever been approved }}.

The scan does not detect: {{ FACT: REPORT.privacy.declared_gaps }}. These are declared gaps, restated
here so a clean scan is not mistaken for coverage it does not provide. Person names in particular
are present throughout and are fabricated.

## Bias, Risks, and Limitations

{{ WRITE: work through the checklist at the top of this template and state every item that holds,
in plain terms, with the numbers that support it. Do not soften a finding to make the corpus look
better than it is — a reader who discovers the omission later has reason to distrust everything
else in the card. }}

### Recommendations

{{ WRITE: what a user should do about the limitations above. Be concrete: which fields not to
trust, which claims not to draw, what to do instead. }}

## Citation [optional]

**BibTeX:**

```bibtex
@misc{ {{ WRITE: key }},
  author       = { {{ WRITE }} },
  title        = { {{ WRITE: the dataset name }} },
  year         = { {{ FACT: year from MANIFEST.completed_at }} },
  version      = { {{ WRITE: the dataset version }} },
  howpublished = {\url{ {{ WRITE: repository URL }} }}
}
```

**APA:**

{{ WRITE: the same, in APA form }}

## Glossary [optional]

- **Slot** — one unit of generation work. Its metadata is assigned before any model call, which is
  what makes the composition exact and lets a discarded record be retried without changing the
  corpus shape.
- **Subdomain** — a category declared by the domain prompt document. Chosen by seed before
  dispatch; the model elaborates a specific scenario within it.
- **Exempt by range** — a privacy finding whose value comes from a range a standard reserves for
  fiction. Reported rather than hidden, so the scan never looks cleaner than it was.
- **Structural reproduction** — same seeded choices at every position, different conversation text.
  What this pipeline guarantees when no model sampling seed is set.
{{ WRITE: add any domain-specific terms a reader would not know }}

## More Information [optional]

The manifest and run report for this corpus are the authoritative provenance record: they carry
the full resolved configuration, input hashes, code revision, and the complete filter accounting.
`ticket-dataset config-from-manifest` recovers the exact configuration from the manifest, and
`ticket-dataset generate --from-manifest` reproduces the run, refusing if any recorded input has
since changed.

## Dataset Card Authors [optional]

{{ WRITE: who wrote this card, including any agent assistance }}

## Dataset Card Contact

{{ WRITE: how to reach the curator }}
