"""Composition control end to end (SC-008, FR-031, FR-031a, FR-031b, FR-032)."""

import collections
import json
from pathlib import Path

import pytest

from ticket_dataset_generator.config.loader import load_config
from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.errors import ConfigError
from ticket_dataset_generator.model.fake import FakeModelClient
from ticket_dataset_generator.run.enums import RunOutcome
from ticket_dataset_generator.run.run import GenerationRun

SKEWED = {
    "category": {
        "billing": 0.50,
        "technical": 0.20,
        "account": 0.15,
        "shipping": 0.08,
        "product": 0.05,
        "other": 0.02,
    },
    "priority": {"low": 0.15, "normal": 0.45, "high": 0.25, "urgent": 0.15},
    "channel": {"email": 0.45, "chat": 0.35, "phone": 0.12, "web_form": 0.08},
    "resolution_status": {
        "resolved": 0.65,
        "unresolved": 0.10,
        "escalated": 0.20,
        "abandoned": 0.05,
    },
}


def _config(tmp_path: Path, **overrides) -> GenerationConfig:
    base = {
        "record_count": 500,
        "output_path": tmp_path / "release" / "corpus.jsonl",
        "composition": SKEWED,
        "max_concurrency": 8,
    }
    return GenerationConfig(**{**base, **overrides})


async def _run(config: GenerationConfig):
    return await GenerationRun(config=config, seed=3, model_client=FakeModelClient()).execute()


async def test_every_member_lands_within_the_default_tolerance(
    tmp_path: Path, staging_root: Path
) -> None:
    # SC-008, at a corpus size where the 2pp default is achievable.
    result = await _run(_config(tmp_path))
    assert result.outcome is RunOutcome.COMPLETED

    records = [json.loads(line) for line in result.artifact_path.read_text().splitlines()]
    for dimension, requested in SKEWED.items():
        counts = collections.Counter(record["metadata"][dimension] for record in records)
        for member, want in requested.items():
            achieved = counts[member] / len(records)
            assert abs(achieved - want) <= 0.02, f"{dimension}.{member}: {achieved:.3f} vs {want}"


async def test_all_three_distributions_are_reported(tmp_path: Path, staging_root: Path) -> None:
    # Requested to assigned is apportionment error; assigned to achieved is discard drift.
    # Without the middle term a tolerance failure has no attributable cause (FR-031a).
    result = await _run(_config(tmp_path))
    report = json.loads(result.report_path.read_text())
    for key in ("composition_requested", "composition_assigned", "composition_achieved"):
        assert set(report[key]) == set(SKEWED), key
    assert report["composition_drift_pp"]["category"]["billing"] == pytest.approx(0.0, abs=0.5)


async def test_the_manifest_carries_all_three_too(tmp_path: Path, staging_root: Path) -> None:
    result = await _run(_config(tmp_path))
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["composition_requested"]["category"]["billing"] == 0.5
    assert manifest["composition_assigned"]["category"]["billing"] == pytest.approx(0.5, abs=0.002)
    assert manifest["composition_achieved"]["category"]["billing"] == pytest.approx(0.5, abs=0.02)


async def test_apportionment_alone_is_exact(tmp_path: Path, staging_root: Path) -> None:
    # With no discards, assigned should equal requested to within one record — which is what
    # makes any observed drift attributable to discards rather than to planning.
    result = await _run(_config(tmp_path))
    manifest = json.loads(result.manifest_path.read_text())
    for dimension, requested in SKEWED.items():
        for member, want in requested.items():
            assigned = manifest["composition_assigned"][dimension].get(member, 0.0)
            assert abs(assigned - want) < 1 / 500


async def test_drift_past_the_tolerance_fails_the_run(tmp_path: Path, staging_root: Path) -> None:
    # A judge that rejects one category's records skews the corpus; the run must fail on
    # composition and name the member (FR-031).
    def responder(role, system, user):
        from ticket_dataset_generator.model.client import ModelResponse, ModelRole

        criteria = ["single_issue", "role_consistency", "conversational_flow", "metadata_fit"]
        if role is ModelRole.JUDGE:
            # Reject everything written for the billing category.
            score = 0.1 if "category=billing" in system + user else 0.95
            return ModelResponse(
                text=json.dumps(
                    {"criteria": dict.fromkeys(criteria, score), "justification": "scripted"}
                ),
                model_id="fake-model-1",
            )
        count = int(user.split("turn_count=")[1].split("\n")[0])
        turns = [
            {"role": "customer" if i % 2 == 0 else "agent", "content": f"turn {i}"}
            for i in range(count)
        ]
        return ModelResponse(
            text=json.dumps({"scenario": "a situation", "turns": turns}), model_id="fake-model-1"
        )

    config = _config(tmp_path, max_attempts_per_slot=1, coherence={"max_discard_rate": 1.0})
    result = await GenerationRun(
        config=config, seed=3, model_client=FakeModelClient(responder=responder)
    ).execute()

    assert result.outcome is RunOutcome.FAILED
    assert any("composition.category.billing" in failure for failure in result.failures)
    assert result.artifact_path is None


# --- refusals, before any model call (FR-031b, FR-032) --------------------------------------


def test_proportions_that_do_not_sum_are_refused() -> None:
    with pytest.raises(ConfigError, match="sum to 1.4"):
        load_config(Path("configs/samples/bad-composition.toml"))


def test_an_unachievable_tolerance_is_refused_with_both_remedies() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(Path("configs/samples/tight-tolerance.toml"))
    joined = " ".join(caught.value.problems)
    assert "unachievable at 20 records" in joined
    assert "at least 50 records" in joined
    assert "at least 5.00pp" in joined


def test_the_billing_heavy_config_is_satisfiable() -> None:
    config = load_config(Path("configs/samples/billing-heavy.toml"))
    assert config.record_count == 500
    assert config.composition_tolerance_pp == 2.0
