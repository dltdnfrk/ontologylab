from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

FIXTURE_ENV = "STATEMENT_HARNESS_FIXTURE_DIR"
RULES_VERSION = "units-v1"
ELIGIBLE_SECTIONS = frozenset({"results", "discussion", "conclusion"})
SECTION_LABELS = ELIGIBLE_SECTIONS | {"methods", "section_unresolved"}
ROLES = frozenset({
    "arm",
    "result",
    "dose",
    "contrast",
    "hedge",
    "pseudo_cue",
    "protected_abbreviation",
    "unresolved",
    "context",
    "antecedent",
    "asserting_sentence",
})
CLAIM_ROLES = frozenset({"arm", "result", "unresolved", "asserting_sentence"})
POLARITIES = frozenset({"supports", "no_effect", "refutes"})
SUPPORTS_TOKENS = ("reduced", "lost cover", "increased")
NULL_TOKENS = ("did not", "unchanged", "not significantly", "ineffective")
DEV_ONLY_IDS = (
    "PMC12632097",
    "10.1186/s12866-025-04356-y",
    "PMC12546283",
    "10.1007/s10340-025-01925-y",
    "PMC12563837",
    "10.3390/genes16101169",
    "PMC12713700",
    "10.1002/ps.70214",
    "PMC11298438",
    "10.3389/fmicb.2024.1425392",
)
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
TOP_KEYS = frozenset({
    "id",
    "case",
    "rules_version",
    "text",
    "section_spans",
    "rationale",
    "expected_slots",
})


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


def line_value(rationale: str, label: str) -> str | None:
    prefix = f"{label}: "
    found = [
        line[len(prefix):].strip()
        for line in rationale.splitlines()
        if line.startswith(prefix)
    ]
    assert len(found) <= 1, label
    if not found:
        return None
    assert found[0], label
    return found[0]


def member_line(rationale: str, label: str) -> list[str] | None:
    raw = line_value(rationale, label)
    if raw is None:
        return None
    if raw == "none":
        return []
    names = [part.strip() for part in raw.split(";")]
    assert names and all(names), label
    assert all(name != "none" for name in names), label
    return names


