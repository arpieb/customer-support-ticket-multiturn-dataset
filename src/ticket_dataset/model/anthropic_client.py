"""The only module that imports ``anthropic`` (contracts/model-io.md, research R1).

Everything else in the package depends on the :class:`~ticket_dataset.model.client.ModelClient`
protocol, which is what lets the whole pipeline — and therefore the whole test suite — run
offline against a fake. Nothing in ``tests/`` imports this module.

Two choices are worth stating because they are not obvious:

*Structural validation stays ours.* ``output_config.format`` constrains the response, which makes
malformed output rare rather than impossible. FR-009b requires every failure to be an accounted
discard, so the response comes back as text and the pipeline validates it — a malformed response
must not escape as an SDK exception.

*Refusal fallback is on by default.* A safety decline would otherwise cost a slot and a call.
The provenance consequence is absorbed by recording the model that actually served each record
(FR-027a), so a fallback cannot quietly make the manifest's model identity a lie.
"""

from typing import Any

import anthropic

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

#: The array form of server-side refusal fallback, which is what the SDK documents for Python.
FALLBACK_BETA = "server-side-fallback-2026-06-01"
FALLBACK_MODEL = "claude-opus-4-8"

_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.REFUSAL,
}


class AnthropicModelClient(ModelClient):
    """A ``ModelClient`` backed by the Anthropic Messages API."""

    def __init__(
        self,
        config: GenerationConfig,
        *,
        client: Any | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._config = config
        # Credentials resolve from the environment: ANTHROPIC_API_KEY, then ANTHROPIC_AUTH_TOKEN,
        # then an `ant auth login` profile. They are an access mechanism, never an input that
        # influences output, and are never written to any artifact (FR-008).
        self._client = client or anthropic.AsyncAnthropic(max_retries=4)
        self._limiter = limiter or RateLimiter(config.requests_per_minute)

    def _spec(self, role: ModelRole) -> ModelSpec:
        return (
            self._config.models.generator
            if role is ModelRole.GENERATOR
            else self._config.models.judge
        )

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
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": spec.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }
        if spec.fallback_enabled:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = [{"model": FALLBACK_MODEL}]

        try:
            if spec.fallback_enabled:
                response = await self._client.beta.messages.create(**request)
            else:
                request.pop("betas", None)
                request.pop("fallbacks", None)
                response = await self._client.messages.create(**request)
        except anthropic.APIStatusError as error:
            raise ModelUnavailable(f"{error.status_code}: {error.message}") from error
        except anthropic.APIConnectionError as error:
            raise ModelUnavailable(str(error)) from error

        stop_reason = _STOP_REASONS.get(response.stop_reason or "", StopReason.OTHER)
        if stop_reason is StopReason.REFUSAL:
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise ModelRefusal(f"model declined ({category or 'unspecified'})")

        text = next(
            (block.text for block in response.content if getattr(block, "type", "") == "text"),
            "",
        )
        return ModelResponse(
            text=text,
            # The model that *actually* served the request, which a fallback can change.
            model_id=getattr(response, "model", spec.model_id),
            stop_reason=stop_reason,
            usage=dict(getattr(response, "usage", {}) or {}) if hasattr(response, "usage") else {},
        )
