"""Versioned, append-only SQLite audit chain and external checkpoint verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from itertools import zip_longest

EVENT_FIELDS = (
    "ts, workspace_dir, agent_id, session_id, tool_name, target, "
    "decision, reason, extra"
)
_ORIGIN = "audit_chain_origin"
_SEALS = "audit_chain_seals"
_TABLES = {
    _ORIGIN: f"""CREATE TABLE {_ORIGIN} (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        ledger_id TEXT NOT NULL, sealed_at TEXT NOT NULL,
        legacy_through INTEGER NOT NULL
    )""",
    _SEALS: f"""CREATE TABLE {_SEALS} (
        event_rowid INTEGER PRIMARY KEY, digest TEXT NOT NULL
    )""",
}
# The INSERT guard also blocks INSERT OR REPLACE, even when SQLite's
# recursive_triggers option is off on a different writer's connection.
_TRIGGERS = {}
for table, key in (
    ("audit_events", "rowid"),
    (_ORIGIN, "singleton"),
    (_SEALS, "event_rowid"),
):
    for operation in ("update", "delete", "insert"):
        name = f"{table}_protect_{operation}"
        predicate = (
            f" WHEN EXISTS (SELECT 1 FROM {table} WHERE {key} = NEW.{key})"
            if operation == "insert"
            else ""
        )
        _TRIGGERS[name] = (
            f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON {table}{predicate} "
            "BEGIN SELECT RAISE(ABORT, 'audit storage is append-only'); END"
        )
_SCHEMA_OBJECTS = {**_TABLES, **_TRIGGERS}
CHECKPOINT_PATTERN = r"[0-9a-f]{32}:(?:0|[1-9][0-9]{0,18}):[0-9a-f]{64}"


def _hash(*parts) -> str:
    # SQLite permits BLOB values even in a TEXT column. Keep the digest
    # deterministic for preserved legacy data and detect an altered type.
    def encode_blob(value):
        if isinstance(value, bytes):
            return {"sqlite_blob": value.hex()}
        raise TypeError("Unexpected audit storage value")

    return hashlib.sha256(
        json.dumps(
            ("qwenpaw-audit-v1", *parts),
            ensure_ascii=True,
            separators=(",", ":"),
            default=encode_blob,
        ).encode("ascii")
    ).hexdigest()


def _schema_state(conn: sqlite3.Connection) -> str:
    names = ",".join("?" for _ in _SCHEMA_OBJECTS)
    existing = {
        row[0]: row[1]
        for row in conn.execute(
            f"SELECT name, sql FROM sqlite_master WHERE name IN ({names})",
            tuple(_SCHEMA_OBJECTS),
        )
    }
    if not existing:
        return "unsealed"
    return "protected" if existing == _SCHEMA_OBJECTS else "protection_missing"


def _origin(conn: sqlite3.Connection) -> tuple:
    row = conn.execute(
        f"SELECT ledger_id, sealed_at, legacy_through FROM {_ORIGIN} WHERE singleton = 1"
    ).fetchone()
    if row is None:
        raise sqlite3.IntegrityError("audit chain origin missing")
    return tuple(row)


def _tail(conn: sqlite3.Connection, origin: tuple) -> tuple[int, str]:
    row = conn.execute(
        f"SELECT event_rowid, digest FROM {_SEALS} ORDER BY event_rowid DESC LIMIT 1"
    ).fetchone()
    return tuple(row) if row is not None else (0, _hash("origin", *origin))


def _last_event(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM audit_events").fetchone()[
        0
    ]


def install(conn: sqlite3.Connection) -> None:
    """Seal history as a migration baseline, once, inside the caller's transaction."""
    state = _schema_state(conn)
    if state == "protected":
        origin = _origin(conn)
        if _tail(conn, origin)[0] != _last_event(conn):
            raise sqlite3.IntegrityError("audit chain tail mismatch")
        return
    if state != "unsealed":
        raise sqlite3.IntegrityError("audit protection schema changed")
    for sql in _TABLES.values():
        conn.execute(sql)
    origin = (
        uuid.uuid4().hex,
        datetime.now(timezone.utc).isoformat(),
        _last_event(conn),
    )
    conn.execute(f"INSERT INTO {_ORIGIN} VALUES (1, ?, ?, ?)", origin)
    previous = _hash("origin", *origin)
    for row in conn.execute(
        f"SELECT rowid, {EVENT_FIELDS} FROM audit_events ORDER BY rowid"
    ):
        previous = _hash("event", previous, tuple(row))
        conn.execute(f"INSERT INTO {_SEALS} VALUES (?, ?)", (row[0], previous))
    for sql in _TRIGGERS.values():
        conn.execute(sql)
    # The TEXT-timestamp original is retained for recovery, not used by the
    # live ledger; protect it against row edits as well if it exists.
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_events_legacy'",
    ).fetchone():
        for op in ("UPDATE", "DELETE", "INSERT"):
            conn.execute(
                f"CREATE TRIGGER audit_events_legacy_protect_{op.lower()} "
                f"BEFORE {op} ON audit_events_legacy "
                "BEGIN SELECT RAISE(ABORT, 'audit storage is append-only'); END",
            )


