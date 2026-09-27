"""Canonical statement scope, independent of display labels and polarity."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from ontologylab.kgstore_base import normalize_name
from ontologylab.unit_normalization import normalize_dose


# Explicit engineering-reviewed aliases; no fuzzy matching or inferred scope.
# Tuple entries are source spellings; the dictionary key is the stored value.
QUALIFIER_VOCABULARIES = {
    "study_context": {
        "in_vitro": ("in vitro", "in-vitro"),
        "greenhouse": ("glasshouse", "glasshouse screening", "greenhouse screening"),
        "field_trial": ("field", "field trial", "field experiment"),
        "crop_trial": ("crop trial",),
        "bioassay": ("bioassay",),
        "background": ("background",),
    },
    "aspect": {
        "growth": ("growth",),
        "oviposition": ("oviposition",),
        "mortality": ("mortality",),
        "survival": ("survival",),
        "yield": ("yield",),
        "density": ("density",),
        "abundance": ("abundance",),
        "bubble_development": ("bubble development",),
        "fresh_weight": ("fresh weight", "fresh-weight"),
        "dry_weight": ("dry weight", "dry-weight"),
        "tiller_number": ("tiller number",),
        "fresh_weight_and_tiller_number": ("fresh weight and tiller number",),
    },
    "application_timing": {
        "pre_emergence": ("pre-emergence", "preemergence", "pre emergence"),
        "post_emergence": ("post-emergence", "postemergence", "post emergence"),
        "early_post_emergence": (
            "early-postemergence", "early postemergence", "early-post-emergence",
            "early post-emergence",
        ),
    },
    "direction": {
        "increased": ("increase", "increasing"),
        "decreased": ("decrease", "decreasing"),
        "unchanged": ("no change",),
    },
    "life_stage": {
        "egg": ("eggs",),
        "larva": ("larvae", "larval"),
        "pupa": ("pupae", "pupal"),
        "nymph": ("nymphs", "nymphal"),
        "adult": ("adults",),
        "seedling": ("seedlings",),
    },
    "form_or_variant_kind": {
        "strain": ("strain",),
        "isolate": ("isolate",),
        "variant": ("variant",),
        "life_stage": ("life stage",),
    },
}

_HYPHENS = str.maketrans({char: "-" for char in "\u2010\u2011\u2012\u2013\u2212"})


def normalize_qualifier_value(value: str) -> str:
    """Normalize Unicode, case and whitespace, never erase meaningful punctuation."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _vocabulary_value(vocabulary: str, value: str) -> str | None:
    for canonical, aliases in QUALIFIER_VOCABULARIES[vocabulary].items():
        if value == canonical or value in aliases:
            return canonical
    return None


def normalize_statement_value(key: str, value: str) -> str:
    """Canonical agrochem value; unknown closed values retain explicit scope."""
    text = normalize_qualifier_value(value)
    if key == "dose":
        return normalize_dose(text)
    if key.endswith("_form_or_variant_qualifier"):
        stage_text = text.removeprefix("life_stage:").removeprefix("life stage:")
        stage = _vocabulary_value("life_stage", stage_text)
        if stage is not None:
            return f"life_stage:{stage}"
        for kind in QUALIFIER_VOCABULARIES["form_or_variant_kind"]:
            if kind == "life_stage":
                continue
            match = re.fullmatch(rf"{kind}(?:\s+|:)(.+)", text)
            if match:
                return f"{kind}:{normalize_name(match[1])}"
        return "other:" + normalize_name(text.removeprefix("other:"))
    if key == "population_context_qualifier":
        return normalize_name(text)
    vocabulary = "aspect" if key.endswith("_aspect_qualifier") else key
    if key.endswith("_direction_qualifier"):
        vocabulary = "direction"
    if vocabulary in ("study_context", "aspect", "application_timing", "direction"):
        if text.startswith("other:"):
            return text
        spelling = text.translate(_HYPHENS)
        known = _vocabulary_value(vocabulary, spelling)
        if known is not None:
            return known
        if key == "study_context":
            # A setting is enumerable, an experiment's identity is not. Never
            # erase "1"/"2", turn a crop trial into a field trial, or drop a name.
            match = re.fullmatch(r"(.+?)(?:\s+|:)(\d+)", spelling)
            if match:
                setting = _vocabulary_value(vocabulary, match[1])
                if setting in ("bioassay", "crop_trial", "field_trial"):
                    return f"{setting}:{match[2]}"
        return f"other:{text}"
    return text


def normalize_statement_qualifiers(qualifiers: dict[str, str]) -> dict[str, str]:
    """Normalize validated agrochem scope without inventing missing fields."""
    return {key: normalize_statement_value(key, value) for key, value in qualifiers.items()}


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
