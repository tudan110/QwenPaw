"""Short-lived, one-use receipts bound to a canonical execution intent."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import defaultdict

POLICY_VERSION = "trusted-agent-v1"


def intent_digest(name: str, params: dict, actor: str, session: str, epoch: int) -> str:
    from pathlib import Path
    from qwenpaw.constant import WORKING_DIR, EnvVarLoader

    policy = Path(WORKING_DIR) / ".qwenpaw" / "policy.yaml"
    fingerprint = hashlib.sha256(
        policy.read_bytes() if policy.exists() else b""
    ).hexdigest()
    settings = [
        EnvVarLoader.get_str(key, "")
        for key in (
            "QWENPAW_READONLY_TOOL_NAMES",
            "QWENPAW_MCP_ALLOWED_URLS",
            "QWENPAW_EGRESS_RULES",
        )
    ]
    payload = json.dumps(
        [POLICY_VERSION, fingerprint, settings, name, params, actor, session, epoch],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def bind_resources(name: str, params: dict) -> dict:
    """Include resolved target and existing file contents in write approval."""
    from pathlib import Path
    from qwenpaw.constant import WORKING_DIR
    from qwenpaw.config.context import get_current_workspace_dir

    if name not in {"write_file", "edit_file", "append_file"}:
        return params
    path = (
        Path(get_current_workspace_dir() or WORKING_DIR)
        / str(params.get("file_path", ""))
    ).resolve()
    digest = "absent"
    if path.exists():
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise PermissionError("审批文件类型或体积超出受控范围")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"parameters": params, "resolved_target": str(path), "before_sha256": digest}


class ApprovalReceipts:
    """Lost on restart by design: an old approval can never resume execution."""

    def __init__(self):
        self._receipts = defaultdict(list)
        self._lock = threading.Lock()

    def issue(
        self,
        name: str,
        params: dict,
        actor: str,
        session: str,
        epoch: int,
        ttl: float = 300,
    ) -> str:
        digest = intent_digest(name, params, actor, session, epoch)
        with self._lock:
            now = time.monotonic()
            self._receipts = defaultdict(
                list,
                {
                    key: [expiry for expiry in entries if expiry > now]
                    for key, entries in self._receipts.items()
                    if any(expiry > now for expiry in entries)
                },
            )
            if sum(map(len, self._receipts.values())) >= 200:
                raise PermissionError("待执行审批过多，请重新申请")
            self._receipts[digest].append(now + ttl)
        return digest

    def consume(
        self, name: str, params: dict, actor: str, session: str, epoch: int
    ) -> None:
        digest = intent_digest(name, params, actor, session, epoch)
        with self._lock:
            entries = self._receipts.get(digest, [])
            while entries:
                if entries.pop(0) > time.monotonic():
                    return
        raise PermissionError("审批已消费、过期或执行意图/控制版本已变化，请重新审批")
