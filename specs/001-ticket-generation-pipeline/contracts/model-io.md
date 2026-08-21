# Contract: Model Interface

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-08-19

This is the contract between the pipeline and the language model — the only place in the design where a
network call happens. It exists so the rest of the pipeline can be tested without one.

---

## The seam: `ModelClient`

Every call goes through one narrow protocol. Nothing else in the package reaches a provider.

```python
class ModelClient(Protocol):
    async def complete_json(
        self,
        *,
        role: ModelRole,  # GENERATOR | JUDGE — selects the configured ModelSpec
        system: str,
        user: str,
        schema: dict,  # JSON Schema constraining the response
    ) -> ModelResponse: ...
```

`ModelResponse` carries `text` (the raw JSON string), `model_id` (**the model that actually served the
request** — not the one requested), `stop_reason`, `usage`, and `retries`. Returning the served model ID is
what makes per-record `generation.model_id` honest under refusal fallback (FR-027).

Two implementations: `LiteLLMModelClient` (real, any provider litellm supports) and `FakeModelClient`
(tests, scripted responses including refusals, malformed JSON, and rate-limit errors). The fake is what lets
contract and integration tests run offline and deterministically — the whole pipeline is exercised without
credentials, and no test imports the real client.

### Request shape

```python
response = await litellm.acompletion(
    model=spec.model_id,  # e.g. "anthropic/claude-opus-4-5"
    max_tokens=spec.max_tokens,
    messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ],
    response_format={
        "type": "json_schema",
        "json_schema": {"name": "response", "schema": schema, "strict": True},
    },
    num_retries=4,
    drop_params=True,
    fallbacks=list(spec.fallback_models),  # omitted when empty
    **spec.extra,  # provider-specific settings
)
```

- **Provider**: whatever `model_id` names. No vendor is pinned — no functional requirement names
  one (research R1). The default is a Claude model because that is what the project was developed
  against.
- **Structured output**: `response_format` constrains the response; the pipeline still parses and
  validates it itself, because FR-009b makes every malformed response an *accounted discard*
  rather than an exception escaping the provider layer.
- **Capability check**: `supports_response_schema(model_id)` is consulted before generating, so a
  model that cannot honour a schema refuses the run rather than turning every record into a
  structural discard.
- **Fallbacks**: provider-neutral. When the configured model declines or fails, the models in
  `fallback_models` are tried; a rescued record stays in the corpus and names its actual producer
  (FR-009n, FR-027a). Empty by default — rescue is opt-in, because a corpus spanning several
  models is a fact a datasheet has to report.
- **Transport retry**: left to litellm (`num_retries`), which covers rate limits, timeouts, and
  5xx. Retries are counted and reported separately from discards (FR-012d).
- **Unsupported parameters**: `drop_params` keeps a provider from failing the run over a setting
  another provider needed.
- **Rate limiting**: a token bucket in front of every call, shared across both roles (FR-012e).

### Failure mapping

| Condition | Handling |
|-----------|----------|
| `ContentPolicyViolationError`, or a content-filter finish reason | Slot retry; on exhaustion, discard `model_refusal` — a distinct outcome from a malformed response, so a prompt domain that trips a classifier is visible rather than hidden behind a flaky-provider statistic (FR-009m). litellm normalizes this across providers, so the distinction does not depend on one vendor's stop-reason vocabulary. A record rescued by a fallback model stays in the corpus and names its actual producer (FR-009n, FR-027a) |
| `stop_reason == "max_tokens"` | Treated as structurally invalid — a truncated conversation is never coerced into a record |
| Unparseable or schema-invalid JSON | Slot retry; on exhaustion, discard `structural_invalid` |
| `RateLimitError`, `ServiceUnavailableError`, `Timeout`, connection error | litellm retries; on exhaustion, counted toward the consecutive-failure limit |
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
| Domain prompt document | `prompts/samples/consumer-electronics-support.md` | The support domain, **declaring an enumerable list of subdomains** (FR-008d). Its hash is a run input; `source_id` derives from it (FR-008a). A slot's subdomain is a seeded choice from that list; the model elaborates the situation within it |
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
checkpoint, or log (FR-008). Which credentials those are depends on the provider — litellm resolves each
one's conventions — and none of them are recorded. Anything else the environment contributes, such as an
alternate endpoint or a region, **is** capable of changing output and is therefore recorded in the manifest
as a non-deterministic input (FR-008c); a setting that cannot be observed causes the run to refuse rather
than proceed unrecorded.
