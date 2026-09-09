#!/usr/bin/env python3
"""Report audit rows whose 'open' claim no longer matches the code.

The audit doc is advertised by AGENTS.md as the current refactor priorities,
so a row that has silently been fixed is worse than no row at all: it sends
the next session to build something that already exists. Each probe below is
the single observable that decides whether its row is still open.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBES = {
    "1": ("ontologylab/server/schemas.py", r"engine: str = OFFLINE_LAUNCH_POLICY\.default_engine"),
    "2": ("ontologylab/server/jobs.py", r"RESEARCH_NO_SOURCES = "),
    "6": ("ontologylab/connectors/paper_api.py", r"allowlist-checked API URL"),
    "7": ("ontologylab/embeddings.py", r"lexical proxy is the honest answer"),
    "8": ("ontologylab/server/routes.py", r"Off the event loop\."),
    "10": ("ontologylab/web/app.js", r"conformal: "),
}


def main() -> int:
    doc = ROOT / "docs" / "ENGINE-PIPELINE-AUDIT-2026-08-19.md"
    text = doc.read_text(encoding="utf-8")
    stale = []
    for row, (rel, pattern) in sorted(PROBES.items(), key=lambda kv: int(kv[0])):
        body = (ROOT / rel).read_text(encoding="utf-8")
        landed = re.search(pattern, body) is not None
        marked = re.search(rf"^\| {row} \|.*(FIXED|해소됨|검증됨)", text, re.M) is not None
        if landed and not marked:
            stale.append(f"row {row}: fixed in {rel} but the doc still lists it as open")
    for line in stale:
        print(f"  {line}")
    print(f"STALE: {len(stale)}")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
