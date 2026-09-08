from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from ontologylab.main import build_arg_parser, main
from ontologylab.method_ir import canonical_json_bytes
from tests.method_cli_support import (
    fragment_argv, import_state, observe_import,
    seed_bridge_fragment, seed_fragment_import,
)


COMMANDS = {
    "workspace-create", "policy-add", "policy-snapshot", "occurrence-import",
    "extract", "fragment-import", "link-import", "bridge-import", "review",
    "decide", "detect-gaps", "compile",
}


def _run(*argv: str) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return int(exc.value.code or 0)


def test_method_nested_commands_exist_without_verify_surface() -> None:
    parser = build_arg_parser()
    action = next(item for item in parser._actions if item.dest == "command")
    assert isinstance(action, argparse._SubParsersAction)
    choices = dict(action.choices or {})
    method = choices["method"]
    nested = next(
        item for item in method._actions
        if item.dest == "method_command"
    )
    assert isinstance(nested, argparse._SubParsersAction)
    assert COMMANDS <= set(nested.choices)
    assert "verify" not in nested.choices


def test_decision_command_requires_named_reviewer_and_note() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["method", "decide"])


def test_occurrence_import_accepts_canonical_json_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "data"
    text = "Heat sample."
    source = tmp_path / "source.txt"
    source.write_text(text, encoding="utf-8")
    assert _run("collect", "--file", str(source), "--data-dir", str(data)) == 0
    from ontologylab.kgstore import KGStore
    store = KGStore.open(data / "kg.sqlite")
    document = store.list_documents()[0]
    store.close()
    payload = {
        "schema_version": "method-occurrence-v1",
        "occurrences": [{
            "id": "occ-cli", "selector": {
                "document_id": document.id,
                "document_content_hash": document.content_hash,
                "span_start": 0, "span_end": len(text),
                "selected_text_hash": (
                    "sha256:" + hashlib.sha256(text.encode()).hexdigest()
                ),
            },
            "statement_text": text, "polarity": "positive",
            "modality": "asserted",
            "temporal_scope": {"state": "absent", "kind": "string"},
            "applicability_scope": {"state": "absent", "kind": "string"},
        }],
    }
    path = tmp_path / "occurrence.json"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    assert _run(
        "method", "workspace-create", "--id", "workspace-cli",
        "--name", "CLI", "--objective", "Import", "--created-by", "human",
        "--data-dir", str(data),
    ) == 0
    assert _run(
        "method", "occurrence-import", "--workspace-id", "workspace-cli",
        "--file", str(path), "--data-dir", str(data),
    ) == 0
    assert "occurrence" in capsys.readouterr().out.lower()


def test_occurrence_import_rejects_noncanonical_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"occurrences": []}', encoding="utf-8")
    assert _run(
        "method", "occurrence-import", "--workspace-id", "missing",
        "--file", str(path), "--data-dir", str(tmp_path / "data"),
    ) == 2


@pytest.mark.parametrize(
    "surrounding",
    [b" ", b"\n", b" \n{canonical}\n\t"],
)
def test_occurrence_import_rejects_surrounding_noncanonical_bytes(
    tmp_path: Path,
    surrounding: bytes,
) -> None:
    from ontologylab.kgstore import KGStore
    from ontologylab.method_ir import canonical_json_bytes

    canonical = canonical_json_bytes({
        "schema_version": "method-occurrence-v1",
        "occurrences": [],
    })
    raw = (
        surrounding.replace(b"{canonical}", canonical)
        if b"{canonical}" in surrounding
        else canonical + surrounding
    )
    path = tmp_path / "surrounded.json"
    path.write_bytes(raw)
    data = tmp_path / "data"
    assert _run(
        "method", "occurrence-import", "--workspace-id", "missing",
        "--file", str(path), "--data-dir", str(data),
    ) == 2
    store = KGStore.open(data / "kg.sqlite")
    try:
        assert store.conn.execute(
            "SELECT COUNT(*) FROM statement_occurrence"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_detect_gaps_and_compile_nested_parser_contracts() -> None:
    parser = build_arg_parser()
    action = next(item for item in parser._actions if item.dest == "command")
    assert isinstance(action, argparse._SubParsersAction)
    method = dict(action.choices or {})["method"]
    nested = next(
        item for item in method._actions
        if isinstance(item, argparse._SubParsersAction)
    )
    detect = dict(nested.choices or {})["detect-gaps"]
    compile_parser = dict(nested.choices or {})["compile"]
    detect.parse_args(["--workspace-id", "workspace-1"])
    compile_parser.parse_args([
        "--workspace-id", "workspace-1",
        "--fixtures", "fixtures.json",
        "--attempt-id", "attempt-1",
    ])
    with pytest.raises(SystemExit):
        compile_parser.parse_args([
            "--workspace-id", "workspace-1",
            "--fixtures", "fixtures.json",
            "--release-id", "release-1",
        ])


def test_qa_compile_parser_accepts_exact_plan_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.qa_methodology_compiler as qa
    import sys

    monkeypatch.setattr(
        qa,
        "compile_methodology",
        lambda timeout: int(timeout != 30),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qa_methodology_compiler.py",
            "compile",
            "--timeout",
            "30",
        ],
    )
    assert qa.main() == 0


