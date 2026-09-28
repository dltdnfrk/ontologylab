from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from ontologylab.statement_candidates import (
    UnsupportedCueVersionError,
    UngroundedUnitError,
    detect_candidates,
)


_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "statement_harness"
_CUE_VERSION = "cues-v1"


@dataclass(frozen=True, slots=True)
class SourceUnit:
    text: str
    start: int
    end: int
    sentence: str
    document_sha256: str
    rules_version: str
    sentence_id: str
    unit_id: str
    section: str
    arm_anchor: str
    result_anchor: str


def _load(name: str) -> dict[str, object]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _unit(
    text: str,
    *,
    start: int = 0,
    end: int | None = None,
    sentence: str | None = None,
    section: str = "results",
    rules_version: str = "units-v1",
    arm_anchor: str = "",
    result_anchor: str = "",
) -> SourceUnit:
    bound = len(text) if end is None else end
    slice_text = text[start:bound] if sentence is None else sentence
    document_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    sentence_id = f"{document_sha256}|{rules_version}|{start}:{bound}"
    joined = (
        f"{document_sha256}|{rules_version}|{start}:{bound}|{arm_anchor}|{result_anchor}"
    )
    return SourceUnit(
        text=text,
        start=start,
        end=bound,
        sentence=slice_text,
        document_sha256=document_sha256,
        rules_version=rules_version,
        sentence_id=sentence_id,
        unit_id=hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        section=section,
        arm_anchor=arm_anchor,
        result_anchor=result_anchor,
    )


def _fixture_unit(name: str) -> tuple[str, SourceUnit]:
    fixture = _load(name)
    text = fixture["text"]
    spans = fixture["section_spans"]
    if not isinstance(text, str) or not isinstance(spans, list) or len(spans) == 0:
        raise AssertionError(name)
    first = spans[0]
    if not isinstance(first, dict):
        raise AssertionError(name)
    section = first.get("section")
    if not isinstance(section, str):
        raise AssertionError(name)
    return text, _unit(text, section=section, rules_version="units-v1")


def test_whereas_mixed_not_scope_stops_at_whereas() -> None:
    text, unit = _fixture_unit("whereas-mixed.json")
    assert text[11:25] == "did not reduce"
    assert text[44:51] == "whereas"
    assert text[11:44] == "did not reduce P. annua biomass, "
    assert text[63:87] == "reduced P. annua biomass"

    cues = detect_candidates(unit, cue_version=_CUE_VERSION)

    assert len(cues) == 1
    cue = cues[0]
    assert cue.cue_version == "cues-v1"
    assert cue.kind == "measured_null"
    assert cue.cue == "did not reduce"
    assert cue.start == 11
    assert cue.end == 25
    assert cue.scope_start == 11
    assert cue.scope_end == 44
    assert text[cue.start:cue.end] == "did not reduce"
    assert text[cue.scope_start:cue.scope_end] == "did not reduce P. annua biomass, "
    assert "mesotrione" not in text[cue.scope_start:cue.scope_end]
    assert cue.direction == "forward"
    assert cue.hedge is False
    assert cue.already_cited is False
    assert cue.scope_unresolved is False


def test_hedge_may_is_flagged_and_not_a_null() -> None:
    text, unit = _fixture_unit("hedge.json")
    assert text[11:14] == "may"
    assert text[11:67] == "may reduce P. annua density relative to untreated plots."

    cues = detect_candidates(unit, cue_version=_CUE_VERSION)

    assert len(cues) == 1
    cue = cues[0]
    assert cue.kind == "hedge"
    assert cue.cue == "may"
    assert cue.start == 11
    assert cue.end == 14
    assert cue.scope_start == 11
    assert cue.scope_end == 67
    assert cue.hedge is True
    assert cue.direction == "forward"
    assert cue.already_cited is False
    assert cue.scope_unresolved is False
    assert not any(item.kind == "measured_null" for item in cues)


def test_pseudo_cue_not_only_does_not_yield_measured_null() -> None:
    text, unit = _fixture_unit("pseudo-cue.json")
    assert text[15:23] == "not only"
    assert text[35:38] == "but"
    assert text[15:35] == "not only persistent "

    cues = detect_candidates(unit, cue_version=_CUE_VERSION)

    assert len(cues) == 1
    cue = cues[0]
    assert cue.kind == "pseudo_cue"
    assert cue.cue == "not only"
    assert cue.start == 15
    assert cue.end == 23
    assert cue.scope_start == 15
    assert cue.scope_end == 35
    assert text[cue.scope_start:cue.scope_end] == "not only persistent "
    assert "reduced" not in text[cue.scope_start:cue.scope_end]
    assert cue.hedge is False
    assert cue.already_cited is False
    assert not any(item.kind == "measured_null" for item in cues)


