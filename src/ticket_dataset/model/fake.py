"""A scripted model, so the whole pipeline can be exercised offline and deterministically.

This is the fixture every test in the suite depends on. It keeps CI free, keeps the suite from
needing credentials, and — because it can be told to refuse, to return malformed JSON, or to
emit identifier-shaped content on cue — lets the failure paths be tested at all, which a real
model could not be relied on to produce.
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ticket_dataset.model.client import (
    ModelClient,
    ModelRefusal,
    ModelResponse,
    ModelRole,
    ModelUnavailable,
    StopReason,
)

DEFAULT_MODEL_ID = "fake-model-1"
FALLBACK_MODEL_ID = "fake-model-fallback"


@dataclass(slots=True)
class Script:
    """What the fake should do on a given call.

    ``behavior`` is one of ``ok``, ``malformed``, ``refusal``, ``refusal_rescued``,
    ``unavailable``, ``max_tokens``, or ``pii``.
    """

    behavior: str = "ok"
    payload: dict[str, Any] | None = None


def _conversation(turn_count: int, *, scenario: str, pii: bool = False) -> dict[str, Any]:
    turns = []
    for index in range(turn_count):
        customer = index % 2 == 0
        if pii and index == 0:
            content = "My order never arrived. Reach me at j.doe@example.com or 555-0142."
        else:
            content = (
                f"Customer message {index // 2 + 1} about the issue."
                if customer
                else f"Agent reply {index // 2 + 1}, looking into it now."
            )
        turns.append({"role": "customer" if customer else "agent", "content": content})
    return {"scenario": scenario, "turns": turns}


@dataclass(slots=True)
class FakeModelClient(ModelClient):
    """A ``ModelClient`` that answers from a script rather than a network.

    By default it returns a well-formed conversation whose length matches whatever the prompt
    asked for, and a passing judge verdict. Tests override either by supplying ``scripts``
    (consumed in order, per role) or a ``responder`` for full control.
    """

    scripts: dict[ModelRole, list[Script]] = field(default_factory=dict)
    responder: Callable[[ModelRole, str, str], ModelResponse] | None = None
    judge_score: float = 0.95
    #: Criteria the fake judge scores. ``None`` means read them out of the rubric it was handed,
    #: which is what a real judge does and what keeps the fixture usable with any rubric.
    judge_criteria: list[str] | None = None
    model_id: str = DEFAULT_MODEL_ID
    calls: list[tuple[ModelRole, str]] = field(default_factory=list)

    def _next_script(self, role: ModelRole) -> Script:
        queue = self.scripts.get(role)
        if not queue:
            return Script()
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def complete_json(
        self,
        *,
        role: ModelRole,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> ModelResponse:
        self.calls.append((role, user))
        if self.responder is not None:
            return self.responder(role, system, user)

        script = self._next_script(role)
        if script.behavior == "unavailable":
            raise ModelUnavailable("scripted transport failure")
        if script.behavior == "refusal":
            raise ModelRefusal("scripted safety decline")
        if script.behavior == "malformed":
            return ModelResponse(text="{not json at all", model_id=self.model_id)
        if script.behavior == "max_tokens":
            return ModelResponse(
                text=json.dumps(_conversation(2, scenario="truncated"))[:-20],
                model_id=self.model_id,
                stop_reason=StopReason.MAX_TOKENS,
            )

        served = FALLBACK_MODEL_ID if script.behavior == "refusal_rescued" else self.model_id

        if role is ModelRole.JUDGE:
            criteria = self.judge_criteria or _criteria_from_rubric(system)
            payload = script.payload or {
                "criteria": dict.fromkeys(criteria, self.judge_score),
                "justification": "scripted verdict",
            }
            return ModelResponse(text=json.dumps(payload), model_id=served)

        payload = script.payload or _conversation(
            _requested_turn_count(user),
            scenario="scripted scenario within the assigned subdomain",
            pii=script.behavior == "pii",
        )
        return ModelResponse(text=json.dumps(payload), model_id=served)


_CRITERION_HEADING = re.compile(r"^##\s+([a-z][a-z0-9_]*)\s+\(weight", re.MULTILINE)


def _criteria_from_rubric(system: str) -> list[str]:
    """Read the criterion names out of the rubric the judge was handed.

    A real judge reads the rubric it is given; a fake that answered with a fixed criterion set
    would pass its own tests and fail against any rubric but one. Falling back to a single
    criterion keeps a rubric-less unit test working.
    """
    found = _CRITERION_HEADING.findall(system)
    return found or ["single_issue"]


def _requested_turn_count(user: str, default: int = 4) -> int:
    """Read the turn count out of the prompt, so the fake honors what it was asked for."""
    marker = "turn_count="
    if marker not in user:
        return default
    tail = user.split(marker, 1)[1]
    digits = ""
    for char in tail:
        if char.isdigit():
            digits += char
        else:
            break
    return int(digits) if digits else default


def scripted(behaviors: Sequence[str], role: ModelRole = ModelRole.GENERATOR) -> FakeModelClient:
    """A client that walks through ``behaviors`` once, then repeats the last one."""
    return FakeModelClient(scripts={role: [Script(behavior=b) for b in behaviors]})
