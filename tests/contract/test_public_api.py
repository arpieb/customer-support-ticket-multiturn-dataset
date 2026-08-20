"""The public surface is a contract, not an accident (contracts/python-api.md).

Everything in ``__all__`` is promised to callers; removing a name or narrowing a signature is a
breaking change requiring a MAJOR bump. This test exists so that promise is checked rather than
assumed, and so an import added for convenience does not quietly become part of the surface.
"""

import subprocess
import sys

import pytest

import ticket_dataset

#: Names the contract document specifies. Kept here deliberately rather than derived from
#: ``__all__``, so the test compares the code against the document rather than against itself.
DOCUMENTED = {
    # Record contract
    "SCHEMA_VERSION",
    "TicketRecord",
    "ConversationTurn",
    "TicketMetadata",
    "RecordQuality",
    "GenerationInfo",
    "Role",
    "Category",
    "Priority",
    "Channel",
    "ResolutionStatus",
    "export_json_schema",
    "is_supported_version",
    "parse_semver",
    # Configuration
    "GenerationConfig",
    "Composition",
    "ModelSpec",
    "Budget",
    "TimeWindow",
    "load_config",
    "validate_config",
    # Generation
    "GenerationRun",
    "RunResult",
    "slot_random",
    # Model access
    "ModelClient",
    "ModelRole",
    "ModelResponse",
    "FakeModelClient",
    # Privacy
    "Detector",
    "DetectorRegistry",
    "Finding",
    "ScanReport",
    "ExceptionStore",
    "PIICategory",
    "FindingStatus",
    "mask",
    # Composition
    "Breach",
    "check_tolerance",
    # Manifest and report
    "RunManifest",
    "RunReport",
    "validate_manifest",
    "validate_manifest_file",
    "DiscardReason",
    "RunOutcome",
    "Verdict",
    # Deduplication
    "DuplicateCounter",
    "content_fingerprint",
    # Errors
    "TicketDatasetError",
    "ConfigError",
    "UnsatisfiableCompositionError",
    "FloorNotCoveredError",
    "OutputPathExistsError",
    "ReleaseGateError",
    "CheckpointMismatchError",
    "CheckpointCorruptError",
    "AmbiguousResumeError",
    "UnobservableEnvironmentError",
    "PromptDocumentError",
    "RubricError",
    "ReasonContainsIdentifierError",
}


def test_every_documented_name_is_exported() -> None:
    missing = sorted(DOCUMENTED - set(ticket_dataset.__all__))
    assert missing == [], f"documented but not exported: {missing}"


def test_nothing_undocumented_is_exported() -> None:
    # An import added for convenience must not quietly become part of the contract.
    extra = sorted(set(ticket_dataset.__all__) - DOCUMENTED)
    assert extra == [], f"exported but not documented: {extra}"


@pytest.mark.parametrize("name", sorted(DOCUMENTED))
def test_every_exported_name_is_importable(name: str) -> None:
    assert hasattr(ticket_dataset, name), name
    assert getattr(ticket_dataset, name) is not None


def test_the_public_api_does_not_import_a_provider_stack() -> None:
    """The model seam is why the suite runs offline (plan.md Testing).

    Checked in a subprocess rather than by clearing ``sys.modules`` here. Purging modules
    in-process leaves every later test importing a fresh copy that fixtures have not patched —
    which is exactly the kind of cross-test damage a contract test should not do — and a fresh
    interpreter is the stronger assertion anyway.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, ticket_dataset; "
            "print(any(m == 'litellm' or m.startswith('litellm.') for m in sys.modules))",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"},
        check=True,
    )
    assert result.stdout.strip() == "False", (
        "importing ticket_dataset pulled in the provider stack; the ModelClient seam exists "
        "so the package can be used and tested without it"
    )


def test_the_schema_version_is_the_one_the_contract_declares() -> None:
    assert ticket_dataset.SCHEMA_VERSION == "1.0.0"
