"""Reproducible generation of multi-turn support ticket datasets in any domain.

Everything re-exported here is the **stable contract** (contracts/python-api.md). Anything else
is internal and may change without a version bump. The surface follows the record contract's
version: removing a name or narrowing a signature is a breaking change requiring a MAJOR bump,
in the same change as the schema, a migration note, and updated validation tests (Constitution I).
"""

from ticket_dataset_generator.config.loader import load_config, validate_config
from ticket_dataset_generator.config.models import (
    Budget,
    Composition,
    GenerationConfig,
    ModelSpec,
    TimeWindow,
)
from ticket_dataset_generator.dedup import DuplicateCounter
from ticket_dataset_generator.dedup import fingerprint as content_fingerprint
from ticket_dataset_generator.errors import (
    AmbiguousResumeError,
    CheckpointCorruptError,
    CheckpointMismatchError,
    ConfigError,
    FloorNotCoveredError,
    OutputPathExistsError,
    PromptDocumentError,
    ReasonContainsIdentifierError,
    ReleaseGateError,
    RubricError,
    TicketDatasetError,
    UnobservableEnvironmentError,
    UnsatisfiableCompositionError,
)
from ticket_dataset_generator.model.client import ModelClient, ModelResponse, ModelRole
from ticket_dataset_generator.model.fake import FakeModelClient
from ticket_dataset_generator.planning.seeding import slot_random
from ticket_dataset_generator.planning.tolerance import Breach
from ticket_dataset_generator.planning.tolerance import check as check_tolerance
from ticket_dataset_generator.privacy.exceptions_store import ExceptionStore
from ticket_dataset_generator.privacy.masking import mask
from ticket_dataset_generator.privacy.registry import (
    Detector,
    DetectorRegistry,
    Finding,
    ScanReport,
)
from ticket_dataset_generator.run.enums import (
    DiscardReason,
    FindingStatus,
    PIICategory,
    RunOutcome,
    Verdict,
)
from ticket_dataset_generator.run.manifest import (
    RunManifest,
    validate_manifest,
    validate_manifest_file,
)
from ticket_dataset_generator.run.report import RunReport
from ticket_dataset_generator.run.run import GenerationRun, RunResult
from ticket_dataset_generator.schema.enums import (
    Category,
    Channel,
    Priority,
    ResolutionStatus,
    Role,
)
from ticket_dataset_generator.schema.export import export_json_schema
from ticket_dataset_generator.schema.record import (
    ConversationTurn,
    GenerationInfo,
    RecordQuality,
    TicketMetadata,
    TicketRecord,
)
from ticket_dataset_generator.schema.version import (
    SCHEMA_VERSION,
    is_supported_version,
    parse_semver,
)

__all__ = [
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
]
