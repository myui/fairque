"""Performance test fixtures and utilities for FairQueue benchmarking."""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List

import pytest
import redis
import redis.asyncio as async_redis

from fairque.core.config import FairQueueConfig, QueueConfig, RedisConfig, WorkerConfig
from fairque.core.models import Priority, Task
from fairque.queue.async_queue import AsyncTaskQueue
from fairque.queue.queue import TaskQueue


@dataclass
class PerformanceMetrics:
    """Container for performance test metrics."""

    operation: str
    total_operations: int
    total_time: float
    min_time: float = float('inf')
    max_time: float = 0.0
    latencies: List[float] = field(default_factory=list)

    @property
    def avg_time(self) -> float:
        """Average time per operation."""
        return self.total_time / self.total_operations if self.total_operations > 0 else 0

    @property
    def ops_per_second(self) -> float:
        """Operations per second."""
        return self.total_operations / self.total_time if self.total_time > 0 else 0

    @property
    def p50(self) -> float:
        """50th percentile latency."""
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        return sorted_latencies[len(sorted_latencies) // 2]

    @property
    def p95(self) -> float:
        """95th percentile latency."""
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    @property
    def p99(self) -> float:
        """99th percentile latency."""
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    def add_measurement(self, duration: float) -> None:
        """Add a single measurement."""
        self.latencies.append(duration)
        self.min_time = min(self.min_time, duration)
        self.max_time = max(self.max_time, duration)

    def summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            "operation": self.operation,
            "total_operations": self.total_operations,
            "total_time_seconds": round(self.total_time, 3),
            "ops_per_second": round(self.ops_per_second, 2),
            "avg_time_ms": round(self.avg_time * 1000, 3),
            "min_time_ms": round(self.min_time * 1000, 3),
            "max_time_ms": round(self.max_time * 1000, 3),
            "p50_ms": round(self.p50 * 1000, 3),
            "p95_ms": round(self.p95 * 1000, 3),
            "p99_ms": round(self.p99 * 1000, 3),
        }


@contextmanager
def measure_time() -> Generator[List[float], None, None]:
    """Context manager to measure execution time."""
    result = []
    start = time.perf_counter()
    try:
        yield result
    finally:
        result.append(time.perf_counter() - start)


def create_test_tasks(
    count: int,
    user_prefix: str = "user",
    num_users: int = 10,
    priority: Priority = Priority.NORMAL,
    payload_size: int = 100,
) -> List[Task]:
    """Create test tasks for benchmarking.

    Args:
        count: Number of tasks to create
        user_prefix: Prefix for user IDs
        num_users: Number of unique users
        priority: Task priority
        payload_size: Size of payload in bytes

    Returns:
        List of test tasks
    """
    tasks = []
    payload = {"data": "x" * payload_size, "index": 0}

    for i in range(count):
        user_id = f"{user_prefix}_{i % num_users}"
        task_payload = {**payload, "index": i}
        task = Task.create(
            user_id=user_id,
            priority=priority,
            payload=task_payload
        )
        tasks.append(task)

    return tasks


class PerformanceBenchmark:
    """Base class for performance benchmarks."""

    def __init__(self, name: str):
        """Initialize benchmark.

        Args:
            name: Benchmark name
        """
        self.name = name
        self.metrics: Dict[str, PerformanceMetrics] = {}

    def record_operation(
        self,
        operation: str,
        func: Callable[[], Any],
        iterations: int = 1,
    ) -> Any:
        """Record performance of an operation.

        Args:
            operation: Operation name
            func: Function to benchmark
            iterations: Number of iterations

        Returns:
            Result of the last function call
        """
        if operation not in self.metrics:
            self.metrics[operation] = PerformanceMetrics(
                operation=operation,
                total_operations=0,
                total_time=0.0
            )

        metric = self.metrics[operation]
        result = None

        for _ in range(iterations):
            with measure_time() as duration:
                result = func()

            metric.add_measurement(duration[0])
            metric.total_operations += 1
            metric.total_time += duration[0]

        return result

    async def record_async_operation(
        self,
        operation: str,
        coro_func: Callable[[], Any],
        iterations: int = 1,
    ) -> Any:
        """Record performance of an async operation.

        Args:
            operation: Operation name
            coro_func: Async function to benchmark
            iterations: Number of iterations

        Returns:
            Result of the last function call
        """
        if operation not in self.metrics:
            self.metrics[operation] = PerformanceMetrics(
                operation=operation,
                total_operations=0,
                total_time=0.0
            )

        metric = self.metrics[operation]
        result = None

        for _ in range(iterations):
            start = time.perf_counter()
            result = await coro_func()
            duration = time.perf_counter() - start

            metric.add_measurement(duration)
            metric.total_operations += 1
            metric.total_time += duration

        return result

    def print_results(self) -> None:
        """Print benchmark results."""
        print(f"\n{'='*60}")
        print(f"Performance Benchmark: {self.name}")
        print(f"{'='*60}")

        for operation, metric in self.metrics.items():
            summary = metric.summary()
            print(f"\nOperation: {summary['operation']}")
            print(f"  Total operations: {summary['total_operations']:,}")
            print(f"  Total time: {summary['total_time_seconds']:.3f}s")
            print(f"  Throughput: {summary['ops_per_second']:,.2f} ops/sec")
            print("  Latency (ms):")
            print(f"    Average: {summary['avg_time_ms']:.3f}")
            print(f"    Min: {summary['min_time_ms']:.3f}")
            print(f"    Max: {summary['max_time_ms']:.3f}")
            print(f"    P50: {summary['p50_ms']:.3f}")
            print(f"    P95: {summary['p95_ms']:.3f}")
            print(f"    P99: {summary['p99_ms']:.3f}")

    def get_results(self) -> Dict[str, Dict[str, Any]]:
        """Get benchmark results as dictionary."""
        return {
            operation: metric.summary()
            for operation, metric in self.metrics.items()
        }


@pytest.fixture
def redis_client():
    """Create Redis client for testing."""
    client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=False)
    # Clean test database
    client.flushdb()
    yield client
    # Cleanup
    client.flushdb()
    client.close()


@pytest.fixture
async def async_redis_client():
    """Create async Redis client for testing."""
    client = async_redis.Redis(host="localhost", port=6379, db=15, decode_responses=False)
    # Clean test database
    await client.flushdb()
    yield client
    # Cleanup
    await client.flushdb()
    await client.close()


@pytest.fixture
def fairqueue_config():
    """Create FairQueue configuration for testing."""
    return FairQueueConfig(
        redis=RedisConfig(
            host="localhost",
            port=6379,
            db=15,
            decode_responses=False,
        ),
        workers=[
            WorkerConfig(
                id="worker1",
                assigned_users=[f"user_{i}" for i in range(5)],
                steal_targets=[f"user_{i}" for i in range(5, 10)],
            ),
            WorkerConfig(
                id="worker2",
                assigned_users=[f"user_{i}" for i in range(5, 10)],
                steal_targets=[f"user_{i}" for i in range(5)],
            ),
        ],
        queue=QueueConfig(
            max_queue_size=100000,
            enable_dlq=True,
            dlq_max_size=10000,
            enable_stats=True,
        ),
    )


@pytest.fixture
def task_queue(redis_client, fairqueue_config):
    """Create TaskQueue instance for testing."""
    return TaskQueue(fairqueue_config, redis_client)


@pytest.fixture
async def async_task_queue(async_redis_client, fairqueue_config):
    """Create AsyncTaskQueue instance for testing."""
    return AsyncTaskQueue(fairqueue_config, async_redis_client)
