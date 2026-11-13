"""Mask configuration responses and preserve unchanged secrets on edits."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from ...drivers.adapters.mcp_binding import PUBLIC_HEADER_KEYS

MASK = "***"


def _secret_key(key: str) -> bool:
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower().replace("-", "_")
    return key in {
        "key",
        "token",
        "password",
        "passwd",
        "secret",
        "authorization",
        "cookie",
        "api_key",
        "access_key",
        "secret_key",
        "private_key",
        "encrypt_key",
        "encryption_key",
    } or key.endswith(
        (
            "_token",
            "_password",
            "_passwd",
            "_secret",
            "_api_key",
            "_access_key",
            "_secret_key",
            "_private_key",
            "_encrypt_key",
            "_encryption_key",
        )
    )


def _sensitive_field(key: str, *, environment: bool, headers: bool) -> bool:
    return (
        environment
        or _secret_key(key)
        or (headers and key.strip().lower() not in PUBLIC_HEADER_KEYS)
    )


def redact_configuration(
    value: Any, *, environment: bool = False, headers: bool = False
) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            sensitive = _sensitive_field(
                key, environment=environment, headers=headers
            )
            result[key] = (
                (MASK if item else item)
                if isinstance(item, str) and sensitive
                else redact_configuration(
                    item,
                    environment=sensitive or key == "env",
                    headers=key.lower() == "headers",
                )
            )
        return result
    if isinstance(value, list):
        return [
            redact_configuration(
                item, environment=environment, headers=headers
            )
            for item in value
        ]
    if environment and isinstance(value, str) and value:
        return MASK
    return value


def restore_configuration_secrets(
    value: Any,
    previous: Any,
    *,
    environment: bool = False,
    headers: bool = False,
) -> Any:
    if isinstance(value, dict):
        previous = previous if isinstance(previous, dict) else {}
        result = {}
        for key, item in value.items():
            sensitive = _sensitive_field(
                key, environment=environment, headers=headers
            )
            prior = previous.get(key)
            if headers and key not in previous:
                prior = next(
                    (
                        v
                        for k, v in previous.items()
                        if k.lower() == key.lower()
                    ),
                    None,
                )
            result[key] = (
                deepcopy(prior if prior is not None else "")
                if item == MASK and sensitive
                else restore_configuration_secrets(
                    item,
                    prior,
                    environment=sensitive or key == "env",
                    headers=key.lower() == "headers",
                )
            )
        return result
    if isinstance(value, list):
        old = previous if isinstance(previous, list) else []
        restored = []
        for index, item in enumerate(value):
            identity = next(
                (
                    key
                    for key in ("id", "name")
                    if isinstance(item, dict) and key in item
                ),
                None,
            )
            if identity:
                prior = next(
                    (
                        entry
                        for entry in old
                        if isinstance(entry, dict)
                        and entry.get(identity) == item[identity]
                    ),
                    None,
                )
            else:
                prior = old[index] if index < len(old) else None
            restored.append(
                restore_configuration_secrets(
                    item, prior, environment=environment, headers=headers
                )
            )
        return restored
    if environment and value == MASK:
        return deepcopy(previous if previous is not None else "")
    return value
