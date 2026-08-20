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

**Credentials.** Generation calls a hosted model through litellm, so which credentials you need depends on
the provider `models.generator` names — `ANTHROPIC_API_KEY` for the default `anthropic/…` model,
`OPENAI_API_KEY` for `openai/…`, and so on. The privacy gate never needs credentials or a network
(FR-024).

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

`configs/smoke.toml` requests 20 records, so the scenario costs about 40 model calls. It also declares
`composition_tolerance_pp = 10.0`: at 20 records, per-member apportionment error is bounded only by
`100/20 = 5pp`, so the 2pp default is arithmetically unachievable and a run would be refused before
generating (FR-031b). Widening it deliberately is exactly what that requirement asks of an operator.

**Expect**: exit `0`; `data/release/smoke.jsonl` with exactly the requested number of lines; a manifest and
report beside it. Every record validates against the record contract, its turns alternate `customer` /
`agent` **starting with the customer** (FR-009), no turn is empty, its turn count lies in the configured
range, and each conversation concerns one support issue.

Turn counts are drawn uniformly from the range (FR-009d), which is testable rather than merely asserted:

```bash
uv run python -c "
import json, collections
c=collections.Counter(len(json.loads(l)['turns']) for l in open('data/release/smoke.jsonl'))
print(sorted(c.items()))   # spread across [min, max]; chi-square it at larger N
"
```

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

**Expect**: exit `1`, and a report that enumerates the covered identifier types (`EMAIL`, `PHONE`,
`CREDIT_CARD`, `US_SSN`) alongside the uncovered ones (non-US government IDs, postal address, bank account),
so a clean section is never read as broader coverage than the gate delivers.
Flagged records are discarded under `privacy_finding` and appended to
`data/interim/<run_id>/quarantine.jsonl`; the discard rate — `privacy_finding` discards divided by every
generator response across all attempts (FR-026a) — exceeds the 0.5% threshold, so the run fails and
**nothing is moved into `data/release/`**. Because the scan runs before judging (FR-016a), flagged records
never reach the judge, so a run that trips this threshold also costs noticeably fewer model calls than the
record count suggests. The report names each finding by record ID, field, category,
detector, and a masked rendering, never the matched value, and cites the quarantine path and count.

```bash
ls data/release/                     # planted-pii.jsonl absent
uv run python -m json.tool data/interim/<run_id>/report.json | head -40   # named by run id (FR-036a)
```

Then approve one finding and confirm it stops blocking while staying visible:

```bash
uv run ticket-dataset privacy approve \
  --from-quarantine data/interim/<run_id>/quarantine.jsonl \
  --record-id <id> --field turns[3].content --category EMAIL \
  --reason "synthetic domain, reviewed 2026-08-19" --by "$(git config user.email)"
uv run ticket-dataset privacy scan data/interim/<run_id>/records.partial.jsonl
```

The `--reason` text is itself scanned and refused if it trips a detector (FR-022b) — try
`--reason "approving j.doe@example.com"` and confirm it is rejected rather than written.

**Expect**: the finding appears as an approved exception rather than a blocker (FR-022), and
`privacy/exceptions.json` contains a fingerprint — not the value. The masked rendering in the report
(`…@example.com`) is usually enough to reach that judgment without opening quarantine at all; quarantine is
the fallback for findings a mask cannot settle.

**Detector floor.** Coverage is demonstrated, not declared. Stub a detector so it still *declares* `US_SSN`
but no longer matches it, and start a run: the canary probe must fail and the run must refuse with exit `2`
**before** generating anything (FR-018, FR-018a). A declaration check would have passed this fixture, which
is the whole point of probing.

**Detector failure.** Make a detector raise on one record: that record must be discarded under
`detector_error` — not `privacy_finding`, and not silently passed — and repeated failures must stop the run
(FR-017a).

---

## Scenario 3 — Reconstruct how a corpus was produced (US3, SC-005, SC-006)

