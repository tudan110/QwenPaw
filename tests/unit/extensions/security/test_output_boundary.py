import json

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from qwenpaw.extensions.security.output_guard.response_boundary import (
    OutputBoundaryMiddleware,
)


def test_sse_split_secret_never_reaches_http_client(monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    app = FastAPI()
    app.add_middleware(OutputBoundaryMiddleware)

    @app.get("/api/console/chat")
    async def chat():
        async def chunks():
            for text in ["sk-", "test1234567890abcdefghijklmn"]:
                yield "data: " + json.dumps(
                    {"choices": [{"delta": {"content": text}}]}
                ) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    response = TestClient(app).get("/api/console/chat")
    assert "test1234567890abcdefghijklmn" not in response.text
    assert "OUTPUT_SECURITY_BLOCKED" in response.text


def test_json_business_output_is_redacted_but_session_exchange_is_untouched():
    app = FastAPI()
    app.add_middleware(OutputBoundaryMiddleware)

    @app.get("/api/portal/knowledge-base/query")
    async def query():
        return {"answer": "password=secretpass123"}

    @app.get("/api/portal/sso/exchange")
    async def exchange():
        return {"access_token": "session-value"}

    client = TestClient(app)
    assert "secretpass123" not in client.get("/api/portal/knowledge-base/query").text
    assert (
        client.get("/api/portal/sso/exchange").json()["access_token"] == "session-value"
    )
