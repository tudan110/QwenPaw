#!/usr/bin/env python3
"""Record HTTP latency, throughput and availability of one inspection sample.

By default this validates parameters without contacting the sample. Select a
safe read-only check: a health endpoint only establishes endpoint reachability.
No credentials, bodies or response headers are written to the report.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import httpx


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def validate_target(url: str) -> None:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"} or not parts.hostname
        or parts.username is not None or parts.password is not None
        or "?" in url or "#" in url or "\\" in url
        or any(char.isspace() for char in url) or not parts.path.startswith("/")
    ):
        raise ValueError("Use one explicit HTTP(S) read-only URL without credentials or query")
    if parts.scheme != "https" and parts.hostname not in {
        "localhost", "127.0.0.1", "::1",
    }:
        raise ValueError("Remote measurements require HTTPS")
    _ = parts.port


async def measure(args, records, *, transport=None) -> dict:
    counts: Counter = Counter()
    histogram: Counter = Counter()
    # Quantize elapsed time upward to 1 ms; keep a bounded number of bins
    # independent of long-run observation length.
    max_bin = 600_000
    token = os.environ.get("QWENPAW_EVAL_ACCESS_TOKEN")
    headers = {"X-QwenPaw-Access-Token": token} if token else {}

    async with httpx.AsyncClient(
        headers=headers, timeout=args.timeout, follow_redirects=False,
        trust_env=False, transport=transport,
    ) as client:
        started_at = utc_now()
        begin = monotonic()
        deadline = begin + args.duration

        async def probe() -> None:
            while monotonic() < deadline:
                scheduled_at = utc_now()
                started = monotonic()
                status = None
                error = None
                ok = False
                try:
                    async with asyncio.timeout(args.timeout):
                        async with client.stream("GET", args.url) as response:
                            status = response.status_code
                            # Response completion is part of the measurement;
                            # retain neither the full body nor individual chunks.
                            async for _ in response.aiter_bytes():
                                pass
                        ok = status == args.expected_status
                except (TimeoutError, httpx.HTTPError) as exc:
                    error = type(exc).__name__
                elapsed = round((monotonic() - started) * 1000, 3)
                if ok:
                    counts["ok"] += 1
                    histogram[min(max_bin, math.ceil(elapsed))] += 1
                else:
                    counts["failed"] += 1
                records.write(json.dumps({
                    "started_at": scheduled_at, "elapsed_ms": elapsed,
                    "status": status, "expected_status_met": ok, "error": error,
                }) + "\n")
                records.flush()
                delay = min(deadline - monotonic(), args.interval - elapsed / 1000)
                if delay > 0:
                    await asyncio.sleep(delay)

        await asyncio.gather(*(probe() for _ in range(args.concurrency)))

    boundary = monotonic()
    elapsed_seconds = round(boundary - begin, 3)
    duration_seconds = max(boundary - begin, 1e-9)
    total = counts["ok"] + counts["failed"]

    def quantile(rank: float) -> int | None:
        cutoff = math.ceil(rank * counts["ok"])
        if not cutoff:
            return None
        so_far = 0
        for value, count in sorted(histogram.items()):
            so_far += count
            if so_far >= cutoff:
                return value
        return None

    return {
        "sample_version": args.sample_version,
        "started_at": started_at, "finished_at": utc_now(),
        "elapsed_seconds": elapsed_seconds,
        "requested_observation_seconds": args.duration,
        "concurrency": args.concurrency, "worker_interval_seconds": args.interval,
        "expected_status": args.expected_status,
        "requests": total, "successes": counts["ok"], "failures": counts["failed"],
        "success_fraction": counts["ok"] / total if total else None,
        "requests_per_second": total / duration_seconds,
        "successful_latency_ms": {"p50": quantile(0.5), "p95": quantile(0.95), "p99": quantile(0.99)},
        "scope": "Endpoint response measurements; requires separate business, model, resource and SLA evidence.",
        "raw_records": "requests.jsonl",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--sample-version", required=True)
    parser.add_argument("--duration", type=float, default=60, help="Seconds; 259200 = 72 hours")
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--expected-status", type=int, default=200)
    parser.add_argument("--output-dir", required=True, type=Path, help="A new directory")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        validate_target(args.url)
    except ValueError as exc:
        parser.error(str(exc))
    if (
        not 1 <= args.duration <= 31 * 86400 or not 0.1 <= args.interval <= 86400
        or not 1 <= args.concurrency <= 64 or not 0.1 <= args.timeout <= 600
        or not 200 <= args.expected_status <= 299
        or not args.sample_version.strip() or len(args.sample_version) > 128
    ):
        parser.error("Invalid duration, interval, concurrency, timeout, status or sample version")
    if not args.execute:
        print("Validated parameters; no requests sent.")
        return
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "requests.jsonl").open("x", encoding="utf-8") as records:
        report = asyncio.run(measure(args, records))
    (args.output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Results: {args.output_dir}")


if __name__ == "__main__":
    main()
