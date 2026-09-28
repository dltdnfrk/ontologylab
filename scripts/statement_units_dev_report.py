#!/usr/bin/env python3
"""Development-only statement-unit coverage over gold full texts.

Opens gold papers read-only, derives Results/Discussion/Conclusion spans,
enumerates units, and records how historical asserting spans sit inside
those units. This is not a precision or recall claim. No model or network
calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ontologylab.statement_candidates import CUE_VERSION, CandidateCue, detect_candidates
from ontologylab.statement_units import (
    RULES_VERSION,
    ArmSlot,
    SectionLabel,
    SectionSpan,
    SourceUnit,
    enumerate_units,
)

BANNER: Final = (
    "development-only, these papers were seen by earlier trials, "
    "not a precision or recall claim"
)
ELIGIBLE: Final = frozenset({"results", "discussion", "conclusion"})
GOLD_NAME: Final = "gold-aligned-qualified.json"


class ReportError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class _CueView:
    text: str
    start: int
    end: int
    sentence: str


@dataclass(frozen=True, slots=True)
class GoldSpan:
    pmcid: str
    polarity: str
    byte_start: int
    byte_end: int
    char_start: int
    char_end: int
    quote: str


@dataclass(frozen=True, slots=True)
class PaperReport:
    pmcid: str
    doi: str
    eligible_sentences: int
    units: int
    explicit_units: int
    unresolved_units: int
    section_unresolved_units: int
    gold_spans: int
    gold_spans_in_units: int
    gold_spans_in_arm_slots: int
    gold_null_rows: int
    gold_null_rows_with_cues: int


@dataclass(frozen=True, slots=True)
class DevReport:
    banner: str
    rules_version: str
    cue_version: str
    gold_dir: str
    papers: tuple[PaperReport, ...]
    totals: PaperReport


def _normalize_heading(line: str) -> str:
    stripped = line.strip().replace("’", "'").replace("‘", "'")
    stripped = re.sub(r"^\d+\.\s+", "", stripped)
    return re.sub(r"\s+", " ", stripped.casefold())


def _heading_label(line: str) -> SectionLabel | None:
    key = _normalize_heading(line)
    if not key:
        return None
    match key:
        case "results" | "result" | "results and discussion":
            return "results"
        case "discussion" | "discussion and conclusion" | "discussion and conclusions":
            return "discussion"
        case "conclusion" | "conclusions":
            return "conclusion"
        case "methods" | "method" | "materials and methods" | "materials and method" | "materials":
            return "methods"
        case (
            "introduction"
            | "background"
            | "references"
            | "acknowledgements"
            | "acknowledgement"
            | "funding"
            | "author contributions"
            | "authors' contributions"
            | "authors contributions"
            | "supplementary information"
            | "supplementary materials"
            | "conflict of interest"
            | "data availability"
        ):
            return "section_unresolved"
        case _:
            return None


def derive_section_spans(text: str) -> tuple[SectionSpan, ...]:
    """Map IMRaD headings to contract labels; uncertain regions stay unresolved."""

    headings: list[tuple[int, int, SectionLabel]] = []
    offset = 0
    for line in text.split("\n"):
        line_end = offset + len(line)
        label = _heading_label(line)
        if label is not None:
            headings.append((offset, line_end, label))
        offset = line_end + 1
    if not headings:
        if not text:
            return ()
        return (SectionSpan("section_unresolved", 0, len(text)),)
    spans: list[SectionSpan] = []
    for index, (_start, end, label) in enumerate(headings):
        content_start = end + 1 if end < len(text) and text[end] == "\n" else end
        content_end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        if content_start < content_end:
            spans.append(SectionSpan(label, content_start, content_end))
    return tuple(spans)


def _char_span(data: bytes, start: int, end: int, quote: str) -> tuple[int, int]:
    if type(start) is not int or type(end) is not int:
        raise ReportError("span_bounds", f"{start}:{end}")
    if not (0 <= start < end <= len(data)):
        raise ReportError("span_bounds", f"{start}:{end}")
    if data[start:end] != quote.encode("utf-8"):
        raise ReportError("span_quote", quote[:80])
    char_start = len(data[:start].decode("utf-8"))
    char_end = len(data[:end].decode("utf-8"))
    return char_start, char_end


def _load_gold(gold_dir: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    path = gold_dir / GOLD_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportError("gold_missing", str(path)) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportError("gold_unreadable", str(exc)) from exc
    if not isinstance(raw, dict):
        raise ReportError("gold_shape", "gold must be an object")
    papers = raw.get("papers")
    relations = raw.get("relations")
    if not isinstance(papers, list) or not papers:
        raise ReportError("gold_shape", "gold needs papers")
    if not isinstance(relations, list) or not relations:
        raise ReportError("gold_shape", "gold needs relations")
    return papers, relations


def _paper_source(gold_dir: Path, paper: dict[str, object]) -> tuple[str, str, bytes, str]:
    pmcid = paper.get("pmcid")
    doi = paper.get("doi")
    source = paper.get("source")
    if not isinstance(pmcid, str) or not pmcid:
        raise ReportError("paper_shape", "missing pmcid")
    if not isinstance(doi, str):
        doi = ""
    if not isinstance(source, str) or not source:
        raise ReportError("paper_shape", f"{pmcid}: missing source")
    path = (gold_dir / source).resolve()
    if not path.is_relative_to(gold_dir.resolve()):
        raise ReportError("source_escape", source)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReportError("source_unreadable", f"{pmcid}: {exc}") from exc
    text = data.decode("utf-8")
    return pmcid, doi, data, text


def _gold_spans(
    pmcid: str,
    data: bytes,
    relations: Sequence[dict[str, object]],
) -> tuple[GoldSpan, ...]:
    rows: list[GoldSpan] = []
    for item in relations:
        if item.get("pmcid") != pmcid:
            continue
        polarity = item.get("polarity")
        span = item.get("span")
        if not isinstance(polarity, str) or not isinstance(span, dict):
            raise ReportError("relation_shape", pmcid)
        start = span.get("start")
        end = span.get("end")
        quote = span.get("quote")
        if not isinstance(quote, str) or type(start) is not int or type(end) is not int:
            raise ReportError("span_shape", pmcid)
        char_start, char_end = _char_span(data, start, end, quote)
        rows.append(GoldSpan(
            pmcid, polarity, start, end, char_start, char_end, quote,
        ))
    return tuple(rows)


def _cues_for(text: str, unit: SourceUnit) -> tuple[CandidateCue, ...]:
    view = _CueView(
        text,
        unit.sentence_start,
        unit.sentence_end,
        text[unit.sentence_start:unit.sentence_end],
    )
    return detect_candidates(view, cue_version=CUE_VERSION)


def _count_eligible_sentences(text: str, units: Sequence[SourceUnit]) -> int:
    sentences: set[tuple[int, int]] = set()
    for unit in units:
        if unit.section not in ELIGIBLE:
            continue
        sentences.add((unit.sentence_start, unit.sentence_end))
    return len(sentences)


def _inside_unit(span: GoldSpan, units: Sequence[SourceUnit]) -> bool:
    return any(
        unit.sentence_start <= span.char_start < span.char_end <= unit.sentence_end
        for unit in units
    )


def _arm_slot_match(span: GoldSpan, units: Sequence[SourceUnit]) -> bool:
    for unit in units:
        if unit.kind != "explicit":
            continue
        for slot in unit.slots:
            if not isinstance(slot, ArmSlot):
                continue
            if slot.start < span.char_end and span.char_start < slot.end:
                return True
    return False


def _null_has_cue(text: str, span: GoldSpan, units: Sequence[SourceUnit]) -> bool:
    for unit in units:
        if not (unit.sentence_start < span.char_end and span.char_start < unit.sentence_end):
            continue
        if _cues_for(text, unit):
            return True
    return False


def _paper_report(
    pmcid: str,
    doi: str,
    text: str,
    units: tuple[SourceUnit, ...],
    spans: tuple[GoldSpan, ...],
) -> PaperReport:
    eligible = tuple(unit for unit in units if unit.section in ELIGIBLE)
    explicit = sum(1 for unit in eligible if unit.kind == "explicit")
    unresolved = sum(1 for unit in eligible if unit.kind == "unresolved")
    heading = sum(1 for unit in units if unit.kind == "section_unresolved")
    nulls = tuple(span for span in spans if span.polarity == "no_effect")
    return PaperReport(
        pmcid=pmcid,
        doi=doi,
        eligible_sentences=_count_eligible_sentences(text, units),
        units=len(eligible),
        explicit_units=explicit,
        unresolved_units=unresolved,
        section_unresolved_units=heading,
        gold_spans=len(spans),
        gold_spans_in_units=sum(1 for span in spans if _inside_unit(span, units)),
        gold_spans_in_arm_slots=sum(1 for span in spans if _arm_slot_match(span, units)),
        gold_null_rows=len(nulls),
        gold_null_rows_with_cues=sum(
            1 for span in nulls if _null_has_cue(text, span, units)
        ),
    )


def _sum_papers(papers: Sequence[PaperReport]) -> PaperReport:
    return PaperReport(
        pmcid="totals",
        doi="",
        eligible_sentences=sum(paper.eligible_sentences for paper in papers),
        units=sum(paper.units for paper in papers),
        explicit_units=sum(paper.explicit_units for paper in papers),
        unresolved_units=sum(paper.unresolved_units for paper in papers),
        section_unresolved_units=sum(paper.section_unresolved_units for paper in papers),
        gold_spans=sum(paper.gold_spans for paper in papers),
        gold_spans_in_units=sum(paper.gold_spans_in_units for paper in papers),
        gold_spans_in_arm_slots=sum(paper.gold_spans_in_arm_slots for paper in papers),
        gold_null_rows=sum(paper.gold_null_rows for paper in papers),
        gold_null_rows_with_cues=sum(paper.gold_null_rows_with_cues for paper in papers),
    )


def build_report(gold_dir: Path) -> DevReport:
    papers_raw, relations_raw = _load_gold(gold_dir)
    reports: list[PaperReport] = []
    for paper in papers_raw:
        if not isinstance(paper, dict):
            raise ReportError("paper_shape", "paper must be an object")
        pmcid, doi, data, text = _paper_source(gold_dir, paper)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        units = enumerate_units(
            text,
            derive_section_spans(text),
            source_sha256=digest,
            rules_version=RULES_VERSION,
        )
        spans = _gold_spans(pmcid, data, [item for item in relations_raw if isinstance(item, dict)])
        reports.append(_paper_report(pmcid, doi, text, units, spans))
    papers = tuple(reports)
    return DevReport(
        banner=BANNER,
        rules_version=RULES_VERSION,
        cue_version=CUE_VERSION,
        gold_dir=str(gold_dir),
        papers=papers,
        totals=_sum_papers(papers),
    )


def _paper_dict(paper: PaperReport) -> dict[str, str | int]:
    return {
        "pmcid": paper.pmcid,
        "doi": paper.doi,
        "eligible_sentences": paper.eligible_sentences,
        "units": paper.units,
        "explicit_units": paper.explicit_units,
        "unresolved_units": paper.unresolved_units,
        "section_unresolved_units": paper.section_unresolved_units,
        "gold_spans": paper.gold_spans,
        "gold_spans_in_units": paper.gold_spans_in_units,
        "gold_spans_in_arm_slots": paper.gold_spans_in_arm_slots,
        "gold_null_rows": paper.gold_null_rows,
        "gold_null_rows_with_cues": paper.gold_null_rows_with_cues,
    }


def report_to_json(report: DevReport) -> dict[str, object]:
    return {
        "banner": report.banner,
        "rules_version": report.rules_version,
        "cue_version": report.cue_version,
        "gold_dir": report.gold_dir,
        "papers": [_paper_dict(paper) for paper in report.papers],
        "totals": {
            "papers": len(report.papers),
            "eligible_sentences": report.totals.eligible_sentences,
            "units": report.totals.units,
            "explicit_units": report.totals.explicit_units,
            "unresolved_units": report.totals.unresolved_units,
            "section_unresolved_units": report.totals.section_unresolved_units,
            "gold_spans": report.totals.gold_spans,
            "gold_spans_in_units": report.totals.gold_spans_in_units,
            "gold_spans_in_arm_slots": report.totals.gold_spans_in_arm_slots,
            "gold_null_rows": report.totals.gold_null_rows,
            "gold_null_rows_with_cues": report.totals.gold_null_rows_with_cues,
        },
    }


def report_to_markdown(report: DevReport) -> str:
    lines = [
        "# Statement-units development coverage",
        "",
        f"**Development-only.** {BANNER}.",
        "",
        f"`rules_version = {report.rules_version}`; `cue_version = {report.cue_version}`.",
        "",
        "| PMCID | eligible sentences | units | explicit | unresolved | gold in units | gold in arm slots | null rows with cues |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for paper in report.papers:
        lines.append(
            f"| {paper.pmcid} | {paper.eligible_sentences} | {paper.units} | "
            f"{paper.explicit_units} | {paper.unresolved_units} | "
            f"{paper.gold_spans_in_units}/{paper.gold_spans} | "
            f"{paper.gold_spans_in_arm_slots}/{paper.gold_spans} | "
            f"{paper.gold_null_rows_with_cues}/{paper.gold_null_rows} |"
        )
    totals = report.totals
    lines.extend([
        f"| totals | {totals.eligible_sentences} | {totals.units} | "
        f"{totals.explicit_units} | {totals.unresolved_units} | "
        f"{totals.gold_spans_in_units}/{totals.gold_spans} | "
        f"{totals.gold_spans_in_arm_slots}/{totals.gold_spans} | "
        f"{totals.gold_null_rows_with_cues}/{totals.gold_null_rows} |",
        "",
        "Eligible sentences include uncued positives. Unresolved units are "
        "ambiguous containers, not guessed claims. Gold asserting spans are "
        "historical development rows, not a recall denominator.",
        "",
    ])
    return "\n".join(lines)


def write_report(report: DevReport, out_prefix: Path) -> None:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    payload = report_to_json(report)
    json_path = Path(str(out_prefix) + ".json")
    md_path = Path(str(out_prefix) + ".md")
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(report_to_markdown(report), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-dir", required=True)
    parser.add_argument("--out-prefix", required=True)
    args = parser.parse_args(argv)
    gold_dir = Path(args.gold_dir)
    out_prefix = Path(args.out_prefix)
    try:
        report = build_report(gold_dir)
    except ReportError as exc:
        print(f"{exc.code}: {exc.detail}", file=sys.stderr)
        return 2
    write_report(report, out_prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
