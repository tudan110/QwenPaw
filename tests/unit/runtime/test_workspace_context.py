"""Workspace context must be visible to tools and scoped to a stream step."""
import asyncio
from types import SimpleNamespace

import pytest

from qwenpaw.config.context import current_workspace_dir, get_current_workspace_dir
from qwenpaw.runtime.runtime import Runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("close_early", [False, True])
async def test_workspace_context_is_inherited_and_restored(tmp_path, monkeypatch, close_early):
    workspace = tmp_path / "agent"
    outer = tmp_path / "outer"
    runtime = Runtime(workspace=None, app_services=None)
    monkeypatch.setattr(runtime, "_normalize", lambda request: request)
    monkeypatch.setattr(runtime, "_build_context", lambda request: SimpleNamespace(workspace_dir=workspace))
    cleaned_up = []

    async def read_in_child():
        return get_current_workspace_dir()

    async def run(_ctx):
        try:
            assert get_current_workspace_dir() == workspace
            yield await asyncio.create_task(read_in_child())
        finally:
            cleaned_up.append(get_current_workspace_dir())

    monkeypatch.setattr(runtime, "_run", run)
    token = current_workspace_dir.set(outer)
    try:
        stream = runtime.run(None)
        assert await anext(stream) == workspace
        assert get_current_workspace_dir() == outer
        if close_early:
            await asyncio.create_task(stream.aclose())
        else:
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
        assert cleaned_up == [workspace]
        assert get_current_workspace_dir() == outer
    finally:
        current_workspace_dir.reset(token)
