"""M2: what a collect run writes down about what you asked for.

`collect.start` is logged before any gate runs. That ordering is deliberate
— a rejected attempt has to leave a trace (see the H3 tests) — but it means
the recorded value has passed no validation. `MAX_PAPER_QUERY_LEN` bounds
what may be searched for; nothing bounded what may be written down.

The record is durable and it accumulates: `provenance.jsonl` is append-only,
`status.json` mirrors the same payload as `last_payload`, and
`Settings.cost_summary()` re-reads every `data/jobs/*/provenance.jsonl` on
the machine. A research topic says what someone wanted to know.

The bound is not redaction. A query the gate would accept is recorded
verbatim; only one already headed for rejection is clipped, and the clip is
marked.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ontologylab.connectors.allowlist import (
    MAX_LOGGED_VALUES,
    MAX_PAPER_QUERY_LEN,
    loggable_collect_inputs,
)
from ontologylab.server import routes
from ontologylab.server.app import create_app

TOPIC = "형광 프로브 스펙트럼 중첩 보정"


def _client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    routes.attach_data_dir(data_dir)
    return TestClient(create_app(data_dir=data_dir))


def _recorded(data_dir: Path, step: str = "collect.start") -> list[dict]:
    out = []
    for path in data_dir.rglob("provenance.jsonl"):
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                line = json.loads(raw)
                if line.get("step") == step:
                    out.append(line["payload"])
    return out


def _status_payloads(data_dir: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in data_dir.rglob("status.json")
    )


# --------------------------------------------------------------------------
# The helper
# --------------------------------------------------------------------------


def test_a_query_the_gate_would_accept_is_recorded_verbatim() -> None:
    """Truncation must not cost the audit trail its fidelity."""
    assert loggable_collect_inputs([TOPIC]) == [TOPIC]


def test_a_query_at_exactly_the_gate_bound_is_untouched() -> None:
    at_bound = "x" * MAX_PAPER_QUERY_LEN

    assert loggable_collect_inputs([at_bound]) == [at_bound]


def test_one_character_over_the_bound_is_clipped_and_marked() -> None:
    over = "x" * (MAX_PAPER_QUERY_LEN + 1)

    [recorded] = loggable_collect_inputs([over])

    assert recorded.startswith("x" * MAX_PAPER_QUERY_LEN)
    assert recorded.endswith("…[truncated]")
    assert len(recorded) < len(over) + len("…[truncated]")


def test_a_reader_is_never_shown_a_clipped_value_as_if_it_were_whole() -> None:
    [recorded] = loggable_collect_inputs(["y" * 5000])

    assert "truncated" in recorded


def test_too_many_values_are_bounded_and_the_omission_is_counted() -> None:
    """An append-only file plus an uncapped list is an unbounded write."""
    values = [f"q{index}" for index in range(MAX_LOGGED_VALUES + 7)]

    recorded = loggable_collect_inputs(values)

    assert len(recorded) == MAX_LOGGED_VALUES + 1  # + the marker
    assert recorded[-1] == "…[7 more omitted]"
    assert recorded[:3] == ["q0", "q1", "q2"], "the kept values are the first ones"


def test_a_list_at_the_count_bound_gets_no_marker(tmp_path) -> None:
    values = [f"q{index}" for index in range(MAX_LOGGED_VALUES)]

    recorded = loggable_collect_inputs(values)

    assert recorded == values
    assert not any("omitted" in value for value in recorded)


def test_an_empty_list_stays_empty() -> None:
    assert loggable_collect_inputs([]) == []


def test_a_huge_list_of_huge_values_is_bounded_on_both_axes() -> None:
    values = ["z" * 5000] * 1000

    recorded = loggable_collect_inputs(values)

    serialized = json.dumps(recorded)
    assert len(recorded) == MAX_LOGGED_VALUES + 1
    assert len(serialized) < 20_000, f"one request could append {len(serialized)}B"


# --------------------------------------------------------------------------
# Wired into both collect paths
# --------------------------------------------------------------------------


def test_a_rejected_oversized_query_is_not_archived_in_full(tmp_path) -> None:
    """The case the plan called harmless.

    `check_paper_query` refuses this query — but `collect.start` was already
    written, so without the bound the full 5000 characters live in the
    permanent record of a request that never reached a connector.
    """
    data_dir = tmp_path / "data"
    client = _client(tmp_path)
    huge = "q" * 5000

    body = client.post("/api/collect", json={"paper_queries": [huge]}).json()

    assert body["error_kind"] == "rejected"
    [payload] = _recorded(data_dir)
    [logged] = payload["paper_queries"]
    assert len(logged) < 300, f"{len(logged)} chars of a refused query were kept"
    assert huge not in json.dumps(payload)


def test_the_same_query_is_bounded_in_status_json_too(tmp_path) -> None:
    """`last_payload` is a second copy of the same dict."""
    client = _client(tmp_path)
    huge = "q" * 5000

    client.post("/api/collect", json={"paper_queries": [huge]})

    assert huge not in _status_payloads(tmp_path / "data")


def test_a_normal_topic_survives_the_round_trip_unchanged(tmp_path) -> None:
    """The audit trail must still say exactly what was asked for."""
    data_dir = tmp_path / "data"
    client = _client(tmp_path)

    client.post(
        "/api/collect", json={"paper_queries": [TOPIC], "paper_source": "arxiv"}
    )

    [payload] = _recorded(data_dir)
    assert payload["paper_queries"] == [TOPIC]


def test_a_long_file_path_is_bounded_as_well(tmp_path) -> None:
    """Not only queries: a path carries a home directory name."""
    data_dir = tmp_path / "data"
    client = _client(tmp_path)
    long_path = "/" + "d" * 5000 + "/notes.md"

    client.post("/api/collect", json={"files": [long_path]})

    [payload] = _recorded(data_dir)
    assert long_path not in json.dumps(payload)


def _cli(argv: list[str]) -> int:
    import pytest

    from ontologylab.main import main as cli_main

    with pytest.raises(SystemExit) as excinfo:
        cli_main(argv)
    return excinfo.value.code


def test_the_cli_bounds_it_the_same_way(tmp_path) -> None:
    """The repo keeps the two collect paths' gates in lockstep on purpose."""
    data_dir = tmp_path / "data"
    huge = "q" * 5000

    exit_code = _cli(
        ["collect", "--data-dir", str(data_dir), "--paper-query", huge]
    )

    assert exit_code == 2, "the gate should still reject it"
    [payload] = _recorded(data_dir)
    assert huge not in json.dumps(payload)


def test_the_cli_still_records_a_normal_topic_verbatim(tmp_path) -> None:
    data_dir = tmp_path / "data"
    notes = tmp_path / "notes.md"
    notes.write_text("A local research note.", encoding="utf-8")

    assert _cli(["collect", "--data-dir", str(data_dir), "--file", str(notes)]) == 0

    [payload] = _recorded(data_dir)
    assert payload["files"] == [str(notes)]
