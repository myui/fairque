"""Performance tests for worker processing capabilities."""

import asyncio
import concurrent.futures
import time
from typing import Dict

import pytest

from fairque.core.models import Task
from fairque.worker.async_worker import AsyncTaskHandler, AsyncWorker
from fairque.worker.worker import TaskHandler, Worker
from tests.performance.conftest import create_test_tasks


class PerformanceTaskHandler(TaskHandler):
    """Test implementation of TaskHandler."""

    def __init__(self, processing_time: float = 0.001, fail_rate: float = 0.0):
        """Initialize test handler.

        Args:
            processing_time: Simulated processing time in seconds
            fail_rate: Probability of task failure (0.0-1.0)
        """
        self.processing_time = processing_time
        self.fail_rate = fail_rate
        self.processed_count = 0
        self.failed_count = 0

    def _process_task(self, task: Task) -> bool:
        """Process a single task."""
        # Simulate processing
        time.sleep(self.processing_time)
        self.processed_count += 1

        # Simulate failures
        import random
        if random.random() < self.fail_rate:
            self.failed_count += 1
            raise Exception(f"Simulated failure for task {task.task_id}")

        return True


class AsyncPerformanceTaskHandler(AsyncTaskHandler):
    """Test implementation of AsyncTaskHandler."""

    def __init__(self, processing_time: float = 0.001, fail_rate: float = 0.0):
        """Initialize async test handler.

        Args:
            processing_time: Simulated processing time in seconds
            fail_rate: Probability of task failure (0.0-1.0)
        """
        self.processing_time = processing_time
        self.fail_rate = fail_rate
        self.processed_count = 0
        self.failed_count = 0

    async def process_task(self, task: Task) -> bool:
        """Process a single task asynchronously."""
        # Simulate async processing
        await asyncio.sleep(self.processing_time)
        self.processed_count += 1

        # Simulate failures
        import random
        if random.random() < self.fail_rate:
            self.failed_count += 1
            raise Exception(f"Simulated failure for task {task.task_id}")

        return True


class TestWorkerPerformance:
    """Test worker processing performance."""

    def test_single_worker_throughput(self, task_queue, fairqueue_config, redis_client):
        """Test single worker throughput."""
        # Create and push tasks
        tasks = create_test_tasks(1000, num_users=10)
        task_queue.push_batch(tasks)

        # Create worker with test handler
        handler = PerformanceTaskHandler(processing_time=0.001)
        worker = Worker(
            config=fairqueue_config,
            task_handler=handler,
            queue=task_queue
        )

        # Process tasks for a fixed duration
        start_time = time.time()
        duration = 5.0  # Run for 5 seconds

        def run_worker():
            # Use proper worker lifecycle methods
            worker.start()
            try:
                while time.time() - start_time < duration:
                    time.sleep(0.1)  # Short sleep to allow processing
            finally:
                worker.stop()

        # Run worker
        run_worker()

        # Calculate metrics
        processing_time = time.time() - start_time
        throughput = handler.processed_count / processing_time if processing_time > 0 else 0

        print(f"\n{'='*60}")
        print("Single Worker Performance")
        print(f"{'='*60}")
        print(f"Processed tasks: {handler.processed_count}")
        print(f"Processing time: {processing_time:.3f}s")
        print(f"Throughput: {throughput:.2f} tasks/sec")
        if throughput > 0:
            print(f"Average latency: {1000/throughput:.3f}ms/task")

    def test_concurrent_workers_performance(self, task_queue, fairqueue_config, redis_client):
        """Test concurrent workers performance."""
        num_workers = 4
        tasks_count = 2000

        # Create and push tasks
        tasks = create_test_tasks(tasks_count, num_users=10)
        task_queue.push_batch(tasks)

        # Create workers
        workers_data = []
        for _ in range(num_workers):
            handler = PerformanceTaskHandler(processing_time=0.001)
            worker = Worker(
                config=fairqueue_config,
                task_handler=handler,
                queue=task_queue
            )
            workers_data.append({
                'worker': worker,
                'handler': handler
            })

        # Run workers concurrently
        start_time = time.time()
        duration = 5.0

        def run_worker(worker_data: Dict) -> int:
            """Run a single worker."""
            worker = worker_data['worker']
            handler = worker_data['handler']

            worker.start()
            try:
                while time.time() - start_time < duration:
                    time.sleep(0.1)  # Short sleep to allow processing
            finally:
                worker.stop()

            return handler.processed_count

        # Execute workers in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(run_worker, worker_data)
                for worker_data in workers_data
            ]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # Calculate metrics
        total_processed = sum(results)
        processing_time = time.time() - start_time
        aggregate_throughput = total_processed / processing_time if processing_time > 0 else 0

        print(f"\n{'='*60}")
        print("Concurrent Workers Performance")
        print(f"{'='*60}")
        print(f"Workers: {num_workers}")
        print(f"Total processed: {total_processed}")
        print(f"Processing time: {processing_time:.3f}s")
        print(f"Aggregate throughput: {aggregate_throughput:.2f} tasks/sec")
        print(f"Per-worker average: {total_processed/num_workers:.1f} tasks")
        if num_workers > 0:
            print(f"Per-worker throughput: {aggregate_throughput/num_workers:.2f} tasks/sec")

    def test_work_stealing_efficiency(self, task_queue, fairqueue_config, redis_client):
        """Test work stealing efficiency."""
        # Push tasks only for worker1's users
        tasks = create_test_tasks(
            1000,
            user_prefix="user",
            num_users=5  # Only worker1's users
        )
        task_queue.push_batch(tasks)

        # Create two workers - worker1 (owner) and worker2 (stealer)
        handler1 = PerformanceTaskHandler(processing_time=0.002)  # Slower
        handler2 = PerformanceTaskHandler(processing_time=0.001)  # Faster

        worker1 = Worker(
            config=fairqueue_config,
            task_handler=handler1,
            queue=task_queue
        )

        worker2 = Worker(
            config=fairqueue_config,
            task_handler=handler2,
            queue=task_queue
        )

        # Run both workers
        start_time = time.time()
        duration = 5.0

        def run_worker(worker, handler):
            worker.start()
            try:
                while time.time() - start_time < duration:
                    time.sleep(0.1)  # Short sleep to allow processing
            finally:
                worker.stop()
            return handler.processed_count

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(run_worker, worker1, handler1)
            future2 = executor.submit(run_worker, worker2, handler2)

            count1 = future1.result()
            count2 = future2.result()

        # Calculate metrics
        total_processed = count1 + count2
        steal_ratio = count2 / total_processed if total_processed > 0 else 0

        print(f"\n{'='*60}")
        print("Work Stealing Efficiency")
        print(f"{'='*60}")
        print(f"Worker1 (owner) processed: {count1}")
        print(f"Worker2 (stealer) processed: {count2}")
        print(f"Total processed: {total_processed}")
        print(f"Steal ratio: {steal_ratio:.2%}")
        if total_processed > 0:
            print(f"Work distribution: {count1}/{count2} ({count1/total_processed:.1%}/{count2/total_processed:.1%})")


