from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, Sequence, assert_never


CUE_VERSION: Final = "cues-v1"

# Contrast words end scope. A comma that only introduces "whereas" is
# punctuation, not the cut: stopping there would let "not" cross the contrast
# word without changing the recorded end.
_CONTRAST_WORDS: Final = ("whereas", "however", "although", "though", "yet", "but")
_CONTRAST: Final = re.compile(
    r"\b(?:" + "|".join(_CONTRAST_WORDS) + r")\b",
    re.IGNORECASE,
)
_RESULT_VERBS: Final = (
    "reduced|reduce|left|increased|increase|decreased|decrease|remained|remain|"
    "failed|did|was|were|showed|show|suppressed|suppress|inhibited|inhibit|"
    "altered|alter|affected|affect|changed|change|lowered|lower|raised|raise|"
    "produced|yielded|had|has|have"
)
_PREDICATE_COORD: Final = re.compile(
    rf"\b(?:and|or)\b(?=\s+(?:{_RESULT_VERBS})\b)",
    re.IGNORECASE,
)
_LEFT_UNCHANGED: Final = re.compile(
    r"\bleft\b(?:\s+\w+){1,4}\s+unchanged\b",
    re.IGNORECASE,
)


class CueKind(StrEnum):
    MEASURED_NULL = "measured_null"
    PSEUDO_CUE = "pseudo_cue"
    HEDGE = "hedge"


