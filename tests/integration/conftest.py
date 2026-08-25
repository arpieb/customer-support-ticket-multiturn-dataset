"""Integration fixtures. Everything here runs against the fake model; nothing calls a network."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from ticket_dataset_generator.run import run as run_module


@pytest.fixture
def staging_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect staging into the test's temp directory, so runs leave nothing behind."""
    root = tmp_path / "interim"
    monkeypatch.setattr(run_module, "STAGING_ROOT", root)
    yield root
