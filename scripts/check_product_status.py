#!/usr/bin/env python3
"""Validate the canonical product-status block and its local evidence paths."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

START: Final = "<!-- product-status:v1:start -->"
END: Final = "<!-- product-status:v1:end -->"
REQUIRED_IDS: Final = ("AC-01", "AC-02", "AC-03", "CHUNK-SWEEP")
VALID_STATUSES: Final = frozenset({"COMPLETE", "INCOMPLETE"})
PATH_RE: Final = re.compile(r"`([^`]+)`")


@dataclass(frozen=True, slots=True)
class StatusEntry:
    item_id: str
    status: str
    evidence: tuple[str, ...]
    follow_up: str
    follow_up_detail: str


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    item_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class StatusReport:
    ok: bool
    entries: tuple[StatusEntry, ...]
    resolved_paths: tuple[str, ...]
    issues: tuple[Issue, ...]

    def payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "entries": [asdict(entry) for entry in self.entries],
            "resolved_paths": list(self.resolved_paths),
            "issues": [
                {"code": issue.code, "id": issue.item_id, "detail": issue.detail}
                for issue in self.issues
            ],
        }


def _table_rows(text: str) -> tuple[list[dict[str, str]], list[Issue]]:
    if text.count(START) != 1 or text.count(END) != 1:
        return [], [Issue("missing_delimiters", "DOCUMENT", "expected one v1 status block")]
    block = text.split(START, 1)[1].split(END, 1)[0]
    lines = [line.strip() for line in block.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return [], [Issue("invalid_table", "DOCUMENT", "status block has no data rows")]
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    expected = ["ID", "Status", "Evidence", "Follow-up"]
    if headers != expected:
        return [], [
            Issue("invalid_table", "DOCUMENT", f"expected columns {', '.join(expected)}")
        ]
    rows: list[dict[str, str]] = []
    issues: list[Issue] = []
    for line_number, line in enumerate(lines[2:], start=3):
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            issues.append(
                Issue("invalid_table", f"ROW-{line_number}", "row width differs from header")
            )
            continue
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows, issues


def _follow_up(cell: str) -> tuple[str, str] | None:
    if cell == "NONE":
        return "NONE", ""
    for kind in ("BLOCKING", "NON-BLOCKING"):
        prefix = f"{kind}:"
        if cell.startswith(prefix) and cell[len(prefix) :].strip():
            return kind, cell[len(prefix) :].strip()
    return None


def _inside_root(root: Path, reference: str) -> Path | None:
    candidate = (root / reference).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


def check_status(document: Path, root: Path) -> StatusReport:
    root = root.resolve()
    document = document if document.is_absolute() else root / document
    try:
        text = document.read_text(encoding="utf-8")
    except OSError as exc:
        issue = Issue("unreadable_document", "DOCUMENT", str(exc))
        return StatusReport(False, (), (), (issue,))

    rows, issues = _table_rows(text)
    if not rows and issues:
        return StatusReport(False, (), (), tuple(issues))
    entries: list[StatusEntry] = []
    resolved_paths: set[str] = set()
    counts = {item_id: 0 for item_id in REQUIRED_IDS}

    for row in rows:
        item_id = row["ID"]
        status = row["Status"]
        evidence = tuple(PATH_RE.findall(row["Evidence"]))
        parsed_follow_up = _follow_up(row["Follow-up"])

        if item_id not in counts:
            issues.append(Issue("unexpected_id", item_id, "ID is not in the canonical set"))
        else:
            counts[item_id] += 1
        if status not in VALID_STATUSES:
            issues.append(Issue("invalid_status", item_id, status))
        elif status != "COMPLETE":
            issues.append(
                Issue("stale_status", item_id, f"expected COMPLETE, got {status}")
            )
        if not evidence:
            issues.append(Issue("empty_evidence", item_id, "at least one path is required"))
        if parsed_follow_up is None:
            issues.append(
                Issue("invalid_followup", item_id, "use NONE, BLOCKING:, or NON-BLOCKING:")
            )
            follow_up, follow_up_detail = "INVALID", row["Follow-up"]
        else:
            follow_up, follow_up_detail = parsed_follow_up
        if status == "COMPLETE" and follow_up == "BLOCKING":
            issues.append(
                Issue(
                    "followup_contradiction",
                    item_id,
                    "COMPLETE cannot have a blocking follow-up",
                )
            )
        if status == "INCOMPLETE" and follow_up != "BLOCKING":
            issues.append(
                Issue(
                    "followup_contradiction",
                    item_id,
                    "INCOMPLETE requires a blocking follow-up",
                )
            )

        for reference in evidence:
            candidate = _inside_root(root, reference)
            if candidate is None or not candidate.is_file():
                issues.append(Issue("broken_path", item_id, reference))
            else:
                resolved_paths.add(reference)
        entries.append(StatusEntry(item_id, status, evidence, follow_up, follow_up_detail))

    for item_id, count in counts.items():
        if count == 0:
            issues.append(Issue("missing_id", item_id, "required row is absent"))
        elif count > 1:
            issues.append(Issue("duplicate_id", item_id, f"found {count} rows"))

    return StatusReport(
        not issues,
        tuple(entries),
        tuple(sorted(resolved_paths)),
        tuple(issues),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--document",
        type=Path,
        default=Path("docs/PRODUCT_SPEC.md"),
        help="status document, absolute or relative to --root",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    report = check_status(args.document, args.root)
    if args.json:
        print(json.dumps(report.payload(), ensure_ascii=False, sort_keys=True))
    else:
        verdict = "PASS" if report.ok else "FAIL"
        print(f"{verdict}: {len(report.entries)} statuses, {len(report.resolved_paths)} paths")
        for issue in report.issues:
            print(f"{issue.code}: {issue.item_id}: {issue.detail}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