```bash
RUN_ID=$(head -1 data/release/smoke.jsonl | uv run python -c "import json,sys; print(json.load(sys.stdin)['run_id'])")
uv run ticket-dataset validate-manifest "data/release/$RUN_ID.manifest.json"
```

Note what that first line demonstrates: the manifest was found **from a record**, with no other knowledge —
manifests are named by run identifier and written beside the artifact (FR-029a), which is what makes FR-029's
claim achievable rather than aspirational.

**Expect**: exit `0`. The manifest carries the seed, the full configuration, the code revision with its
modified-tree indicator, the prompt document and rubric hashes, the schema version, both model identities,
run start and end times, the artifact's filename and checksum, counts, and discards drawn from the closed
reason set. `records_generated - sum(discards) == records_written` reconciles exactly.

Validation checks the arithmetic, not just field presence — so corrupt a copy by bumping one discard count
and it must fail, even though every required field is still there.

Trace one record back using only its own fields:

```bash
head -1 data/release/smoke.jsonl | uv run python -c "
import json,sys
r=json.load(sys.stdin)
print(r['run_id'], r['record_index'], r['source_id'], r['schema_version'])
print('manifest:', f\"data/release/{r['run_id']}.manifest.json\")
"
```

Corrupt a copy of the manifest — delete `seed`, or bump a discard count — and re-validate: it must fail and
name the missing or inconsistent element (FR-028). Altering the corpus after the fact fails too, on the
checksum the manifest records (FR-025b).

---

## Scenario 4 — Composition control (US4, SC-008)

```bash
uv run ticket-dataset generate --config configs/billing-heavy.toml --seed 3
```

**Expect**: every **member** of every controlled dimension within ±2 percentage points of its request, with
all three distributions — requested, assigned, achieved — in the report. `configs/billing-heavy.toml`
requests 500 records, comfortably above the 50-record floor the 2pp default requires.

```bash
uv run python -c "
import json
import glob
m=json.load(open(glob.glob('data/release/*.manifest.json')[0]))
for dim in m['composition_requested']:
    req = m['composition_requested'][dim]
    asg = m['composition_assigned'][dim]
    got = m['composition_achieved'][dim]
    members = set(req) | set(asg) | set(got)
    worst_member = max(members, key=lambda k: abs(req.get(k,0)-got.get(k,0)))
    drift = abs(req.get(worst_member,0)-got.get(worst_member,0)) * 100
    appor = abs(req.get(worst_member,0)-asg.get(worst_member,0)) * 100
    print(f'{dim}: worst member {worst_member} drift {drift:.2f}pp '
          f'(apportionment {appor:.2f}pp, rest is discards)')
"
```

An unsatisfiable request must refuse with exit `2` and name the offending part — before any model call:

```bash
uv run ticket-dataset generate --config configs/bad-composition.toml --seed 1  # proportions sum to 1.4
uv run ticket-dataset generate --config configs/tight-tolerance.toml --seed 1  # 20 records at 2pp
```

The second must name both remedies: at least 50 records, or a tolerance of at least 5pp (FR-031b).

---

## Scenario 5 — Interrupt and resume (SC-012, FR-015a–e)

```bash
uv run ticket-dataset generate --config configs/medium.toml --seed 11 &
sleep 30 && kill -INT %1
```

A run also stops on its own when a declared budget is exhausted or a discard rate breaches its
threshold mid-run. All three paths take the same route: stop, checkpoint, exit `3`.

**Expect**: exit `3`; `data/release/` untouched — incomplete output never occupies the release path at all
(FR-015), so there is nothing there to mistake for a finished corpus; a checkpoint and staging file under
`data/interim/<run_id>/`, both retained because the run did not succeed (FR-015i).

```bash
uv run ticket-dataset generate --config configs/medium.toml --seed 11 --resume
```

