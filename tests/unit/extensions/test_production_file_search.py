"""Real search workers and production policy; unrelated runtime is stubbed."""

import importlib.util
import re
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

from test_report_export_flow import flow  # noqa: F401


@pytest.fixture
def search(flow, monkeypatch, tmp_path):
    file_io = ModuleType("qwenpaw.agents.tools.file_io")
    file_io._resolve_file_path = lambda value: str(tmp_path / value)
    monkeypatch.setitem(sys.modules, file_io.__name__, file_io)
    name = "qwenpaw.agents.tools.file_search"
    source = Path(__file__).resolve().parents[3] / (
        "src/qwenpaw/agents/tools/file_search.py"
    )
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_normal_search_is_allowed_without_admin(flow, tmp_path):
    for name in ("grep_search", "glob_search"):
        assert await flow.policy.check_tool(name, {"pattern": "**/*"}) is False
        assert (
            await flow.policy.check_tool(
                name, {"path": str(tmp_path), "pattern": "*.md"}
            )
            is False
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["../outside", ".env", ".env.local", "secrets", "backups"]
)
async def test_search_rejects_sensitive_or_external_roots(flow, path):
    for name in ("grep_search", "glob_search"):
        with pytest.raises(PermissionError):
            await flow.policy.check_tool(name, {"path": path, "pattern": "*"})


@pytest.mark.asyncio
@pytest.mark.parametrize("pattern", ["../*", "**/../../*", "/tmp/*"])
async def test_glob_rejects_traversal_patterns(flow, pattern):
    with pytest.raises(PermissionError):
        await flow.policy.check_tool("glob_search", {"pattern": pattern})


@pytest.mark.asyncio
async def test_search_rejects_symlink_root(flow, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "alias").symlink_to(
        tmp_path / "docs", target_is_directory=True
    )
    for name in ("grep_search", "glob_search"):
        with pytest.raises(PermissionError):
            await flow.policy.check_tool(
                name, {"path": "alias", "pattern": "*"}
            )


def test_recursive_search_filters_secrets_and_links(search, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/readme.md").write_text("needle public")
    (tmp_path / "docs/.env").write_text("needle secret")
    (tmp_path / "docs/.env.production").write_text("needle secret")
    (tmp_path / "docs/auth.json").write_text("needle credential")
    (tmp_path / "docs/key.pem").write_text("needle private")
    (tmp_path / "docs/.ssh").mkdir()
    (tmp_path / "docs/.ssh/config").write_text("needle ssh")
    (tmp_path / "linked.txt").symlink_to(tmp_path / "docs/.env")
    (tmp_path / "alias").symlink_to(
        tmp_path / "docs", target_is_directory=True
    )
    cancel = threading.Event()
    matches, _ = search._walk_and_grep(
        tmp_path, re.compile("needle"), 0, cancel, None
    )
    assert matches == ["docs/readme.md:1:> needle public"]
    entries, _ = search._walk_and_glob(tmp_path, "**/*", cancel)
    assert entries == ["docs/", "docs/readme.md"]
    entries, _ = search._walk_and_glob(tmp_path, "alias/*", cancel)
    assert entries == []
    entries, _ = search._walk_and_glob(tmp_path, "*/", cancel)
    assert entries == ["docs/"]


def test_single_file_worker_filters_secrets(search, tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("needle secret")
    matches, _ = search._walk_and_grep(
        secret, re.compile("needle"), 0, threading.Event(), None
    )
    assert matches == []


def test_disabled_guard_preserves_existing_search(
    search, monkeypatch, tmp_path
):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    (tmp_path / ".env").write_text("needle secret")
    matches, _ = search._walk_and_grep(
        tmp_path, re.compile("needle"), 0, threading.Event(), None
    )
    assert matches == [".env:1:> needle secret"]


@pytest.mark.parametrize(
    "pattern", ["**/*.md", "docs/**", "d*/*.md", "**/.*", "*/", "**/**"]
)
def test_safe_glob_preserves_normal_patterns(search, tmp_path, pattern):
    (tmp_path / "docs/nested").mkdir(parents=True)
    for name in (
        "root.md",
        "docs/readme.md",
        "docs/.hidden",
        "docs/nested/a.md",
    ):
        (tmp_path / name).write_text("public")
    expected = sorted(
        str(entry.relative_to(tmp_path)) + ("/" if entry.is_dir() else "")
        for entry in tmp_path.glob(pattern)
    )
    actual, _ = search._walk_and_glob(tmp_path, pattern, threading.Event())
    assert actual == expected


@pytest.mark.asyncio
async def test_empty_pattern_keeps_validation_response(search):
    for tool in (search.grep_search, search.glob_search):
        result = await tool("")
        assert "provided" in result.content[0]["text"]
