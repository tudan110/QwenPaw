"""Filesystem paths for the knowledge_kb subsystem.

All KB state lives under qwenpaw's working dir, sharing the same PVC as
agents/workspaces.
"""

from __future__ import annotations

from pathlib import Path

from qwenpaw.constant import WORKING_DIR

# Knowledge agent that drives LLM/embedding configuration.
KNOWLEDGE_AGENT_ID = "knowledge"


def kb_root() -> Path:
    """Return the root data directory for the KB subsystem.

    Resolved at call time (not import time) so the dir reflects any
    runtime override of WORKING_DIR.
    """
    root = Path(WORKING_DIR) / "knowledge_kb"
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_dir() -> Path:
    return kb_root()


def upload_dir() -> Path:
    p = kb_root() / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return kb_root() / "knowledge.db"


def builtin_kb_dir() -> Path:
    """Return the packaged builtin_kb directory shipped with the module."""
    return Path(__file__).resolve().parent / "builtin_kb"
