from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest
from typing import assert_never

from ontologylab.statement_units import (
    ArmSlot,
    MarkSlot,
    ResultSlot,
    SectionSpan,
    SourceUnit,
    UnitContractError,
    enumerate_units,
)

FIXTURE_ENV = "STATEMENT_HARNESS_FIXTURE_DIR"
RULES_VERSION = "units-v1"
REQUIRED_CASES = frozenset({
    "unicode_prefix_p_annua",
    "decimals_doses",
    "whereas_mixed",
    "respectively_three_arm",
    "ambiguous_list_unresolved",
    "tested_mixture",
    "hedge",
    "pseudo_cue",
    "uncued_positive",
    "cross_sentence_antecedent",
})
ELIGIBLE = frozenset({"results", "discussion", "conclusion"})
_GENUS = re.compile(r"(?<![A-Za-z])[A-Z]\. [a-z]+")


def fixture_dir() -> Path:
    override = os.environ.get(FIXTURE_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "fixtures" / "statement_harness"


def fixture_paths() -> list[Path]:
    directory = fixture_dir()
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "fixture_path" in metafunc.fixturenames:
        paths = fixture_paths()
        metafunc.parametrize("fixture_path", paths, ids=[path.name for path in paths])


def document_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_fixture(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(path.name)
    return payload


def require_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AssertionError(label)
    return value


def require_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise AssertionError(label)
    return value


def slot_dicts(payload: dict[str, object]) -> list[dict[str, object]]:
    raw = payload["expected_slots"]
    if not isinstance(raw, list):
        raise AssertionError("expected_slots")
    slots: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise AssertionError("slot")
        slots.append(item)
    return slots


def sections_of(payload: dict[str, object]) -> tuple[SectionSpan, ...]:
    raw = payload["section_spans"]
    if not isinstance(raw, list):
        raise AssertionError("section_spans")
    spans: list[SectionSpan] = []
    for item in raw:
        if not isinstance(item, dict):
            raise AssertionError("section")
        label = require_str(item["section"], "section")
        start = require_int(item["start"], "start")
        end = require_int(item["end"], "end")
        match label:
            case "results" | "discussion" | "conclusion" | "methods" | "section_unresolved":
                spans.append(SectionSpan(label, start, end))
            case _:
                raise AssertionError(label)
    return tuple(spans)


def run_fixture(payload: dict[str, object]) -> tuple[str, tuple[SourceUnit, ...]]:
    text = require_str(payload["text"], "text")
    version = require_str(payload["rules_version"], "rules_version")
    if version != RULES_VERSION:
        raise AssertionError(version)
    units = enumerate_units(
        text,
        sections_of(payload),
        source_sha256=document_sha256(text),
        rules_version=version,
    )
    return text, units


def project(slot: ArmSlot | ResultSlot | MarkSlot) -> tuple[object, ...]:
    match slot:
        case ArmSlot(quote=quote, start=start, end=end, arm=arm, polarity=polarity):
            return ("arm", quote, start, end, arm, polarity)
        case ResultSlot(quote=quote, start=start, end=end, arm=arm):
            return ("result", quote, start, end, arm)
        case MarkSlot(quote=quote, start=start, end=end, role=role):
            return (role, quote, start, end)
        case unreachable:
            assert_never(unreachable)


def expected_key(slot: dict[str, object]) -> tuple[object, ...]:
    role = require_str(slot["role"], "role")
    quote = require_str(slot["quote"], "quote")
    start = require_int(slot["start"], "start")
    end = require_int(slot["end"], "end")
    if role == "arm":
        return (role, quote, start, end, slot["arm"], slot["polarity"])
    if role == "result":
        return (role, quote, start, end, slot["arm"])
    if set(slot) != {"quote", "start", "end", "role"}:
        raise AssertionError(sorted(slot))
    return (role, quote, start, end)


def units_for(text: str, spans: tuple[SectionSpan, ...]) -> tuple[SourceUnit, ...]:
    return enumerate_units(
        text,
        spans,
        source_sha256=document_sha256(text),
        rules_version=RULES_VERSION,
    )


def test_required_cases_are_present() -> None:
    paths = fixture_paths()
    assert paths, fixture_dir()
    cases = [path.stem.replace("-", "_") for path in paths]
    assert set(cases) == REQUIRED_CASES
    assert len(cases) == len(set(cases)) == len(REQUIRED_CASES)


def test_fixture_slots_match_expected(fixture_path: Path) -> None:
    payload = load_fixture(fixture_path)
    text, units = run_fixture(payload)
    actual = [project(slot) for unit in units for slot in unit.slots]
    wanted = [expected_key(slot) for slot in slot_dicts(payload)]
    assert sorted(actual) == sorted(wanted)
    for unit in units:
        for slot in unit.slots:
            assert text[slot.start:slot.end] == slot.quote


def test_assigned_arm_anchors_match_the_fixture(fixture_path: Path) -> None:
    payload = load_fixture(fixture_path)
    _text, units = run_fixture(payload)
    arms = sorted(
        (slot for slot in slot_dicts(payload) if slot["role"] == "arm"),
        key=lambda slot: (require_int(slot["start"], "start"), require_int(slot["end"], "end")),
    )
    explicit = sorted(
        (unit for unit in units if unit.kind == "explicit"),
        key=lambda unit: unit.arm_anchor,
    )
    assert [unit.arm_anchor for unit in explicit] == [
        f"{slot['start']}:{slot['end']}" for slot in arms
    ]
    assert [unit.result_anchor for unit in explicit] == [
        f"{result['start']}:{result['end']}"
        for arm in arms
        for result in slot_dicts(payload)
        if result["role"] == "result" and result["arm"] == arm["quote"]
    ]


def test_unit_identity_follows_the_contract(fixture_path: Path) -> None:
    payload = load_fixture(fixture_path)
    text, units = run_fixture(payload)
    digest = document_sha256(text)
    slots = slot_dicts(payload)
    asserting = [slot for slot in slots if slot["role"] == "asserting_sentence"]
    unresolved = [slot for slot in slots if slot["role"] == "unresolved"]
    if asserting:
        assertion = (
            require_int(asserting[0]["start"], "start"),
            require_int(asserting[0]["end"], "end"),
        )
    elif unresolved:
        assertion = (
            require_int(unresolved[0]["start"], "start"),
            require_int(unresolved[0]["end"], "end"),
        )
    else:
        assertion = (0, len(text))
    if unresolved:
        identity = f"{digest}|{RULES_VERSION}|{assertion[0]}:{assertion[1]}||"
        matching = [unit for unit in units if unit.kind == "unresolved"]
        assert len(matching) == 1
        unit = matching[0]
        assert unit.arm_anchor == ""
        assert unit.result_anchor == ""
        assert unit.unit_id == hashlib.sha256(identity.encode("utf-8")).hexdigest()
        assert unit.sentence_id == f"{digest}|{RULES_VERSION}|{assertion[0]}:{assertion[1]}"
        assert [item.kind for item in units if item.kind == "explicit"] == []
        return
    for unit in units:
        if unit.kind != "explicit":
            continue
        identity = (
            f"{digest}|{RULES_VERSION}|{assertion[0]}:{assertion[1]}"
            f"|{unit.arm_anchor}|{unit.result_anchor}"
        )
        assert unit.unit_id == hashlib.sha256(identity.encode("utf-8")).hexdigest()
        assert (unit.assertion_start, unit.assertion_end) == assertion
        assert unit.sentence_id == f"{digest}|{RULES_VERSION}|{assertion[0]}:{assertion[1]}"
        assert unit.section == "results"
        assert unit.source_sha256 == digest
        assert unit.rules_version == RULES_VERSION
    context = [slot for slot in slots if slot["role"] == "context"]
    if not context:
        return
    linked = [unit for unit in units if unit.kind == "explicit" and unit.context_spans]
    assert len(linked) == 1
    assert linked[0].context_spans == (
        (require_int(context[0]["start"], "start"), require_int(context[0]["end"], "end")),
    )
    dose = next(slot for slot in slots if slot["role"] == "dose")
    assert require_str(dose["quote"], "dose") not in text[assertion[0]:assertion[1]]


def test_genus_abbreviation_stays_inside_one_sentence(fixture_path: Path) -> None:
    payload = load_fixture(fixture_path)
    text, units = run_fixture(payload)
    for match in _GENUS.finditer(text):
        holders = [
            unit for unit in units
            if unit.sentence_start <= match.start() and match.end() <= unit.sentence_end
        ]
        assert holders, (fixture_path.name, match.group(), match.start())


def test_dose_span_stays_inside_one_sentence(fixture_path: Path) -> None:
    payload = load_fixture(fixture_path)
    _text, units = run_fixture(payload)
    for slot in slot_dicts(payload):
        if slot["role"] != "dose":
            continue
        start = require_int(slot["start"], "start")
        end = require_int(slot["end"], "end")
        holders = [
            unit for unit in units
            if unit.sentence_start <= start and end <= unit.sentence_end
        ]
        assert holders, slot["quote"]


def test_eligible_fixture_text_is_covered(fixture_path: Path) -> None:
    payload = load_fixture(fixture_path)
    text, units = run_fixture(payload)
    covered = [False] * len(text)
    for unit in units:
        for index in range(unit.sentence_start, unit.sentence_end):
            covered[index] = True
    for section in sections_of(payload):
        if section.section not in ELIGIBLE:
            continue
        for index in range(section.start, section.end):
            if text[index].strip():
                assert covered[index], (fixture_path.name, index, text[index])


def test_methods_section_is_outside_the_denominator() -> None:
    text = "Mesotrione reduced P. annua density relative to untreated plots."
    assert units_for(text, (SectionSpan("methods", 0, len(text)),)) == ()


def test_uncertain_heading_is_recorded_not_parsed() -> None:
    text = "Mesotrione reduced P. annua density relative to untreated plots."
    units = units_for(text, (SectionSpan("section_unresolved", 0, len(text)),))
    assert len(units) == 1
    unit = units[0]
    assert unit.kind == "section_unresolved"
    assert unit.slots == ()
    assert unit.arm_anchor == ""
    assert unit.result_anchor == ""
    identity = f"{document_sha256(text)}|{RULES_VERSION}|0:{len(text)}||"
    assert unit.unit_id == hashlib.sha256(identity.encode("utf-8")).hexdigest()


def test_missing_heading_is_not_an_invented_negative() -> None:
    text = "Mesotrione reduced P. annua density relative to untreated plots."
    units = units_for(text, ())
    assert len(units) == 1
    assert units[0].kind == "section_unresolved"
    assert units[0].slots == ()
    assert units[0].arm_anchor == ""


def test_sentence_without_an_arm_stays_in_the_manifest() -> None:
    text = "Plots were inspected on Monday."
    units = units_for(text, (SectionSpan("results", 0, len(text)),))
    assert len(units) == 1
    unit = units[0]
    assert unit.kind == "sentence"
    assert unit.arm_anchor == ""
    assert unit.result_anchor == ""
    assert text[unit.sentence_start:unit.sentence_end] == text
    identity = f"{document_sha256(text)}|{RULES_VERSION}|0:{len(text)}||"
    assert unit.unit_id == hashlib.sha256(identity.encode("utf-8")).hexdigest()
    assert unit.sentence_id == f"{document_sha256(text)}|{RULES_VERSION}|0:{len(text)}"


@pytest.mark.parametrize("section", ["results", "discussion", "conclusion"])
def test_eligible_section_keeps_an_assigned_sentence(section: str) -> None:
    text = "Mesotrione reduced P. annua density relative to untreated plots."
    match section:
        case "results" | "discussion" | "conclusion":
            label = section
        case _:
            raise AssertionError(section)
    units = units_for(text, (SectionSpan(label, 0, len(text)),))
    assert len(units) == 1
    assert units[0].kind == "explicit"
    assert units[0].section == label
    assert units[0].arm_anchor == "0:10"
    assert text[0:10] == "Mesotrione"


def test_uncovered_prose_is_section_unresolved() -> None:
    body = "Mesotrione reduced P. annua density relative to untreated plots."
    text = f"Note.\n\n{body}"
    start = len(text) - len(body)
    units = units_for(text, (SectionSpan("results", start, len(text)),))
    headings = [unit for unit in units if unit.kind == "section_unresolved"]
    explicit = [unit for unit in units if unit.kind == "explicit"]
    assert len(headings) == 1
    assert text[headings[0].assertion_start:headings[0].assertion_end].strip() == "Note."
    assert headings[0].slots == ()
    assert len(explicit) == 1
    assert explicit[0].section == "results"


def test_table_line_stays_unresolved() -> None:
    text = "| Mesotrione | reduced density |"
    units = units_for(text, (SectionSpan("results", 0, len(text)),))
    assert len(units) == 1
    unit = units[0]
    assert unit.kind == "unresolved"
    assert unit.arm_anchor == ""
    assert len(unit.slots) == 1
    assert unit.slots[0].role == "unresolved"
    assert unit.slots[0].quote == text


def test_source_hash_mismatch_is_rejected() -> None:
    with pytest.raises(UnitContractError) as caught:
        enumerate_units("abc", (), source_sha256="0" * 64, rules_version=RULES_VERSION)
    assert caught.value.code == "source_sha256"


def test_unsupported_rules_version_is_rejected() -> None:
    text = "Plots were inspected on Monday."
    with pytest.raises(UnitContractError) as caught:
        enumerate_units(
            text,
            (),
            source_sha256=document_sha256(text),
            rules_version="units-v0",
        )
    assert caught.value.code == "rules_version"


def test_overlapping_sections_are_rejected() -> None:
    text = "abcd"
    spans = (SectionSpan("results", 0, 3), SectionSpan("discussion", 2, 4))
    with pytest.raises(UnitContractError) as caught:
        units_for(text, spans)
    assert caught.value.code == "section_order"


def test_section_past_the_text_is_rejected() -> None:
    text = "abcd"
    with pytest.raises(UnitContractError) as caught:
        units_for(text, (SectionSpan("results", 0, 9),))
    assert caught.value.code == "section_bounds"


def test_coordinated_clauses_with_their_own_verbs_keep_each_arm() -> None:
    text = "Mesotrione reduced weed density and Glyphosate increased yield."
    assert len(text) == 63
    assert text[0:10] == "Mesotrione"
    assert text[11:31] == "reduced weed density"
    assert text[36:46] == "Glyphosate"
    assert text[47:62] == "increased yield"
    units = units_for(text, (SectionSpan("results", 0, 63),))
    explicit = [unit for unit in units if unit.kind == "explicit"]
    assert [unit.arm_anchor for unit in explicit] == ["0:10", "36:46"]
    assert [unit.result_anchor for unit in explicit] == ["11:31", "47:62"]
    slots = [project(slot) for unit in units for slot in unit.slots]
    assert sorted(slots) == sorted([
        ("arm", "Mesotrione", 0, 10, "Mesotrione", "supports"),
        ("result", "reduced weed density", 11, 31, "Mesotrione"),
        ("arm", "Glyphosate", 36, 46, "Glyphosate", "supports"),
        ("result", "increased yield", 47, 62, "Glyphosate"),
    ])
    digest = document_sha256(text)
    for unit in explicit:
        assert (unit.assertion_start, unit.assertion_end) == (0, 63)
        identity = f"{digest}|{RULES_VERSION}|0:63|{unit.arm_anchor}|{unit.result_anchor}"
        assert unit.unit_id == hashlib.sha256(identity.encode("utf-8")).hexdigest()


def test_shared_verb_list_stays_unresolved() -> None:
    text = "Mesotrione and Glyphosate reduced weed density."
    assert len(text) == 47
    units = units_for(text, (SectionSpan("results", 0, 47),))
    assert [unit.kind for unit in units] == ["unresolved"]
    unit = units[0]
    assert unit.arm_anchor == ""
    assert unit.result_anchor == ""
    assert len(unit.slots) == 1
    slot = unit.slots[0]
    assert slot.role == "unresolved"
    assert slot.quote == "Mesotrione and Glyphosate reduced weed density."
    assert slot.start == 0
    assert slot.end == 47
