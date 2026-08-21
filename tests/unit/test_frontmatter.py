"""The front matter reader for the two committed prompt documents.

Deliberately not a YAML dependency: the front matter is a handful of scalars and one flat list,
and keeping the parser small keeps the committed inputs simple enough to review by eye — which is
the control the privacy assumption actually rests on.
"""

from pathlib import Path

from ticket_dataset.generation.frontmatter import (
    parse_front_matter,
    read_document,
    split_front_matter,
)


def test_a_document_without_front_matter_is_all_body() -> None:
    front, body = split_front_matter("# Just a heading\n\nText.\n")
    assert front == ""
    assert body.startswith("# Just a heading")


def test_front_matter_is_separated_from_the_body() -> None:
    front, body = split_front_matter("---\nkey: value\n---\n\n# Body\n")
    assert front.strip() == "key: value"
    assert body.strip() == "# Body"


def test_an_unterminated_block_is_not_treated_as_front_matter() -> None:
    text = "---\nkey: value\n\n# Body without a closing delimiter\n"
    front, body = split_front_matter(text)
    assert front == ""
    assert body == text


def test_scalars_are_parsed_and_typed() -> None:
    parsed = parse_front_matter("name: thing\ncount: 3\nratio: 0.25\nflag: true\n")
    assert parsed == {"name": "thing", "count": 3, "ratio": 0.25, "flag": True}


def test_a_version_string_stays_a_string() -> None:
    # "1.0.0" must not become a float; a rubric_id or version is an identifier, not a number.
    assert parse_front_matter("version: 1.0.0\n")["version"] == "1.0.0"


def test_a_flat_list_is_parsed() -> None:
    parsed = parse_front_matter("subdomains:\n  - refund\n  - shipping-delay\n")
    assert parsed["subdomains"] == ["refund", "shipping-delay"]


def test_a_nested_mapping_is_parsed() -> None:
    parsed = parse_front_matter("criteria:\n  single_issue: 0.5\n  flow: 0.5\n")
    assert parsed["criteria"] == {"single_issue": 0.5, "flow": 0.5}


def test_a_key_opened_and_never_filled_is_none() -> None:
    assert parse_front_matter("subdomains:\n")["subdomains"] is None


def test_comments_and_blank_lines_are_ignored() -> None:
    parsed = parse_front_matter("# a comment\n\nname: thing\n\n  # indented comment\n")
    assert parsed == {"name": "thing"}


def test_scalars_and_blocks_can_be_mixed() -> None:
    parsed = parse_front_matter("domain_id: test\nsubdomains:\n  - a\n  - b\nversion: 2.0.0\n")
    assert parsed["domain_id"] == "test"
    assert parsed["subdomains"] == ["a", "b"]
    assert parsed["version"] == "2.0.0"


def test_reading_a_real_document(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("---\nid: x\nitems:\n  - one\n---\n\n# Body\n\nText.\n")
    front, body = read_document(path)
    assert front == {"id": "x", "items": ["one"]}
    assert body.startswith("# Body")


def test_the_committed_documents_parse() -> None:
    domain, _ = read_document(Path("prompts/samples/consumer-electronics-support.md"))
    rubric, _ = read_document(Path("prompts/coherence-rubric.md"))
    assert isinstance(domain["subdomains"], list)
    assert isinstance(rubric["criteria"], dict)
