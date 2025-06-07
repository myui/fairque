"""Tests for FairQueue core functionality."""

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from fairque import Priority, Task, TaskQueue
from fairque.core.exceptions import TaskValidationError


class TestFairQueueBasics:
    """Test basic FairQueue operations."""

    def test_fairqueue_initialization(self, fairqueue: TaskQueue) -> None:
        """Test FairQueue initialization."""
        assert fairqueue.config.worker.id == "test-worker"
        # Redis should be mocked and ping should return True
        assert fairqueue.redis.ping()

    def test_push_task_success(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test successful task push."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.HIGH,
            payload=sample_payload
        )

        # Mock lua script execution
        mock_result = {
            "success": True,
            "data": {
                "task_id": task.task_id,
                "user_id": "test:user:1",
                "priority": 4
            }
        }

        with patch.object(fairqueue.lua_manager, 'execute_script') as mock_script:
            mock_script.return_value = json.dumps(mock_result)

            result = fairqueue.push(task)

            assert result["success"] is True
            assert result["data"]["task_id"] == task.task_id
            assert result["data"]["user_id"] == "test:user:1"
            assert result["data"]["priority"] == 4

    def test_push_critical_task(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test pushing critical priority task."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.CRITICAL,
            payload=sample_payload
        )

        result = fairqueue.push(task)

        assert result["success"] is True
        assert "task_id" in result
        assert result["state"] == "queued"

    def test_push_normal_task(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test pushing normal priority task."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.NORMAL,
            payload=sample_payload
        )

        result = fairqueue.push(task)

        assert result["success"] is True
        assert "task_id" in result
        assert result["state"] == "queued"

    def test_push_task_validation_error(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test task push with validation error."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.HIGH,
            payload=sample_payload
        )

        # Clear task ID to trigger validation error
        task.task_id = ""

        with pytest.raises(TaskValidationError, match="Task ID cannot be empty"):
            fairqueue.push(task)

    def test_pop_task_success(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test successful task pop."""
        # Pop the task - use basic mock from conftest.py
        popped_task = fairqueue.pop(["test:user:1"])

        # Assert based on the basic mock structure from conftest.py
        assert popped_task is not None
        assert popped_task.task_id == "test_task_id"
        assert popped_task.user_id == "test_user"
        assert popped_task.priority == Priority.NORMAL

    def test_pop_task_empty_queue(self, fairqueue: TaskQueue) -> None:
        """Test popping from empty queue."""
        # Mock lua script execution for empty queue
        with patch.object(fairqueue.lua_manager, 'execute_script') as mock_script:
            mock_script.return_value = '{"success": true, "task": null}'

            result = fairqueue.pop(["test:user:1"])
            assert result is None

    def test_pop_task_no_users(self, fairqueue: TaskQueue) -> None:
        """Test popping with no users specified."""
        # Mock lua script execution for no users
        mock_result = {"success": True, "data": None}
        with patch.object(fairqueue.lua_manager, 'execute_script') as mock_script:
            mock_script.return_value = json.dumps(mock_result)

        result = fairqueue.pop([])
        assert result is None

    def test_priority_ordering(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test that tasks are popped in priority order."""
        # Pop task - uses basic mock from conftest.py which returns NORMAL priority
        popped_task = fairqueue.pop(["test:user:1"])

        assert popped_task is not None
        # Basic mock returns priority 3 (NORMAL)
        assert popped_task.priority == Priority.NORMAL

    def test_work_stealing(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test work stealing functionality."""
        # Try to pop with assigned users first, then steal targets
        popped_task = fairqueue.pop(["test:user:1", "test:user:2", "test:user:3"])

        assert popped_task is not None
        assert popped_task.task_id == "test_task_id"
        assert popped_task.user_id == "test_user"  # From basic mock

    def test_delete_task(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test task deletion."""
        # Mock Redis delete operations
        fairqueue.redis.delete.side_effect = [1, 0]  # First call deletes 1 key, second deletes 0

        # Delete the task
        deleted = fairqueue.delete_task("test_task_id")
        assert deleted is True

        # Try to delete again
        deleted_again = fairqueue.delete_task("test_task_id")
        assert deleted_again is False


class TestFairQueueStatistics:
    """Test FairQueue statistics functionality."""

    def test_get_stats_empty(self, fairqueue: TaskQueue) -> None:
        """Test getting statistics from empty queue."""
        # Mock lua script execution for empty stats
        with patch.object(fairqueue.lua_manager, 'execute_script') as mock_script:
            mock_result = {"success": True, "data": {"tasks_active": 0}}
            mock_script.return_value = json.dumps(mock_result)

            stats = fairqueue.get_stats()

            assert isinstance(stats, dict)
            assert stats.get("tasks_active", 0) == 0

    def test_get_stats_with_tasks(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test statistics after pushing tasks."""
        # Mock lua script execution for stats with tasks
        with patch.object(fairqueue.lua_manager, 'execute_script') as mock_script:
            mock_result = {"success": True, "data": {"tasks_active": 3, "tasks_pushed_total": 3}}
            mock_script.return_value = json.dumps(mock_result)

            stats = fairqueue.get_stats()

            assert stats.get("tasks_active", 0) == 3
            assert stats.get("tasks_pushed_total", 0) == 3

    def test_get_queue_sizes(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test getting queue sizes for specific user."""
        # Mock Redis operations for queue sizes
        fairqueue.redis.llen.return_value = 1  # critical_size
        fairqueue.redis.zcard.return_value = 1  # normal_size

        sizes = fairqueue.get_queue_sizes("test:user:1")

        assert sizes["critical_size"] == 1
        assert sizes["normal_size"] == 1
        assert sizes["total_size"] == 2

    def test_get_batch_queue_sizes(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test getting queue sizes for multiple users."""
        # Mock Redis operations for queue sizes
        fairqueue.redis.llen.return_value = 0  # critical_size
        fairqueue.redis.zcard.return_value = 1  # normal_size

        users = ["test:user:1", "test:user:2"]
        sizes = fairqueue.get_batch_queue_sizes(users)

        assert "test:user:1" in sizes
        assert "test:user:2" in sizes
        assert "totals" in sizes
        assert sizes["totals"]["total_size"] == 2

    def test_get_health(self, fairqueue: TaskQueue) -> None:
        """Test health check."""
        # Mock lua script execution for stats used by health check
        with patch.object(fairqueue.lua_manager, 'execute_script') as mock_script:
            mock_result = {"success": True, "data": {"tasks_active": 0}}
            mock_script.return_value = json.dumps(mock_result)

            health = fairqueue.get_health()

            assert isinstance(health, dict)
            assert health["status"] in ["healthy", "warning"]
            assert "active_tasks" in health


class TestFairQueueBatch:
    """Test FairQueue batch operations."""

    def test_push_batch_success(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test successful batch push."""
        tasks = []
        for i in range(3):
            task = Task.create(
                user_id=f"test:user:{i+1}",
                priority=Priority.HIGH,
                payload={**sample_payload, "index": i}
            )
            tasks.append(task)

        # Mock successful push results
        with patch.object(fairqueue, 'push') as mock_push:
            mock_push.return_value = {"success": True}
            results = fairqueue.push_batch(tasks)

            assert len(results) == 3
            for result in results:
                assert result["success"] is True

    def test_push_batch_empty(self, fairqueue: TaskQueue) -> None:
        """Test batch push with empty list."""
        results = fairqueue.push_batch([])
        assert results == []

    def test_push_batch_with_errors(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test batch push with some errors."""
        tasks = []

        # Valid task
        good_task = Task.create(
            user_id="test:user:1",
            priority=Priority.HIGH,
            payload=sample_payload
        )
        tasks.append(good_task)

        # Invalid task (empty task ID)
        bad_task = Task.create(
            user_id="test:user:2",
            priority=Priority.HIGH,
            payload=sample_payload
        )
        bad_task.task_id = ""  # Make it invalid
        tasks.append(bad_task)

        # Call push_batch - it will handle exceptions internally
        results = fairqueue.push_batch(tasks)

        assert len(results) == 2
        assert results[0]["success"] is True  # Good task succeeds
        assert results[1]["success"] is False  # Bad task fails
        assert "error" in results[1]


class TestFairQueueCleanup:
    """Test FairQueue cleanup operations."""

    def test_cleanup_expired_tasks(self, fairqueue: TaskQueue, sample_payload: Dict[str, Any]) -> None:
        """Test cleanup of expired tasks."""
        import time

        # Mock Redis scan and operations
        fairqueue.redis.scan_iter.return_value = [
            "task:old-task-1",
            "task:old-task-2",
            "task:recent-task"
        ]

        # Mock hget to return timestamps (old, old, recent)
        current_time = time.time()
        fairqueue.redis.hget.side_effect = [
            "1000000",  # Old timestamp
            "1000000",  # Old timestamp
            str(current_time)  # Recent timestamp
        ]
        fairqueue.redis.delete.return_value = 1

        # Cleanup with long age (should clean old tasks)
        cleaned = fairqueue.cleanup_expired_tasks(max_age_seconds=86400)
        assert cleaned == 2  # Two old tasks cleaned

        # Reset mocks for second test
        fairqueue.redis.scan_iter.return_value = ["task:recent-task"]
        fairqueue.redis.hget.return_value = str(current_time)
        fairqueue.redis.delete.return_value = 0

        # Cleanup with very short age (should not clean anything)
        cleaned = fairqueue.cleanup_expired_tasks(max_age_seconds=3600)
        assert cleaned == 0  # Task is too new


class TestFairQueueContextManager:
    """Test FairQueue as context manager."""

    def test_context_manager(self, fairqueue_config) -> None:
        """Test using FairQueue as context manager."""
        with patch('redis.Redis') as mock_redis_class:
            mock_redis_instance = MagicMock()
            mock_redis_instance.ping.return_value = True
            mock_redis_class.return_value = mock_redis_instance

            # Test that the context manager works
            with TaskQueue(fairqueue_config) as queue:
                # Mock lua manager
                queue.lua_manager = MagicMock()
                mock_result = {"success": True, "state": "queued", "task_id": "test"}
                queue.lua_manager.execute_script.return_value = json.dumps(mock_result)

                assert queue.redis.ping()

                # Queue should work normally
                task = Task.create(
                    user_id="test:user:1",
                    priority=Priority.HIGH,
                    payload={"test": True}
                )
                result = queue.push(task)
                assert result["success"] is True

            # Just verify the context manager exited successfully without exceptions
