"""JSON Schema export of the record contract, and the normalization the drift check uses.

The committed contract and the Pydantic export describe the same contract in different dialects.
Pydantic hoists every enum into ``$defs`` and writes nullable fields as ``anyOf``; the committed
file inlines some enums and writes ``type: [..., "null"]``. Comparing them raw fails for reasons
that say nothing about the contract, and the likely reaction would be to weaken the check that
Principle I depends on. So both sides are reduced to the same canonical form first:

* ``$ref`` pointers are resolved, so representation stops mattering
* nullable unions are written one way
* annotations — descriptions, titles, examples — are dropped, because they are documentation

One thing survives only in the committed file: the ``allOf``/``if``/``then`` conditional binding
``resolved_at`` to ``resolution_status``. Pydantic enforces that in a model validator, which
JSON Schema generation cannot express. It is therefore excluded from the structural comparison
and asserted separately, so a third party validating with the schema alone still gets FR-006b.
"""

import json
from pathlib import Path
from typing import Any

from ticket_dataset.schema.record import TicketRecord
from ticket_dataset.schema.version import SCHEMA_VERSION

SCHEMA_ID = (
    "https://github.com/arpieb/customer-support-ticket-multiturn-dataset/"
    f"schemas/record/{SCHEMA_VERSION}"
)

_ANNOTATION_KEYS = frozenset({"description", "title", "$comment", "examples", "default"})

#: Excluded from structural comparison; asserted separately. See the module docstring.
_CONDITIONAL_KEYS = frozenset({"allOf", "if", "then", "else"})


def _resolve(node: Any, defs: dict[str, Any], depth: int = 0) -> Any:
    """Inline ``$ref`` pointers into ``$defs`` so the two dialects compare."""
    if depth > 12:  # This contract is not recursive; the bound is a guard, not a feature.
        raise ValueError("schema nesting is deeper than expected; is a $ref cyclic?")
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = defs[ref.removeprefix("#/$defs/")]
            merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
            return _resolve(merged, defs, depth + 1)
        return {k: _resolve(v, defs, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(item, defs, depth + 1) for item in node]
    return node


def _canonical(node: Any) -> Any:
    """Drop annotations and conditionals, and write nullable unions one way."""
    if isinstance(node, dict):
        node = {k: v for k, v in node.items() if k not in _ANNOTATION_KEYS | _CONDITIONAL_KEYS}

        # anyOf [X, {"type": "null"}]  ->  X with "null" added to its type
        any_of = node.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2:
            nulls = [b for b in any_of if b == {"type": "null"}]
            others = [b for b in any_of if b != {"type": "null"}]
            if len(nulls) == 1 and len(others) == 1 and isinstance(others[0], dict):
                merged = {**others[0], **{k: v for k, v in node.items() if k != "anyOf"}}
                t = merged.get("type")
                merged["type"] = sorted({*(t if isinstance(t, list) else [t]), "null"})
                node = merged

        t = node.get("type")
        if isinstance(t, list):
            node["type"] = sorted(t)
        if isinstance(node.get("enum"), list):
            node["enum"] = sorted(node["enum"])
        return {k: _canonical(v) for k, v in sorted(node.items())}
    if isinstance(node, list):
        return [_canonical(item) for item in node]
    return node


def _reduce(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs", {})
    resolved = _resolve({k: v for k, v in schema.items() if k != "$defs"}, defs)
    return _canonical(resolved)


def export_json_schema() -> dict[str, Any]:
    """The record contract as JSON Schema, as generated from the authoritative model (FR-001)."""
    schema = TicketRecord.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = SCHEMA_ID
    schema["title"] = "TicketRecord"
    return schema


def structural_form(schema: dict[str, Any]) -> dict[str, Any]:
    """The canonical form two schemas are compared on: names, types, enums, required sets."""
    reduced = _reduce(schema)
    reduced.pop("$schema", None)
    reduced.pop("$id", None)
    return reduced


def load_committed_schema(path: Path) -> dict[str, Any]:
    """Read the committed contract file."""
    return json.loads(path.read_text())
