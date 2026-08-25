from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from ontologylab.server.app import create_app
from tests.conftest import drop_test_session

_PARAM_RE = re.compile(r"\{[^}]+\}")


def _api_routes(app) -> list[APIRoute]:
    routes: list[APIRoute] = []
    for route in app.routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            routes.extend(
                item for item in original.routes if isinstance(item, APIRoute)
            )
        elif isinstance(route, APIRoute):
            routes.append(route)
    return routes


def _concrete_path(path: str) -> str:
    return _PARAM_RE.sub("x", path)


def test_every_api_route_requires_session(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    client = drop_test_session(TestClient(app))
    routes = [route for route in _api_routes(app) if route.path.startswith("/api/")]

    assert len(routes) == 86, [
        (route.path, sorted(route.methods or ())) for route in routes
    ]

    health = client.get("/healthz")
    assert health.status_code == 200, health.text
    assert health.json() == {"ok": True}

    for route in routes:
        path = _concrete_path(route.path)
        for method in sorted(route.methods or ()):
            kwargs = {"json": {}} if method not in {"GET", "HEAD", "OPTIONS"} else {}
            response = client.request(method, path, **kwargs)
            assert response.status_code == 401, (
                method,
                route.path,
                response.status_code,
                response.text,
            )
            assert response.json()["error_kind"] == "unauthenticated"
            assert "default_engine" not in response.text

    for path in sorted({route.path for route in routes}):
        concrete = _concrete_path(path)
        for method in ("HEAD", "OPTIONS"):
            response = client.request(method, concrete)
            assert response.status_code == 401, (
                method,
                path,
                response.status_code,
                response.text,
            )
