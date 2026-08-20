"""The privacy gate must never acquire a model dependency by accident.

FR-024 requires every detector to work without contacting a network service. The `datafog`
core install satisfies that; `datafog[nlp]` would not, because it pulls spaCy models that are
downloaded at install or first use. A stray extra would break the guarantee silently, so this
test fails the build rather than letting it regress (research R7).
"""

import importlib.util


def test_no_model_runtime_installed() -> None:
    for package in ("spacy", "torch", "transformers"):
        assert importlib.util.find_spec(package) is None, (
            f"{package} is importable, which means a model-backed extra was installed. "
            "The privacy gate must stay offline and deterministic (FR-024)."
        )


def test_detection_engine_available() -> None:
    assert importlib.util.find_spec("datafog") is not None, (
        "datafog is not installed; the blocking floor cannot be covered (FR-018)."
    )
