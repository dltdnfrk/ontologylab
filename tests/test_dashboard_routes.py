from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab.server.app import create_app
from ontologylab.web_assets import verify_assets
from tests.conftest import drop_test_session


@pytest.mark.parametrize(
    "path",
    ["/", "/sources", "/review", "/packs", "/artifacts", "/mcp",
     "/merge", "/communities", "/graph", "/engines", "/settings"],
)
def test_dashboard_deep_link_bootstraps_the_app_and_local_session(
    tmp_path: Path, path: str,
) -> None:
    client = drop_test_session(TestClient(
        create_app(data_dir=tmp_path / "data"), base_url="http://127.0.0.1",
    ))

    response = client.get(path)

    assert response.status_code == 200
    assert response.content == verify_assets().content["index.html"]
    assert response.headers["cache-control"] == "no-store"
    assert "ontologylab_session" in response.cookies
    assert client.get("/api/proposals").status_code == 200


@pytest.mark.parametrize("path", ["/not-a-page", "/api/not-a-route", "/static/nope.js"])
def test_dashboard_routing_does_not_hide_unknown_paths(tmp_path: Path, path: str) -> None:
    client = TestClient(create_app(data_dir=tmp_path / "data"))

    response = client.get(path)

    assert response.status_code == 404
