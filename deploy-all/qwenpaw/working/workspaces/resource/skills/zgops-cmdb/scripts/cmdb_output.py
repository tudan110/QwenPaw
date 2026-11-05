"""Redact CMDB credentials at CLI output boundaries, not in HTTP requests."""

from __future__ import annotations

import builtins
import json
import os
import re
import sys
from collections.abc import Callable
from typing import Any, TextIO


MASK = "[REDACTED]"
_SECRET_NAMES = (
    r"bearer[_-]?token|login[_-]?(?:pwd|password)|password|passwd|pwd|"
    r"(?:access|refresh)[_-]?token|token|api[_-]?key|"
    r"(?:client[_-]?)?secret|private[_-]?key|authorization"
)
_SECRET_KEY = re.compile(rf"(?:{_SECRET_NAMES})", re.IGNORECASE)
_TEXT_SECRET = re.compile(
    rf"""(?<![\w])(?P<label>["']?(?:{_SECRET_NAMES})["']?[ \t]*[:=][ \t]*)"""
    r"""(?P<value>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\r\n]+)""",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer[ \t]+[^\s,;\"'<>]+", re.IGNORECASE)


def redact_output(value: Any) -> Any:
    """Return a redacted copy, including nested JSON and credential text."""
    if isinstance(value, dict):
        return {
            key: (
                MASK
                if isinstance(key, str) and _SECRET_KEY.fullmatch(key)
                else redact_output(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_output(item) for item in value]
    if not isinstance(value, str):
        return value

    text = value
    if text.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            redacted = redact_output(parsed)
            if redacted != parsed:
                return json.dumps(redacted, ensure_ascii=False, indent=2)
            return text
    text = _TEXT_SECRET.sub(
        lambda match: match.group("label") + json.dumps(MASK), text
    )
    text = _BEARER.sub("Bearer " + MASK, text)
    token = os.environ.get("INOE_API_TOKEN", "")
    if token:
        text = text.replace(token, MASK)
    return text


def safe_print(
    *values: Any,
    sep: str = " ",
    end: str = "\n",
    file: TextIO | None = None,
    flush: bool = False,
) -> None:
    text = sep.join(str(value) for value in values)
    builtins.print(redact_output(text), end=end, file=file, flush=flush)


def run_cli(main: Callable[[], int]) -> int:
    """Report CLI failures without dumping raw response bodies in tracebacks."""
    try:
        return main()
    except Exception as error:
        safe_print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