def test_compile_cli_blocks_with_exact_failed_gate_names(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tests.test_method_compiler import _fixture

    fixture = tmp_path / "blocked.json"
    fixture.write_bytes(canonical_json_bytes(
        _fixture("gate-g7-replay.json")["fixtures"]
    ))
    assert _run(
        "method", "compile",
        "--workspace-id", "missing",
        "--fixtures", str(fixture),
        "--attempt-id", "attempt-cli",
        "--data-dir", str(tmp_path / "data"),
    ) == 2
    assert "method compile" in capsys.readouterr().err


@pytest.mark.parametrize("with_evidence", [True, False])
def test_fragment_import_preserves_supplied_field_evidence(
    tmp_path: Path, with_evidence: bool,
) -> None:
    payload = seed_fragment_import(tmp_path)
    if not with_evidence:
        payload["field_evidence"] = []
    before = import_state(tmp_path)
    assert _run(*fragment_argv(tmp_path, payload)) == 0
    after = import_state(tmp_path)
    expected = [(
        "evidence-1", "step-z", "/temperature", "occ-1", "supports",
    )] if with_evidence else []
    assert after["evidence"] == expected, "supplied evidence must not be dropped"
    assert [(row[0], row[1]) for row in after["fragments"]] == [
        ("input-a", "proposed"), ("step-z", "proposed"),
    ]
    fragments = {row[0]: row for row in after["fragments"]}
    assert fragments["step-z"][2] == "source_supported"
    assert json.loads(fragments["step-z"][3])["temperature"]["value"] == 80.0
    assert json.loads(fragments["input-a"][3])["amount"] == {
        "state": "unknown", "kind": "real",
    }
    assert after["occurrences"] == [("occ-1", "proposed")]
    assert after["authority_counts"] == (0, 0, 0, 0)
    assert after["graph"] == before["graph"]


@pytest.mark.parametrize(
    "layer", ["parser-bridge", "existing-bridge", "missing-fragment", "missing-occurrence"],
)
def test_fragment_import_refuses_evidence_at_its_actual_error_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], layer: str,
) -> None:
    import sqlite3

    from ontologylab.method_ir import IRValidationError
    from ontologylab.method_store import MethodNotFoundError, MethodValidationError

    payload = seed_fragment_import(tmp_path)
    if layer == "parser-bridge":
        payload["fragments"][0]["epistemic_class"] = "bridge_assumption"
    elif layer == "existing-bridge":
        seed_bridge_fragment(tmp_path, payload)
        payload["fragments"] = []
    elif layer == "missing-fragment":
        payload["field_evidence"][0]["fragment_id"] = "missing-fragment"
    else:
        payload["field_evidence"][0]["occurrence_id"] = "private-missing-occurrence"
    before = import_state(tmp_path)
    calls = observe_import(monkeypatch)
    assert _run(*fragment_argv(tmp_path, payload)) == 2
    output = capsys.readouterr()
    assert '"status": "ok"' not in output.out
    assert "method fragment-import:" in output.err
    assert import_state(tmp_path) == before, "refusal must roll back the whole import"
    assert calls.persisted_ids == []
    assert len(calls.exit_errors) == 1
    error = calls.exit_errors[0]
    if layer == "parser-bridge":
        assert isinstance(error, IRValidationError)
        assert calls.evidence_ids == [] and calls.failures == []
        assert "$.field_evidence[0].role" in output.err
    else:
        assert calls.evidence_ids == ["evidence-1"]
        assert len(calls.failures) == 1
        if layer == "missing-occurrence":
            assert type(error) is MethodValidationError
            assert isinstance(calls.failures[0], sqlite3.IntegrityError)
            assert error.__cause__ is calls.failures[0]
            assert "private-missing-occurrence" not in output.err
        else:
            expected_type = MethodNotFoundError if layer == "missing-fragment" else MethodValidationError
            assert type(error) is expected_type
            assert error is calls.failures[0]


def test_fragment_import_mixed_evidence_rolls_back_fragments_and_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    from ontologylab.method_store import MethodValidationError

    payload = seed_fragment_import(tmp_path)
    payload["field_evidence"].append({
        **payload["field_evidence"][0],
        "id": "evidence-2", "occurrence_id": "missing-after-valid-evidence",
    })
    before = import_state(tmp_path)
    calls = observe_import(monkeypatch)
    result = _run(*fragment_argv(tmp_path, payload))
    after = import_state(tmp_path)
    assert (after["fragments"], after["evidence"]) == ([], []), (
        "failed import must retain neither new fragments nor the first evidence row"
    )
    assert after == before
    assert result == 2
    assert calls.evidence_ids == ["evidence-1", "evidence-2"]
    assert calls.persisted_ids == ["evidence-1"]
    assert len(calls.exit_errors) == len(calls.failures) == 1
    error = calls.exit_errors[0]
    assert type(error) is MethodValidationError
    assert isinstance(calls.failures[0], sqlite3.IntegrityError)
    assert error.__cause__ is calls.failures[0]


def test_fragment_import_does_not_translate_unrelated_fragment_sql_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    from ontologylab.method_store import MethodStore

    payload = seed_fragment_import(tmp_path)
    before = import_state(tmp_path)
    failure = sqlite3.IntegrityError("unrelated fragment insertion failure")

    def fail_fragment(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(MethodStore, "propose_fragment", fail_fragment)
    with pytest.raises(sqlite3.IntegrityError) as caught:
        main(list(fragment_argv(tmp_path, payload)))
    assert caught.value is failure
    assert import_state(tmp_path) == before
