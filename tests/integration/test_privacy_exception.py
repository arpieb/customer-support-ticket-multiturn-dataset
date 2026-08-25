"""An approved finding stops blocking and stays visible (FR-022, FR-022a, FR-022b)."""

import json
from pathlib import Path

import pytest

from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.errors import ReasonContainsIdentifierError
from ticket_dataset_generator.model.client import ModelResponse, ModelRole
from ticket_dataset_generator.model.fake import FakeModelClient
from ticket_dataset_generator.privacy.detectors.datafog_detector import DataFogDetector
from ticket_dataset_generator.privacy.exceptions_store import ExceptionStore
from ticket_dataset_generator.privacy.quarantine import Quarantine
from ticket_dataset_generator.run.enums import FindingStatus, PIICategory, RunOutcome
from ticket_dataset_generator.run.run import GenerationRun

VALUE = "jane.roe@acme-corp.co.uk"


def _config(tmp_path: Path, exceptions: Path) -> GenerationConfig:
    return GenerationConfig(
        record_count=8,
        output_path=tmp_path / "release" / "corpus.jsonl",
        composition_tolerance_pp=20.0,
        max_attempts_per_slot=1,
        privacy={"exceptions": exceptions},
        composition={
            "category": {"account": 1.0},
            "priority": {"normal": 1.0},
            "channel": {"email": 1.0},
            "resolution_status": {"resolved": 1.0},
        },
    )


def _client() -> FakeModelClient:
    def responder(role: ModelRole, system: str, user: str) -> ModelResponse:
        if role is ModelRole.JUDGE:
            criteria = ["single_issue", "role_consistency", "conversational_flow", "metadata_fit"]
            return ModelResponse(
                text=json.dumps({"criteria": dict.fromkeys(criteria, 0.95), "justification": "ok"}),
                model_id="fake-model-1",
            )
        count = int(user.split("turn_count=")[1].split("\n")[0])
        turns = [
            {
                "role": "customer" if i % 2 == 0 else "agent",
                "content": f"reach me at {VALUE}" if i == 0 else f"turn {i}",
            }
            for i in range(count)
        ]
        return ModelResponse(
            text=json.dumps({"scenario": "contact details", "turns": turns}),
            model_id="fake-model-1",
        )

    return FakeModelClient(responder=responder)


async def _run(config: GenerationConfig):
    return await GenerationRun(config=config, seed=42, model_client=_client()).execute()


async def test_without_an_approval_the_value_blocks(tmp_path: Path, staging_root: Path) -> None:
    result = await _run(_config(tmp_path, tmp_path / "exceptions.json"))
    assert result.outcome is RunOutcome.FAILED
    assert any(f.blocks for f in result.findings)


async def test_an_approved_value_stops_blocking(tmp_path: Path, staging_root: Path) -> None:
    exceptions = tmp_path / "exceptions.json"
    store = ExceptionStore.load(exceptions)
    store.approve(
        category=PIICategory.EMAIL,
        value=VALUE,
        reason="vendor sandbox mailbox, confirmed not a real person",
        approved_by="rbates8",
    )
    store.save()

    config = _config(tmp_path, exceptions)
    result = await _run(config)

    assert result.outcome is RunOutcome.COMPLETED
    assert result.records_written == 8
    assert Path(config.output_path).exists()


async def test_an_approved_finding_stays_visible_in_the_report(
    tmp_path: Path, staging_root: Path
) -> None:
    # Suppression changes a finding's status, never its presence: the report must not look
    # cleaner than the scan was (FR-022).
    exceptions = tmp_path / "exceptions.json"
    store = ExceptionStore.load(exceptions)
    store.approve(
        category=PIICategory.EMAIL, value=VALUE, reason="vendor sandbox", approved_by="rbates8"
    )
    store.save()

    result = await _run(_config(tmp_path, exceptions))
    assert result.findings
    assert all(f.status is FindingStatus.APPROVED for f in result.findings)
    assert not any(f.blocks for f in result.findings)


async def test_the_approvals_file_holds_only_a_fingerprint(
    tmp_path: Path, staging_root: Path
) -> None:
    exceptions = tmp_path / "exceptions.json"
    store = ExceptionStore.load(exceptions)
    store.approve(
        category=PIICategory.EMAIL, value=VALUE, reason="vendor sandbox", approved_by="rbates8"
    )
    store.save()
    text = exceptions.read_text()
    assert "jane.roe" not in text.lower()
    assert "acme-corp" not in text.lower()
    assert "vendor sandbox" in text


async def test_a_reviewer_can_approve_from_quarantine(tmp_path: Path, staging_root: Path) -> None:
    # The reviewer never retypes or pastes the value: it is read out of quarantine in place and
    # fingerprinted there (FR-021b, contracts/cli.md).
    first = await _run(_config(tmp_path, tmp_path / "exceptions.json"))
    assert first.quarantine_path is not None

    quarantine = Quarantine(path=first.quarantine_path)
    blocking = next(f for f in first.findings if f.blocks)
    recovered = quarantine.find(blocking.record_id, blocking.field)
    assert recovered is not None
    assert VALUE in recovered


async def test_a_reason_containing_an_identifier_is_refused(tmp_path: Path) -> None:
    # A free-text reason that may hold a value defeats the fingerprinting beside it (FR-022b).
    detector = DataFogDetector()
    store = ExceptionStore.load(tmp_path / "exceptions.json")
    with pytest.raises(ReasonContainsIdentifierError):
        store.approve(
            category=PIICategory.EMAIL,
            value=VALUE,
            reason=f"approving {VALUE} because it is a sandbox",
            approved_by="rbates8",
            scan_reason=lambda text: detector.scan(text),
        )
    assert store.entries == []
