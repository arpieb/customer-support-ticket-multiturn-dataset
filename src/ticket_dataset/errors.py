"""The exception hierarchy (contracts/python-api.md).

None of these may carry a matched PII value. A finding names the record, the field, the
category, the detector, and a masked rendering — never the value itself (FR-020), and an
exception message is no exception to that.
"""


class TicketDatasetError(Exception):
    """Base for every error this package raises."""


class ConfigError(TicketDatasetError):
    """A configuration is invalid or internally contradictory (FR-011).

    Carries *every* problem found, not the first: an operator fixing a config should see the
    whole list rather than discovering them one run at a time.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        joined = "\n  - ".join(self.problems)
        super().__init__(f"configuration is invalid:\n  - {joined}")


class UnsatisfiableCompositionError(ConfigError):
    """A composition request cannot be satisfied at the requested corpus size (FR-032)."""


class FloorNotCoveredError(TicketDatasetError):
    """The registered detectors did not demonstrate coverage of the blocking floor (FR-018a)."""


class OutputPathExistsError(TicketDatasetError):
    """The destination artifact exists, or another run claimed it (FR-014, FR-014a).

    There is deliberately no overwrite option to catch: the data directory is outside version
    control, so an overwritten corpus and its manifest are unrecoverable.
    """


class CheckpointMismatchError(TicketDatasetError):
    """Resume attempted with changed config, seed, prompt document, or rubric (FR-015e)."""


class CheckpointCorruptError(TicketDatasetError):
    """The checkpoint is unreadable; partial output is preserved and restarting is explicit."""


class AmbiguousResumeError(TicketDatasetError):
    """More than one checkpointed run matches the inputs (FR-015h)."""

    def __init__(self, candidates: list[str]) -> None:
        self.candidates = list(candidates)
        listed = ", ".join(self.candidates)
        super().__init__(
            f"{len(self.candidates)} checkpointed runs match these inputs: {listed}. "
            "Name one with --run-id."
        )


class UnobservableEnvironmentError(TicketDatasetError):
    """An environment setting could alter model routing but cannot be recorded (FR-008c)."""


class PromptDocumentError(TicketDatasetError):
    """The domain prompt document declares no usable subdomain list (FR-008d)."""


class RubricError(TicketDatasetError):
    """The coherence rubric is missing criteria, weights, or an identifier (FR-009p)."""


class ReasonContainsIdentifierError(TicketDatasetError):
    """An exception's stated reason tripped a detector (FR-022b).

    The offending value is never included here — that would defeat the fingerprinting this
    error exists to protect.
    """
