# -*- coding: utf-8 -*-
"""Forward request credentials to trusted local collaboration endpoints."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlsplit

from qwenpaw.constant import EnvVarLoader
from qwenpaw.extensions.api.inoe_settings_store import CURRENT_REQUEST_TOKEN
from qwenpaw.extensions.api.sso_auth import normalize_token
from qwenpaw.extensions.api.access_session import CURRENT_IDENTITY
from qwenpaw.sandbox import SandboxConfig

_REQUEST_TOKEN_ENV = "QWENPAW_REQUEST_INOE_TOKEN"
_ACCESS_TOKEN_ENV = "QWENPAW_REQUEST_ACCESS_TOKEN"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def get_request_token() -> str:
    token = CURRENT_REQUEST_TOKEN.get()
    if token is None:
        token = EnvVarLoader.get_str(_REQUEST_TOKEN_ENV, "") or ""
    return normalize_token(token)


def get_access_token() -> str:
    identity = CURRENT_IDENTITY.get()
    if identity is not None:
        return identity.access_token
    return EnvVarLoader.get_str(_ACCESS_TOKEN_ENV, "") or ""


def is_trusted_api_target(target_url: str, trusted_url: str) -> bool:
    target = urlsplit(target_url)
    if (
        target.scheme not in {"http", "https"}
        or target.username is not None
        or target.password is not None
    ):
        return False
    configured = [
        trusted_url,
        *EnvVarLoader.get_str("QWENPAW_INTERNAL_API_ORIGINS", "").split(","),
    ]
    for origin in configured:
        trusted = urlsplit(origin.strip())
        same_host = target.hostname == trusted.hostname or (
            target.hostname in _LOOPBACK_HOSTS
            and trusted.hostname in _LOOPBACK_HOSTS
        )
        default_port = 443 if target.scheme == "https" else 80
        if (
            target.scheme == trusted.scheme
            and same_host
            and (target.port or default_port) == (trusted.port or default_port)
        ):
            return True
    return False


def agent_api_headers(target_url: str, trusted_url: str) -> dict[str, str]:
    access_token = get_access_token()
    token = get_request_token()
    if not token and not access_token:
        return {}
    if not is_trusted_api_target(target_url, trusted_url) or urlsplit(
        target_url
    ).path.rstrip("/") not in {"", "/api", "/copaw-api/api"}:
        raise ValueError(
            "Refusing to forward INOE credentials to an untrusted agent API"
        )
    return (
        {"X-QwenPaw-Access-Token": access_token}
        if access_token
        else {"X-Inoe-Token": token}
    )


def subprocess_request_environment(
    environment: dict[str, str],
) -> dict[str, str]:
    """Override only the child environment; never mutate process globals."""
    result = environment.copy()
    for key in (
        _REQUEST_TOKEN_ENV,
        _ACCESS_TOKEN_ENV,
        "COPAW_REQUEST_INOE_TOKEN",
        "COPAW_REQUEST_ACCESS_TOKEN",
    ):
        result.pop(key, None)
    token = get_request_token()
    if token:
        result[_REQUEST_TOKEN_ENV] = token
        result["INOE_API_TOKEN"] = token
    access_token = get_access_token()
    if access_token:
        result[_ACCESS_TOKEN_ENV] = access_token
    return result


def sandbox_request_environment(config: SandboxConfig) -> SandboxConfig:
    """Preserve explicit credential masks and environment allowlists."""
    token = get_request_token()
    if not token:
        return config
    keys = (_REQUEST_TOKEN_ENV, "INOE_API_TOKEN", _ACCESS_TOKEN_ENV)
    if any(config.env_vars.get(key) == "" for key in keys):
        return config
    env = config.env_vars.copy()
    for key in keys:
        if config.env_mode != "allowlist" or key in env:
            value = get_access_token() if key == _ACCESS_TOKEN_ENV else token
            if value:
                env[key] = value
            elif (
                key == _ACCESS_TOKEN_ENV and CURRENT_IDENTITY.get() is not None
            ):
                env[key] = ""
    return replace(config, env_vars=env)