**Expect**: exit `0`, with no record regenerated and no `record_id` duplicated. The resume found its
candidate by matching input fingerprints — no run identifier needed, because only one checkpointed run
matches (FR-015h). The manifest describes the whole corpus as one run, reconciles across both segments,
reports `resumed_count: 1`, and carries one `segments` entry per attempt with the code revision each
produced (FR-015f). On success the staging file and checkpoint are gone; the report remains (FR-015i).

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
than producing a mixed-provenance corpus (FR-015e). Then check the deliberate exception: commit a code
change and resume. That must **succeed**, adding a second `segments` entry with the new revision (FR-015f) —
the corpus is described rather than blocked, the same trade FR-025a makes for a modified working tree.

Two more failure paths:

```bash
printf 'garbage' > data/interim/<run_id>/checkpoint.json
uv run ticket-dataset generate --config configs/medium.toml --seed 11 --resume   # exit 2, staging preserved

uv run ticket-dataset generate --config configs/medium.toml --seed 11 &          # claims the output path
uv run ticket-dataset generate --config configs/medium.toml --seed 11            # exit 2, path claimed
```

An unreadable checkpoint refuses and leaves the partial output alone — restarting is the operator's explicit
act, never the tool's inference (FR-015g). A destination another run has claimed refuses immediately rather
than at the end, after both runs have paid for their calls (FR-014a).

---

## Scenario 6 — Concurrency does not compromise reproducibility (SC-013)

```bash
uv run ticket-dataset generate --config configs/smoke.toml --seed 42 --out data/release/c1.jsonl    # concurrency 1
uv run ticket-dataset generate --config configs/smoke16.toml --seed 42 --out data/release/c16.jsonl # concurrency 16
```

**Expect**: identical composition and identical per-position seeded choices — same assigned metadata, same
assigned `subdomain`, same turn count, and **same ticket timestamps** at every `record_index` (FR-006a).
That list is exactly what FR-010a defines as equivalence, so this scenario tests the definition rather than
an interpretation of it. The `scenario` the model elaborates
within that subdomain differs, as does conversation text, and both are expected and documented (FR-010,
FR-008d).

```bash
uv run python -c "
import json
a=[json.loads(l) for l in open('data/release/c1.jsonl')]
b=[json.loads(l) for l in open('data/release/c16.jsonl')]
key=lambda r:(r['record_index'], r['subdomain'], r['metadata']['category'], r['metadata']['priority'],
              r['metadata']['channel'], r['metadata']['resolution_status'], len(r['turns']),
              r['metadata']['created_at'], r['metadata'].get('resolved_at'))
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

Review the sample by hand, compare human judgements against the recorded scores, and record the comparison
alongside the rubric version. Until that has happened at least once, the 0.8 threshold is a documented
default, not a validated one — say so in any datasheet.

**This is deliberately not enforced.** No requirement obliges a calibration record to exist or a release to
cite one (CHK063), so whether calibration ever happened leaves no trace in the repository. If that turns out
to matter, the fix is a committed calibration artifact that a datasheet must reference.

---

## Scale check (SC-001)

`configs/release.toml` requests 100,000 records — on the order of 200,000 model calls before retries and
discards — and declares a budget (`max_runtime`, `max_model_calls`) so an unattended run has a ceiling. A
defective generator does not cost the full run either: the privacy and coherence discard rates are
re-evaluated once 5,000 records have been generated, and a breach stops and checkpoints (FR-037). When
a ceiling is reached the run stops and checkpoints with exit `3`, leaving the partial corpus and its
accounting intact rather than continuing past it (FR-012f). Do not run it casually; it is the acceptance run
for a release, not part of the test suite.
Memory is expected to stay flat: only per-slot state, a bounded reorder buffer, and two digest sets
(~3 MB each at 100k) are held.

The routine substitute is a memory-shape test against the fake model client: generate 10,000 records with
`FakeModelClient` and assert that peak RSS does not scale with corpus size.

---

## What is not covered here

- **Sampled human review of a release** and the datasheet are release acts governed by the constitution,
  not steps in this pipeline.
- **Validating a corpus an external tool postprocessed** is feature 002.
