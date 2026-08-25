"""Prompt assembly (contracts/model-io.md).

The system prefix is **byte-stable across a run**: the domain document and the rubric go there,
per-slot content goes in the user message. That is not a style preference — a run makes two
calls per record, and a prefix that varied would pay for the whole domain document on every one
of them instead of caching it.
"""

from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.generation.domain_doc import DomainDocument
from ticket_dataset_generator.generation.rubric import Rubric
from ticket_dataset_generator.planning.slots import Slot

_GENERATOR_INSTRUCTIONS = """\
You write synthetic customer support conversations for a research dataset.

Return a JSON object with exactly two keys:
  "scenario": one sentence naming the specific situation you wrote about, within the subdomain
              you were assigned. This is recorded on the record, so make it specific enough to
              tell two conversations in the same subdomain apart.
  "turns":    the conversation, as a list of {"role": "customer"|"agent", "content": "..."}.

Hard requirements, each of which is checked and will cause the conversation to be discarded:
  - Exactly the number of turns you are asked for. Not one more, not one fewer.
  - The customer speaks first, and roles alternate strictly from there.
  - No turn is empty or whitespace.
  - The whole exchange concerns one issue.
  - Every identifier-shaped value is obviously synthetic: @example.com addresses, 555-01xx
    phone numbers, invented order numbers. Never write a real one.

The domain you are writing in follows.
"""

_JUDGE_INSTRUCTIONS = """\
You score synthetic customer support conversations against a rubric, for quality control on a
research dataset.

Return a JSON object with exactly two keys:
  "criteria":      an object mapping each criterion named in the rubric to a score from 0.0 to
                   1.0. Score every criterion; omitting one invalidates the verdict.
  "justification": one or two sentences on what drove the scores.

Do not return an overall score. It is computed from your per-criterion scores using weights the
rubric declares, so a headline number would be ignored.

The rubric follows.
"""


def generator_system_prompt(document: DomainDocument) -> str:
    """Stable across every generation call in a run, so the prefix caches."""
    return f"{_GENERATOR_INSTRUCTIONS}\n---\n\n{document.body.strip()}\n"


def judge_system_prompt(rubric: Rubric) -> str:
    """Stable across every judging call in a run."""
    return f"{_JUDGE_INSTRUCTIONS}\n---\n\n{rubric.body.strip()}\n"


def generator_user_prompt(slot: Slot, config: GenerationConfig) -> str:
    """Per-slot content: the assignment the model writes a conversation *for*.

    The metadata is assigned rather than chosen, which is what makes the composition tolerance
    achievable by construction (research R3). ``turn_count=`` is written in a stable form
    because the structural check rejects any other length (FR-009d).
    """
    return (
        f"Write one support conversation with these attributes.\n\n"
        f"subdomain={slot.subdomain}\n"
        f"turn_count={slot.turn_count}\n"
        f"category={slot.category}\n"
        f"priority={slot.priority}\n"
        f"channel={slot.channel}\n"
        f"resolution_status={slot.resolution_status}\n"
        f"language={config.language}\n\n"
        f"Elaborate a specific situation within the subdomain — do not restate the subdomain "
        f"name. The conversation must end consistently with its resolution status, and read as "
        f"though it happened over {slot.channel}."
    )


def judge_user_prompt(conversation_turns: list[dict[str, str]], slot: Slot) -> str:
    """Per-record content: the candidate conversation and what it was written for."""
    rendered = "\n\n".join(
        f"[{index}] {turn['role']}: {turn['content']}"
        for index, turn in enumerate(conversation_turns)
    )
    return (
        f"Score this conversation against the rubric.\n\n"
        f"It was written for: category={slot.category}, priority={slot.priority}, "
        f"channel={slot.channel}, resolution_status={slot.resolution_status}, "
        f"subdomain={slot.subdomain}.\n\n"
        f"---\n\n{rendered}\n"
    )
