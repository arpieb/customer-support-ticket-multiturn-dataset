# Quickstart: Ticket Generation Pipeline

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-19

Runnable scenarios that prove the feature works end to end. Each maps to a success criterion or an
acceptance scenario, and each is expected to have an automated counterpart under `tests/`.

Details live in the contracts rather than here: [record.schema.json](./contracts/record.schema.json),
[manifest.schema.json](./contracts/manifest.schema.json), [cli.md](./contracts/cli.md),
[python-api.md](./contracts/python-api.md), [model-io.md](./contracts/model-io.md).

---

## Setup

```bash
uv sync                       # installs from the committed uv.lock
uv run ticket-dataset --help
```

**Credentials.** Generation calls a hosted model. Either export `ANTHROPIC_API_KEY`, or run
`ant auth login` once — the SDK resolves a stored profile with no environment variable set. Check with
`ant auth status`. The privacy gate never needs credentials or a network (FR-024).

**Offline-install guard.** The privacy scan must not acquire a model dependency by accident:

```bash
uv run python -c "import importlib.util as u; assert u.find_spec('spacy') is None and u.find_spec('torch') is None; print('offline detector install OK')"
```

This is also an automated test — a stray `datafog` extra would otherwise silently break the offline
guarantee (research R7).

---

## Scenario 1 — Generate a small corpus (US1, SC-002)

```bash
uv run ticket-dataset generate --config configs/smoke.toml --seed 42
```

`configs/smoke.toml` requests ~20 records, so the scenario costs about 40 model calls.

**Expect**: exit `0`; `data/release/smoke.jsonl` with exactly the requested number of lines; a manifest and
report beside it. Every record validates against the record contract, its turns alternate `customer` /
`agent` starting with the customer, no turn is empty, and each conversation concerns one support issue.

```bash
wc -l data/release/smoke.jsonl
uv run python -c "
import json,sys
from ticket_dataset import TicketRecord
n=0
for line in open('data/release/smoke.jsonl'):
    TicketRecord.model_validate_json(line); n+=1
print(f'{n} records, all conforming')
"
```

---

## Scenario 2 — The privacy gate blocks (US2, SC-004)

Run with the seeded-defect prompt document, which deliberately elicits identifier-shaped content:

```bash
uv run ticket-dataset generate --config configs/planted-pii.toml --seed 7
```

**Expect**: exit `1`. Flagged records are discarded under `privacy_finding` and appended to
`data/interim/<run_id>/quarantine.jsonl`; the discard rate — `privacy_finding` discards divided by every
generator response across all attempts (FR-026a) — exceeds the 0.5% threshold, so the run fails and
**nothing is moved into `data/release/`**. The report names each finding by record ID, field, category,
detector, and a masked rendering, never the matched value, and cites the quarantine path and count.

```bash
ls data/release/                     # planted-pii.jsonl absent
uv run python -m json.tool data/interim/<run_id>/report.json | head -40
```

Then approve one finding and confirm it stops blocking while staying visible:

```bash
uv run ticket-dataset privacy approve \
  --from-quarantine data/interim/<run_id>/quarantine.jsonl \
  --record-id <id> --field turns[3].content --category EMAIL \
  --reason "synthetic domain, reviewed 2026-08-19"
uv run ticket-dataset privacy scan data/interim/<run_id>/records.partial.jsonl
```

**Expect**: the finding appears as an approved exception rather than a blocker (FR-022), and
`privacy/exceptions.json` contains a fingerprint — not the value. The masked rendering in the report
(`…@example.com`) is usually enough to reach that judgment without opening quarantine at all; quarantine is
the fallback for findings a mask cannot settle.

**Detector floor.** Deregister a floor category in a test fixture and start a run: it must refuse with exit
`2` **before** generating anything (FR-018).

---

## Scenario 3 — Reconstruct how a corpus was produced (US3, SC-005, SC-006)

```bash
uv run ticket-dataset validate-manifest data/release/smoke.manifest.json
```

**Expect**: exit `0`. The manifest carries the seed, the full configuration, the code revision with its
dirty flag, the prompt document and rubric hashes, the schema version, both model identities, counts, and
discards by reason. `records_generated - sum(discards) == records_written` reconciles exactly.

Trace one record back using only its own fields:

```bash
head -1 data/release/smoke.jsonl | uv run python -c "
import json,sys
r=json.load(sys.stdin)
print(r['run_id'], r['record_index'], r['source_id'], r['schema_version'])
"
```