def append(conn: sqlite3.Connection, values: tuple) -> None:
    """Write event and seal atomically; caller holds a BEGIN IMMEDIATE transaction."""
    if _schema_state(conn) != "protected":
        raise sqlite3.IntegrityError("audit protection unavailable")
    tail_id, previous = _tail(conn, _origin(conn))
    if tail_id != _last_event(conn):
        raise sqlite3.IntegrityError("audit chain tail mismatch")
    rowid = conn.execute(
        f"INSERT INTO audit_events ({EVENT_FIELDS}) VALUES (?,?,?,?,?,?,?,?,?)",
        values,
    ).lastrowid
    conn.execute(
        f"INSERT INTO {_SEALS} VALUES (?, ?)",
        (
            rowid,
            _hash("event", previous, (rowid, *values)),
        ),
    )


def status(conn: sqlite3.Connection) -> dict:
    state = _schema_state(conn)
    if state != "protected":
        return {"state": state}
    try:
        origin = _origin(conn)
    except sqlite3.IntegrityError:
        return {"state": "protection_missing"}
    return {
        "state": (
            "protected"
            if _tail(conn, origin)[0] == _last_event(conn)
            else "tail_mismatch"
        ),
        "sealed_at": origin[1],
        "legacy_through": origin[2],
    }


def verify(conn: sqlite3.Connection, checkpoint: str | None = None) -> dict:
    info = status(conn)
    if info["state"] != "protected":
        return {
            **info,
            "checked_events": 0,
            "external_match": False if checkpoint else None,
        }
    origin = _origin(conn)
    ledger_id = origin[0]
    prefix, anchor_id, anchor_hash = (
        checkpoint.split(":") if checkpoint else (None, "0", None)
    )
    previous = _hash("origin", *origin)
    matched = prefix == ledger_id and anchor_id == "0" and anchor_hash == previous
    events = conn.execute(
        f"SELECT rowid, {EVENT_FIELDS} FROM audit_events ORDER BY rowid"
    )
    seals = conn.execute(
        f"SELECT event_rowid, digest FROM {_SEALS} ORDER BY event_rowid"
    )
    count, last_id = 0, 0
    for event, seal in zip_longest(events, seals):
        if event is None or seal is None:
            rowid = (event if event is not None else seal)[0]
            return {
                **info,
                "state": "mismatch",
                "checked_events": count,
                "first_bad_id": rowid,
                "external_match": False if checkpoint else None,
            }
        rowid = event[0]
        previous = _hash("event", previous, tuple(event))
        if (rowid, previous) != tuple(seal):
            return {
                **info,
                "state": "mismatch",
                "checked_events": count,
                "first_bad_id": rowid,
                "external_match": False if checkpoint else None,
            }
        count, last_id = count + 1, rowid
        if prefix == ledger_id and anchor_id == str(rowid):
            matched = anchor_hash == previous
    # A missing/misaligned middle row trips the pair comparison; additional
    # trailing rows on either side are also covered by the tail check above.
    result = {
        **info,
        "state": "verified",
        "checked_events": count,
        "external_match": matched if checkpoint else None,
    }
    if checkpoint and not matched:
        return {**result, "state": "checkpoint_mismatch"}
    return {**result, "checkpoint": f"{ledger_id}:{last_id}:{previous}"}


def valid_checkpoint(value: str) -> bool:
    return re.fullmatch(CHECKPOINT_PATTERN, value) is not None


def retention_policy() -> dict:
    configured = os.getenv("QWENPAW_AUDIT_EXTENDED_RETENTION_MONTHS", "36")
    valid = (
        re.fullmatch(r"[0-9]{2,4}", configured) is not None and int(configured) >= 36
    )
    return {
        "minimum_months": 6,
        "extended_months": int(configured) if valid else 36,
        "valid_configuration": valid,
        "local_auto_purge": False,
        "archive_status": "not_verified",
    }