def test_uncued_positive_returns_no_cues() -> None:
    text, unit = _fixture_unit("uncued-positive.json")
    assert text[11:35] == "reduced P. annua density"
    assert "not" not in text

    uncued = detect_candidates(unit, cue_version=_CUE_VERSION)
    cited = detect_candidates(unit, cue_version=_CUE_VERSION, cited_spans=((0, 10),))

    assert uncued == ()
    assert cited == ()
    assert isinstance(uncued, tuple)


def test_respectively_unchanged_scope_stays_on_its_arm() -> None:
    text, unit = _fixture_unit("respectively-three-arm.json")
    assert text[54:76] == "left density unchanged"
    assert text[37:52] == "reduced density"
    assert text[81:96] == "reduced biomass"

    cues = detect_candidates(unit, cue_version=_CUE_VERSION)

    assert len(cues) == 1
    cue = cues[0]
    assert cue.kind == "measured_null"
    assert cue.cue == "left density unchanged"
    assert cue.start == 54
    assert cue.end == 76
    assert cue.scope_start == 54
    assert cue.scope_end == 76
    assert text[cue.scope_start:cue.scope_end] == "left density unchanged"
    assert "reduced density" not in text[cue.scope_start:cue.scope_end]
    assert "reduced biomass" not in text[cue.scope_start:cue.scope_end]
    assert cue.hedge is False
    assert cue.already_cited is False
    assert cue.scope_unresolved is False


def test_cited_overlap_keeps_cues_marked_already_cited() -> None:
    _, unit = _fixture_unit("whereas-mixed.json")

    cues = detect_candidates(unit, cue_version=_CUE_VERSION, cited_spans=((0, 10),))

    assert len(cues) == 1
    cue = cues[0]
    assert cue.cue == "did not reduce"
    assert cue.kind == "measured_null"
    assert cue.start == 11
    assert cue.end == 25
    assert cue.scope_start == 11
    assert cue.scope_end == 44
    assert cue.already_cited is True


def test_citation_outside_the_unit_is_not_already_cited() -> None:
    _, unit = _fixture_unit("whereas-mixed.json")

    outside = detect_candidates(unit, cue_version=_CUE_VERSION, cited_spans=((88, 100),))
    adjacent = detect_candidates(unit, cue_version=_CUE_VERSION, cited_spans=((88, 89),))
    touching = detect_candidates(
        unit, cue_version=_CUE_VERSION, cited_spans=((87, 88),),
    )

    assert len(outside) == 1
    assert outside[0].already_cited is False
    assert outside[0].cue == "did not reduce"
    assert len(adjacent) == 1
    assert adjacent[0].already_cited is False
    assert len(touching) == 1
    assert touching[0].already_cited is True
    assert touching[0].cue == "did not reduce"


def test_document_offsets_follow_unit_start() -> None:
    body, _ = _fixture_unit("whereas-mixed.json")
    text = "PREFIX " + body
    unit = _unit(text, start=7, end=7 + len(body))
    assert text[18:32] == "did not reduce"
    assert text[51:58] == "whereas"

    cues = detect_candidates(unit, cue_version=_CUE_VERSION)

    assert len(cues) == 1
    cue = cues[0]
    assert cue.start == 18
    assert cue.end == 32
    assert cue.scope_start == 18
    assert cue.scope_end == 51
    assert text[cue.scope_start:cue.scope_end] == "did not reduce P. annua biomass, "
    assert "mesotrione" not in text[cue.scope_start:cue.scope_end]


def test_but_cuts_not_scope() -> None:
    text = "Glyphosate did not reduce biomass but mesotrione reduced biomass."
    assert text[11:25] == "did not reduce"
    assert text[34:37] == "but"
    unit = _unit(text)

    cues = detect_candidates(unit, cue_version=_CUE_VERSION)

    assert len(cues) == 1
    cue = cues[0]
    assert cue.cue == "did not reduce"
    assert cue.scope_start == 11
    assert cue.scope_end == 34
    assert "mesotrione" not in text[cue.scope_start:cue.scope_end]


def test_however_cuts_not_scope() -> None:
    text = "Glyphosate did not reduce biomass however mesotrione reduced biomass."
    assert text[11:25] == "did not reduce"
    assert text[34:41] == "however"
    unit = _unit(text)

    cues = detect_candidates(unit, cue_version=_CUE_VERSION)

    assert len(cues) == 1
    cue = cues[0]
    assert cue.cue == "did not reduce"
    assert cue.scope_start == 11
    assert cue.scope_end == 34
    assert "mesotrione" not in text[cue.scope_start:cue.scope_end]


def test_unknown_cue_version_is_rejected() -> None:
    _, unit = _fixture_unit("hedge.json")

    with pytest.raises(UnsupportedCueVersionError) as caught:
        detect_candidates(unit, cue_version="cues-v0")

    assert caught.value.cue_version == "cues-v0"


def test_ungrounded_unit_is_rejected() -> None:
    unit = _unit("abcdef", start=0, end=3, sentence="zzz")

    with pytest.raises(UngroundedUnitError) as caught:
        detect_candidates(unit, cue_version=_CUE_VERSION)

    assert caught.value.start == 0
    assert caught.value.end == 3
