"""Canonical statement scope, independent of display labels and polarity."""

from __future__ import annotations

import json
import unicodedata
from typing import Any


def normalize_qualifier_value(value: str) -> str:
    """Normalize Unicode, case and whitespace, never erase meaningful punctuation."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def canonical_qualifiers(qualifiers: dict[str, Any]) -> str:
    """Stable identity suffix; polarity is already a separate identity component.

    Unlike normalize_name, punctuation is retained: doses 0.1 and 01 must
    remain different. Non-string values from other ontologies retain their
    JSON types. The agrochem vocabulary admits only non-empty strings.
    """
    return json.dumps(
        {key: normalize_qualifier_value(value) if isinstance(value, str) else value
         for key, value in qualifiers.items() if key != "polarity"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
