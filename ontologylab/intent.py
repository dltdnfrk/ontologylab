"""Read one sentence and name an action from a fixed table.

The model's job here is narrow on purpose: it picks a name out of
`ACTIONS` and fills a couple of validated parameters. It never returns
code, a URL, a SQL fragment, or a search query to run — so widening what a
sentence can reach is an edit to this table, visible in review, rather than
an emergent property of a prompt.

That matters because chat moved work behind a sentence. On every other
screen the person clicks a control that exists; here they type prose and
something happens. The table is what keeps "something" enumerable.

Mutating actions are marked `confirm=True` and are *not* run by
classification. They come back needing a second, explicit request. Chat
moves the asking into a sentence, not the deciding.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ontologylab.engines import INTENT_MARKER_CLOSE, INTENT_MARKER_OPEN


@dataclass(frozen=True)
class Action:
    """One thing a sentence is allowed to reach.

    `summary` is English because it is also the machine-facing catalogue —
    `help` lists these, and the MCP surface reads the same table. The
    browser owns any Korean the person actually reads.
    """

    summary: str
    # True only for actions that change something a person would not want
    # changed by a misread sentence. Read-only actions are safe to run on a
    # classification alone; these are not.
    confirm: bool = False
    # Parameter names this action accepts. Anything else the model invents
    # is dropped rather than passed through — an unknown key reaching a
    # handler is how a prompt starts choosing arguments.
    params: tuple[str, ...] = ()


ACTIONS: dict[str, Action] = {
    "research": Action(
        "Search the paper sources for a topic and extract proposals",
        params=("topic",),
    ),
    "show_review": Action("Open the review queue"),
    "show_graph": Action("Open the knowledge graph"),
    "show_packs": Action("List built packs"),
    "show_sources": Action("List collected documents"),
    "search_entities": Action(
        "Search the graph for an entity by name", params=("query",)
    ),
    "enrich": Action("Look verified entities up in the curated resources"),
    "build_pack": Action(
        "Build a knowledge pack from everything approved",
        confirm=True,
        params=("name",),
    ),
    "status": Action("Report what is in the store right now"),
    "help": Action("Explain what can be asked"),
    "unknown": Action("Nothing matched; list what can be asked"),
}


def requires_confirmation(action: str) -> bool:
    """Whether this action must be asked about before it runs.

    Reads `ACTIONS` at call time rather than a frozen snapshot taken at
    import. A module-level `CONFIRM_REQUIRED = frozenset(...)` was the first
    shape of this and it tested green against a hand-typed set: with exactly
    one mutating action, "the set of confirming actions" and "a set
    containing build_pack" are the same value, so the test could not tell a
    re-derivation from a copy. Adding an action would then quietly not be
    gated.
    """
    entry = ACTIONS.get(action)
    return bool(entry and entry.confirm)


@dataclass
class Intent:
    """How one message was read."""

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    # The model's one-line restatement, shown back to the person. A misread
    # is only correctable if it is visible.
    reading: str = ""
    # Set when classification itself failed. Carries the reason for the log,
    # never for the screen — see `routes.chat`.
    error: Optional[str] = None

    @property
    def needs_confirmation(self) -> bool:
        return requires_confirmation(self.action)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "params": dict(self.params),
            "reading": self.reading,
            "needs_confirmation": self.needs_confirmation,
        }


_PROMPT = """You route one message to exactly one action.

Actions:
{catalogue}

Reply with ONLY a JSON object, no prose and no code fence:
{{"action": "<one name from the list>", "params": {{...}}, "reading": "<one short sentence, in the user's language, restating what they asked for>"}}

Rules:
- `action` MUST be one of the names above. If nothing fits, use "unknown".
- `params` may only contain the keys listed for that action. Omit it if there are none.
- `reading` restates the request; it never promises a result.

{open_marker}
{message}
{close_marker}
"""


def _catalogue() -> str:
    lines = []
    for name, action in ACTIONS.items():
        if name == "unknown":
            continue
        keys = f"  params: {', '.join(action.params)}" if action.params else ""
        lines.append(f"- {name}: {action.summary}{keys}")
    return "\n".join(lines)


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """Pull the object out of a reply that may be wrapped.

    Engines here are CLI-backed and sometimes fence their output or add a
    line before it. Refusing anything but a bare object would turn a
    cosmetic difference into "I didn't understand you".
    """
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _clean_params(action: str, raw: Any) -> dict[str, Any]:
    """Keep only the keys this action declares, as strings.

    The model does not get to invent argument names. A stray key here is
    the difference between "the table decides what chat can reach" and "the
    prompt does".
    """
    allowed = ACTIONS[action].params
    if not allowed or not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in allowed:
        value = raw.get(key)
        if value is None:
            continue
        text = " ".join(str(value).split())
        if text:
            out[key] = text
    return out


async def classify(
    message: str, engine: Any, model: Optional[str] = None
) -> Intent:
    """Read `message` and return the action it names.

    Never raises: a failure to classify is an `Intent` carrying `error`, so
    the caller can answer with something rather than a 500. The reason
    reaches the log; the screen gets the outcome only.
    """
    prompt = _PROMPT.format(
        catalogue=_catalogue(),
        message=message.strip(),
        open_marker=INTENT_MARKER_OPEN,
        close_marker=INTENT_MARKER_CLOSE,
    )
    try:
        text, _usage = await engine.generate(prompt, model=model)
    except Exception as exc:  # engine failure is an answer, not a crash
        return Intent("unknown", error=f"{type(exc).__name__}: {exc}")

    parsed = _extract_json(text)
    if parsed is None:
        return Intent("unknown", error="the engine did not return an object")

    action = str(parsed.get("action", "")).strip()
    if action not in ACTIONS:
        # An invented name is the same outcome as no match, but it is worth
        # keeping the name in the log — a model reaching for an action that
        # does not exist is a signal about what people are trying to do.
        return Intent("unknown", error=f"unknown action {action!r}")

    reading = " ".join(str(parsed.get("reading", "")).split())
    return Intent(
        action=action,
        params=_clean_params(action, parsed.get("params")),
        reading=reading,
    )
