"""Code revision, input hashes, and environment provenance (FR-008c, FR-025, FR-025a, R10).

Principle II requires a run to be replayable or *auditable*. A commit SHA recorded from a
modified working tree silently misrepresents what produced the artifact, so the modification is
recorded as an explicit flag rather than left invisible. Refusing to run on a dirty tree would
block ordinary development, so recording the caveat is the trade — and weighing it belongs to the
separate act of deciding to release.

The environment is handled the other way round. Credentials are an access mechanism: they never
influence output and are never written to any artifact. Anything else the environment contributes
— an alternate endpoint, a profile selection, an inference region — *can* change output, and is
therefore recorded as a non-deterministic input. A setting that cannot be observed refuses the run
rather than proceeding unrecorded.
"""

import os
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

#: Environment variables that can change which model serves a request, how it is routed, or the
#: parameters it runs under. Recorded in the manifest when set (FR-008c).
ROUTING_VARIABLES = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_AUTH_TOKEN_FILE",
    "ANTHROPIC_WORKSPACE_ID",
    "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_ORGANIZATION_ID",
    "ANTHROPIC_SERVICE_ACCOUNT_ID",
    "AWS_REGION",
    "CLOUD_ML_REGION",
    "ANTHROPIC_VERTEX_PROJECT_ID",
)

#: Never recorded, anywhere, under any circumstances (FR-008).
CREDENTIAL_VARIABLES = frozenset(
    {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"}
)


@dataclass(frozen=True, slots=True)
class CodeRevision:
    commit: str | None
    dirty: bool
    unavailable_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "commit": self.commit,
            "dirty": self.dirty,
            "unavailable_reason": self.unavailable_reason,
        }


def _git(*args: str, cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=cwd, check=True, timeout=10
        )
    except subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired:
        return None
    return result.stdout.strip()


def capture_revision(cwd: Path | None = None) -> CodeRevision:
    """The commit that produced this run, with the modification caveat attached."""
    commit = _git("rev-parse", "HEAD", cwd=cwd)
    if commit is None:
        return CodeRevision(
            commit=None,
            dirty=False,
            unavailable_reason="not a git repository, or git is unavailable",
        )
    status = _git("status", "--porcelain", cwd=cwd)
    if status is None:
        return CodeRevision(
            commit=commit, dirty=False, unavailable_reason="could not determine tree state"
        )
    return CodeRevision(commit=commit, dirty=bool(status.strip()), unavailable_reason=None)


def hash_file(path: Path) -> str:
    """``sha256`` over a run input's contents (FR-025)."""
    return sha256(Path(path).read_bytes()).hexdigest()


def hash_inputs(paths: dict[str, Path]) -> dict[str, str]:
    """Label → digest for every committed input a run consumed."""
    return {label: hash_file(path) for label, path in paths.items() if Path(path).exists()}


def environment_overrides(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Routing-capable environment settings, recorded as provenance (FR-008c).

    Credentials are excluded by name rather than by redaction: a value that is never read cannot
    be written by accident.
    """
    source = os.environ if environ is None else environ
    overrides: dict[str, str] = {}
    for name in ROUTING_VARIABLES:
        value = source.get(name)
        if value:
            overrides[name] = value
    for name in CREDENTIAL_VARIABLES:
        assert name not in overrides, "a credential must never be recorded (FR-008)"
    return overrides