class TestAsyncWorkerPerformance:
    """Test async worker processing performance."""

    @pytest.mark.asyncio
    async def test_async_worker_throughput(self, async_task_queue, fairqueue_config, async_redis_client):
        """Test async worker throughput."""
        # Create and push tasks
        tasks = create_test_tasks(1000, num_users=10)
        await async_task_queue.push_batch(tasks)

        # Create async worker with test handler
        handler = AsyncPerformanceTaskHandler(processing_time=0.001)
        worker = AsyncWorker(
            config=fairqueue_config,
            task_handler=handler,
            queue=async_task_queue
        )

        # Process tasks for a fixed duration
        start_time = time.time()
        duration = 5.0
        processed_before = handler.processed_count

        # Run worker for duration
        async def run_for_duration():
            await worker.start()
            try:
                await asyncio.sleep(duration)
            finally:
                await worker.stop()

        await run_for_duration()

        # Calculate metrics
        processing_time = time.time() - start_time
        processed = handler.processed_count - processed_before
        throughput = processed / processing_time if processing_time > 0 else 0

        print(f"\n{'='*60}")
        print("Async Worker Performance")
        print(f"{'='*60}")
        print(f"Processed tasks: {processed}")
        print(f"Processing time: {processing_time:.3f}s")
        print(f"Throughput: {throughput:.2f} tasks/sec")
        if throughput > 0:
            print(f"Average latency: {1000/throughput:.3f}ms/task")

    @pytest.mark.asyncio
    async def test_async_concurrent_processing(self, async_task_queue, fairqueue_config, async_redis_client):
        """Test async concurrent task processing."""
        # Create and push tasks
        tasks = create_test_tasks(2000, num_users=10)
        await async_task_queue.push_batch(tasks)

        # Create async worker with concurrent processing
        handler = AsyncPerformanceTaskHandler(processing_time=0.01)  # 10ms per task

        # Note: We can't modify config attributes directly, so we'll just use the default
        worker = AsyncWorker(
            config=fairqueue_config,
            task_handler=handler,
            queue=async_task_queue
        )

        # Run worker with concurrent processing
        start_time = time.time()
        duration = 5.0

        async def run_concurrent():
            await worker.start()
            try:
                await asyncio.sleep(duration)
            finally:
                await worker.stop()

        await run_concurrent()

        # Calculate metrics
        processing_time = time.time() - start_time
        throughput = handler.processed_count / processing_time if processing_time > 0 else 0
        max_concurrent = fairqueue_config.worker.max_concurrent_tasks
        theoretical_max = max_concurrent / 0.01 if max_concurrent > 0 else 0  # Based on processing time
        efficiency = throughput / theoretical_max if theoretical_max > 0 else 0

        print(f"\n{'='*60}")
        print("Async Concurrent Processing Performance")
        print(f"{'='*60}")
        print(f"Max concurrent tasks: {max_concurrent}")
        print(f"Processed tasks: {handler.processed_count}")
        print(f"Processing time: {processing_time:.3f}s")
        print(f"Throughput: {throughput:.2f} tasks/sec")
        print(f"Theoretical max: {theoretical_max:.2f} tasks/sec")
        print(f"Efficiency: {efficiency:.1%}")
