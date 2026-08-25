"""The domain prompt document must declare a usable subdomain list (FR-008a, FR-008d)."""

import re
from pathlib import Path

import pytest

from ticket_dataset_generator.config.defaults import DEFAULT_PROMPT_DOCUMENT
from ticket_dataset_generator.errors import PromptDocumentError
from ticket_dataset_generator.generation.domain_doc import load_domain_document
from ticket_dataset_generator.privacy.detectors.datafog_detector import DataFogDetector
from ticket_dataset_generator.privacy.registry import DetectorRegistry

VALID = """---
domain_id: test-domain
subdomains:
  - refund
  - shipping-delay
---

# Test domain

A body with something in it.
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "domain.md"
    path.write_text(text)
    return path


def test_a_valid_document_parses(tmp_path: Path) -> None:
    document = load_domain_document(_write(tmp_path, VALID))
    assert document.subdomains == ("refund", "shipping-delay")
    assert document.body.startswith("# Test domain")


def test_the_committed_document_is_valid() -> None:
    # The project's own prompt document must satisfy its own parser.
    document = load_domain_document(DOMAIN_DOCUMENT)
    assert len(document.subdomains) >= 10


def test_source_id_identifies_the_version(tmp_path: Path) -> None:
    document = load_domain_document(_write(tmp_path, VALID))
    assert document.source_id.startswith("domain.md@")
    assert document.sha256.startswith(document.source_id.split("@")[1])


def test_editing_the_document_changes_its_identity(tmp_path: Path) -> None:
    # A change to the prompt document is a change in provenance, which is why its hash is a run
    # input (FR-008a).
    before = load_domain_document(_write(tmp_path, VALID)).source_id
    after = load_domain_document(_write(tmp_path, VALID + "\nAn extra line.\n")).source_id
    assert before != after


def test_a_document_without_subdomains_is_refused(tmp_path: Path) -> None:
    text = "---\ndomain_id: test\n---\n\n# Body\n\nText.\n"
    with pytest.raises(PromptDocumentError, match="declares no `subdomains`"):
        load_domain_document(_write(tmp_path, text))


def test_an_empty_subdomain_list_is_refused(tmp_path: Path) -> None:
    text = "---\ndomain_id: test\nsubdomains:\n---\n\n# Body\n\nText.\n"
    with pytest.raises(PromptDocumentError, match="declares no `subdomains`|is empty"):
        load_domain_document(_write(tmp_path, text))


def test_duplicate_subdomains_are_refused(tmp_path: Path) -> None:
    # Duplicates would skew the seeded draw without anyone noticing.
    text = "---\nsubdomains:\n  - refund\n  - refund\n---\n\n# Body\n\nText.\n"
    with pytest.raises(PromptDocumentError, match="duplicate subdomains"):
        load_domain_document(_write(tmp_path, text))


def test_an_empty_body_is_refused(tmp_path: Path) -> None:
    text = "---\nsubdomains:\n  - refund\n---\n"
    with pytest.raises(PromptDocumentError, match="body is empty"):
        load_domain_document(_write(tmp_path, text))


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PromptDocumentError, match="not found"):
        load_domain_document(tmp_path / "absent.md")


def test_subdomains_are_ordered_so_the_draw_is_stable(tmp_path: Path) -> None:
    # The seeded draw indexes into this list; a reordering of the document must not silently
    # reassign every slot's subdomain.
    text = "---\nsubdomains:\n  - zeta\n  - alpha\n  - mid\n---\n\n# Body\n\nText.\n"
    assert load_domain_document(_write(tmp_path, text)).subdomains == ("alpha", "mid", "zeta")


# --- The prompt's own examples must survive the gate they teach the model to pass -------------
#
# Steering is only as good as its examples. An example that the scan would block teaches the
# model to produce blocked records, and the failure is invisible until a live run wastes them.

DOMAIN_DOCUMENT = Path(DEFAULT_PROMPT_DOCUMENT)

_BACKTICKED = re.compile(r"`([^`]+)`")

#: Values the prompt shows in order to forbid them. Each MUST still block — that is what makes it
#: worth naming — and each MUST still appear in the prompt, so the list cannot outlive its text.
COUNTER_EXAMPLES = frozenset({"SL-882130477"})


def _scan(value: str) -> list:
    registry = DetectorRegistry()
    registry.register(DataFogDetector())
    return registry.scan_text(
        f"my reference is {value} if that helps",
        record_id="prompt-example",
        field_name="turns[0].content",
    )


def _identifier_examples() -> set[str]:
    body = DOMAIN_DOCUMENT.read_text()
    return {token for token in _BACKTICKED.findall(body) if any(c.isdigit() for c in token)}


def test_every_identifier_the_prompt_offers_is_one_the_gate_accepts() -> None:
    for example in sorted(_identifier_examples() - COUNTER_EXAMPLES):
        blocking = [f for f in _scan(example) if f.blocks]
        assert not blocking, (
            f"{DOMAIN_DOCUMENT} offers `{example}` as an example, but the privacy gate blocks "
            f"it as {[f.category for f in blocking]}. Choose a value the gate accepts, or add "
            f"it to COUNTER_EXAMPLES if the prompt names it in order to forbid it."
        )


@pytest.mark.parametrize("example", sorted(COUNTER_EXAMPLES))
def test_the_forbidden_examples_are_present_and_still_blocked(example: str) -> None:
    # If either half stops holding, the prompt is teaching against a rule that no longer bites.
    assert example in DOMAIN_DOCUMENT.read_text()
    assert [f for f in _scan(example) if f.blocks]
