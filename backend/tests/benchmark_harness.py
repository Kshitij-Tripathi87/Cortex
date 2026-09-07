"""Nexus Sustained Load & Concurrency Benchmark Harness.

Standardized benchmarking framework for measuring:
- Concurrency scaling (10, 50, 100, 250, 500, 1000+ workers)
- High-resolution percentile latencies (P50, P90, P95, P99, Min, Max, Mean)
- Throughput (ops/sec) under sustained concurrent load
- Zero-error reliability and isolation across tenants/workspaces
- Memory overhead tracking (tracemalloc)
"""

from __future__ import annotations

import asyncio
import math
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkResult:
    """Standardized result container for load and concurrency measurements."""

    name: str
    concurrency: int
    total_ops: int
    successful_ops: int
    failed_ops: int
    error_rate_pct: float
    total_duration_s: float
    throughput_ops_s: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float
    peak_memory_mb: float
    first_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_line(self) -> str:
        return (
            f"[{self.name}] C={self.concurrency:4d} | "
            f"Ops={self.total_ops:5d} | "
            f"Rate={self.throughput_ops_s:7.1f} ops/s | "
            f"P50={self.p50_ms:6.2f}ms | "
            f"P95={self.p95_ms:6.2f}ms | "
            f"P99={self.p99_ms:6.2f}ms | "
            f"Errors={self.error_rate_pct:4.2f}%"
        )


def _compute_percentile(sorted_data: list[float], percentile: float) -> float:
    """Compute percentile from sorted data using linear interpolation."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * percentile
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


async def run_load_benchmark(
    name: str,
    concurrency: int,
    task_factory: Callable[[int], Awaitable[Any]],
    total_ops: int | None = None,
    warmup_ops: int = 0,
) -> BenchmarkResult:
    """Execute a sustained concurrent load benchmark.

    Args:
        name: Name of the critical path / benchmark.
        concurrency: Number of concurrent workers.
        task_factory: Async callable that takes worker index (int) and executes one op.
        total_ops: Total operations to perform. Defaults to concurrency.
        warmup_ops: Optional warm-up iterations to discard before measurement.

    Returns:
        BenchmarkResult with detailed latency, throughput, and error metrics.
    """
    total = total_ops if total_ops is not None else concurrency

    # Optional Warmup
    if warmup_ops > 0:
        warmup_tasks = [task_factory(i % concurrency) for i in range(warmup_ops)]
        await asyncio.gather(*warmup_tasks, return_exceptions=True)

    tracemalloc.start()
    latencies_ms: list[float] = []
    failed_ops = 0
    first_error: str | None = None
    sem = asyncio.Semaphore(concurrency)

    async def _worker(op_idx: int) -> None:
        nonlocal failed_ops, first_error
        async with sem:
            t0 = time.perf_counter()
            try:
                await task_factory(op_idx)
                t1 = time.perf_counter()
                latencies_ms.append((t1 - t0) * 1000.0)
            except Exception as exc:
                failed_ops += 1
                if first_error is None:
                    import traceback
                    first_error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                t1 = time.perf_counter()
                latencies_ms.append((t1 - t0) * 1000.0)

    start_wall = time.perf_counter()
    tasks = [_worker(i) for i in range(total)]
    await asyncio.gather(*tasks)
    end_wall = time.perf_counter()

    _, peak_mem_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    duration = max(end_wall - start_wall, 1e-9)
    successful_ops = total - failed_ops
    error_rate = (failed_ops / total) * 100.0 if total > 0 else 0.0
    throughput = successful_ops / duration

    sorted_lats = sorted(latencies_ms)
    min_lat = sorted_lats[0] if sorted_lats else 0.0
    max_lat = sorted_lats[-1] if sorted_lats else 0.0
    mean_lat = sum(sorted_lats) / len(sorted_lats) if sorted_lats else 0.0

    p50 = _compute_percentile(sorted_lats, 0.50)
    p90 = _compute_percentile(sorted_lats, 0.90)
    p95 = _compute_percentile(sorted_lats, 0.95)
    p99 = _compute_percentile(sorted_lats, 0.99)

    return BenchmarkResult(
        name=name,
        concurrency=concurrency,
        total_ops=total,
        successful_ops=successful_ops,
        failed_ops=failed_ops,
        error_rate_pct=error_rate,
        total_duration_s=duration,
        throughput_ops_s=throughput,
        p50_ms=p50,
        p90_ms=p90,
        p95_ms=p95,
        p99_ms=p99,
        min_ms=min_lat,
        max_ms=max_lat,
        mean_ms=mean_lat,
        peak_memory_mb=peak_mem_bytes / (1024 * 1024),
        first_error=first_error,
    )
