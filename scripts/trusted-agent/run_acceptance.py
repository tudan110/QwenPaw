#!/usr/bin/env python3
"""Read-only business probe/effect runner. No traffic without --execute.

JSONL cases require id, path, method, body, expected_json. expected_json is a
small subset of the expected JSON object; absent expectations are reported as
unjudged. HTTP 200 alone never counts as business/answer correctness.
"""

import argparse
import asyncio
import json
import os
import statistics
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

READ_POSTS = {
    "/api/portal/knowledge-base/query",
    "/api/portal/alarm-analyst/diagnose",
    "/api/portal/fault-disposal/diagnose",
}


def load_cases(path):
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not cases:
        raise ValueError("Case set is empty")
    ids = set()
    for case in cases:
        if not case.get("id") or case["id"] in ids:
            raise ValueError("Case ids must be unique and nonempty")
        ids.add(case["id"])
        target = case.get("path", "")
        parsed = urlsplit(target)
        if (
            parsed.scheme
            or parsed.netloc
            or not target.startswith("/api/")
            or ".." in target
            or "\\" in target
            or "%" in parsed.path
        ):
            raise ValueError("Case path must be a local API path")
        method = case.get("method", "GET").upper()
        if method != "POST" or parsed.path not in READ_POSTS:
            raise ValueError(
                "Only the declared read-only business POST probes are enabled"
            )
        if "expected_json" in case and (
            not isinstance(case["expected_json"], dict) or not case["expected_json"]
        ):
            raise ValueError("expected_json must be a nonempty object subset")
    return cases


def matches(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(actual[key], value)
            for key, value in expected.items()
        )
    return actual == expected


async def run(args, cases):
    timings = []
    counts = {"requests": 0, "http_ok": 0, "task_judged": 0, "task_passed": 0}
    record_path = args.output.with_suffix(".requests.jsonl")
    start = time.monotonic()
    deadline = start + args.duration
    token = os.environ.get("QWENPAW_EVAL_ACCESS_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with record_path.open("w") as record_file:
        async with httpx.AsyncClient(
            base_url=args.base_url,
            headers=headers,
            timeout=args.timeout,
            trust_env=False,
            follow_redirects=False,
        ) as client:

            async def worker(index):
                while time.monotonic() < deadline:
                    case = cases[index % len(cases)]
                    index += 1
                    begin = time.monotonic()
                    result = {
                        "case_id": case["id"],
                        "http_ok": False,
                        "judged": "expected_json" in case,
                        "task_ok": False,
                    }
                    try:
                        response = await client.post(
                            case["path"], json=case.get("body", {})
                        )
                        result["status_code"] = response.status_code
                        result["http_ok"] = 200 <= response.status_code < 300
                        if result["http_ok"] and result["judged"]:
                            result["task_ok"] = matches(
                                response.json(), case["expected_json"]
                            )
                    except Exception as exc:
                        result["error_type"] = type(
                            exc
                        ).__name__  # no body, URL query or credentials
                    result["elapsed_ms"] = round((time.monotonic() - begin) * 1000, 3)
                    record_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                    counts["requests"] += 1
                    counts["http_ok"] += int(result["http_ok"])
                    counts["task_judged"] += int(result["judged"])
                    counts["task_passed"] += int(result["task_ok"])
                    if len(timings) < 50000:
                        timings.append(result["elapsed_ms"])
                    else:
                        index_in_sample = random.randrange(counts["requests"])
                        if index_in_sample < len(timings):
                            timings[index_in_sample] = result["elapsed_ms"]

            await asyncio.gather(*(worker(i) for i in range(args.concurrency)))
    elapsed = time.monotonic() - start
    timings.sort()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": elapsed,
        "concurrency": args.concurrency,
        **counts,
        "http_success_rps": counts["http_ok"] / elapsed,
        "quantile_sample_size": len(timings),
        "quantile_method": "reservoir sample up to 50000",
        "latency_ms": {
            "p50": statistics.median(timings) if timings else None,
            "p95": (
                timings[min(int(len(timings) * 0.95), len(timings) - 1)]
                if timings
                else None
            ),
        },
        "limitations": [
            "Full request latency; first-token latency and process resource metrics require separate instrumentation",
            "Repeated probes are not independent gold samples or a lab verdict",
            "No availability SLA or 72-hour observation inferred",
        ],
        "records_file": str(record_path),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    base = urlsplit(args.base_url)
    if (
        base.scheme not in {"http", "https"}
        or not base.hostname
        or base.username
        or base.password
        or base.query
        or base.fragment
    ):
        parser.error("base URL must be HTTP(S), without credentials, query or fragment")
    if args.duration <= 0 or args.concurrency < 1 or args.timeout <= 0:
        parser.error("duration, timeout and concurrency must be positive")
    cases = load_cases(args.cases)
    if not args.execute:
        print(f"Validated {len(cases)} cases; no network requests sent")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(asyncio.run(run(args, cases)), ensure_ascii=False, indent=2)
            + "\n"
        )
        print(f"Results: {args.output}")
