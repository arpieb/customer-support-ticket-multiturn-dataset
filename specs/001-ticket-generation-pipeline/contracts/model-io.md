# Contract: Model Interface

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-08-19

This is the contract between the pipeline and the language model — the only place in the design where a
network call happens. It exists so the rest of the pipeline can be tested without one.

---

## The seam: `ModelClient`

Every call goes through one narrow protocol. Nothing else in the package imports `anthropic`.

```python
class ModelClient(Protocol):
    async def complete_json(
        self,
        *,
        role: ModelRole,          # GENERATOR | JUDGE — selects the configured ModelSpec
        system: str,
        user: str,
        schema: dict,             # JSON Schema constraining the response
    ) -> ModelResponse: ...
```

`ModelResponse` carries `text` (the raw JSON string), `model_id` (**the model that actually served the
request** — not the one requested), `stop_reason`, `usage`, and `retries`. Returning the served model ID is
what makes per-record `generation.model_id` honest under refusal fallback (FR-027).

Two implementations: `AnthropicModelClient` (real) and `FakeModelClient` (tests, scripted responses
including refusals, malformed JSON, and rate-limit errors). The fake is what lets contract and integration
tests run offline and deterministically — the whole pipeline is exercised without credentials.

### Request shape

```python
response = await client.beta.messages.create(
    model=spec.model_id,
    max_tokens=spec.max_tokens,
    system=system,
    messages=[{"role": "user", "content": user}],
    thinking={"type": "adaptive"},
    output_config={
        "effort": spec.effort,
        "format": {"type": "json_schema", "schema": schema},
    },
    betas=["server-side-fallback-2026-06-01"],
    fallbacks=[{"model": "claude-opus-4-8"}],
)
```

- **Model**: `claude-opus-5` by default for both roles, configurable per role (research R1).
- **Structured output**: `output_config.format` constrains the response; the pipeline still parses and
  validates it itself, because FR-009b makes every malformed response an *accounted discard* rather than an
  exception escaping the SDK.
- **Refusal fallback**: enabled by default so a policy decline is a rescued record rather than a lost slot.
  The scalar `fallbacks="default"` form (beta `server-side-fallback-2026-07-01`) is the alternative and
  requires no model list; a header paired with the wrong form is a 400. Disable via config when an operator
  wants a single model identity guaranteed across the corpus.
- **Transport retry**: left to the SDK (`max_retries`), which covers 408/409/429/5xx and connection errors.
  Retries are counted and reported separately from discards (FR-012d).
- **Rate limiting**: a token bucket in front of every call, shared across both roles (FR-012e).

### Failure mapping

| Condition | Handling |
|-----------|----------|
| `stop_reason == "refusal"` after fallback | Slot retry; on exhaustion, discard `model_refusal` — a distinct outcome from a malformed response, so a prompt domain that trips a classifier is visible rather than hidden behind a flaky-provider statistic (FR-009m). A record rescued by a fallback model stays in the corpus and names its actual producer (FR-009n, FR-027a) |
| `stop_reason == "max_tokens"` | Treated as structurally invalid — a truncated conversation is never coerced into a record |
| Unparseable or schema-invalid JSON | Slot retry; on exhaustion, discard `structural_invalid` |
| `RateLimitError`, 5xx, connection error | SDK retries; on exhaustion, counted toward the consecutive-failure limit |
| Judge call fails after retries | Discard `unjudgeable` — never an admitted unjudged record (FR-009l) |

Consecutive failures across slots trip the circuit breaker: the run stops and checkpoints rather than
burning the remaining corpus emitting discards (spec Edge Cases).

---

## Generation request

**System prompt** is assembled from the committed domain prompt document plus fixed instructions. It is
**byte-stable across a run** — the volatile per-slot content goes in the user message — so the system
prefix caches and the run does not pay for the domain document 100,000 times.

**User message** carries the slot's assignment: the four metadata values, the exact turn count, the
configured language (FR-009r), and the **assigned subdomain**, chosen by a seeded draw from the prompt
document's declared list (FR-008d). The
model elaborates a specific situation within that subdomain; it does not choose the subdomain itself.

**Response schema** (`GeneratedConversation`):

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["scenario", "turns"],
  "properties": {
    "scenario": {"type": "string", "minLength": 1},
    "turns": {
      "type": "array",
      "minItems": 2,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["role", "content"],
        "properties": {
          "role": {"type": "string", "enum": ["customer", "agent"]},
          "content": {"type": "string", "minLength": 1}
        }
      }
    }
  }
}
```

The model returns **content only**. It never sees or writes `record_id`, `run_id`, `record_index`,
`schema_version`, or `coherence_score` — a model that could write those could corrupt provenance. Turn
`index` is assigned by the pipeline from array order.

**Post-conditions checked by the pipeline** (each a named discard, never a coercion — FR-009b):
turn count equals the slot's `turn_count`; roles alternate strictly and the **customer opens** (FR-009); no turn is
empty or whitespace-only; `scenario` is non-empty. The record's `subdomain` is written by the pipeline from
the slot, never taken from the response.

---

## Judge request

**System prompt** is the committed rubric document plus scoring instructions — again byte-stable across the
run, so it caches.

**User message** carries the candidate conversation's turns and its assigned metadata.

**Response schema** (`JudgeVerdict`):

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["score", "criteria", "justification"],
  "properties": {
    "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    "criteria": {"type": "object", "additionalProperties": {"type": "number"}},
    "justification": {"type": "string"}
  }
}
```

The pipeline computes the coherence score as the **weighted mean of `criteria`** using the rubric's declared
weights, rather than trusting a `score` the model reports alongside them (FR-009p) — a model can return a
holistic number inconsistent with its own sub-scores, and the derived value is the one the threshold means.
Only that score and the rubric ID reach the record (FR-009i). `criteria` and `justification` are used during
calibration (SC-011) and then dropped — they are only meaningful beside the rubric version that produced
them, and persisting them would multiply corpus size for no downstream use.

---

## Committed prompt inputs

| Artifact | Path | Role |
|----------|------|------|
| Domain prompt document | `prompts/domain.md` | The support domain, **declaring an enumerable list of subdomains** (FR-008d). Its hash is a run input; `source_id` derives from it (FR-008a). A slot's subdomain is a seeded choice from that list; the model elaborates the situation within it |
| Coherence rubric | `prompts/coherence-rubric.md` | What the judge scores against. Declares `rubric_id`, a version, its **criteria, and each criterion's weight** — weights summing to 1 (FR-009p). Its hash is a run input (FR-009g) |

Both are committed files, not strings in code. Changing either changes the manifest's input hashes, so a
change in domain or in judging standards is visible as a change in provenance rather than as an unexplained
shift in the corpus.

---

## What the pipeline never sends

The domain prompt document and every generated conversation are synthetic by construction. No real support
transcript, customer record, or operator environment value is ever placed in a prompt (FR-008, Principle
IV). The privacy scan runs on **output**, offline, and is not a substitute for this.

Credentials are the one thing the pipeline reads from the environment, and they are an access mechanism
rather than a generation input: they never influence output and are never written to a manifest, report,
checkpoint, or log (FR-008). Anything else the environment contributes — an alternate endpoint, a profile
selection, an inference region — **is** capable of changing output and is therefore recorded in the
manifest as a non-deterministic input (FR-008c). `AnthropicModelClient` surfaces the effective endpoint and
routing settings for that record; a setting it cannot observe causes the run to refuse rather than proceed
unrecorded.
