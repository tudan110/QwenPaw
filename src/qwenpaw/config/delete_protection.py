# -*- coding: utf-8 -*-
"""Narrow, one-way configuration change for the destructive-operation guard."""

from __future__ import annotations

import json
import os
import stat
from tempfile import NamedTemporaryFile

from . import utils
from ..extensions.api.delete_block_middleware import delete_ops_env_override


class DeleteProtectionConflict(Exception):
    """The file changed, is unsupported, or is not the effective source."""


def enable_delete_protection() -> bool:
    """Atomically enable the existing config setting, preserving unrelated keys.

    Only an explicit JSON false can be changed. No config repair, generated
    defaults or environment override is written by this operation.
    """
    with utils._config_lock:
        if delete_ops_env_override() is not None:
            raise DeleteProtectionConflict("部署环境变量覆盖此策略，请由运维变更。")
        path = utils.get_config_path().resolve()
        original = path.read_bytes()
        data = json.loads(original)
        security = data.get("security") if isinstance(data, dict) else None
        if not isinstance(security, dict):
            raise DeleteProtectionConflict("运行配置缺少安全配置段，未写入。")
        current = security.get("delete_ops_disabled")
        if current is True:
            return False
        if current is not False:
            raise DeleteProtectionConflict("运行配置不是可安全修改的显式布尔值，未写入。")
        security["delete_ops_disabled"] = True
        mode = stat.S_IMODE(path.stat().st_mode)
        temporary = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".delete-policy-", delete=False,
            ) as output:
                temporary = output.name
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, mode)
            if path.read_bytes() != original or delete_ops_env_override() is not None:
                raise DeleteProtectionConflict("配置已变更，请刷新后核对。")
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                os.unlink(temporary)
        # load_config reloads on mtime changes; invalidate explicitly here too.
        utils._config_cache = None
        utils._config_mtime = None
        return True