def slots_with(slots: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    return [slot for slot in slots if slot["role"] == role]


def one_slot(slots: list[dict[str, Any]], role: str) -> dict[str, Any]:
    found = slots_with(slots, role)
    assert len(found) == 1, role
    return found[0]


def assert_slice(text: str, slot: dict[str, Any], label: str) -> None:
    start = slot["start"]
    end = slot["end"]
    quote = slot["quote"]
    assert type(start) is int and type(end) is int, label
    assert isinstance(quote, str) and quote, label
    assert 0 <= start < end <= len(text), f"{label} {start}:{end} outside 0:{len(text)}"
    actual = text[start:end]
    assert actual == quote, f"{label} {start}:{end} {actual!r} != {quote!r}"


def assert_inside(inner: dict[str, Any], outer: dict[str, Any], label: str) -> None:
    assert inner["start"] >= outer["start"] and inner["end"] <= outer["end"], label


def assert_disjoint(left: dict[str, Any], right: dict[str, Any], label: str) -> None:
    assert left["end"] <= right["start"] or right["end"] <= left["start"], label


def check_unicode(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    assert line_value(rationale, "Unicode prefix") == "\u00b5"
    assert text.startswith("\u00b5")
    assert len("\u00b5".encode("utf-8")) > 1
    protected = one_slot(slots, "protected_abbreviation")
    assert protected["quote"] == "P. annua"
    assert line_value(rationale, "Protected abbreviation") == "P. annua"
    assert protected["start"] > 0


def check_decimals(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    del text
    dose = one_slot(slots, "dose")
    quote = dose["quote"]
    assert quote == line_value(rationale, "Dose span")
    number, _, unit = quote.partition(" ")
    left, dot, right = number.partition(".")
    assert unit and left.isdigit() and dot == "." and right.isdigit(), quote


def check_whereas(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    del text, rationale
    arms = sorted(slots_with(slots, "arm"), key=lambda slot: slot["start"])
    assert [slot["polarity"] for slot in arms] == ["no_effect", "supports"]


def check_respectively(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    del text, rationale
    arms = sorted(slots_with(slots, "arm"), key=lambda slot: slot["start"])
    assert len(arms) == 3
    assert [slot["polarity"] for slot in arms] == ["supports", "no_effect", "supports"]


def check_ambiguous(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    unresolved = one_slot(slots, "unresolved")
    assert unresolved["quote"] == text
    assert [slot["role"] for slot in slots] == ["unresolved"]
    members = member_line(rationale, "List members unresolved")
    assert members is not None and len(members) >= 2
    for name in members:
        assert name in text


def check_mixture(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    del text
    arm = one_slot(slots, "arm")
    ingredients = member_line(rationale, "Not arms")
    assert ingredients is not None and len(ingredients) >= 2
    for name in ingredients:
        assert name in arm["quote"]
        assert name != arm["quote"]
    assert arm["polarity"] == "supports"


def check_hedge(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    del text
    hedge = one_slot(slots, "hedge")
    assert hedge["quote"] == line_value(rationale, "Hedge cue")
    assert one_slot(slots, "arm")["polarity"] is None


def check_pseudo(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    del text
    cue = one_slot(slots, "pseudo_cue")
    assert cue["quote"] == line_value(rationale, "Pseudo-cue")
    assert one_slot(slots, "arm")["polarity"] == "supports"
    assert all(slot.get("polarity") != "no_effect" for slot in slots)


def check_uncued(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    del text
    assert line_value(rationale, "Cues") == "none"
    assert slots_with(slots, "hedge") == []
    assert slots_with(slots, "pseudo_cue") == []
    assert slots_with(slots, "contrast") == []
    assert one_slot(slots, "arm")["polarity"] == "supports"


def check_cross_sentence(text: str, slots: list[dict[str, Any]], rationale: str) -> None:
    context = one_slot(slots, "context")
    asserting = one_slot(slots, "asserting_sentence")
    antecedent = one_slot(slots, "antecedent")
    dose = one_slot(slots, "dose")
    arm = one_slot(slots, "arm")
    result = one_slot(slots, "result")
    assert text == context["quote"] + " " + asserting["quote"]
    assert antecedent["quote"] == line_value(rationale, "Antecedent")
    assert dose["quote"] == line_value(rationale, "Not borrowed")
    assert_inside(antecedent, context, "antecedent")
    assert_inside(dose, context, "dose")
    assert_disjoint(dose, asserting, "dose borrowed into asserting sentence")
    assert_inside(arm, asserting, "arm")
    assert_inside(result, asserting, "result")
    assert dose["quote"] not in asserting["quote"]
    assert arm["quote"] in asserting["quote"]


CASE_CHECKS = {
    "unicode_prefix_p_annua": check_unicode,
    "decimals_doses": check_decimals,
    "whereas_mixed": check_whereas,
    "respectively_three_arm": check_respectively,
    "ambiguous_list_unresolved": check_ambiguous,
    "tested_mixture": check_mixture,
    "hedge": check_hedge,
    "pseudo_cue": check_pseudo,
    "uncued_positive": check_uncued,
    "cross_sentence_antecedent": check_cross_sentence,
}


def test_required_cases_are_present() -> None:
    assert set(CASE_CHECKS) == REQUIRED_CASES
    paths = fixture_paths()
    assert paths, f"no fixtures in {fixture_dir()}"
    cases = [
        json.loads(path.read_text(encoding="utf-8"))["case"]
        for path in paths
    ]
    names = [path.name for path in paths]
    assert len(paths) == len(cases) == len(set(cases)) == len(REQUIRED_CASES), names
    assert set(cases) == REQUIRED_CASES, names


def test_fixture_oracle(fixture_path: Path) -> None:
    raw = fixture_path.read_text(encoding="utf-8")
    for token in DEV_ONLY_IDS:
        assert token not in raw, token
    payload = json.loads(raw)
    assert set(payload) == TOP_KEYS, fixture_path.name
    assert payload["id"] == fixture_path.stem
    case = payload["case"]
    assert case == fixture_path.stem.replace("-", "_")
    assert case in CASE_CHECKS, case
    assert payload["rules_version"] == RULES_VERSION
    text = payload["text"]
    rationale = payload["rationale"]
    assert isinstance(text, str) and text
    assert isinstance(rationale, str)
    assert rationale.splitlines()[0].startswith("Assigned arms: ")
    slots = payload["expected_slots"]
    assert isinstance(slots, list) and slots
    for index, slot in enumerate(slots):
        label = f"{fixture_path.name}[{index}]"
        _assert_slot_schema(slot, label)
        assert_slice(text, slot, label)
    _assert_sections(text, payload["section_spans"], slots, fixture_path.name)
    assigned = member_line(rationale, "Assigned arms")
    assert assigned is not None
    assert len(set(assigned)) == len(assigned)
    arms = sorted(slots_with(slots, "arm"), key=lambda slot: (slot["start"], slot["end"]))
    assert [slot["quote"] for slot in arms] == assigned
    _assert_split_members(text, rationale, assigned, slots)
    _assert_results(slots, assigned)
    _assert_polarity_words(slots)
    CASE_CHECKS[case](text, slots, rationale)


def _assert_sections(
    text: str,
    section_spans: Any,
    slots: list[dict[str, Any]],
    label: str,
) -> None:
    assert isinstance(section_spans, list) and section_spans, label
    previous = 0
    for span in section_spans:
        assert set(span) == {"section", "start", "end"}, label
        assert span["section"] in SECTION_LABELS, span["section"]
        start, end = span["start"], span["end"]
        assert type(start) is int and type(end) is int, label
        assert previous <= start < end <= len(text), label
        previous = end
    for slot in slots:
        covered = any(
            span["start"] <= slot["start"] and slot["end"] <= span["end"]
            for span in section_spans
        )
        assert covered, slot["role"]
        if slot["role"] in CLAIM_ROLES:
            eligible = any(
                span["section"] in ELIGIBLE_SECTIONS
                and span["start"] <= slot["start"]
                and slot["end"] <= span["end"]
                for span in section_spans
            )
            assert eligible, slot["role"]


def _assert_slot_schema(slot: Any, label: str) -> None:
    assert isinstance(slot, dict), label
    role = slot["role"]
    assert role in ROLES, label
    keys = set(slot)
    if role == "arm":
        assert keys == {"quote", "start", "end", "role", "arm", "polarity"}, label
        assert slot["arm"] == slot["quote"], label
        assert slot["polarity"] in POLARITIES or slot["polarity"] is None, label
    elif role == "result":
        assert keys == {"quote", "start", "end", "role", "arm"}, label
        assert isinstance(slot["arm"], str) and slot["arm"], label
    else:
        assert keys == {"quote", "start", "end", "role"}, label


def _assert_split_members(
    text: str,
    rationale: str,
    assigned: list[str],
    slots: list[dict[str, Any]],
) -> None:
    if "whereas" in text:
        assert member_line(rationale, "Whereas members") == assigned
        assert len(assigned) >= 2
        assert one_slot(slots, "contrast")["quote"] == "whereas"
    elif "respectively" in text:
        assert member_line(rationale, "Respectively members") == assigned
        assert one_slot(slots, "contrast")["quote"] == "respectively"
    else:
        assert slots_with(slots, "contrast") == []
    unresolved_members = member_line(rationale, "List members unresolved")
    if unresolved_members is not None:
        assert assigned == []
        assert len(unresolved_members) >= 2
    if not assigned:
        assert unresolved_members is not None


def _assert_results(slots: list[dict[str, Any]], assigned: list[str]) -> None:
    results = slots_with(slots, "result")
    assert sorted(str(slot["arm"]) for slot in results) == sorted(assigned)
    for result in results:
        assert result["arm"] in assigned


def _assert_polarity_words(slots: list[dict[str, Any]]) -> None:
    results_by_arm = {slot["arm"]: slot for slot in slots_with(slots, "result")}
    hedged = bool(slots_with(slots, "hedge"))
    for arm in slots_with(slots, "arm"):
        polarity = arm["polarity"]
        result_quote = str(results_by_arm[arm["quote"]]["quote"])
        if polarity == "supports":
            assert any(token in result_quote for token in SUPPORTS_TOKENS), result_quote
        elif polarity == "no_effect":
            assert any(token in result_quote for token in NULL_TOKENS), result_quote
        elif polarity == "refutes":
            raise AssertionError("refutes is not in this fixture set")
        elif polarity is None:
            assert hedged
        else:
            raise AssertionError(polarity)
