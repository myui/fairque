"""Integration tests for complete FairQueue workflow."""

import time
from typing import Any, Dict

from fairque import Priority, Task, TaskHandler, TaskQueue, Worker


class IntegrationTaskHandler(TaskHandler):
    """Test task handler for integration tests."""

    def __init__(self):
        self.processed_tasks = []
        self.failed_tasks = []
        self.processing_time = 0.1  # Simulate processing time

    def _process_task(self, task: Task) -> bool:
        """Process a task with simulated work."""
        time.sleep(self.processing_time)

        # Simulate failure for tasks with "fail" in payload
        if task.payload.get("should_fail", False):
            return False

        self.processed_tasks.append(task)
        return True

    def process_task(self, task: Task) -> bool:
        """Process a task with simulated work."""
        return self._process_task(task)

    def on_task_success(self, task: Task, duration: float) -> None:
        """Handle successful task completion."""
        pass

    def on_task_failure(self, task: Task, error: Exception, duration: float) -> None:
        """Handle task failure."""
        self.failed_tasks.append((task, error))


class TestFairQueueIntegration:
    """Integration tests for complete FairQueue workflow."""

    def test_complete_workflow(self, fairqueue_integration: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test complete push -> pop -> process workflow."""
        # Create tasks with different priorities
        tasks = []
        for i, priority in enumerate([Priority.LOW, Priority.HIGH, Priority.CRITICAL]):
            task = Task.create(
                user_id="test:user:1",
                priority=priority,
                payload={**sample_payload, "task_number": i}
            )
            tasks.append(task)
            fairqueue_integration.push(task)

        # Verify tasks were pushed
        stats = fairqueue_integration.get_stats()
        assert stats.get("tasks_active", 0) == 3

        # Pop tasks and verify priority ordering
        popped_tasks = []
        for _ in range(3):
            task = fairqueue_integration.pop(["test:user:1"])
            if task:
                popped_tasks.append(task)
                fairqueue_integration.delete_task(task.task_id)

        assert len(popped_tasks) == 3
        # CRITICAL should be first
        assert popped_tasks[0].priority == Priority.CRITICAL

        # Verify final state
        final_stats = fairqueue_integration.get_stats()
        assert final_stats.get("tasks_active", 0) == 0

    def test_multi_user_work_stealing(self, fairqueue_integration: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test work stealing across multiple users."""
        # Push tasks for different users
        user_tasks = {}
        for user_id in ["test:user:1", "test:user:2", "test:user:3", "test:user:4"]:
            task = Task.create(
                user_id=user_id,
                priority=Priority.HIGH,
                payload={**sample_payload, "user": user_id}
            )
            user_tasks[user_id] = task
            fairqueue_integration.push(task)

        # Get batch queue sizes
        sizes = fairqueue_integration.get_batch_queue_sizes(list(user_tasks.keys()))
        assert sizes["totals"]["total_size"] == 4

        # Pop all tasks (should work across users due to work stealing)
        popped_tasks = []
        user_list = ["test:user:1", "test:user:2", "test:user:3", "test:user:4"]

        for _ in range(4):
            task = fairqueue_integration.pop(user_list)
            if task:
                popped_tasks.append(task)
                fairqueue_integration.delete_task(task.task_id)

        assert len(popped_tasks) == 4

        # Verify all users' tasks were processed
        processed_users = {task.user_id for task in popped_tasks}
        assert len(processed_users) == 4

    def test_priority_mixed_users(self, fairqueue_integration: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test priority handling with mixed users."""
        # Create tasks with different priorities for different users
        test_cases = [
            ("test:user:1", Priority.LOW),
            ("test:user:2", Priority.CRITICAL),
            ("test:user:1", Priority.HIGH),
            ("test:user:3", Priority.NORMAL),
        ]

        pushed_tasks = []
        for user_id, priority in test_cases:
            task = Task.create(
                user_id=user_id,
                priority=priority,
                payload={**sample_payload, "user": user_id, "priority": priority.name}
            )
            pushed_tasks.append(task)
            fairqueue_integration.push(task)

        # Pop all tasks
        popped_tasks = []
        user_list = ["test:user:1", "test:user:2", "test:user:3"]

        while True:
            task = fairqueue_integration.pop(user_list)
            if not task:
                break
            popped_tasks.append(task)
            fairqueue_integration.delete_task(task.task_id)

        assert len(popped_tasks) == 4

        # Verify CRITICAL task was processed first
        assert popped_tasks[0].priority == Priority.CRITICAL
        assert popped_tasks[0].user_id == "test:user:2"


class TestWorkerIntegration:
    """Integration tests with Worker processing."""

    def test_worker_basic_processing(self, fairqueue_config, redis_client_integration, sample_payload: Dict[str, Any]) -> None:
        """Test basic worker task processing."""
        task_handler = IntegrationTaskHandler()
        task_handler.processing_time = 0.05  # Fast processing for test

        with TaskQueue(fairqueue_config, redis_client_integration) as queue:
            # Push some tasks
            tasks = []
            for i in range(3):
                task = Task.create(
                    user_id="test:user:1",
                    priority=Priority.HIGH,
                    payload={**sample_payload, "task_id": i}
                )
                tasks.append(task)
                queue.push(task)

            # Start worker for a short time
            with Worker(fairqueue_config, task_handler, queue) as worker:
                worker.start()

                # Wait for tasks to be processed
                start_time = time.time()
                while len(task_handler.processed_tasks) < 3 and (time.time() - start_time) < 5:
                    time.sleep(0.1)

            # Verify all tasks were processed
            assert len(task_handler.processed_tasks) == 3
            assert len(task_handler.failed_tasks) == 0

            # Verify worker stats
            worker_stats = worker.get_stats()
            assert worker_stats["tasks_processed"] == 3
            assert worker_stats["tasks_failed"] == 0

    def test_worker_with_failures(self, fairqueue_config, redis_client_integration, sample_payload: Dict[str, Any]) -> None:
        """Test worker handling task failures."""
        task_handler = IntegrationTaskHandler()
        task_handler.processing_time = 0.05

        with TaskQueue(fairqueue_config, redis_client_integration) as queue:
            # Push tasks - some will fail
            tasks = []
            for i in range(4):
                should_fail = (i % 2 == 0)  # Every other task fails
                task = Task.create(
                    user_id="test:user:1",
                    priority=Priority.HIGH,
                    payload={**sample_payload, "task_id": i, "should_fail": should_fail}
                )
                tasks.append(task)
                queue.push(task)

            # Start worker
            with Worker(fairqueue_config, task_handler, queue) as worker:
                worker.start()

                # Wait for processing
                start_time = time.time()
                total_processed = 0
                while total_processed < 4 and (time.time() - start_time) < 5:
                    total_processed = len(task_handler.processed_tasks) + len(task_handler.failed_tasks)
                    time.sleep(0.1)

            # Verify results
            assert len(task_handler.processed_tasks) == 2  # 2 successful
            assert len(task_handler.failed_tasks) == 2     # 2 failed

            worker_stats = worker.get_stats()
            assert worker_stats["tasks_processed"] == 2
            assert worker_stats["tasks_failed"] == 2

    def test_worker_concurrent_processing(self, fairqueue_config, redis_client_integration, sample_payload: Dict[str, Any]) -> None:
        """Test worker concurrent task processing."""
        task_handler = IntegrationTaskHandler()
        task_handler.processing_time = 0.2  # Longer processing to test concurrency

        # Update config for concurrent processing
        fairqueue_config.worker.max_concurrent_tasks = 3

        with TaskQueue(fairqueue_config, redis_client_integration) as queue:
            # Push multiple tasks
            tasks = []
            for i in range(5):
                task = Task.create(
                    user_id="test:user:1",
                    priority=Priority.HIGH,
                    payload={**sample_payload, "task_id": i}
                )
                tasks.append(task)
                queue.push(task)

            start_time = time.time()

            with Worker(fairqueue_config, task_handler, queue) as worker:
                worker.start()

                # Wait for all tasks to be processed
                while len(task_handler.processed_tasks) < 5 and (time.time() - start_time) < 10:
                    time.sleep(0.1)

            processing_time = time.time() - start_time

            # With 3 concurrent workers and 0.2s processing time each,
            # 5 tasks should complete in roughly 0.4s (2 batches)
            # Allow some margin for test execution overhead
            assert processing_time < 1.0  # Should be much faster than sequential (1.0s)
            assert len(task_handler.processed_tasks) == 5

    def test_worker_graceful_shutdown(self, fairqueue_config, redis_client_integration, sample_payload: Dict[str, Any]) -> None:
        """Test worker graceful shutdown."""
        task_handler = IntegrationTaskHandler()
        task_handler.processing_time = 0.3  # Longer processing

        with TaskQueue(fairqueue_config, redis_client_integration) as queue:
            # Push tasks
            for i in range(3):
                task = Task.create(
                    user_id="test:user:1",
                    priority=Priority.HIGH,
                    payload={**sample_payload, "task_id": i}
                )
                queue.push(task)

            worker = Worker(fairqueue_config, task_handler, queue)
            worker.start()

            # Let some tasks start processing
            time.sleep(0.1)

            # Stop worker (should wait for active tasks)
            stop_start = time.time()
            worker.stop()
            stop_duration = time.time() - stop_start

            # Verify graceful shutdown
            assert worker.get_stats()["is_running"] is False
            # Should have waited for active tasks (but not too long due to our timeout)
            assert stop_duration < fairqueue_config.worker.graceful_shutdown_timeout + 1

    def test_worker_health_check(self, fairqueue_config, redis_client_integration, sample_payload: Dict[str, Any]) -> None:
        """Test worker health monitoring."""
        task_handler = IntegrationTaskHandler()

        with TaskQueue(fairqueue_config, redis_client_integration) as queue:
            worker = Worker(fairqueue_config, task_handler, queue)

            # Worker not started - should be unhealthy
            assert not worker.is_healthy()

            # Start worker - should be healthy
            worker.start()
            time.sleep(0.1)  # Give it time to start
            assert worker.is_healthy()

            # Stop worker - should be unhealthy
            worker.stop()
            assert not worker.is_healthy()


class TestConcurrentWorkers:
    """Test multiple workers processing tasks concurrently."""

    def test_multiple_workers_same_queue(self, fairqueue_config, redis_client_integration, sample_payload: Dict[str, Any]) -> None:
        """Test multiple workers processing from the same queue."""
        # Create two task handlers
        handler1 = IntegrationTaskHandler()
        handler2 = IntegrationTaskHandler()

        # Fast processing
        handler1.processing_time = 0.05
        handler2.processing_time = 0.05

        # Create configs for two workers
        config1 = fairqueue_config
        config1.worker.id = "worker-1"

        config2 = fairqueue_config
        config2.worker.id = "worker-2"
        config2.worker.assigned_users = ["test:user:3", "test:user:4"]

        with TaskQueue(fairqueue_config, redis_client_integration) as queue:
            # Push tasks for different users
            tasks = []
            all_users = ["test:user:1", "test:user:2", "test:user:3", "test:user:4"]

            for i, user_id in enumerate(all_users * 2):  # 8 tasks total
                task = Task.create(
                    user_id=user_id,
                    priority=Priority.HIGH,
                    payload={**sample_payload, "task_id": i, "user": user_id}
                )
                tasks.append(task)
                queue.push(task)

            # Start both workers
            with Worker(config1, handler1, queue) as worker1, \
                 Worker(config2, handler2, queue) as worker2:

                worker1.start()
                worker2.start()

                # Wait for all tasks to be processed
                start_time = time.time()
                total_processed = 0

                while total_processed < 8 and (time.time() - start_time) < 5:
                    total_processed = (len(handler1.processed_tasks) +
                                     len(handler2.processed_tasks))
                    time.sleep(0.1)

            # Verify all tasks were processed
            assert len(handler1.processed_tasks) + len(handler2.processed_tasks) == 8

            # Verify no task was processed twice
            all_processed_ids = set()
            for task in handler1.processed_tasks + handler2.processed_tasks:
                assert task.task_id not in all_processed_ids
                all_processed_ids.add(task.task_id)


class TestErrorRecovery:
    """Test error recovery and edge cases."""

    def test_queue_recovery_after_redis_disconnect(self, fairqueue_config, sample_payload: Dict[str, Any]) -> None:
        """Test queue behavior after Redis connection issues."""
        # This test would require more complex setup to simulate Redis disconnection
        # For now, we'll test basic error handling

        with TaskQueue(fairqueue_config) as queue:
            # Push a task successfully
            task = Task.create(
                user_id="test:user:1",
                priority=Priority.HIGH,
                payload=sample_payload
            )
            result = queue.push(task)
            assert result["success"] is True

            # Verify we can still operate normally
            popped_task = queue.pop(["test:user:1"])
            assert popped_task is not None
            assert popped_task.task_id == task.task_id

    def test_worker_error_handling(self, fairqueue_config, redis_client_integration, sample_payload: Dict[str, Any]) -> None:
        """Test worker handling of various error conditions."""

        class ErrorTaskHandler(TaskHandler):
            def __init__(self):
                self.call_count = 0

            def _process_task(self, task: Task) -> bool:
                self.call_count += 1

                # Raise exception on first call
                if self.call_count == 1:
                    raise ValueError("Simulated processing error")

                # Return False on second call
                if self.call_count == 2:
                    return False

                # Success on third call
                return True

            def process_task(self, task: Task) -> bool:
                return self._process_task(task)

        task_handler = ErrorTaskHandler()

        with TaskQueue(fairqueue_config, redis_client_integration) as queue:
            # Push tasks
            for i in range(3):
                task = Task.create(
                    user_id="test:user:1",
                    priority=Priority.HIGH,
                    payload={**sample_payload, "task_id": i}
                )
                queue.push(task)

            with Worker(fairqueue_config, task_handler, queue) as worker:
                worker.start()

                # Wait for processing
                start_time = time.time()
                while task_handler.call_count < 3 and (time.time() - start_time) < 5:
                    time.sleep(0.1)

            # Verify error handling
            stats = worker.get_stats()
            assert stats["tasks_processed"] == 1  # Only third task succeeded
            assert stats["tasks_failed"] == 2     # First two failed
            assert task_handler.call_count == 3
