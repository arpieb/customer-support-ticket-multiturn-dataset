"""The committed domain prompt document (FR-008a, FR-008d).

The document is a run input: its hash goes into the manifest, so a change to it is visible as a
change in provenance rather than as an unexplained shift in the corpus. It must declare an
enumerable subdomain list, because without one "scenario selection" cannot be a seeded choice at
all and the corpus cannot be stratified deterministically.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from ticket_dataset_generator.errors import PromptDocumentError
from ticket_dataset_generator.generation.frontmatter import read_document

#: How much of the digest goes into ``source_id``. Long enough to identify a version, short
#: enough to read on a record.
SOURCE_ID_DIGEST_LENGTH = 12


@dataclass(frozen=True, slots=True)
class DomainDocument:
    path: Path
    subdomains: tuple[str, ...]
    body: str
    sha256: str

    @property
    def source_id(self) -> str:
        """The identity every record carries (FR-003, FR-008a)."""
        return f"{self.path.name}@{self.sha256[:SOURCE_ID_DIGEST_LENGTH]}"


def load_domain_document(path: Path) -> DomainDocument:
    """Read and validate the domain prompt document."""
    path = Path(path)
    if not path.exists():
        raise PromptDocumentError(f"domain prompt document not found: {path}")

    front, body = read_document(path)
    declared = front.get("subdomains")

    if declared is None:
        raise PromptDocumentError(
            f"{path} declares no `subdomains` list. Scenario selection is a seeded choice "
            "(FR-012b), which requires an enumerable list to draw from (FR-008d)."
        )
    if not isinstance(declared, list):
        raise PromptDocumentError(
            f"{path}: `subdomains` must be a list of names, got {type(declared).__name__}"
        )

    cleaned = [item.strip() for item in declared if isinstance(item, str) and item.strip()]
    if not cleaned:
        raise PromptDocumentError(f"{path}: `subdomains` is empty; nothing to draw from")
    if len(set(cleaned)) != len(cleaned):
        duplicates = sorted({name for name in cleaned if cleaned.count(name) > 1})
        raise PromptDocumentError(
            f"{path}: duplicate subdomains would skew the seeded draw: {', '.join(duplicates)}"
        )
    if not body.strip():
        raise PromptDocumentError(
            f"{path}: the document body is empty; there is nothing to prompt with"
        )

    return DomainDocument(
        path=path,
        subdomains=tuple(sorted(cleaned)),
        body=body,
        sha256=sha256(path.read_bytes()).hexdigest(),
    )
