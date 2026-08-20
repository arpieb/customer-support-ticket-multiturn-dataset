"""The one module that talks to a model provider (contracts/model-io.md, research R1).

Provider access goes through **litellm**, so the pipeline is not tied to one vendor. Everything
else in the package depends on the :class:`~ticket_dataset.model.client.ModelClient` protocol,
which is what lets the whole test suite run offline against a fake; this module is the only place
a network call can originate.

Choosing an abstraction layer rather than a vendor SDK costs a little — provider-specific features
reach the request through an ``extra`` mapping rather than typed parameters — and buys the thing
the spec actually asks for. No functional requirement names a vendor: FR-009a says "a language
model", FR-027 says "any generation model identity". Pinning one SDK would have written a vendor
into a contract that deliberately does not have one.

Two choices are worth stating because they are not obvious:

*Structural validation stays ours.* ``response_format`` constrains the response, which makes
malformed output rare rather than impossible. FR-009b requires every failure to be an accounted
discard, so the response comes back as text and the pipeline validates it — a malformed response
must not escape as a provider exception.

*Refusal is a first-class outcome.* ``ContentPolicyViolationError`` is litellm's normalized signal
for a safety decline, across providers. That maps to :class:`ModelRefusal`, which the pipeline
accounts for separately from malformed output and transport failure (FR-009m).
"""

from typing import Any

import litellm
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    ContentPolicyViolationError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from ticket_dataset.config.models import GenerationConfig, ModelSpec
from ticket_dataset.model.client import (
    ModelClient,
    ModelRefusal,
    ModelResponse,
    ModelRole,
    ModelUnavailable,
    StopReason,
)
from ticket_dataset.model.limiter import RateLimiter

#: Provider errors that mean "try again later" rather than "this request is wrong".
_TRANSPORT_ERRORS = (
    RateLimitError,
    ServiceUnavailableError,
    APIConnectionError,
    InternalServerError,
    Timeout,
)

_STOP_REASONS = {
    "stop": StopReason.END_TURN,
    "end_turn": StopReason.END_TURN,
    "length": StopReason.MAX_TOKENS,
    "max_tokens": StopReason.MAX_TOKENS,
    "content_filter": StopReason.REFUSAL,
}


class LiteLLMModelClient(ModelClient):
    """A ``ModelClient`` backed by litellm, so any supported provider can serve a run."""

    def __init__(
        self,
        config: GenerationConfig,
        *,
        limiter: RateLimiter | None = None,
        completion: Any | None = None,
    ) -> None:
        self._config = config
        # Injectable so a test can exercise this module's mapping without a network. Nothing in
        # the suite does — the fake client covers the pipeline — but the seam costs nothing.
        self._completion = completion or litellm.acompletion
        self._limiter = limiter or RateLimiter(config.requests_per_minute)

    def _spec(self, role: ModelRole) -> ModelSpec:
        return (
            self._config.models.generator
            if role is ModelRole.GENERATOR
            else self._config.models.judge
        )

    @staticmethod
    def supports_structured_output(model_id: str) -> bool:
        """Whether this model can be constrained to a JSON schema.

        Checked before generating rather than discovered on the first response: a model that
        cannot honour the schema would turn every record into a structural discard.
        """
        try:
            return bool(litellm.supports_response_schema(model=model_id))
        except Exception:  # noqa: BLE001 - an unknown model is simply unverifiable here
            return False

    async def complete_json(
        self,
        *,
        role: ModelRole,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> ModelResponse:
        spec = self._spec(role)
        # Bound the run's own request rate, so it cannot throttle itself into failure (FR-012e).
        await self._limiter.acquire()

        request: dict[str, Any] = {
            "model": spec.model_id,
            "max_tokens": spec.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": schema, "strict": True},
            },
            # litellm's own retry of transient failures; the pipeline layers slot-level retry and
            # its accounting on top rather than reimplementing transport (FR-012d).
            "num_retries": 4,
            # A provider that rejects an unsupported parameter should not fail the run over a
            # setting another provider needed.
            "drop_params": True,
        }
        if spec.sampling_seed is not None:
            request["seed"] = spec.sampling_seed
        if spec.fallback_models:
            # Provider-neutral rescue: try these models when the configured one declines or
            # fails. A rescued record stays in the corpus and names its actual producer
            # (FR-009n, FR-027a).
            request["fallbacks"] = list(spec.fallback_models)
        # Provider-specific settings the contract does not model — thinking budgets, effort,
        # safety settings. Passed through untyped on purpose: typing them would put one vendor's
        # vocabulary back into the configuration.
        request.update(spec.extra)

        try:
            response = await self._completion(**request)
        except ContentPolicyViolationError as refusal:
            # A safety decline is a distinct outcome from malformed output and from a transport
            # failure; conflating them would hide a prompt domain that trips a classifier behind
            # a statistic that reads as a flaky provider (FR-009m).
            raise ModelRefusal(str(refusal)) from refusal
        except _TRANSPORT_ERRORS as unavailable:
            raise ModelUnavailable(str(unavailable)) from unavailable
        except APIError as error:
            raise ModelUnavailable(f"{type(error).__name__}: {error}") from error

        choice = response.choices[0]
        finish = (getattr(choice, "finish_reason", "") or "").lower()
        stop_reason = _STOP_REASONS.get(finish, StopReason.OTHER)
        if stop_reason is StopReason.REFUSAL:
            raise ModelRefusal(f"provider stopped with {finish!r}")

        usage = getattr(response, "usage", None)
        return ModelResponse(
            text=choice.message.content or "",
            # The model that *actually* served the request, which a fallback can change.
            model_id=getattr(response, "model", spec.model_id),
            stop_reason=stop_reason,
            usage=dict(usage) if usage else {},
        )
