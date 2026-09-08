from __future__ import annotations

import json
from pathlib import Path

from tests.research_surface_fixtures import _research_surface


def test_corpus_summary_keeps_full_acquisition_detail(
    tmp_path: Path,
) -> None:
    # Given: the same run exposed through compact job status
    _client, _job_id, acquisition, job_dir = _research_surface(
        tmp_path, degraded=False, partial=True
    )

    # When: the durable corpus summary is read by its owner
    persisted = json.loads(
        (job_dir / "literature-corpus-summary.json").read_text(encoding="utf-8")
    )

    # Then: its complete acquisition assessment was not compacted in place
    expected = json.loads(
        json.dumps(acquisition, ensure_ascii=False, sort_keys=True)
    )
    assert persisted["acquisition_assessment"] == expected
    assert "overlap_and_diversity" in persisted["acquisition_assessment"]
    assert "source_failures" in persisted["acquisition_assessment"]
