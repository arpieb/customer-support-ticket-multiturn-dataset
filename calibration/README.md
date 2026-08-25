# Calibration records

SC-011 asks that the coherence judge be calibrated against human judgement before a corpus is
released. Calibration is a human act — someone reads conversations and forms an opinion — so what
lives here is the evidence that it happened and what it found: which rubric was judged, which
sample, by whom, and how far the judge and the reviewer agreed.

One record per rubric version, named `<rubric_id>.calibration.json`, so a release can find the
calibration for the rubric its corpus was actually judged against.

## Doing one

```bash
# 1. Draw a reproducible sample. Any JSONL of records works, including a staging file from a
#    run that failed its thresholds — the records it wrote are still real judge output.
uv run ticket-dataset-generator sample-for-review \
  --corpus data/release/my-corpus.jsonl \
  --seed 5 --n 20 --out calibration/sample-001.jsonl

# 2. Read them and fill in `human_score` on every line, 0.0-1.0, same scale as the rubric.
#    That single number is the whole of the reviewer's job — see the note below before
#    reaching for anything per-criterion.

# 3. Compare.
uv run ticket-dataset-generator calibrate calibration/sample-001.jsonl \
  --by "$(git config user.email)" --seed 5 \
  --notes "what you concluded"
```

**Score overall, not per criterion.** `calibrate` can compare per-criterion scores, but nothing
supplies the judge's side of that comparison: a record stores the weighted mean and `rubric_id`,
not the four criteria behind them (FR-009p). A reviewer who scored each criterion would be doing
four times the work for a result that is discarded, so `sample-for-review` does not offer the
field, and `calibrate` says so plainly if it finds one filled in. Making it useful means
persisting the judge's per-criterion scores onto the record, which is a schema change and has not
been made.

## Reading the result

**Gate agreement** is whether you and the judge made the same admit/reject decision at the
threshold. That is what the threshold is for, and it is the number a release should turn on. The
detail line separates the two ways of disagreeing, because they are not equally bad: records the
judge *admitted that you rejected* are records the corpus kept and nobody vouched for.

**Rank correlation** is whether the judge orders conversations the way you do. The distinction
matters when the two of you disagree — a judge that is uniformly generous but correctly ordered
can be fixed by moving the threshold; one that ranks badly cannot be fixed that way at all.
Reported as undefined, not zero, when either side gave every record the same score: "expressed no
opinion" is a different finding from "disagrees".

**Spread** is how much of the scale each side used. It is the number that condemned rubric v1: a
20-record sample produced **three distinct judge scores**, 70% of them a perfect 1.0, which left
the 0.8 threshold unable to separate anything. If the judge's `distinct` count is small relative
to the sample, the rubric is offering anchors rather than a scale, and no threshold will help.

## What this does not do

Nothing enforces that a calibration exists. A release is not blocked by its absence, and the
datasheet obligation in T116 is a human one — see checklist item **CHK063**, which was closed as an
accepted deferral. If that changes, the check is available: a record is named by `rubric_id`, so
matching one against a corpus's rubric is a lookup.