Corrupt a copy of the manifest — delete `seed`, or bump a discard count — and re-validate: it must fail and
name the missing or inconsistent element (FR-028).

---

## Scenario 4 — Composition control (US4, SC-008)

```bash
uv run ticket-dataset generate --config configs/billing-heavy.toml --seed 3
```

**Expect**: achieved composition within ±2 percentage points of the request on every controlled dimension,
with both the requested and achieved distributions in the report.

```bash
uv run python -c "
import json
m=json.load(open('data/release/billing-heavy.manifest.json'))
for dim in m['composition_requested']:
    req, got = m['composition_requested'][dim], m['composition_achieved'][dim]
    worst = max(abs(req.get(k,0)-got.get(k,0)) for k in set(req)|set(got))
    print(f'{dim}: worst drift {worst*100:.2f}pp')
"
```

An unsatisfiable request must refuse with exit `2` and name the offending dimension:

```bash
uv run ticket-dataset generate --config configs/bad-composition.toml --seed 1   # proportions sum to 1.4
```

---

## Scenario 5 — Interrupt and resume (SC-012, FR-015a–e)

```bash
uv run ticket-dataset generate --config configs/medium.toml --seed 11 &
sleep 30 && kill -INT %1
```

**Expect**: exit `3`; `data/release/` untouched; a checkpoint under `data/interim/<run_id>/`.

```bash
uv run ticket-dataset generate --config configs/medium.toml --seed 11 --resume
```

**Expect**: exit `0`, with no record regenerated and no `record_id` duplicated. The manifest describes the
whole corpus as one run, reconciles across both segments, and reports `resumed_count: 1`.

```bash
uv run python -c "
import json
ids=[json.loads(l)['record_id'] for l in open('data/release/medium.jsonl')]
idx=[json.loads(l)['record_index'] for l in open('data/release/medium.jsonl')]
assert len(ids)==len(set(ids)), 'duplicate record IDs'
assert idx==sorted(idx) and idx==list(range(len(idx))), 'positions not dense and ordered'
print('resume clean:', len(ids), 'records')
"
```

Now resume with a changed input — edit `prompts/domain.md` and retry: it must refuse with exit `2` rather
than producing a mixed-provenance corpus (FR-015e).

---

## Scenario 6 — Concurrency does not compromise reproducibility (SC-013)

```bash
uv run ticket-dataset generate --config configs/smoke.toml --seed 42 --out data/release/c1.jsonl   # max_concurrency 1
uv run ticket-dataset generate --config configs/smoke16.toml --seed 42 --out data/release/c16.jsonl # max_concurrency 16
```

**Expect**: identical composition and identical per-position seeded choices — same assigned metadata and
same turn count at every `record_index`. Conversation *text* differs, and that is expected and documented
(FR-010).

```bash
uv run python -c "
import json
a=[json.loads(l) for l in open('data/release/c1.jsonl')]
b=[json.loads(l) for l in open('data/release/c16.jsonl')]
key=lambda r:(r['record_index'], r['metadata']['category'], r['metadata']['priority'],
              r['metadata']['channel'], r['metadata']['resolution_status'], len(r['turns']))
assert list(map(key,a))==list(map(key,b))
print('seeded choices identical across concurrency levels')
"
```

The unit-level counterpart is cheaper and should exist too: `slot_random(seed, position, attempt)` yields
identical draws regardless of call order.

---

## Scenario 7 — Judge calibration (SC-011)

```bash
uv run ticket-dataset sample-for-review --corpus data/release/smoke.jsonl --n 20 --seed 5 \
  --out data/interim/calibration-sample.jsonl
```

Review the sample by hand, compare human judgments against the recorded scores, and record the comparison
alongside the rubric version. Until that has happened at least once, the 0.8 threshold is a documented
default, not a validated one — say so in any datasheet.

---

## Scale check (SC-001)

`configs/release.toml` requests 100,000 records — on the order of 200,000 model calls before retries and
discards. Do not run it casually; it is the acceptance run for a release, not part of the test suite.
Memory is expected to stay flat: only per-slot state, a bounded reorder buffer, and two digest sets
(~3 MB each at 100k) are held.

The routine substitute is a memory-shape test against the fake model client: generate 10,000 records with
`FakeModelClient` and assert that peak RSS does not scale with corpus size.

---

## What is not covered here

- **Sampled human review of a release** and the datasheet are release acts governed by the constitution,
  not steps in this pipeline.
- **Validating a corpus an external tool postprocessed** is feature 002.
