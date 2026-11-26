from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.v1.router import api_router


def test_retired_callback_is_not_registered():
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    paths = app.openapi()["paths"]
    assert paths
    assert not any("golink" in path.lower() for path in paths)
    with TestClient(app) as client:
        response = client.post("/api/v1/provider-callbacks/golink", json={})
        assert response.status_code == 404
