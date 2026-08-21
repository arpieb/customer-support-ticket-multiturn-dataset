# Customer Support Ticket Multi-Turn Dataset

A reproducible generator for multi-turn customer support conversations: synthetic ticket records
with conversation turns, ticket metadata, and the provenance needed to audit how any corpus was
produced.

Every run takes an explicit seed and a single configuration, writes a manifest recording how it
happened, and passes its own output through a blocking privacy scan before anything reaches the
release path. Those are not features bolted on — they are what
[the project constitution](.specify/memory/constitution.md) requires of any dataset this
repository publishes.

## Install

```bash
uv sync
uv run ticket-dataset --help
```

Python 3.14 or later. Dependencies are managed with `uv`; `uv.lock` is committed and updated in
the same change as any dependency edit.

## Credentials

Generating conversations calls a hosted model, so a run needs credentials:

Which credentials depends on which provider you point it at. Model access goes through
[litellm](https://docs.litellm.ai/), so `models.generator` and `models.judge` take a
`<provider>/<model>` string and the provider's usual environment variables apply:

```bash
export ANTHROPIC_API_KEY=...        # anthropic/claude-opus-4-5   (the default)
export OPENAI_API_KEY=...           # openai/gpt-5
export GEMINI_API_KEY=...           # gemini/gemini-2.5-pro
```

**No vendor is pinned.** No requirement in this project names one — switching providers is a
configuration change, not a code change.

### A self-hosted or remote provider

Anything litellm reaches works, including a remote Ollama server. The model string names the
provider; anything that provider needs goes in `extra`:

```toml
[models.generator]
model_id = "ollama_chat/llama3.1"

[models.generator.extra]
api_base = "http://ollama.internal:11434"    # without this, litellm assumes localhost
```

`configs/samples/ollama-remote.toml` is a worked example. Two things worth knowing:

- **Use `ollama_chat/`, not `ollama/`.** The chat endpoint honours the system message this
  pipeline relies on for its cache-stable prompt prefix, and supports the structured-output
  `format` parameter that response validation is built around (Ollama ≥ 0.5).
- **Smaller models fail structural validation more often.** Every response must return the exact
  turn count with strictly alternating roles; a model that drifts will produce discards rather
  than bad records, and the run reports them by reason. If the coherence discard rate exceeds its
  threshold the run fails, which is the intended signal — not a bug to work around.
- **Expect to raise `privacy.max_discard_rate`.** The 0.5% default assumes a model that follows
  the prompt document almost always. A 20-record run against `gpt-oss:20b` complied 22 times out
  of 25 and invented a realistic-looking domain three times — 12%, which fails the default. Raising
  it weakens an alarm, not the gate: those records are still blocked and still quarantined. Read
  `quarantine.jsonl` to see what tripped, and lower the threshold back as steering improves.

Credentials are an **access mechanism**, not a generation input. They never influence output and
are never written to a manifest, report, checkpoint, or log. Anything else in the environment that
could change *which* model serves a request — an alternate endpoint, a profile, a region — is
recorded in the manifest, because it can change output and unrecorded state that changes output is
exactly what reproducibility forbids.

The privacy scan needs neither credentials nor a network. That is deliberate: the gate protecting
the release path never depends on a remote service.

## Your first corpus

`configs/samples/smoke.toml` asks for 20 records — about 40 model calls.

```bash
uv run ticket-dataset generate --config configs/samples/smoke.toml --seed 42
```

It reports progress as it goes — records completed, elapsed time, rate, and an estimate — so a
long run against a slow model is visibly working rather than possibly hung:

```
  7/20 records  (35%)  1m12s  5.8/min  eta 2m14s
```

Progress goes to stderr; stdout carries only the machine-readable report, so piping is safe.
`--quiet` suppresses it for unattended runs.

Check what it would do first, without spending anything:

```bash
uv run ticket-dataset generate --config configs/samples/smoke.toml --seed 42 --dry-run
```

On success you get three files in `data/release/`:

| File | What it is |
|---|---|
| `smoke.jsonl` | The corpus, one JSON record per line |
| `<run_id>.manifest.json` | How the run happened: seed, config, code revision, input hashes, counts, discards |
| `<run_id>.report.json` | What the run found: privacy findings, composition, score distribution |

The manifest is named by run identifier so that **a single record locates its own provenance** —
take any record's `run_id`, look for `<run_id>.manifest.json` beside the corpus, and you have the
seed and configuration that produced it.

## Writing a configuration

A configuration is TOML. The minimum is a record count and an output path; everything else has a
documented default.

```toml
record_count = 500
output_path = "data/release/my-corpus.jsonl"

[turns]
min = 4
max = 10

[composition.category]
billing = 0.5
technical = 0.3
account = 0.2

[models.generator]
model_id = "anthropic/claude-opus-4-5"     # any litellm-supported provider

[models.judge]
model_id = "anthropic/claude-opus-4-5"
```

Two things commonly surprise people, and both refuse **before** any model call rather than after:

- **Proportions must sum to 1.0** for each dimension you specify.
- **Small corpora cannot hold tight tolerances.** Assigning whole records bounds per-member error
  at `100 / record_count`, so a 20-record corpus cannot honour the default ±2pp. The run refuses
  and names both remedies — a larger corpus, or a wider tolerance.
  `configs/samples/smoke.toml` widens it to 10pp for exactly this reason.

See `configs/samples/` for worked examples, and
[the feature specification](specs/001-ticket-generation-pipeline/spec.md) for every setting.

Those samples are tracked; anything else under `configs/` is ignored by git. Put your own configs
there — they tend to carry a host address or a model only you can reach, which is nobody else's
default. Nothing is lost by keeping them out of the repository: every manifest embeds the full
resolved config a run used, so a published corpus stays reproducible from its own artifacts.

## What the run guarantees

- **Reproducible structure.** The same seed and configuration produce the same metadata, subdomain,
  turn count, and timestamps at every position, whatever concurrency you run at. Conversation
  *text* is model output and is not reproducible; the manifest records the model identity and
  parameters so a run that cannot be replayed can still be audited.
- **Nothing unscanned reaches the release path.** There is no code path that puts a file in
  `data/release/` without the privacy gate having demonstrated its detector coverage for that run.
- **Accounting that closes.** `records generated − discards = records written`, always, including
  across an interruption and resume.

## Interruptions

A long run checkpoints as it goes. If it stops — you killed it, a budget ceiling was reached, or a
discard rate breached its threshold — the partial corpus and its checkpoint stay in
`data/interim/<run_id>/`, and nothing appears in `data/release/`.

```bash
uv run ticket-dataset generate --config configs/samples/medium.toml --seed 11 --resume
```

Resuming refuses if the configuration, seed, prompt document, or rubric changed since the
checkpoint — continuing under changed inputs would produce a corpus the manifest could not honestly
describe. A changed **code revision** does not refuse; it is recorded as an additional manifest
segment instead.

## Privacy

The scan runs on every structurally valid response, before it is judged, and blocks any record
carrying an unreviewed finding.

```bash
uv run ticket-dataset privacy scan data/release/my-corpus.jsonl
```

Findings never reproduce the matched value. They carry a masked rendering — the domain of an email,
the issuer range of a card, shape alone for a government identifier — which is what a reviewer
adjudicates from. Values drawn from ranges standards reserve for fiction (`example.com`,
`555-0100`–`555-0199`, the published test card numbers) are reported but never block: they cannot
belong to anyone.

For anything a mask cannot settle, blocked records are quarantined under `data/interim/<run_id>/`
and can be approved in place:

```bash
uv run ticket-dataset privacy approve \
  --from-quarantine data/interim/<run_id>/quarantine.jsonl \
  --record-id <id> --field 'turns[3].content' \
  --category EMAIL --reason "vendor sandbox address" --by "$(git config user.email)"
```

The approvals file stores a fingerprint, never the value — and the reason you type is itself
scanned, so an approval cannot smuggle the value back in through free text.

## Known limitations

Stated here rather than discovered later:

- **Postal addresses, bank accounts, non-US government identifiers, and person names are not
  detected.** Offline detection of them is not reliable, so they are declared gaps that every
  report restates. The corpus is synthetic by construction; the scan is a safety net confirming
  that held, not the primary control.
- **The coherence threshold is a default, not a validated one.** Nothing obliges a calibration to
  happen or a release to cite one. `sample-for-review` and `ticket-dataset calibrate` make the
  comparison cheap and leave a committed record under `calibration/`, but running them is a
  choice. See `calibration/README.md`.
- **A judge can score generously without anyone noticing.** Rubric v1 offered three anchors per
  criterion and a self-hosted judge returned three distinct scores across twenty records, 70% of
  them perfect — leaving the threshold nothing to separate. v2 uses a continuous scale, but the
  general risk remains: check the `distinct` count in a calibration record before trusting a
  threshold.
- **The judge shares the generating model by default.** Self-preference bias is real; the
  mitigation is that the judge scores declared rubric criteria rather than choosing between
  candidates. Pointing the roles at different models is a configuration change.
- **Turn counts are uniform over the configured range**, which produces more long conversations
  than real support traffic contains.

## Development

```bash
uv run pytest          # the whole suite; no test makes a network call
uv run ruff check .
uv run ruff format .
```

The entire pipeline is exercised against a scripted fake model, so the suite is free, fast, and
deterministic. `src/ticket_dataset/model/litellm_client.py` is the only module that reaches a
provider; nothing under `tests/` imports it, and a contract test asserts that importing the
package does not pull the provider stack in.

The record contract is the Pydantic model in `src/ticket_dataset/schema/record.py`; it exports
[`contracts/record.schema.json`](specs/001-ticket-generation-pipeline/contracts/record.schema.json)
and a contract test fails on any drift, so a schema change cannot land without the published
contract changing in the same commit.
