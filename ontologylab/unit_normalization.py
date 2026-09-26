"""Platform-owned normalization of measured values on extraction proposals.

The model emits ``value`` and ``unit`` as free text ("250", "g a.i./ha"). They
stay untouched as the raw record; this module adds a ``measurement`` block
with a parsed number in a canonical unit, so "250 g/ha" and "0.25 kg/ha" can
be compared at query time. It never merges nodes on the normalized value:
two trials that measured the same rate are still two trials.

Stdlib only. The table covers the agrochem/diagnostic subset the presets
extract; an unlisted unit is recorded as ``unknown_unit`` rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ontologylab.models import ProposedEntity


@dataclass(frozen=True, slots=True)
class Unit:
    code: str  # canonical UCUM-style code this surface maps onto
    dimension: str
    factor: float  # multiply a value in this unit by factor -> dimension base


# Dimension bases: areal_mass -> kg/ha, concentration -> mg/L,
# mass_fraction -> mg/kg, areal_volume -> L/ha, time -> d, ratio -> %.
_BASE = {
    "areal_mass": "kg/ha",
    "concentration": "mg/L",
    "mass_fraction": "mg/kg",
    "areal_volume": "L/ha",
    "time": "d",
    "ratio": "%",
}

UNIT_TABLE: dict[str, Unit] = {
    "g/ha": Unit("g/ha", "areal_mass", 0.001),
    "kg/ha": Unit("kg/ha", "areal_mass", 1.0),
    "mg/l": Unit("mg/L", "concentration", 1.0),
    "g/l": Unit("g/L", "concentration", 1000.0),
    "ug/l": Unit("ug/L", "concentration", 0.001),
    "mg/kg": Unit("mg/kg", "mass_fraction", 1.0),
    "ppm": Unit("mg/kg", "mass_fraction", 1.0),
    "l/ha": Unit("L/ha", "areal_volume", 1.0),
    "ml/ha": Unit("mL/ha", "areal_volume", 0.001),
    "ml/l": Unit("mL/L", "ratio", 0.1),
    "%": Unit("%", "ratio", 1.0),
    "d": Unit("d", "time", 1.0),
    "day": Unit("d", "time", 1.0),
    "days": Unit("d", "time", 1.0),
    "h": Unit("h", "time", 1.0 / 24.0),
}

# "a.i." (active ingredient) and "a.e." (acid equivalent) are a basis, not a
# unit: 250 g a.i./ha is a rate of the active, not of the formulated product.
_BASIS_RE = re.compile(r"\b(a\.?\s?i\.?|a\.?\s?e\.?)(?=\s|/|$)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)")
_MICRO = str.maketrans({"\u00b5": "u", "\u03bc": "u"})

MEASUREMENT_KEY = "measurement"


def _parse_unit(raw: str) -> tuple[Unit | None, str | None]:
    text = raw.translate(_MICRO).strip()
    basis_match = _BASIS_RE.search(text)
    basis = None
    if basis_match:
        basis = "a.e." if "e" in basis_match.group(1).lower() else "a.i."
        text = _BASIS_RE.sub("", text)
    key = re.sub(r"\s+", "", text).lower()
    return UNIT_TABLE.get(key), basis


def _parse_value(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    match = _NUMBER_RE.match(raw)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def measurement(value: Any, unit: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None
    number = _parse_value(value)
    raw = f"{value} {unit}".strip() if unit not in (None, "") else str(value)
    block: dict[str, Any] = {"raw": raw, "value": None, "unit": None, "basis": None}
    if number is None:
        block["status"] = "unparsed"
        return block
    if unit in (None, ""):
        block.update(value=number, status="no_unit")
        return block
    parsed, basis = _parse_unit(str(unit))
    block["basis"] = basis
    if parsed is None:
        block.update(value=number, status="unknown_unit")
        return block
    block.update(
        value=number * parsed.factor,
        unit=_BASE[parsed.dimension],
        dimension=parsed.dimension,
        status="normalized",
    )
    return block


def normalize_measurement(proposal: ProposedEntity) -> ProposedEntity:
    properties = proposal.properties
    block = measurement(properties.get("value"), properties.get("unit"))
    if block is None:
        properties.pop(MEASUREMENT_KEY, None)
    else:
        properties[MEASUREMENT_KEY] = block
    return proposal


def comparable(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two measurements can be compared only when both normalized into one
    dimension on the same basis; anything else would compare unlike things."""
    return (
        a.get("status") == "normalized"
        and b.get("status") == "normalized"
        and a.get("dimension") == b.get("dimension")
        and a.get("basis") == b.get("basis")
    )


__all__ = [
    "MEASUREMENT_KEY",
    "UNIT_TABLE",
    "comparable",
    "measurement",
    "normalize_measurement",
]
