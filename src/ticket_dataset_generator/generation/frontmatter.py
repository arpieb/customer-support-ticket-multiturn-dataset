"""A minimal YAML-ish front matter reader for the two committed prompt documents.

Deliberately not a YAML dependency. The front matter these documents carry is a handful of
scalars and one flat list, and the parser refusing anything more exotic is a feature: it keeps
the committed inputs simple enough to review by eye, which is the control the privacy assumption
actually rests on (spec Assumptions).
"""

from pathlib import Path
from typing import Any

DELIMITER = "---"


def split_front_matter(text: str) -> tuple[str, str]:
    """Return ``(front_matter, body)``; front matter is empty when there is none."""
    if not text.startswith(DELIMITER):
        return "", text
    rest = text[len(DELIMITER) :].lstrip("\n")
    end = rest.find(f"\n{DELIMITER}")
    if end == -1:
        return "", text
    return rest[:end], rest[end + len(DELIMITER) + 1 :].lstrip("\n")


def parse_front_matter(text: str) -> dict[str, Any]:
    """Parse scalars, flat lists, and one level of nested ``key: value`` pairs."""
    parsed: dict[str, Any] = {}
    current_key: str | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # A list item continues whatever key was opened above it.
        if stripped.startswith("- "):
            if current_key is None:
                continue
            if not isinstance(parsed.get(current_key), list):
                parsed[current_key] = []
            parsed[current_key].append(stripped[2:].strip())
            continue

        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        indented = line[0].isspace()

        # An indented `key: value` belongs to the key opened above it.
        if indented and current_key is not None:
            if not isinstance(parsed.get(current_key), dict):
                parsed[current_key] = {}
            parsed[current_key][key] = _coerce(value)
            continue

        # A bare `key:` opens a block; its type is decided by what follows.
        parsed[key] = None if value == "" else _coerce(value)
        current_key = key

    return parsed


def _coerce(value: str) -> Any:
    if value in {"true", "false"}:
        return value == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value.strip("\"'")


def read_document(path: Path) -> tuple[dict[str, Any], str]:
    """Read a committed prompt document as ``(front_matter, body)``."""
    text = Path(path).read_text(encoding="utf-8")
    front, body = split_front_matter(text)
    return parse_front_matter(front), body
