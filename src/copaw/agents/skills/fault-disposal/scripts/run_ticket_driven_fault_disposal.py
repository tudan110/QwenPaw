#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path


def _load_fault_disposal_app():
    skill_root = Path(__file__).resolve().parents[1]
    runtime_app = skill_root / "runtime" / "app.py"
    if runtime_app.exists():
        if str(skill_root) not in sys.path:
            sys.path.insert(0, str(skill_root))
        from runtime.app import FaultDisposalAgentApp

        return FaultDisposalAgentApp

    raise FileNotFoundError(
        "Cannot resolve fault-disposal skill runtime app.",
    )


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _decode_payload(raw_value: str) -> dict:
    decoded = base64.b64decode(raw_value.encode("utf-8")).decode("utf-8")
    return json.loads(decoded)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Skill wrapper for ticket-driven fault disposal",
    )
    parser.add_argument(
        "command",
        choices=["diagnose", "diagnose-stream", "execute-action"],
    )
    parser.add_argument("--payload-base64", required=True)
    args = parser.parse_args()

    payload = _decode_payload(args.payload_base64)
    app = _load_fault_disposal_app()()

    if args.command == "diagnose":
        result = app.diagnose(payload)
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return

    if args.command == "diagnose-stream":
        for event in app.diagnose_stream(payload):
            print(json.dumps(event, ensure_ascii=False), flush=True)
            if isinstance(event, dict) and event.get("event") == "message":
                time.sleep(0.22)
        return

    result = app.execute_action(payload)
    print(json.dumps(result.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
