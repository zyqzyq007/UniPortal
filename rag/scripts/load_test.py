#!/usr/bin/env python3
"""Small asyncio load test for the chat SSE endpoint.

Example:
    uv run python scripts/load_test.py --requests 20 --concurrency 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass

import httpx


@dataclass
class Sample:
    ok: bool
    status_code: int
    latency_ms: float
    ttft_ms: float
    token_events: int
    error: str = ""


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(percent * len(ordered)) - 1)
    return ordered[index]


async def run_one(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
    message: str,
    mode: str,
) -> Sample:
    async with semaphore:
        start = time.perf_counter()
        first_token_at: float | None = None
        token_events = 0
        status_code = 0
        try:
            async with client.stream(
                "POST",
                url,
                json={"message": message, "mode": mode, "stream": True},
            ) as response:
                status_code = response.status_code
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    if event.get("type") == "token":
                        token_events += 1
                        first_token_at = first_token_at or time.perf_counter()

            end = time.perf_counter()
            return Sample(
                ok=status_code == 200 and token_events > 0,
                status_code=status_code,
                latency_ms=(end - start) * 1000,
                ttft_ms=((first_token_at or end) - start) * 1000,
                token_events=token_events,
            )
        except Exception as exc:
            end = time.perf_counter()
            return Sample(
                ok=False,
                status_code=status_code,
                latency_ms=(end - start) * 1000,
                ttft_ms=0.0,
                token_events=token_events,
                error=str(exc),
            )


async def main_async(args: argparse.Namespace) -> int:
    url = f"{args.base_url.rstrip('/')}/api/chat/stream"
    semaphore = asyncio.Semaphore(args.concurrency)
    timeout = httpx.Timeout(args.timeout)

    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout) as client:
        samples = await asyncio.gather(
            *[
                run_one(client, semaphore, url, args.message, args.mode)
                for _ in range(args.requests)
            ]
        )
    elapsed = time.perf_counter() - start

    successful = [sample for sample in samples if sample.ok]
    latencies = [sample.latency_ms for sample in successful]
    ttfts = [sample.ttft_ms for sample in successful]
    token_events = [sample.token_events for sample in successful]
    report = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "successful": len(successful),
        "failed": len(samples) - len(successful),
        "requests_per_second": round(args.requests / elapsed, 2),
        "latency_ms": {
            "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
        },
        "ttft_ms": {
            "avg": round(sum(ttfts) / len(ttfts), 2) if ttfts else 0,
            "p50": round(percentile(ttfts, 0.50), 2),
            "p95": round(percentile(ttfts, 0.95), 2),
            "p99": round(percentile(ttfts, 0.99), 2),
        },
        "token_events": {
            "avg": round(sum(token_events) / len(token_events), 2) if token_events else 0,
            "min": min(token_events) if token_events else 0,
            "max": max(token_events) if token_events else 0,
        },
        "errors": [asdict(sample) for sample in samples if not sample.ok][:10],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["failed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test the RAG SSE endpoint")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--mode", choices=["thinking", "fast"], default="fast")
    parser.add_argument("--message", default="液压系统压力低如何排查？")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
