from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from ontologylab.method_pack import (
    MethodPackError,
    MethodPackSql,
    copy_method_releases,
)
from tests.test_method_pack import seed_method_pack_database


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            "UPDATE method_compilation_attempt SET passed=0 "
            "WHERE id='attempt-1'",
            "attempt is stale",
        ),
        (
            "DELETE FROM method_compilation_gate "
            "WHERE attempt_id='attempt-1' AND gate_id='G8'",
            "gate rows are invalid",
        ),
        (
            "UPDATE method_release SET method_id='method-other' "
            "WHERE id='release-1'",
            "binding is invalid",
        ),
        (
            "UPDATE method_release SET compiler_version='compiler-v1' "
            "WHERE id='release-1'",
            "binding is invalid",
        ),
        (
            "UPDATE method_release SET review_receipt_json='{}' "
            "WHERE id='release-1'",
            "reviewer receipt is stale",
        ),
    ],
)
def test_relational_mutants_fail_closed(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    source = seed_method_pack_database(tmp_path / "source.sqlite")
    target = sqlite3.connect(tmp_path / "pack.sqlite")
    source.execute("PRAGMA foreign_keys=OFF")
    source.execute("PRAGMA ignore_check_constraints=ON")
    for trigger in (
        "method_release_no_update",
        "method_release_semantic_check",
        "method_release_attempt_binding",
        "method_release_requires_passed_gates",
        "method_attempt_no_update",
        "method_gate_no_delete",
    ):
        source.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    source.execute(mutation)
    source.commit()
    try:
        with pytest.raises(MethodPackError, match=expected):
            copy_method_releases(
                MethodPackSql(source, target),
                ("release-1",),
            )
        assert target.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name LIKE 'compiled_method%'"
        ).fetchall() == []
    finally:
        source.close()
        target.close()
