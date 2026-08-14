from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "qa_methodology_compiler.py"
SOURCE = ROOT / "docs" / "METHODOLOGY-COMPILER-ARCHITECTURE.md"


def _run_e2e(work_root: Path) -> tuple[dict, dict]:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "e2e",
            "--source",
            str(SOURCE),
            "--timeout",
            "60",
            "--work-root",
            str(work_root),
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": ".",
        },
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payloads = [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.startswith("{")
    ]
    proofs = [payload for payload in payloads if "semantic" in payload]
    assert len(proofs) == 1, result.stdout
    return proofs[0], payloads[-1]


def test_e2e_real_document_to_stdio_mcp_proof_is_deterministic(
    tmp_path: Path,
) -> None:
    # Given one frozen source and a work root reused after full cleanup
    work_root = tmp_path / "work"
    work_root.mkdir()

    # When the full e2e proof runs twice as independent processes
    first, first_cleanup = _run_e2e(work_root)
    second, second_cleanup = _run_e2e(work_root)

    # Then canonical semantics are byte-stable while operational ids differ
    assert first["semantic"] == second["semantic"]
    semantic = first["semantic"]
    assert semantic["gates_all_passed"] is True
    assert semantic["release_id"] == "real-release-1"
    assert semantic["release_content_hash"].startswith("sha256:")
    assert semantic["publication_receipt_hash"].startswith("sha256:")
    assert semantic["bridge_trace_status"] == "accepted_as_assumption"
    assert semantic["bridge_graph_edges"] == 0
    assert set(semantic["method_tools"]) == {
        "list_methods",
        "get_method",
        "trace_method",
        "list_method_gaps",
    }
    assert semantic["forbidden_tools"] == []
    assert all(
        proof["operational"]["pack_id"].startswith("real-proof-")
        for proof in (first, second)
    )
    assert first["operational"]["source_hash_verified"] is True
    assert first["operational"]["pack_bytes_unchanged"] is True
    assert first["operational"]["mcp_process_exited"] is True
    assert first_cleanup["cleanup"] == "absent"
    assert second_cleanup["cleanup"] == "absent"
