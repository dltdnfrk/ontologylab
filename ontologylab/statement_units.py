"""Deterministic statement-unit enumerator for the statement harness.

``rules_version`` is ``units-v1``. Offsets are zero-based half-open Python
character offsets into the unchanged text. Every eligible Results, Discussion,
or Conclusion sentence is kept, including a sentence with no cue. Explicit arm
and result slots are emitted only when the wording assigns them. A coordinated
list without that assignment is one unresolved unit. ``unit_id`` is the SHA-256
of the contract's pipe-joined identity. This module does not call a model and
does not write ``verified``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final, Literal, assert_never

RULES_VERSION: Final = "units-v1"
_ELIGIBLE: Final = frozenset({"results", "discussion", "conclusion"})
_LABELS: Final = _ELIGIBLE | {"methods", "section_unresolved"}
_FUNCTION_WORDS: Final = frozenset({
    "the", "a", "an", "these", "those", "was", "were", "after", "and", "or",
    "reduced", "reduce", "left", "lost", "increased", "did", "may", "might", "could",
})
_ENDPOINT_WORD: Final = (
    r"(?!relative\b|and\b|or\b|whereas\b|however\b|respectively\b|"
    r"after\b|to\b|but\b|than\b|untreated\b|plots\b)[a-z]+"
)
_SUPPORTS_TOKENS: Final = ("reduced", "lost cover", "increased")
_NULL_TOKENS: Final = ("did not", "unchanged", "not significantly", "ineffective")
_PRONOUNS: Final = frozenset({"It", "They", "This", "These"})

# A genus abbreviation such as "P. annua" is not a sentence boundary. Removing
# this pattern splits the sentence after "P.".
_GENUS_PERIOD: Final = re.compile(r"(?<![A-Za-z])[A-Z]\.(?=\s+[a-z])")
_DECIMAL_PERIOD: Final = re.compile(r"\d\.\d")
_DOSE_ABBREV_PERIOD: Final = re.compile(r"\ba\.i\.")
_OTHER_ABBREV_PERIOD: Final = re.compile(
    r"\b(?:e\.g\.|i\.e\.|et al\.|Fig\.|vs\.|cf\.|Dr\.|No\.|Mr\.|Mrs\.|St\.)",
)
_PROTECTED_PERIODS: Final = (
    _GENUS_PERIOD,
    _DECIMAL_PERIOD,
    _DOSE_ABBREV_PERIOD,
    _OTHER_ABBREV_PERIOD,
)
_SENTENCE_PUNCT: Final = frozenset(".!?。！？")
_GENUS_SPAN: Final = re.compile(r"(?<![A-Za-z])[A-Z]\.\s+[a-z][a-z-]+")
_DOSE: Final = re.compile(
    r"\b\d+(?:\.\d+)?\s+(?:kg|g|mg|ug|µg|l|L|mL|ha|%|ppm)"
    r"(?:/[A-Za-z]+)?(?:\s+a\.i\./[A-Za-z]+)?",
)
_RESULT: Final = re.compile(
    rf"did not reduce(?:\s+[A-Z]\.\s+[a-z]+)?(?:\s+{_ENDPOINT_WORD}){{0,2}}"
    rf"|left\s+[a-z]+\s+unchanged"
    rf"|lost cover"
    rf"|reduced(?:\s+[A-Z]\.\s+[a-z]+)?(?:\s+{_ENDPOINT_WORD}){{0,2}}"
    rf"|reduce(?:\s+[A-Z]\.\s+[a-z]+)?(?:\s+{_ENDPOINT_WORD}){{0,2}}"
    rf"|increased(?:\s+{_ENDPOINT_WORD}){{0,2}}",
)
_OUTCOME_START: Final = re.compile(
    r"\b(?:did not reduce|reduced|reduce|left|lost|increased)\b",
)
_MIXTURE: Final = re.compile(
    r"\btank mixture of\s+[A-Za-z0-9-]+(?:\s+plus\s+[A-Za-z0-9-]+)+",
)
_HEDGE: Final = re.compile(r"\b(?:may|might|could)\b", re.IGNORECASE)
_PSEUDO_CUE: Final = re.compile(r"\bnot only\b", re.IGNORECASE)
_CONTRAST_WORD: Final = re.compile(
    r"\b(?:whereas|however|respectively)\b",
    re.IGNORECASE,
)
_CONTRAST_SPLIT: Final = re.compile(r"\b(?:whereas|however)\b", re.IGNORECASE)
_PREDICATE: Final = re.compile(
    r"\b(?:were associated|was associated|did not reduce|did not|"
    r"may|might|could|reduced|reduce|left|lost|increased|"
    r"was sprayed|were sprayed|was not only|were not only)\b",
    re.IGNORECASE,
)
_LEADING_NAME: Final = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)\b")
_PRONOUN: Final = re.compile(r"^\s*(It|They|This|These)\b")
_AFTER_ARM: Final = re.compile(
    r"\bafter\s+([A-Za-z][A-Za-z0-9-]*)\b(?=\s+relative\s+to\b)",
)
_NAME: Final = re.compile(r"\b[A-Z][A-Za-z0-9-]*\b")
_BARE_NAME: Final = re.compile(r"[A-Za-z][A-Za-z0-9-]*")

SectionLabel = Literal[
    "results",
    "discussion",
    "conclusion",
    "methods",
    "section_unresolved",
]
UnitKind = Literal["explicit", "unresolved", "sentence", "section_unresolved"]
Polarity = Literal["supports", "no_effect", "refutes"]
MarkRole = Literal[
    "dose",
    "contrast",
    "hedge",
    "pseudo_cue",
    "protected_abbreviation",
    "unresolved",
    "context",
    "antecedent",
    "asserting_sentence",
]


class UnitContractError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class SectionSpan:
    section: SectionLabel
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.section not in _LABELS:
            raise UnitContractError("section_label", str(self.section))
        if type(self.start) is not int or type(self.end) is not int:
            raise UnitContractError("section_bounds", f"{self.start}:{self.end}")
        if self.start < 0 or self.start >= self.end:
            raise UnitContractError("section_bounds", f"{self.start}:{self.end}")


@dataclass(frozen=True, slots=True)
class ArmSlot:
    quote: str
    start: int
    end: int
    role: Literal["arm"]
    arm: str
    polarity: Polarity | None


@dataclass(frozen=True, slots=True)
class ResultSlot:
    quote: str
    start: int
    end: int
    role: Literal["result"]
    arm: str


@dataclass(frozen=True, slots=True)
class MarkSlot:
    quote: str
    start: int
    end: int
    role: MarkRole


Slot = ArmSlot | ResultSlot | MarkSlot


@dataclass(frozen=True, slots=True)
class SourceUnit:
    unit_id: str
    sentence_id: str
    source_sha256: str
    rules_version: str
    section: SectionLabel
    kind: UnitKind
    sentence_start: int
    sentence_end: int
    assertion_start: int
    assertion_end: int
    arm_anchor: str
    result_anchor: str
    context_spans: tuple[tuple[int, int], ...]
    slots: tuple[Slot, ...]


@dataclass(frozen=True, slots=True)
class _Assignment:
    arm_start: int
    arm_end: int
    result_start: int
    result_end: int
    polarity: Polarity | None


@dataclass(frozen=True, slots=True)
class _Explicit:
    assignments: tuple[_Assignment, ...]


@dataclass(frozen=True, slots=True)
class _Unresolved:
    pass


@dataclass(frozen=True, slots=True)
class _Plain:
    pass


_Decision = _Explicit | _Unresolved | _Plain


def enumerate_units(
    text: str,
    section_spans: tuple[SectionSpan, ...] | list[SectionSpan],
    *,
    source_sha256: str,
    rules_version: str,
) -> tuple[SourceUnit, ...]:
    """Return source units in document order.

    ``source_sha256`` must be the lowercase SHA-256 hex digest of
    ``text.encode("utf-8")``. ``rules_version`` must be ``units-v1``.
    Methods text is omitted. Missing or ``section_unresolved`` headings are
    recorded and are not turned into a negative claim.
    """

    digest = _require_source_hash(text, source_sha256)
    version = _require_rules_version(rules_version)
    sections = _require_sections(text, tuple(section_spans))
    units: list[SourceUnit] = []
    cursor = 0
    for section in sections:
        if section.start > cursor and text[cursor:section.start].strip():
            units.append(_heading_unit(text, cursor, section.start, digest, version))
        units.extend(_units_in_section(text, section, digest, version))
        cursor = section.end
    if cursor < len(text) and text[cursor:].strip():
        units.append(_heading_unit(text, cursor, len(text), digest, version))
    return tuple(units)


def _require_source_hash(text: str, source_sha256: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if source_sha256 != digest:
        raise UnitContractError(
            "source_sha256",
            "document hash does not match the unchanged text",
        )
    return digest


def _require_rules_version(rules_version: str) -> str:
    if rules_version != RULES_VERSION:
        raise UnitContractError("rules_version", rules_version)
    return rules_version


def _require_sections(
    text: str,
    spans: tuple[SectionSpan, ...],
) -> tuple[SectionSpan, ...]:
    previous = 0
    for span in spans:
        if span.start > len(text) or span.end > len(text):
            raise UnitContractError("section_bounds", f"{span.start}:{span.end}")
        if span.start < previous:
            raise UnitContractError(
                "section_order",
                f"{span.start} overlaps or precedes {previous}",
            )
        previous = span.end
    return spans


def _units_in_section(
    text: str,
    section: SectionSpan,
    digest: str,
    version: str,
) -> tuple[SourceUnit, ...]:
    label = section.section
    match label:
        case "methods":
            return ()
        case "section_unresolved":
            return (_heading_unit(text, section.start, section.end, digest, version),)
        case "results" | "discussion" | "conclusion":
            return _eligible_units(text, section, digest, version)
        case unreachable:
            assert_never(unreachable)


def _eligible_units(
    text: str,
    section: SectionSpan,
    digest: str,
    version: str,
) -> tuple[SourceUnit, ...]:
    units: list[SourceUnit] = []
    previous: tuple[int, int] | None = None
    for start, end, table in _line_spans(text, section.start, section.end):
        if table:
            units.append(_unresolved_sentence(
                text, start, end, section.section, digest, version,
            ))
            previous = None
            continue
        for sentence_start, sentence_end in _sentence_spans(text[start:end], start):
            built = _units_for_sentence(
                text,
                sentence_start,
                sentence_end,
                previous,
                section.section,
                digest,
                version,
            )
            units.extend(built)
            previous = (sentence_start, sentence_end)
    return tuple(units)


def _line_spans(
    text: str,
    start: int,
    end: int,
) -> tuple[tuple[int, int, bool], ...]:
    spans: list[tuple[int, int, bool]] = []
    cursor = start
    while cursor < end:
        newline = text.find("\n", cursor, end)
        line_end = end if newline < 0 else newline
        if cursor < line_end and text[cursor:line_end].strip():
            line = text[cursor:line_end]
            table = "\t" in line or line.count("|") >= 2
            spans.append((cursor, line_end, table))
        if newline < 0:
            break
        cursor = newline + 1
    return tuple(spans)


def _sentence_spans(text: str, base: int) -> tuple[tuple[int, int], ...]:
    protected = _protected_period_indexes(text)
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        boundary = (
            char in _SENTENCE_PUNCT
            and index not in protected
            and (index + 1 >= len(text) or text[index + 1].isspace())
        )
        if not boundary:
            index += 1
            continue
        end = index + 1
        if start < end:
            spans.append((base + start, base + end))
        next_start = end
        while next_start < len(text) and text[next_start].isspace():
            next_start += 1
        start = next_start
        index = next_start
    if start < len(text):
        spans.append((base + start, base + len(text)))
    return tuple(spans)


def _protected_period_indexes(text: str) -> frozenset[int]:
    indexes: set[int] = set()
    for pattern in _PROTECTED_PERIODS:
        for match in pattern.finditer(text):
            for offset, char in enumerate(match.group()):
                if char == ".":
                    indexes.add(match.start() + offset)
    return frozenset(indexes)


def _units_for_sentence(
    text: str,
    start: int,
    end: int,
    previous: tuple[int, int] | None,
    section: SectionLabel,
    digest: str,
    version: str,
) -> tuple[SourceUnit, ...]:
    sentence = text[start:end]
    decision = _classify(sentence)
    match decision:
        case _Explicit(assignments):
            return _explicit_units(
                text, start, end, assignments, previous, section, digest, version,
            )
        case _Unresolved():
            return (_unresolved_sentence(text, start, end, section, digest, version),)
        case _Plain():
            return (_plain_sentence(
                text, start, end, section, digest, version,
            ),)
        case unreachable:
            assert_never(unreachable)


def _classify(sentence: str) -> _Decision:
    if _MIXTURE.search(sentence) is not None:
        assignment = _parse_single(sentence)
        if assignment is None:
            return _Unresolved()
        return _Explicit((assignment,))
    if re.search(r"\brespectively\b", sentence, re.IGNORECASE) is not None:
        parsed = _parse_respectively(sentence)
        if parsed is None:
            return _Unresolved()
        return _Explicit(parsed)
    if _CONTRAST_SPLIT.search(sentence) is not None:
        parsed = _parse_contrast(sentence)
        if parsed is None:
            return _Unresolved()
        return _Explicit(parsed)
    if _coordinated_subject(sentence):
        return _Unresolved()
    parsed = _parse_and_clauses(sentence)
    if parsed is not None:
        return _Explicit(parsed)
    assignment = _parse_single(sentence)
    if assignment is None:
        return _Plain()
    return _Explicit((assignment,))


def _coordinated_subject(sentence: str) -> bool:
    if _MIXTURE.search(sentence) is not None:
        return False
    predicate = _PREDICATE.search(sentence)
    head = sentence if predicate is None else sentence[:predicate.start()]
    names = [
        part for part in _split_coordination(head)
        if _BARE_NAME.fullmatch(part) is not None
    ]
    return len(names) >= 2


def _split_coordination(text: str) -> tuple[str, ...]:
    normalized = re.sub(r"\s+\band\b\s+", ", ", text.strip(), flags=re.IGNORECASE)
    normalized = re.sub(r"\s+\bor\b\s+", ", ", normalized, flags=re.IGNORECASE)
    parts = [part.strip() for part in normalized.split(",")]
    return tuple(part for part in parts if part and part.lower() not in {"and", "or"})


def _parse_respectively(sentence: str) -> tuple[_Assignment, ...] | None:
    marker = re.search(r",\s+respectively\b", sentence, re.IGNORECASE)
    if marker is None:
        return None
    body = sentence[:marker.start()]
    outcome = _OUTCOME_START.search(body)
    if outcome is None:
        return None
    arms = _split_coordination(body[:outcome.start()])
    results = _split_coordination(body[outcome.start():])
    if len(arms) < 2 or len(arms) != len(results):
        return None
    if any(_BARE_NAME.fullmatch(arm) is None for arm in arms):
        return None
    if any(_RESULT.fullmatch(result) is None for result in results):
        return None
    assignments: list[_Assignment] = []
    arm_from = 0
    result_from = outcome.start()
    for arm, result in zip(arms, results, strict=True):
        arm_at = sentence.find(arm, arm_from)
        result_at = sentence.find(result, result_from)
        if arm_at < 0 or result_at < 0:
            return None
        polarity = _polarity(result, hedged=False)
        if polarity is None:
            return None
        assignments.append(_Assignment(
            arm_at, arm_at + len(arm), result_at, result_at + len(result), polarity,
        ))
        arm_from = arm_at + len(arm)
        result_from = result_at + len(result)
    return tuple(assignments)


def _parse_contrast(sentence: str) -> tuple[_Assignment, ...] | None:
    if _PSEUDO_CUE.search(sentence) is not None:
        return None
    parts = _CONTRAST_SPLIT.split(sentence)
    if len(parts) < 2:
        return None
    assignments: list[_Assignment] = []
    cursor = 0
    for clause in parts:
        local = sentence.find(clause, cursor)
        if local < 0:
            return None
        cursor = local + len(clause)
        if not clause.strip():
            return None
        assignment = _parse_single(clause)
        if assignment is None:
            return None
        assignments.append(_Assignment(
            local + assignment.arm_start,
            local + assignment.arm_end,
            local + assignment.result_start,
            local + assignment.result_end,
            assignment.polarity,
        ))
    if len(assignments) < 2:
        return None
    return tuple(assignments)


def _parse_and_clauses(sentence: str) -> tuple[_Assignment, ...] | None:
    if re.search(r"\band\b", sentence, re.IGNORECASE) is None:
        return None
    parts = re.split(r"\band\b", sentence, flags=re.IGNORECASE)
    if len(parts) < 2:
        return None
    assignments: list[_Assignment] = []
    cursor = 0
    for clause in parts:
        local = sentence.find(clause, cursor)
        if local < 0 or not clause.strip():
            return None
        cursor = local + len(clause)
        assignment = _parse_single(clause)
        if assignment is None:
            return None
        assignments.append(_Assignment(
            local + assignment.arm_start,
            local + assignment.arm_end,
            local + assignment.result_start,
            local + assignment.result_end,
            assignment.polarity,
        ))
    if len(assignments) < 2:
        return None
    return tuple(assignments)


def _parse_single(clause: str) -> _Assignment | None:
    result = _RESULT.search(clause)
    if result is None:
        return None
    arm = _arm_in_clause(clause, result)
    if arm is None:
        return None
    arm_start, arm_end = arm
    hedged = _HEDGE.search(clause[:result.end()]) is not None
    polarity = _polarity(result.group(), hedged=hedged)
    if polarity is None and not hedged:
        return None
    return _Assignment(arm_start, arm_end, result.start(), result.end(), polarity)


def _arm_in_clause(clause: str, result: re.Match[str]) -> tuple[int, int] | None:
    mixture = _MIXTURE.search(clause)
    if mixture is not None and mixture.start() < result.start():
        return mixture.start(), mixture.end()
    pronoun = _PRONOUN.match(clause)
    if pronoun is not None:
        return pronoun.start(1), pronoun.end(1)
    leading = _LEADING_NAME.match(clause)
    if (
        leading is not None
        and leading.group(1).lower() not in _FUNCTION_WORDS
        and leading.end(1) <= result.start()
    ):
        return leading.start(1), leading.end(1)
    after = _AFTER_ARM.search(clause)
    if after is not None and after.start() >= result.end():
        return after.start(1), after.end(1)
    return None


def _polarity(result_quote: str, *, hedged: bool) -> Polarity | None:
    if hedged:
        return None
    if any(token in result_quote for token in _NULL_TOKENS):
        return "no_effect"
    if any(token in result_quote for token in _SUPPORTS_TOKENS):
        return "supports"
    return None


def _explicit_units(
    text: str,
    start: int,
    end: int,
    assignments: tuple[_Assignment, ...],
    previous: tuple[int, int] | None,
    section: SectionLabel,
    digest: str,
    version: str,
) -> tuple[SourceUnit, ...]:
    absolute = tuple(_shift(item, start) for item in assignments)
    link = _link_slots(text, start, end, absolute, previous)
    shared = _shared_slots(text, start, end, absolute)
    units: list[SourceUnit] = []
    for index, assignment in enumerate(absolute):
        slots: list[Slot] = []
        if index == 0:
            slots.extend(link)
            slots.extend(shared)
        slots.append(_arm_slot(text, assignment))
        slots.append(_result_slot(text, assignment))
        context_spans: tuple[tuple[int, int], ...] = ()
        if link and previous is not None:
            context_spans = (previous,)
        units.append(_unit(
            digest,
            version,
            section,
            "explicit",
            (start, end),
            (start, end),
            (assignment.arm_start, assignment.arm_end),
            (assignment.result_start, assignment.result_end),
            context_spans,
            tuple(slots),
        ))
    return tuple(units)


def _shift(item: _Assignment, origin: int) -> _Assignment:
    return _Assignment(
        item.arm_start + origin,
        item.arm_end + origin,
        item.result_start + origin,
        item.result_end + origin,
        item.polarity,
    )


def _link_slots(
    text: str,
    start: int,
    end: int,
    assignments: tuple[_Assignment, ...],
    previous: tuple[int, int] | None,
) -> tuple[MarkSlot, ...]:
    if previous is None or not _adjacent(text, previous, (start, end)):
        return ()
    if not assignments or text[assignments[0].arm_start:assignments[0].arm_end] not in _PRONOUNS:
        return ()
    antecedent = _antecedent(text, previous[0], previous[1])
    if antecedent is None:
        return ()
    antecedent_start, antecedent_end = antecedent
    return (
        _mark(text, previous[0], previous[1], "context"),
        _mark(text, antecedent_start, antecedent_end, "antecedent"),
        _mark(text, start, end, "asserting_sentence"),
    )


def _adjacent(
    text: str,
    previous: tuple[int, int],
    sentence: tuple[int, int],
) -> bool:
    return text[previous[1]:sentence[0]].strip() == ""


def _antecedent(text: str, start: int, end: int) -> tuple[int, int] | None:
    sentence = text[start:end]
    mixture = _MIXTURE.search(sentence)
    if mixture is not None:
        return start + mixture.start(), start + mixture.end()
    name = _NAME.search(sentence)
    if name is None:
        return None
    return start + name.start(), start + name.end()


def _shared_slots(
    text: str,
    start: int,
    end: int,
    assignments: tuple[_Assignment, ...],
) -> tuple[MarkSlot, ...]:
    covers = [(item.arm_start, item.arm_end) for item in assignments]
    covers.extend((item.result_start, item.result_end) for item in assignments)
    doses = _marked(text, start, end, _DOSE, "dose")
    covers.extend((slot.start, slot.end) for slot in doses)
    genus = tuple(
        slot for slot in _marked(text, start, end, _GENUS_SPAN, "protected_abbreviation")
        if not any(outer_start <= slot.start and slot.end <= outer_end for outer_start, outer_end in covers)
    )
    return (
        *genus,
        *doses,
        *_marked(text, start, end, _HEDGE, "hedge"),
        *_marked(text, start, end, _PSEUDO_CUE, "pseudo_cue"),
        *_marked(text, start, end, _CONTRAST_WORD, "contrast"),
    )


def _marked(
    text: str,
    start: int,
    end: int,
    pattern: re.Pattern[str],
    role: MarkRole,
) -> tuple[MarkSlot, ...]:
    sentence = text[start:end]
    return tuple(
        _mark(text, start + match.start(), start + match.end(), role)
        for match in pattern.finditer(sentence)
    )


def _arm_slot(text: str, assignment: _Assignment) -> ArmSlot:
    quote = text[assignment.arm_start:assignment.arm_end]
    return ArmSlot(
        quote, assignment.arm_start, assignment.arm_end, "arm", quote, assignment.polarity,
    )


def _result_slot(text: str, assignment: _Assignment) -> ResultSlot:
    quote = text[assignment.result_start:assignment.result_end]
    arm = text[assignment.arm_start:assignment.arm_end]
    return ResultSlot(
        quote, assignment.result_start, assignment.result_end, "result", arm,
    )


def _plain_sentence(
    text: str,
    start: int,
    end: int,
    section: SectionLabel,
    digest: str,
    version: str,
) -> SourceUnit:
    slots = _marked(text, start, end, _DOSE, "dose")
    return _unit(
        digest, version, section, "sentence",
        (start, end), (start, end), None, None, (), slots,
    )


def _unresolved_sentence(
    text: str,
    start: int,
    end: int,
    section: SectionLabel,
    digest: str,
    version: str,
) -> SourceUnit:
    return _unit(
        digest, version, section, "unresolved",
        (start, end), (start, end), None, None, (),
        (_mark(text, start, end, "unresolved"),),
    )


def _heading_unit(
    text: str,
    start: int,
    end: int,
    digest: str,
    version: str,
) -> SourceUnit:
    return _unit(
        digest, version, "section_unresolved", "section_unresolved",
        (start, end), (start, end), None, None, (), (),
    )


def _unit(
    digest: str,
    version: str,
    section: SectionLabel,
    kind: UnitKind,
    sentence: tuple[int, int],
    assertion: tuple[int, int],
    arm: tuple[int, int] | None,
    result: tuple[int, int] | None,
    context_spans: tuple[tuple[int, int], ...],
    slots: tuple[Slot, ...],
) -> SourceUnit:
    arm_anchor = "" if arm is None else f"{arm[0]}:{arm[1]}"
    result_anchor = "" if result is None else f"{result[0]}:{result[1]}"
    return SourceUnit(
        unit_id=_unit_id(digest, version, assertion, arm_anchor, result_anchor),
        sentence_id=f"{digest}|{version}|{sentence[0]}:{sentence[1]}",
        source_sha256=digest,
        rules_version=version,
        section=section,
        kind=kind,
        sentence_start=sentence[0],
        sentence_end=sentence[1],
        assertion_start=assertion[0],
        assertion_end=assertion[1],
        arm_anchor=arm_anchor,
        result_anchor=result_anchor,
        context_spans=context_spans,
        slots=slots,
    )


def _mark(text: str, start: int, end: int, role: MarkRole) -> MarkSlot:
    return MarkSlot(text[start:end], start, end, role)


def _unit_id(
    source_sha256: str,
    rules_version: str,
    assertion: tuple[int, int],
    arm_anchor: str,
    result_anchor: str,
) -> str:
    start, end = assertion
    payload = f"{source_sha256}|{rules_version}|{start}:{end}|{arm_anchor}|{result_anchor}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
