"""What was used, in order — as data rather than as a sentence.

The pipeline already narrated itself, but only as log lines
(``[ontologylab] pubmed returned 12 result(s)``). A line is enough for a
scrolling console and not enough for the screen this product actually has:
the browser cannot group by tool, colour a failure, or collapse a finished
run into one row, because by the time the text arrives the structure is
gone. Re-parsing English prose in JavaScript to get it back is how that
kind of thing rots.

So the unit is a `Step`, and the log line is *derived from it*. That
direction matters. The obvious alternative — keep logging strings and
append a parallel list of structured events — is the duplicated-constant
bug this repo keeps finding: two writers, one of which someone forgets, and
nothing fails when they disagree. Here there is one writer. `Step.line` is
the only place a progress line is spelled, so a step that reaches the
browser and a line that reaches the job log cannot describe different work.

`detail` is deliberately narrow. It holds a count, a name, or a failure
*kind* — never an exception's text. Exception text in this codebase can
carry a request URL, and a request URL can carry an API key; that is why
`fetch_sources` reports `failure.kind` to the log and sends the exception
to provenance instead. A `Step` is shown on screen, so it inherits the
stricter of the two rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Long enough for a source name, a query, or a pack id; short enough that a
# step row stays one line on screen. Truncation is visible (…) rather than
# silent, because a cut-off detail that looks complete is a small lie.
MAX_DETAIL = 120

# How one (action, status) pair reads in the job log. The strings for
# `query` are load-bearing: they are what the Jobs screen has always shown
# and what `test_search_query.py` pins, so they are reproduced exactly.
_LINES: dict[tuple[str, str], str] = {
    ("query", "running"): "querying {tool}",
    ("query", "ok"): "{tool} returned {detail} result(s)",
    ("query", "failed"): "{tool} did not answer ({detail})",
    ("query", "skipped"): "{tool} skipped ({detail})",
    ("phase", "running"): "{detail} phase started",
    ("formulate", "ok"): "searching for: {detail}",
    ("formulate", "skipped"): "query not reformulated; {detail}",
    ("gather", "ok"): "collected {detail}",
    ("store", "ok"): "stored {detail}",
    ("extract", "ok"): "extraction done: {detail}",
}

_STATUSES = ("running", "ok", "failed", "skipped")


@dataclass(frozen=True)
class Step:
    """One thing that was used, and how it went.

    `tool` is the thing itself — a source name (`pubmed`), an engine
    (`claude`), the local store (`store`). `action` is what was asked of
    it. Both stay machine-readable: the browser owns the Korean, the same
    way it owns `PHASE_KO`, so the server never ships display text it would
    then have to keep in sync with the screen.
    """

    tool: str
    action: str
    status: str = "ok"
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(
                f"unknown step status {self.status!r}; expected one of "
                f"{', '.join(_STATUSES)}"
            )

    @property
    def shown_detail(self) -> str:
        text = " ".join(str(self.detail).split())
        return text if len(text) <= MAX_DETAIL else text[: MAX_DETAIL - 1] + "…"

    @property
    def line(self) -> str:
        """The job-log rendering. The only place a progress line is spelled."""
        template = _LINES.get((self.action, self.status))
        if template is None:
            detail = f" ({self.shown_detail})" if self.detail else ""
            template = f"{{tool}} {self.action} {self.status}{detail}"
        body = template.format(tool=self.tool, detail=self.shown_detail)
        return f"[ontologylab] {body}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "action": self.action,
            "status": self.status,
            "detail": self.shown_detail,
        }


def source_step(kind: str, source: str, detail: object) -> Step:
    """Translate a `fetch_sources` event into a step.

    `source_start` matters most: during a fan-out that can sit silent for
    thirty seconds it is the only evidence that anything is happening.
    """
    status = {
        "source_start": "running",
        "source_ok": "ok",
        "source_failed": "failed",
    }.get(kind)
    if status is None:
        # An event kind nobody has taught this function about still has to
        # surface — losing it would make the log quieter exactly when
        # something unexpected happened.
        return Step(tool=source, action=kind, status="ok", detail=str(detail))
    return Step(
        tool=source,
        action="query",
        status=status,
        detail="" if detail is None else str(detail),
    )
