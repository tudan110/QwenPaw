"""Pure integrity checks shared by execution and seed maintenance."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

CODE_SUFFIXES = {".py", ".so", ".pth"}


def relative_path(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe managed path: {value}")
    return path


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_skill(
    working: Path, manifest: dict[str, Any], skill: str
) -> dict[str, Any]:
    working = working.resolve()
    root = working / relative_path(skill)
    parts = Path(skill).parts
    if len(parts) != 4 or parts[0] != "workspaces" or parts[2] != "skills":
        raise ValueError(f"Not a managed skill root: {skill}")
    if any(
        path.is_symlink() for path in [root, *root.parents] if path != working
    ):
        return {
            "skill": skill,
            "execution_ready": False,
            "blockers": [{"code": "SYMLINK_BLOCKED", "path": skill}],
        }
    files = manifest.get("managed_skills", {}).get(skill, {}).get("files", {})
    if not isinstance(files, dict) or not files:
        return {
            "skill": skill,
            "execution_ready": False,
            "blockers": [{"code": "SKILL_NOT_DECLARED", "path": skill}],
        }
    blockers = []
    for name, expected in sorted(files.items()):
        relative = relative_path(name)
        if not relative.is_relative_to(Path(skill)):
            raise ValueError(f"Managed file outside skill: {name}")
        path = working / relative
        if any(
            parent.is_symlink()
            for parent in [path, *path.parents]
            if parent != working
        ):
            blockers.append({"code": "SYMLINK_BLOCKED", "path": name})
        elif not path.is_file():
            blockers.append({"code": "MANAGED_FILE_MISSING", "path": name})
        else:
            actual = file_hash(path)
            if actual != expected:
                blockers.append(
                    {
                        "code": "MANAGED_HASH_MISMATCH",
                        "path": name,
                        "expected": expected,
                        "actual": actual,
                    }
                )
    if root.is_symlink() or not root.resolve().is_relative_to(working):
        blockers.append({"code": "SYMLINK_BLOCKED", "path": skill})
    elif root.is_dir():
        for path in sorted(root.rglob("*")):
            name = str(path.relative_to(working))
            if path.is_symlink():
                blockers.append({"code": "SYMLINK_BLOCKED", "path": name})
            elif (
                path.is_file()
                and path.suffix in CODE_SUFFIXES
                and name not in files
            ):
                blockers.append(
                    {
                        "code": "UNDECLARED_CODE",
                        "path": name,
                        "sha256": file_hash(path),
                    }
                )
    return {
        "skill": skill,
        "execution_ready": not blockers,
        "blockers": blockers,
    }


def inspect_managed_skills(
    working: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    results = [
        inspect_skill(working, manifest, skill)
        for skill in sorted(manifest.get("managed_skills", {}))
    ]
    return {
        "execution_ready": all(item["execution_ready"] for item in results),
        "skills": results,
    }
