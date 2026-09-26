"""No abstract-only extraction through the direct entries (plan todo 15).

The gate review for todo 5 drove an abstract-only research document through
``POST /api/extract`` to completion. ``extraction_eligibility`` now answers
once for the route, the CLI, the unnamed every-document expansion they share,
and the ``/api/documents`` rows; each entry is pinned here. An upload without
an Observation is the user's own document and stays extractable.
"""

from __future__ import annotations

import hashlib
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ontologylab import paths  # noqa: E402
from ontologylab.authority_repo import insert_observation  # noqa: E402
from ontologylab.extraction_eligibility import (  # noqa: E402
    NOT_FULL_TEXT,
    UNKNOWN_DOCUMENT,
    extraction_eligibilities,
    extraction_eligibility,
)
from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.main import main  # noqa: E402
from ontologylab.paths import kg_db_path  # noqa: E402
from ontologylab.server.app import create_app  # noqa: E402

TEXT = "The ApiGateway forwards requests to the RateLimiter before the OrderService."


def _seed(store: KGStore, title: str, *, kinds: tuple[str, ...] = ()) -> str:
    text = f"{title}. {TEXT}"
    doc, created = store.insert_document(
        source_kind="paper_api" if kinds else "upload",
        source_uri=f"file:///{title}.txt",
        title=title,
        raw_text=text,
        content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        source="crossref" if kinds else "",
        evidence_grade="peer_reviewed" if kinds else "",
    )
    assert created
    for index, kind in enumerate(kinds):
        insert_observation(
            store.conn, idempotency_key=f"{title}-{index}",
            representation_id=doc.id, content_kind=kind,
        )
    store.conn.commit()
    return doc.id


def _seeded(tmp_path: Path, **titles: tuple[str, ...]) -> tuple[Path, dict[str, str]]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = KGStore.open(kg_db_path(data_dir))
    try:
        ids = {title: _seed(store, title, kinds=kinds) for title, kinds in titles.items()}
    finally:
        store.close()
    return data_dir, ids


def _run_rows(data_dir: Path) -> list[tuple[str, str]]:
    store = KGStore.open(kg_db_path(data_dir))
    try:
        return [
            (row["document_id"], row["status"])
            for row in store.conn.execute(
                "SELECT document_id, status FROM extraction_runs ORDER BY created_ts"
            )
        ]
    finally:
        store.close()


def _extract_job_dirs(data_dir: Path) -> list[str]:
    jobs = paths.jobs_dir(data_dir)
    return sorted(p.name for p in jobs.glob("extract-*")) if jobs.exists() else []


class _JobDone:
    """Subscribe to worker completion before the POST, then await it."""

    def __init__(self, app) -> None:
        self.finished = threading.Event()
        real_run = app.state.jobs._run

        def observed(*args, **kwargs):
            try:
                return real_run(*args, **kwargs)
            finally:
                self.finished.set()

        self._patch = patch.object(app.state.jobs, "_run", observed)

    def __enter__(self) -> "_JobDone":
        self._patch.start()
        return self

    def __exit__(self, *exc) -> None:
        self._patch.stop()

    def wait(self) -> None:
        assert self.finished.wait(15), "extraction job did not finish within 15s"


def test_helper_judges_by_best_observation_or_absence(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        full = _seed(store, "full", kinds=("abstract", "fulltext"))
        abstract = _seed(store, "abstract", kinds=("abstract",))
        upload = _seed(store, "upload")
        odd = _seed(store, "odd", kinds=("supplement",))
        assert extraction_eligibility(store.conn, full) == (True, "")
        assert extraction_eligibility(store.conn, upload) == (True, "")
        eligible, reason = extraction_eligibility(store.conn, abstract)
        assert eligible is False
        assert "'abstract'" in reason and "abstract-only" in reason
        assert extraction_eligibility(store.conn, odd)[0] is False
        assert extraction_eligibility(store.conn, "nope") == (False, "unknown document id")
        verdicts = extraction_eligibilities(store.conn, [full, abstract, "nope", upload])
        assert [v.code for v in verdicts] == ["", NOT_FULL_TEXT, UNKNOWN_DOCUMENT, ""]
        assert [v.content_kind for v in verdicts] == ["fulltext", "abstract", None, None]
    finally:
        store.close()


def test_route_refuses_abstract_only_before_any_job(tmp_path: Path) -> None:
    data_dir, ids = _seeded(tmp_path, abstract=("abstract",))
    client = TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))

    resp = client.post(
        "/api/extract", json={"doc_ids": [ids["abstract"]], "engine": "mock", "model": None}
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["ok"] is False
    assert detail["error_kind"] == "not_extractable"
    assert ids["abstract"] in detail["detail"] and "abstract-only" in detail["detail"]
    assert [(r["doc_id"], r["content_kind"]) for r in detail["refused"]] == [
        (ids["abstract"], "abstract")
    ]
    assert client.get("/api/jobs").json()["jobs"] == []
    assert _run_rows(data_dir) == []
    assert _extract_job_dirs(data_dir) == []


def test_route_refuses_unknown_document_with_404(tmp_path: Path) -> None:
    data_dir, ids = _seeded(tmp_path, upload=())
    client = TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))

    resp = client.post(
        "/api/extract", json={"doc_ids": [ids["upload"], "no-such-doc"], "engine": "mock"}
    )
    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["error_kind"] == "unknown_document"
    assert detail["refused"] == [
        {"doc_id": "no-such-doc", "content_kind": None, "reason": "unknown document id"}
    ]
    assert client.get("/api/jobs").json()["jobs"] == []
    assert _run_rows(data_dir) == []


