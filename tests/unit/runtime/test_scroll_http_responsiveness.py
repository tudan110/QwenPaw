# -*- coding: utf-8 -*-
"""Slow storage initialization must not block HTTP or leak on cancellation."""

import asyncio
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.runtime.builder import AgentBuilder


async def test_health_responds_while_history_initializes(
    monkeypatch, tmp_path
):
    entered, release = Event(), Event()
    built = []

    def initialize(*args, **kwargs):
        entered.set()
        release.wait(3)
        store = HistoryStore(tmp_path / "history.db")
        built.append(store)
        return SimpleNamespace(
            context_manager=SimpleNamespace(close=store.close)
        )

    monkeypatch.setattr(
        AgentBuilder, "_build_scroll_components", staticmethod(initialize)
    )
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"ok": True}

    task = asyncio.create_task(AgentBuilder._prepare_scroll_components())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await asyncio.wait_for(client.get("/health"), 0.5)
        assert response.status_code == 200
        assert not task.done()
    finally:
        release.set()
        await task
        for store in built:
            store.close()


async def test_cancelled_initialization_closes_its_eventual_connection(
    monkeypatch, tmp_path
):
    entered, release, closed = Event(), Event(), Event()

    def initialize():
        entered.set()
        release.wait(3)
        store = HistoryStore(tmp_path / "history.db")

        def close():
            store.close()
            closed.set()

        return SimpleNamespace(context_manager=SimpleNamespace(close=close))

    monkeypatch.setattr(
        AgentBuilder, "_build_scroll_components", staticmethod(initialize)
    )
    task = asyncio.create_task(AgentBuilder._prepare_scroll_components())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    assert await asyncio.to_thread(closed.wait, 1)
