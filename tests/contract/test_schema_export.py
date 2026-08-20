"""The committed record contract and the authoritative model must not drift (Constitution I).

A schema change that does not also change ``contracts/record.schema.json`` fails here, so a
breaking change cannot land without the contract changing in the same commit.

The comparison is structural — names, types, enums, required sets — because the two sides are
written in different JSON Schema dialects and prose descriptions are documentation rather than
contract. The one thing the model cannot express, the ``resolved_at`` conditional, is asserted
separately so it cannot quietly disappear from the published contract.
"""

import json
from pathlib import Path

import pytest

from ticket_dataset.schema.export import (
    SCHEMA_ID,
    export_json_schema,
    load_committed_schema,
    structural_form,
)
from ticket_dataset.schema.version import SCHEMA_VERSION

CONTRACT_PATH = Path("specs/001-ticket-generation-pipeline/contracts/record.schema.json")


@pytest.fixture(scope="module")
def committed() -> dict:
    assert CONTRACT_PATH.exists(), f"committed contract missing at {CONTRACT_PATH}"
    return load_committed_schema(CONTRACT_PATH)


def test_export_matches_committed_contract(committed: dict) -> None:
    assert structural_form(export_json_schema()) == structural_form(committed), (
        "The record model and the committed contract disagree. Either the change was "
        "unintended, or the contract needs updating in this same commit (Constitution I)."
    )


def test_contract_declares_the_current_version(committed: dict) -> None:
    assert committed["$id"] == SCHEMA_ID
    assert SCHEMA_VERSION in committed["$id"]


def test_committed_contract_keeps_the_resolved_at_conditional(committed: dict) -> None:
    # Pydantic enforces this in a model validator, which schema generation cannot express.
    # Without it in the published file, a consumer validating with the schema alone would not
    # get FR-006b, so its presence is checked rather than assumed.
    branches = committed["$defs"]["TicketMetadata"]["allOf"]
    rendered = json.dumps(branches)
    assert "resolved" in rendered
    assert any("required" in b.get("then", {}) for b in branches), (
        "the conditional requiring resolved_at when the status is 'resolved' is missing"
    )
    assert any(b.get("then", {}).get("properties", {}).get("resolved_at") for b in branches)
