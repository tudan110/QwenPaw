import pytest
import httpx
from fastapi import FastAPI, Request

from qwenpaw.extensions.api.access_session import AccessIdentity
from qwenpaw.app.routers import execution_control as api
from qwenpaw.extensions.security.execution_control import ControlStore


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "7")
    store = ControlStore(tmp_path / "control.db")
    monkeypatch.setattr(api, "get_control_store", lambda: store)
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        if request.headers.get("fixture-identity"):
            request.state.access_identity = AccessIdentity(
                user={"userId": request.headers["fixture-identity"]},
                inoe_token="fixture",
            )
        return await call_next(request)

    app.include_router(api.router, prefix="/api")
    return app


async def test_control_requires_existing_trusted_admin_and_version(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/security/control")).status_code == 403
        assert (
            await client.get("/api/security/control", headers={"fixture-identity": "8"})
        ).status_code == 403
        headers = {"fixture-identity": "7"}
        assert (await client.get("/api/security/control", headers=headers)).json()[
            "epoch"
        ] == 0
        response = await client.post(
            "/api/security/control/freeze",
            headers=headers,
            json={"expected_epoch": 0, "reason": "incident"},
        )
        assert response.status_code == 200
        assert response.json()["frozen"] == 1
        assert response.json()["remote_effects"] == "unknown"
        assert (
            await client.post(
                "/api/security/control/unfreeze",
                headers=headers,
                json={"expected_epoch": 0, "reason": "stale"},
            )
        ).status_code == 409
        assert (
            await client.post(
                "/api/security/control/unfreeze",
                headers=headers,
                json={"expected_epoch": 1, "reason": "recovered"},
            )
        ).json()["frozen"] == 0
