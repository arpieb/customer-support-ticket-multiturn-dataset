"""The CLI paths that actually produce a corpus (contracts/cli.md).

These exist because their absence hid a real defect: `--resume` was accepted as an option while
the command body never used it, and `validate-manifest` was missing entirely, and the suite
passed. `test_cli_generate.py` covers refusals, `--dry-run`, and `schema` — none of which reach
the code that was broken.

The model is stubbed by pointing the CLI's provider client at the fake, so these run offline like
everything else.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI = [sys.executable, "-m", "ticket_dataset_generator.cli.main"]

#: Runs the CLI with the provider client replaced by the fake, so a real generate can be
#: exercised without a network. sitecustomize is the least invasive hook: no production code
#: learns about tests.
STUB = """
import ticket_dataset_generator.model.litellm_client as real
from ticket_dataset_generator.model.fake import FakeModelClient

class _Stub(FakeModelClient):
    def __init__(self, config, **kwargs):
        super().__init__()

    @staticmethod
    def supports_structured_output(model_id):
        return True

real.LiteLLMModelClient = _Stub
"""


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    (cwd / "sitecustomize.py").write_text(STUB)
    return subprocess.run(
        [*CLI, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": f"{Path.cwd() / 'src'}:{cwd}",
            "ANTHROPIC_API_KEY": "",
        },
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A scratch project: prompts, a config, and the data directories."""
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "domain.md").write_text(
        "---\nsubdomains:\n  - refund\n  - shipping-delay\n---\n\n# Domain\n\nSupport tickets.\n"
    )
    (tmp_path / "prompts" / "coherence-rubric.md").write_text(
        "---\nrubric_id: test-v1\ncriteria:\n  single_issue: 1.0\n---\n\n# Rubric\n\nScore it.\n"
    )
    for directory in ("data/release", "data/interim"):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "run.toml").write_text(
        "record_count = 12\n"
        'output_path = "data/release/corpus.jsonl"\n'
        'prompt_document = "prompts/domain.md"\n'
        "composition_tolerance_pp = 20.0\n"
        "max_concurrency = 2\n"
        "[composition.category]\nbilling = 1.0\n"
        "[composition.priority]\nnormal = 1.0\n"
        "[composition.channel]\nemail = 1.0\n"
        "[composition.resolution_status]\nresolved = 1.0\n"
    )
    return tmp_path


def test_a_successful_run_exits_zero_and_publishes(workspace: Path) -> None:
    result = _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace)
    assert result.returncode == 0, result.stderr
    corpus = workspace / "data" / "release" / "corpus.jsonl"
    assert corpus.exists()
    assert len(corpus.read_text().splitlines()) == 12


def test_stdout_is_the_run_report_and_nothing_else(workspace: Path) -> None:
    # Progress and prose go to stderr, so a piped invocation is never corrupted.
    result = _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace)
    report = json.loads(result.stdout)
    assert report["outcome"] == "completed"
    assert report["records_written"] == 12
    assert report["verdict"] == "pass"


def test_progress_appears_on_stderr(workspace: Path) -> None:
    # The gap this file exists to close: a long run must not look hung (FR-012).
    result = _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace)
    assert "records" in result.stderr
    assert "/12 records" in result.stderr


def test_quiet_suppresses_progress_but_not_the_report(workspace: Path) -> None:
    result = _run("generate", "--config", "run.toml", "--seed", "42", "--quiet", cwd=workspace)
    assert result.returncode == 0
    assert "/12 records" not in result.stderr
    assert json.loads(result.stdout)["records_written"] == 12


def test_validate_manifest_accepts_a_manifest_the_run_wrote(workspace: Path) -> None:
    generated = _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace)
    run_id = json.loads(generated.stdout)["run_id"]

    result = _run("validate-manifest", f"data/release/{run_id}.manifest.json", cwd=workspace)
    assert result.returncode == 0, result.stderr
    assert "valid" in result.stderr


def test_validate_manifest_rejects_one_whose_counts_do_not_reconcile(workspace: Path) -> None:
    generated = _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace)
    run_id = json.loads(generated.stdout)["run_id"]
    manifest_path = workspace / "data" / "release" / f"{run_id}.manifest.json"

    manifest = json.loads(manifest_path.read_text())
    manifest["records_written"] += 1  # every field still present, the arithmetic no longer closes
    manifest_path.write_text(json.dumps(manifest))

    result = _run("validate-manifest", str(manifest_path), cwd=workspace)
    assert result.returncode == 1
    assert "do not reconcile" in result.stderr


def test_validate_manifest_reports_a_missing_file(workspace: Path) -> None:
    result = _run("validate-manifest", "data/release/absent.manifest.json", cwd=workspace)
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_resume_refuses_when_there_is_nothing_to_resume(workspace: Path) -> None:
    # The defect this file exists to catch: --resume was accepted and silently ignored, so this
    # invocation used to start a fresh run and exit 0.
    result = _run("generate", "--config", "run.toml", "--seed", "42", "--resume", cwd=workspace)
    assert result.returncode == 2, result.stdout
    assert "nothing to resume" in result.stderr
    assert not (workspace / "data" / "release" / "corpus.jsonl").exists()


def test_a_seed_is_still_required(workspace: Path) -> None:
    result = _run("generate", "--config", "run.toml", cwd=workspace)
    assert result.returncode != 0


# --- reproducing a recorded run (FR-040, FR-041) ----------------------------------------------
#
# The claim these make good on is that a manifest is enough to repeat the run it describes.
# Asserting the config merely *parses* would not test that; only regenerating and comparing the
# corpus does.


def _manifest_of(workspace: Path) -> Path:
    (manifest,) = (workspace / "data" / "release").glob("*.manifest.json")
    return manifest


