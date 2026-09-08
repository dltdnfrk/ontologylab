"""HTTP route failures expose typed summaries, never exception text."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ontologylab.server import routes
from ontologylab.server.app import create_app
from ontologylab.work_view import WorkNotFound

SECRET = "route-secret-must-not-surface-84c1"


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path / "data",
            packs_dir=tmp_path / "packs",
        )
    )


def test_reconciliation_failure_does_not_echo_its_identifier(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_inspection(*_args, **_kwargs):
        raise WorkNotFound(SECRET)

    monkeypatch.setattr(
        "ontologylab.reconciliation.inspect_work",
        fail_inspection,
    )

    response = _client(tmp_path).get(f"/api/reconcile/works/{SECRET}")

    assert response.status_code == 404
    assert SECRET not in response.text
    assert response.json()["detail"] == "unexpected WorkNotFound"


def test_pack_failure_does_not_echo_filesystem_exception_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_build(*_args, **_kwargs):
        raise OSError(f"/private/secret/{SECRET}/pack.sqlite")

    monkeypatch.setattr(routes, "build_pack_release", fail_build)

    response = _client(tmp_path).post(
        "/api/packs/build",
        json={"name": "safe-error"},
    )

    assert response.status_code == 200
    assert SECRET not in response.text
    assert response.json()["detail"] == (
        "a network or filesystem operation failed"
    )