def test_route_extracts_fulltext_and_observationless_upload(tmp_path: Path) -> None:
    data_dir, ids = _seeded(tmp_path, full=("abstract", "fulltext"), upload=())
    app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    client = TestClient(app)

    with _JobDone(app) as done:
        resp = client.post(
            "/api/extract",
            json={"doc_ids": [ids["full"], ids["upload"]], "engine": "mock", "model": None},
        )
        assert resp.status_code == 202, resp.text
        done.wait()
    job = client.get(f"/api/jobs/{resp.json()['job_id']}").json()
    assert job["status"] == "complete", job
    assert job["totals"]["nodes_new"] > 0
    assert sorted(_run_rows(data_dir)) == sorted(
        [(ids["full"], "complete"), (ids["upload"], "complete")]
    )


def test_unnamed_extraction_skips_abstract_only_documents(tmp_path: Path) -> None:
    data_dir, ids = _seeded(tmp_path, abstract=("abstract",), upload=())
    app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    client = TestClient(app)

    with _JobDone(app) as done:
        resp = client.post("/api/extract", json={"engine": "mock", "model": None})
        assert resp.status_code == 202, resp.text
        done.wait()
    job = client.get(f"/api/jobs/{resp.json()['job_id']}").json()
    assert job["status"] == "complete", job
    assert _run_rows(data_dir) == [(ids["upload"], "complete")]
    skipped = [line for line in job["progress"] if "skipped" in line]
    assert skipped and ids["abstract"] in skipped[0] and "'abstract'" in skipped[0]


def test_documents_rows_carry_the_same_verdict(tmp_path: Path) -> None:
    data_dir, ids = _seeded(
        tmp_path, full=("fulltext",), abstract=("abstract",), upload=(), odd=("supplement",)
    )
    client = TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))

    rows = {doc["id"]: doc for doc in client.get("/api/documents").json()["documents"]}
    assert (rows[ids["full"]]["extractable"], rows[ids["full"]]["extract_blocked_reason"]) == (True, None)
    assert rows[ids["upload"]]["content_kind"] == "metadata_only"
    assert (rows[ids["upload"]]["extractable"], rows[ids["upload"]]["extract_blocked_reason"]) == (True, None)
    assert rows[ids["abstract"]]["extractable"] is False
    assert "'abstract'" in rows[ids["abstract"]]["extract_blocked_reason"]
    assert rows[ids["odd"]]["extractable"] is False
    assert "'supplement'" in rows[ids["odd"]]["extract_blocked_reason"]


def test_cli_extract_refuses_abstract_only_without_a_job_dir(tmp_path: Path, capsys) -> None:
    data_dir, ids = _seeded(tmp_path, abstract=("abstract",))

    with pytest.raises(SystemExit) as excinfo:
        main(["extract", "--engine", "mock", "--doc-ids", ids["abstract"],
              "--data-dir", str(data_dir)])
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "extraction refused" in err and ids["abstract"] in err and "'abstract'" in err
    assert _run_rows(data_dir) == []
    assert _extract_job_dirs(data_dir) == []


def test_cli_extract_runs_an_observationless_upload(tmp_path: Path) -> None:
    data_dir, ids = _seeded(tmp_path, upload=())

    with pytest.raises(SystemExit) as excinfo:
        main(["extract", "--engine", "mock", "--doc-ids", ids["upload"],
              "--data-dir", str(data_dir)])
    assert excinfo.value.code == 0
    assert _run_rows(data_dir) == [(ids["upload"], "complete")]