def _contents(corpus: Path) -> list:
    return [json.loads(line)["turns"] for line in corpus.read_text().splitlines()]


def test_a_recovered_config_regenerates_the_same_corpus(workspace: Path) -> None:
    assert _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace).returncode == 0
    original = _contents(workspace / "data" / "release" / "corpus.jsonl")

    recovered = _run(
        "config-from-manifest",
        str(_manifest_of(workspace).relative_to(workspace)),
        "--out",
        "recovered.toml",
        cwd=workspace,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert "seed 42" in recovered.stderr

    again = _run(
        "generate",
        "--config",
        "recovered.toml",
        "--seed",
        "42",
        "--out",
        "data/release/again.jsonl",
        cwd=workspace,
    )
    assert again.returncode == 0, again.stderr
    assert _contents(workspace / "data" / "release" / "again.jsonl") == original


def test_from_manifest_reproduces_without_a_config_file_at_all(workspace: Path) -> None:
    assert _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace).returncode == 0
    original = _contents(workspace / "data" / "release" / "corpus.jsonl")

    result = _run(
        "generate",
        "--from-manifest",
        str(_manifest_of(workspace).relative_to(workspace)),
        "--out",
        "data/release/again.jsonl",
        cwd=workspace,
    )
    assert result.returncode == 0, result.stderr
    assert _contents(workspace / "data" / "release" / "again.jsonl") == original


def test_from_manifest_refuses_when_the_prompt_has_since_changed(workspace: Path) -> None:
    assert _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace).returncode == 0
    prompt = workspace / "prompts" / "domain.md"
    prompt.write_text(prompt.read_text() + "\nAn added instruction.\n")

    result = _run(
        "generate",
        "--from-manifest",
        str(_manifest_of(workspace).relative_to(workspace)),
        "--out",
        "data/release/again.jsonl",
        cwd=workspace,
    )
    assert result.returncode == 2
    assert "prompt_document  DIFFERS" in result.stderr
    assert not (workspace / "data" / "release" / "again.jsonl").exists()


def test_allow_drift_proceeds_but_says_it_is_not_a_reproduction(workspace: Path) -> None:
    assert _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace).returncode == 0
    prompt = workspace / "prompts" / "domain.md"
    prompt.write_text(prompt.read_text() + "\nAn added instruction.\n")

    result = _run(
        "generate",
        "--from-manifest",
        str(_manifest_of(workspace).relative_to(workspace)),
        "--allow-drift",
        "--out",
        "data/release/again.jsonl",
        cwd=workspace,
    )
    assert result.returncode == 0, result.stderr
    assert "will NOT reproduce" in result.stderr


def test_naming_both_sources_refuses_rather_than_choosing(workspace: Path) -> None:
    assert _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace).returncode == 0
    result = _run(
        "generate",
        "--config",
        "run.toml",
        "--from-manifest",
        str(_manifest_of(workspace).relative_to(workspace)),
        cwd=workspace,
    )
    assert result.returncode == 2
    assert "one or the other" in result.stderr


def test_out_is_honoured_when_the_configured_path_is_already_taken(workspace: Path) -> None:
    # Regression: the occupied-path check ran against the config's own output_path before --out
    # was applied, so a run was refused over a destination it would never have written to. The
    # reproduction path hits this every time, since a recovered config names a published file.
    assert _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace).returncode == 0
    assert (workspace / "data" / "release" / "corpus.jsonl").exists()

    result = _run(
        "generate",
        "--config",
        "run.toml",
        "--seed",
        "7",
        "--out",
        "data/release/elsewhere.jsonl",
        cwd=workspace,
    )
    assert result.returncode == 0, result.stderr
    assert (workspace / "data" / "release" / "elsewhere.jsonl").exists()


def test_reproduction_holds_with_a_multi_member_composition(workspace: Path) -> None:
    """The gap that let a determinism defect survive a green suite.

    Every other config here declares one member per dimension, so the composition pools are
    uniform and shuffling them cannot change anything. A pool shuffle keyed to the interpreter
    rather than the seed was invisible under those configs, and visible immediately under this
    one.
    """
    (workspace / "run.toml").write_text(
        "record_count = 12\n"
        'output_path = "data/release/corpus.jsonl"\n'
        'prompt_document = "prompts/domain.md"\n'
        "composition_tolerance_pp = 30.0\n"
        "max_concurrency = 2\n"
        "[composition.category]\nbilling = 0.5\ntechnical = 0.5\n"
        "[composition.priority]\nnormal = 1.0\n"
        "[composition.channel]\nemail = 0.5\nchat = 0.5\n"
        "[composition.resolution_status]\nresolved = 0.75\nescalated = 0.25\n"
    )
    assert _run("generate", "--config", "run.toml", "--seed", "42", cwd=workspace).returncode == 0
    corpus = workspace / "data" / "release" / "corpus.jsonl"
    original = [json.loads(line) for line in corpus.read_text().splitlines()]
    assert len({r["metadata"]["category"] for r in original}) == 2, "pool is not actually mixed"

    result = _run(
        "generate",
        "--from-manifest",
        str(_manifest_of(workspace).relative_to(workspace)),
        "--out",
        "data/release/again.jsonl",
        cwd=workspace,
    )
    assert result.returncode == 0, result.stderr
    again = [
        json.loads(line)
        for line in (workspace / "data" / "release" / "again.jsonl").read_text().splitlines()
    ]

    # Metadata assignment and content alike, since a reproduction is only worth the name if the
    # composition lands on the same positions.
    for a, b in zip(original, again, strict=True):
        assert a["metadata"] == b["metadata"]
        assert a["turns"] == b["turns"]
        assert a["subdomain"] == b["subdomain"]
