"""Calibration of extractor confidence against review outcomes.

The extractor attaches a ``confidence`` to every proposal, and until now
the system only clamped it to 0..1 — there was no evidence that a 0.9
meant anything. LLM confidences are notoriously miscalibrated (Guo et al.
2017 measured exactly this failure in modern networks), and this pipeline
sits on the one asset that fixes it for free: the review queue. Every
approve/reject is a label next to the confidence the extractor claimed.

Two tools, both stdlib:

- **ECE** (expected calibration error): bin reviewed items by claimed
  confidence, compare each bin's claimed mean to its observed approval
  rate, weight by bin size. This is the *measurement* — it says how wrong
  the raw confidences are, in units of probability.
- **Isotonic regression** via pool-adjacent-violators (PAVA): the standard
  non-parametric recalibration map. It learns a monotone step function
  from claimed confidence to observed approval rate — monotone because a
  calibrator that could *reverse* the extractor's ranking would be
  claiming to know more than the data does.

Boundaries, same shape as the critic's and the conformal line's:
calibrated values order and annotate the queue; nothing here writes to
``nodes``/``edges``, and stored confidences are never rewritten — the
extractor's claim is provenance, the calibrated view is derived.

The honest caveat: an isotonic fit evaluated on its own training data
looks better than it is. This module reports raw ECE (unbiased — no
fitting involved) and exposes the fitted curve; a held-out calibrated ECE
would need more review history than a young store has, so it is not
reported at all rather than reported optimistically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ontologylab.kgstore import KGStore

ECE_BINS = 10

# Below this many reviewed items a curve is astrology; report the data
# count and decline to fit. 20 gives each of two labels a fighting chance
# to appear across the confidence range.
MIN_CALIBRATION_ITEMS = 20

_CONFIDENCE_SQL = """
SELECT confidence, status FROM {table}
WHERE status IN ('verified', 'rejected') AND confidence IS NOT NULL
"""


def review_outcomes(store: KGStore) -> list[tuple[float, int]]:
    """(claimed confidence, human label) for every reviewed item.

    Label 1 = verified, 0 = rejected. Nodes and edges pool together: the
    extractor's confidence scale is shared, and splitting would halve an
    already-small calibration set.
    """
    pairs: list[tuple[float, int]] = []
    for table in ("nodes", "edges"):
        for row in store.conn.execute(_CONFIDENCE_SQL.format(table=table)):
            pairs.append(
                (float(row["confidence"]), 1 if row["status"] == "verified" else 0)
            )
    return pairs


def expected_calibration_error(
    pairs: list[tuple[float, int]], *, n_bins: int = ECE_BINS
) -> dict[str, Any]:
    """ECE over equal-width bins, with the per-bin table for a reliability plot.

    ECE = Σ_b (n_b / N) · |mean claimed_b − observed approval rate_b|.
    0 means the claimed numbers are exactly as good as they say; 0.2 means
    a claimed 0.9 is, on average, a 0.7.
    """
    bins: list[dict[str, Any]] = [
        {"low": b / n_bins, "high": (b + 1) / n_bins, "count": 0,
         "claimed_sum": 0.0, "approved": 0}
        for b in range(n_bins)
    ]
    for confidence, label in pairs:
        index = min(int(confidence * n_bins), n_bins - 1)
        bins[index]["count"] += 1
        bins[index]["claimed_sum"] += confidence
        bins[index]["approved"] += label

    total = len(pairs)
    ece = 0.0
    table: list[dict[str, Any]] = []
    for entry in bins:
        if entry["count"] == 0:
            continue
        claimed = entry["claimed_sum"] / entry["count"]
        observed = entry["approved"] / entry["count"]
        ece += (entry["count"] / total) * abs(claimed - observed)
        table.append(
            {
                "low": round(entry["low"], 2),
                "high": round(entry["high"], 2),
                "count": entry["count"],
                "claimed": round(claimed, 4),
                "observed": round(observed, 4),
            }
        )
    return {"ece": round(ece, 4) if total else None, "n": total, "bins": table}


@dataclass(frozen=True)
class IsotonicCalibrator:
    """A monotone step function: claimed confidence → calibrated probability.

    ``boundaries[i]`` is the smallest claimed confidence of block i;
    ``values[i]`` is that block's pooled approval rate. Blocks are strictly
    increasing in value by PAVA construction.
    """

    boundaries: tuple[float, ...]
    values: tuple[float, ...]

    def predict(self, confidence: float) -> float:
        result = self.values[0]
        for boundary, value in zip(self.boundaries, self.values):
            if confidence >= boundary:
                result = value
            else:
                break
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundaries": [round(b, 4) for b in self.boundaries],
            "values": [round(v, 4) for v in self.values],
        }


def fit_isotonic(pairs: list[tuple[float, int]]) -> IsotonicCalibrator:
    """Pool-adjacent-violators over (confidence, label), ascending.

    Walk the labels in confidence order; whenever a block's mean fails to
    exceed its predecessor's, merge them. What survives is the least-squares
    monotone fit — the classical PAVA result, no solver needed.
    """
    if not pairs:
        raise ValueError("cannot calibrate on an empty set")
    ordered = sorted(pairs)
    # Exact ties pool FIRST. Isotonic regression cannot order equal inputs,
    # and skipping this step let `sorted` arrange tied confidences by label
    # (all rejects before all approves), which PAVA then read as a perfectly
    # increasing pair of blocks — one x mapped to two values, and an
    # extractor that claimed 0.9 everywhere came out "calibrated" at 1.0
    # instead of its true approval rate. Caught by the test that stages
    # exactly that extractor.
    tied: list[list[float]] = []  # [label_sum, count, confidence]
    for confidence, label in ordered:
        if tied and tied[-1][2] == confidence:
            tied[-1][0] += float(label)
            tied[-1][1] += 1.0
        else:
            tied.append([float(label), 1.0, confidence])

    # Each block: [label_sum, count, smallest_confidence]
    blocks: list[list[float]] = []
    for label_sum, count, confidence in tied:
        blocks.append([label_sum, count, confidence])
        while (
            len(blocks) >= 2
            and blocks[-2][0] / blocks[-2][1] >= blocks[-1][0] / blocks[-1][1]
        ):
            merged_sum, merged_count, _ = blocks.pop()
            blocks[-1][0] += merged_sum
            blocks[-1][1] += merged_count
    return IsotonicCalibrator(
        boundaries=tuple(block[2] for block in blocks),
        values=tuple(block[0] / block[1] for block in blocks),
    )


def calibration_report(store: KGStore) -> dict[str, Any]:
    """Raw ECE + the fitted curve, or an honest refusal on thin data."""
    pairs = review_outcomes(store)
    report: dict[str, Any] = {
        "n": len(pairs),
        "min_required": MIN_CALIBRATION_ITEMS,
        "available": len(pairs) >= MIN_CALIBRATION_ITEMS,
        "raw": expected_calibration_error(pairs),
        "curve": None,
    }
    if report["available"]:
        report["curve"] = fit_isotonic(pairs).to_dict()
    return report


__all__ = [
    "ECE_BINS",
    "MIN_CALIBRATION_ITEMS",
    "IsotonicCalibrator",
    "calibration_report",
    "expected_calibration_error",
    "fit_isotonic",
    "review_outcomes",
]
