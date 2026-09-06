"""Identifier helpers. All domain rows use ULIDs (tech spec 4)."""

from __future__ import annotations

from ulid import ULID


def new_id() -> str:
    """A fresh ULID as a 26-character string, lexicographically sortable by time."""
    return str(ULID())


def is_valid_id(value: str) -> bool:
    """True when `value` parses as a ULID. Used to reject malformed path params."""
    try:
        ULID.from_str(value)
    except (ValueError, TypeError):
        return False
    return True
