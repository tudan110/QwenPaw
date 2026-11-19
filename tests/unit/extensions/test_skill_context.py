"""Bounded context artifacts with the real production path guards."""

import importlib.util
import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest

from test_report_export_flow import flow  # noqa: F401


@pytest.fixture
def context_tool(flow, monkeypatch):  # noqa: F811
    name = "qwenpaw.agents.tools.skill_context"
    source = Path(__file__).resolve().parents[3] / (
        "src/qwenpaw/agents/tools/skill_context.py"
    )
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", [{"名称": "路由器", "rows": [1]}, []])
async def test_json_created_in_fixed_workspace_context_directory(
    context_tool, tmp_path, value
):
    result = await context_tool.write_skill_context(
        json.dumps(value, ensure_ascii=False)
    )
    assert result.state == "ok"
    metadata = json.loads(result.content[0]["text"])
    path = Path(metadata["file_path"])
    assert path.parent == tmp_path / "artifacts/skill-context"
    assert path.suffix == ".json" and len(path.stem) == 32
    assert json.loads(path.read_text()) == value
    assert metadata["size_bytes"] == path.stat().st_size
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "content", ["{} trailing", "null", "1", '"text"', "[NaN]", "[Infinity]"]
)
async def test_invalid_or_non_structured_json_creates_no_artifact(
    context_tool, tmp_path, content
):
    result = await context_tool.write_skill_context(content)
    assert result.state == "error"
    assert not (tmp_path / "artifacts").exists()


async def test_context_tool_accepts_no_path_or_file_name(context_tool):
    with pytest.raises(TypeError):
        await context_tool.write_skill_context("{}", file_path="evil.py")


async def test_size_is_bounded_before_and_after_serialization(
    context_tool, tmp_path, monkeypatch
):
    monkeypatch.setattr(context_tool, "_MAX_BYTES", 16)
    for content in ('{"value":"过大的中文内容"}', '{"x": [1,2,3,4]}'):
        result = await context_tool.write_skill_context(content)
        assert result.state == "error"
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize("link", ["artifacts", "artifacts/skill-context"])
async def test_context_directory_symlinks_are_rejected(
    context_tool, tmp_path, link
):
    target = tmp_path / "other"
    target.mkdir()
    link_path = tmp_path / link
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(target, target_is_directory=True)
    result = await context_tool.write_skill_context("{}")
    assert result.state == "error"
    assert list(target.iterdir()) == []


def test_secret_directory_is_rejected(context_tool, tmp_path):
    secret = tmp_path / "secrets"
    secret.mkdir()
    with pytest.raises(PermissionError):
        context_tool._write_context("{}", secret)
    assert list(secret.iterdir()) == []


async def test_existing_file_is_never_overwritten(
    context_tool, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        context_tool.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32)
    )
    assert (
        await context_tool.write_skill_context('{"value":1}')
    ).state == "ok"
    result = await context_tool.write_skill_context('{"value":2}')
    assert result.state == "error"
    path = tmp_path / "artifacts/skill-context" / ("a" * 32 + ".json")
    assert json.loads(path.read_text()) == {"value": 1}


async def test_symlink_swap_during_directory_creation_is_rejected(
    context_tool, tmp_path, monkeypatch
):
    outside = tmp_path / "other"
    outside.mkdir()
    mkdir = context_tool.os.mkdir

    def swap(name, mode=0o777, *, dir_fd=None):
        if name == "artifacts":
            (tmp_path / "artifacts").symlink_to(
                outside, target_is_directory=True
            )
            raise FileExistsError(name)
        return mkdir(name, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(context_tool.os, "mkdir", swap)
    result = await context_tool.write_skill_context("{}")
    assert result.state == "error"
    assert list(outside.iterdir()) == []


async def test_context_tool_is_discovered(context_tool):
    from qwenpaw.runtime.tool_registry import get_builtin_tool_funcs

    assert context_tool.write_skill_context in get_builtin_tool_funcs()


async def test_context_preparation_does_not_grant_general_writes(context_tool):
    from qwenpaw.extensions.security import execution_policy

    assert (
        await execution_policy.check_tool(
            "write_skill_context", {"content": '{"rows":[]}'}
        )
        is False
    )
    with pytest.raises(PermissionError):
        await execution_policy.check_tool(
            "write_file", {"file_path": "context.json", "content": "{}"}
        )