class CueDirection(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"


class UnsupportedCueVersionError(Exception):
    def __init__(self, cue_version: str) -> None:
        self.cue_version = cue_version
        super().__init__(f"unsupported cue version: {cue_version}")


class UngroundedUnitError(Exception):
    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end
        super().__init__(f"unit sentence is not text[{start}:{end}]")


class _UnitText(Protocol):
    @property
    def text(self) -> str: ...

    @property
    def start(self) -> int: ...

    @property
    def end(self) -> int: ...

    @property
    def sentence(self) -> str: ...


@dataclass(frozen=True, slots=True)
class CandidateCue:
    cue_version: str
    kind: CueKind
    cue: str
    start: int
    end: int
    scope_start: int
    scope_end: int
    direction: CueDirection
    hedge: bool
    already_cited: bool
    scope_unresolved: bool


@dataclass(frozen=True, slots=True)
class _Spec:
    kind: CueKind
    direction: CueDirection
    hedge: bool
    rank: int
    pattern: re.Pattern[str]


def _literal(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)


def _specs() -> tuple[_Spec, ...]:
    measured = (
        "no significant difference",
        "no significant effect",
        "no detectable effect",
        "not statistically different",
        "did not significantly",
        "not significantly",
        "no significant",
        "did not differ",
        "did not reduce",
        "did not alter",
        "did not affect",
        "did not change",
        "failed to reduce",
        "failed to",
        "no difference",
        "no effect",
        "not significant",
        "did not",
        "no change",
        "ineffective",
        "not",
        "no",
    )
    pseudo = ("not only", "without difficulty", "not just", "not merely")
    hedges = (
        "may",
        "might",
        "could",
        "suggest",
        "indicate",
        "appear",
        "seem",
        "possible",
        "potential",
        "likely",
        "unlikely",
    )
    rows = [
        _Spec(CueKind.MEASURED_NULL, CueDirection.FORWARD, False, 1, _literal(phrase))
        for phrase in measured
    ]
    rows.append(
        _Spec(CueKind.MEASURED_NULL, CueDirection.BACKWARD, False, 1, _literal("unchanged"))
    )
    rows.append(
        _Spec(CueKind.MEASURED_NULL, CueDirection.FORWARD, False, 1, _LEFT_UNCHANGED)
    )
    rows.extend(
        _Spec(CueKind.PSEUDO_CUE, CueDirection.FORWARD, False, 0, _literal(phrase))
        for phrase in pseudo
    )
    rows.extend(
        _Spec(CueKind.HEDGE, CueDirection.FORWARD, True, 1, _literal(phrase))
        for phrase in hedges
    )
    return tuple(rows)


_SPECS: Final = _specs()


def _ground(unit: _UnitText) -> tuple[str, int]:
    start = unit.start
    end = unit.end
    sentence = unit.sentence
    if unit.text[start:end] != sentence:
        raise UngroundedUnitError(start, end)
    return sentence, start


def _already_cited(start: int, end: int, cited_spans: Sequence[tuple[int, int]]) -> bool:
    return any(start < cited_end and cited_start < end for cited_start, cited_end in cited_spans)


def _next_cut(pattern: re.Pattern[str], sentence: str, pos: int) -> int | None:
    match = pattern.search(sentence, pos)
    if match is None:
        return None
    return match.start()


def _forward_end(sentence: str, cue_end: int) -> int:
    contrast = _next_cut(_CONTRAST, sentence, cue_end)
    coord = _next_cut(_PREDICATE_COORD, sentence, cue_end)
    end = len(sentence)
    stopped_on_contrast = False
    if contrast is not None and contrast < end:
        end = contrast
        stopped_on_contrast = True
    if coord is not None and coord < end:
        end = coord
        stopped_on_contrast = False
    if not stopped_on_contrast:
        while end > cue_end and sentence[end - 1].isspace():
            end -= 1
    return end


def _backward_start(sentence: str, cue_start: int) -> int:
    previous = 0
    for pattern in (_CONTRAST, _PREDICATE_COORD):
        for match in pattern.finditer(sentence, 0, cue_start):
            previous = max(previous, match.end())
    while previous < cue_start and sentence[previous].isspace():
        previous += 1
    return previous


def _scope(
    sentence: str, start: int, end: int, direction: CueDirection,
) -> tuple[int, int, bool]:
    if _CONTRAST.search(sentence, start, end) is not None:
        return start, end, True
    match direction:
        case CueDirection.FORWARD:
            return start, _forward_end(sentence, end), False
        case CueDirection.BACKWARD:
            return _backward_start(sentence, start), end, False
        case unreachable:
            assert_never(unreachable)


@dataclass(frozen=True, slots=True)
class _Hit:
    spec: _Spec
    start: int
    end: int


def _longest(sentence: str) -> tuple[_Hit, ...]:
    found: list[tuple[int, int, int, _Hit]] = []
    for spec in _SPECS:
        for match in spec.pattern.finditer(sentence):
            hit = _Hit(spec, match.start(), match.end())
            found.append((-(hit.end - hit.start), hit.start, spec.rank, hit))
    found.sort(key=lambda item: (item[0], item[1], item[2]))
    chosen: list[_Hit] = []
    occupied: list[tuple[int, int]] = []
    for _, _, _, hit in found:
        if any(hit.start < end and start < hit.end for start, end in occupied):
            continue
        chosen.append(hit)
        occupied.append((hit.start, hit.end))
    return tuple(chosen)


def detect_candidates(
    unit: _UnitText,
    *,
    cue_version: str,
    cited_spans: Sequence[tuple[int, int]] = (),
) -> tuple[CandidateCue, ...]:
    """Return longest-match cues whose scope stops at the clause cut.

    An empty result means the unit has no cue. It does not mean the unit was
    pruned. cited_spans marks already_cited when the unit overlaps one of
    them; the cues are still returned.
    """
    if cue_version != CUE_VERSION:
        raise UnsupportedCueVersionError(cue_version)
    sentence, origin = _ground(unit)
    already_cited = _already_cited(unit.start, unit.end, cited_spans)
    cues: list[CandidateCue] = []
    for hit in _longest(sentence):
        scope_start, scope_end, unresolved = _scope(
            sentence, hit.start, hit.end, hit.spec.direction,
        )
        cues.append(CandidateCue(
            cue_version=cue_version,
            kind=hit.spec.kind,
            cue=sentence[hit.start:hit.end],
            start=origin + hit.start,
            end=origin + hit.end,
            scope_start=origin + scope_start,
            scope_end=origin + scope_end,
            direction=hit.spec.direction,
            hedge=hit.spec.hedge,
            already_cited=already_cited,
            scope_unresolved=unresolved,
        ))
    return tuple(sorted(cues, key=lambda cue: (cue.start, cue.end, cue.kind.value)))
