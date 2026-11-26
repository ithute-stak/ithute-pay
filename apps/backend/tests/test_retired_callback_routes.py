from fastapi import FastAPI
from api.v1.router import api_router


def test_retired_callback_is_not_registered():
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    assert not any("golink" in route.path.lower() for route in app.routes)
