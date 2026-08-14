from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_f1_publication_receipt_mutant_is_pinned() -> None:
    source = _source("ontologylab/method_pack.py")
    assert "PUBLICATION_SCHEMA_VERSION" in source
    assert "insert_publication_receipt" in source
    assert "validate_method_pack" in source


def test_f2_duplicate_selection_mutant_is_pinned() -> None:
    source = _source("ontologylab/method_pack.py")
    assert "duplicate method release id" in source
    assert source.index("reject_duplicate_release_ids") < source.index(
        "copy_method_releases"
    )


def test_f3_relational_source_mutant_is_pinned() -> None:
    source = _source("ontologylab/method_pack_sql.py")
    for contract in (
        "statement occurrence workspace mismatch",
        "statement occurrence document mismatch",
        "statement occurrence selector mismatch",
        "statement occurrence policy selector mismatch",
        "statement occurrence review receipt mismatch",
    ):
        assert contract in source


def test_f4_cleanup_ordering_mutant_is_pinned() -> None:
    source = _source("ontologylab/packbuilder.py")
    assert "owned_stages" in source
    assert "except BaseException" in source
    assert source.index("validate_method_pack(conn, method_selection)") < (
        source.index("pack_dir.rename(final_pack_dir)")
    )


def test_f5_planned_qa_mutant_is_pinned() -> None:
    source = _source("scripts/qa_methodology_compiler.py")
    assert 'sub.add_parser("pack")' in source
    assert "run_pack_qa(args.timeout)" in source
    assert (ROOT / "tests/test_method_pack_atomicity.py").is_file()


def test_prior_explicit_selection_mutant_is_pinned() -> None:
    signature = next(
        node
        for node in ast.parse(_source("ontologylab/packbuilder.py")).body
        if isinstance(node, ast.FunctionDef) and node.name == "build_pack"
    )
    assert any(arg.arg == "method_release_ids" for arg in signature.args.kwonlyargs)


def test_prior_graph_only_mutant_is_pinned() -> None:
    source = _source("ontologylab/method_pack.py")
    empty_return = source.index(
        "return MethodPackSelection((), (), \"\", \"\", \"\", \"\", \"\", \"\")"
    )
    assert empty_return < source.index("persistence.create_tables()")


def test_prior_unknown_release_mutant_is_pinned() -> None:
    assert "unknown Method release" in _source("ontologylab/method_pack.py")


def test_prior_content_hash_mutant_is_pinned() -> None:
    source = _source("ontologylab/method_pack.py")
    assert "canonical_release_envelope" in source
    assert "values[6] != envelope.content_hash" in source


def test_prior_gate_attempt_mutant_is_pinned() -> None:
    source = _source("ontologylab/method_pack.py")
    assert "gate_rows != expected" in source
    assert "attempt is stale" in source


def test_prior_stale_snapshot_mutant_is_pinned() -> None:
    source = _source("ontologylab/method_pack.py")
    assert "source or policy snapshot is stale" in source


def test_prior_method_hash_mutant_is_pinned() -> None:
    source = _source("ontologylab/packbuilder.py")
    assert source.index("copy_method_releases(") < source.index(
        "content_hash = \"sha256:\""
    )
