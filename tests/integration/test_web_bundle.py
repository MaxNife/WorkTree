"""The committed web bundle (web/dist) is served by FastAPI as a single-page app."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import WEB_DIST

pytestmark = pytest.mark.skipif(
    not WEB_DIST.exists(), reason="web bundle not built (npm run build)"
)


def test_index_is_served_at_the_root_and_for_client_side_routes(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert 'id="app"' in root.text
    # A deep link to a client-side route falls back to index.html.
    assert client.get("/design").text == root.text


def test_hashed_assets_are_served_with_the_right_type(client: TestClient) -> None:
    index = client.get("/").text
    script = re.search(r'src="(/assets/[^"]+\.js)"', index)
    assert script, "index.html must reference a built script"
    asset = client.get(script.group(1))
    assert asset.status_code == 200
    assert "javascript" in asset.headers["content-type"]
    assert client.get("/favicon.svg").status_code == 200


def test_unknown_api_paths_stay_json_errors_not_the_app(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_paths_cannot_escape_the_bundle_folder(client: TestClient) -> None:
    for attempt in (
        "/..%2f..%2fpyproject.toml",
        "/%2e%2e/%2e%2e/pyproject.toml",
        "/assets/..%2f..%2f..%2fpyproject.toml",
    ):
        response = client.get(attempt)
        assert "[project]" not in response.text
        assert "uaf" not in response.text.lower() or 'id="app"' in response.text
