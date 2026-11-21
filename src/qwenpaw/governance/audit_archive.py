"""Prepare a verified SQLite snapshot for upload to an independent WORM store."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..constant import WORKING_DIR
from .audit_integrity import retention_policy, valid_checkpoint, verify


def archive(source: Path, destination: Path, checkpoint: str | None = None) -> Path:
    if not source.is_file():
        raise ValueError("Audit database does not exist")
    if not destination.is_dir() or destination.resolve().is_relative_to(
        source.parent.resolve()
    ):
        raise ValueError(
            "Use an existing staging directory outside the live audit directory"
        )
    if checkpoint is not None and not valid_checkpoint(checkpoint):
        raise ValueError("Invalid external audit checkpoint")
    policy = retention_policy()
    if not policy["valid_configuration"]:
        raise ValueError(
            "Correct QWENPAW_AUDIT_EXTENDED_RETENTION_MONTHS before archiving"
        )
    now = datetime.now(timezone.utc)
    batch_name = f"critical-audit-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex}"
    # sqlite3.backup includes committed WAL frames. The immutable copy is
    # staged only after verification and uses DELETE mode (single-file restore).
    with tempfile.TemporaryDirectory(prefix=".audit-", dir=destination) as temp:
        staged = Path(temp) / batch_name
        staged.mkdir(mode=0o700)
        snapshot = staged / "audit.db"
        snapshot.touch(mode=0o600, exist_ok=False)
        with (
            closing(
                sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
            ) as live,
            closing(sqlite3.connect(snapshot)) as copy,
        ):
            live.backup(copy)
            copy.execute("PRAGMA journal_mode=DELETE")
            copy.execute("BEGIN")
            result = verify(copy, checkpoint)
        if result["state"] != "verified":
            raise ValueError(f"Snapshot integrity check failed: {result['state']}")
        manifest = {
            **result,
            "archived_snapshot_at_utc": now.isoformat(),
            "recommended_lock_months": policy["extended_months"],
        }
        manifest_path = staged / "manifest.json"
        with os.fdopen(
            os.open(manifest_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
            "w",
            encoding="utf-8",
        ) as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        final = destination / batch_name
        staged.rename(final)
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination", type=Path, help="Existing restricted staging directory"
    )
    parser.add_argument(
        "--database", type=Path, default=WORKING_DIR / "governance" / "audit.db"
    )
    parser.add_argument(
        "--previous-manifest",
        type=Path,
        help="Manifest fetched from an independently locked store",
    )
    args = parser.parse_args()
    try:
        checkpoint = None
        if args.previous_manifest is not None:
            checkpoint = json.loads(args.previous_manifest.read_text(encoding="utf-8"))[
                "checkpoint"
            ]
            if not isinstance(checkpoint, str):
                raise ValueError("Invalid external audit checkpoint")
        result = archive(args.database, args.destination, checkpoint)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.exit(1, f"Audit snapshot not staged: {exc}\n")
    print(f"Snapshot staged, not independently archived: {result}")


if __name__ == "__main__":
    main()
