"""The CLI contract: exit statuses and stream discipline (contracts/cli.md, FR-036b).

Nothing here reaches a model. The refused paths never get that far by construction, and the
successful path is driven through the programmatic API with a fake client — the CLI's own job is
argument parsing, rendering, and the exit status, which is what these tests pin.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI = [sys.executable, "-m", "ticket_dataset.cli.main"]


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*CLI, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src", "ANTHROPIC_API_KEY": ""},
    )


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "run.toml"
    path.write_text(body)
    return path


def test_help_exits_zero() -> None:
    assert _run("--help").returncode == 0


def test_a_missing_config_is_refused_with_exit_two(tmp_path: Path) -> None:
    # Exit 2 means nothing was generated and nothing was spent.
    result = _run("generate", "--config", str(tmp_path / "absent.toml"), "--seed", "1")
    assert result.returncode == 2
    assert "does not exist" in result.stderr


def test_an_invalid_config_is_refused_with_exit_two(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        'record_count = 0\noutput_path = "data/release/nope.jsonl"\n',
    )
    result = _run("generate", "--config", str(config), "--seed", "1")
    assert result.returncode == 2
    assert "record_count" in result.stderr


def test_an_unachievable_tolerance_is_refused_before_generating(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        "record_count = 20\n"
        'output_path = "data/release/tight.jsonl"\n'
        "composition_tolerance_pp = 2.0\n",
    )
    result = _run("generate", "--config", str(config), "--seed", "1")
    assert result.returncode == 2
    assert "unachievable at 20 records" in result.stderr


def test_a_seed_is_required(tmp_path: Path) -> None:
    # There is no implicit or time-derived seed (Constitution II).
    config = _write_config(tmp_path, 'record_count = 60\noutput_path = "data/release/x.jsonl"\n')
    result = _run("generate", "--config", str(config))
    assert result.returncode != 0
    assert "seed" in (result.stderr + result.stdout).lower()


def test_dry_run_plans_without_calling_a_model() -> None:
    # The plan is machine-readable on stdout; progress and prose stay on stderr.
    result = _run("generate", "--config", "configs/smoke.toml", "--seed", "42", "--dry-run")
    assert result.returncode == 0
    plan = json.loads(result.stdout)
    assert plan["slots"] == 20
    assert plan["model_calls_estimated"] == 40
    assert plan["rubric_id"] == "coherence-v1"


def test_stdout_carries_machine_readable_output_only() -> None:
    result = _run("generate", "--config", "configs/smoke.toml", "--seed", "42", "--dry-run")
    json.loads(result.stdout)  # parses cleanly, so no progress text leaked into it


def test_schema_export_is_valid_json() -> None:
    result = _run("schema")
    assert result.returncode == 0
    exported = json.loads(result.stdout)
    assert exported["title"] == "TicketRecord"


@pytest.mark.parametrize("occupied", ["data/release/smoke.jsonl"])
def test_an_existing_output_path_is_refused(tmp_path: Path, occupied: str) -> None:
    path = Path(occupied)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    try:
        result = _run("generate", "--config", "configs/smoke.toml", "--seed", "42", "--dry-run")
        assert result.returncode == 2
        assert "no overwrite flag" in result.stderr
    finally:
        path.unlink()
