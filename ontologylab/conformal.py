"""P4 — a triage line with a finite-sample guarantee, from review history.

The review queue is a calibration set nobody had to build: every approve
and reject is a human label sitting next to a critic score. Split conformal
prediction turns that into a threshold τ with a distribution-free
guarantee — **among items a human would reject, at most α slip above τ**
(marginally, under exchangeability of rejected-item scores):

    P( score(new rejection-worthy item) > τ ) ≤ α

τ is the ⌈(n+1)(1−α)⌉-th smallest critic score among the n *rejected*
items. Rejected scores are the nonconformity scores: the guarantee is about
how confidently a bad item can masquerade, so it is calibrated on the bad
items. Verified counts are reported for context but play no part in τ —
that asymmetry is the method, not an oversight.

What the threshold is FOR: ordering and badging the queue ("items above
the line are safe to review last"). What it is NOT for: approving. The
critic's hard boundary holds — there is no code path from any score,
conformal or otherwise, to a status change. Automation earns trust here by
quantifying its own error rate, not by taking the decision.

When rejections are scarce the answer is honestly "not yet": the guarantee
needs ⌈(n+1)(1−α)⌉ ≤ n, i.e. at least ⌈(1−α)/α⌉ rejected-and-scored items
(19 at α=0.05). Reporting a fake threshold before that would be worse than
none.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ontologylab.kgstore import KGStore

DEFAULT_ALPHA = 0.05

# Latest critic score per (kind, item), joined to the human decision.
# `status` is the label: verified = the human kept it, rejected = the human
# threw it out. Proposed items are the ones a threshold would triage, so
# they are excluded from calibration by construction.
_CALIBRATION_SQL = """
SELECT n.status AS status, c.score AS score
FROM {table} n
JOIN (
    SELECT kind, item_id, score,
           ROW_NUMBER() OVER (
               PARTITION BY kind, item_id ORDER BY created_ts DESC
           ) AS rn
    FROM critic_reviews
    WHERE kind = :kind
) c ON c.item_id = n.id AND c.rn = 1
WHERE n.status IN ('verified', 'rejected')
"""


class ConformalError(Exception):
    """Raised for invalid parameters (never for 'not enough data')."""


def minimum_rejected(alpha: float) -> int:
    """Smallest calibration size that can support a level-α guarantee."""
    return math.ceil((1.0 - alpha) / alpha)


@dataclass(frozen=True)
class Triage:
    """One computed triage line, or the honest absence of one."""

    available: bool
    alpha: float
    threshold: float | None
    n_rejected: int
    n_verified: int
    needed_rejected: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "alpha": self.alpha,
            "threshold": self.threshold,
            "n_rejected": self.n_rejected,
            "n_verified": self.n_verified,
            "needed_rejected": self.needed_rejected,
            "guarantee": (
                None
                if not self.available
                else (
                    f"P(critic score of a rejection-worthy item > "
                    f"{self.threshold}) <= {self.alpha} "
                    f"(split conformal, n={self.n_rejected})"
                )
            ),
        }


def calibration_scores(store: KGStore) -> tuple[list[float], list[float]]:
    """(rejected_scores, verified_scores) from reviewed, critic-scored items."""
    rejected: list[float] = []
    verified: list[float] = []
    for table, kind in (("nodes", "node"), ("edges", "edge")):
        for row in store.conn.execute(
            _CALIBRATION_SQL.format(table=table), {"kind": kind}
        ):
            (rejected if row["status"] == "rejected" else verified).append(
                float(row["score"])
            )
    return rejected, verified


def conformal_threshold(rejected_scores: list[float], alpha: float) -> float | None:
    """τ = the ⌈(n+1)(1−α)⌉-th smallest rejected score, or None if n is short.

    The rank comes from the split-conformal quantile: with n exchangeable
    calibration scores, a fresh score from the same distribution exceeds
    the k-th smallest with probability ≤ (n+1−k)/(n+1); k = ⌈(n+1)(1−α)⌉
    makes that bound ≤ α.
    """
    if not 0.0 < alpha < 1.0:
        raise ConformalError(f"alpha must be in (0, 1), got {alpha}")
    n = len(rejected_scores)
    k = math.ceil((n + 1) * (1.0 - alpha))
    if n == 0 or k > n:
        return None
    return sorted(rejected_scores)[k - 1]


def triage(store: KGStore, *, alpha: float = DEFAULT_ALPHA) -> Triage:
    """Compute the triage line for this store's review history."""
    rejected, verified = calibration_scores(store)
    threshold = conformal_threshold(rejected, alpha)
    return Triage(
        available=threshold is not None,
        alpha=alpha,
        threshold=threshold,
        n_rejected=len(rejected),
        n_verified=len(verified),
        needed_rejected=minimum_rejected(alpha),
    )


__all__ = [
    "DEFAULT_ALPHA",
    "ConformalError",
    "Triage",
    "calibration_scores",
    "conformal_threshold",
    "minimum_rejected",
    "triage",
]
