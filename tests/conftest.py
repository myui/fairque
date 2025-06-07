"""Test configuration and fixtures for FairQueue tests."""

from typing import Generator
from unittest.mock import MagicMock

import pytest

from fairque import FairQueueConfig, TaskQueue
from fairque.core.config import QueueConfig, RedisConfig, WorkerConfig


@pytest.fixture
def redis_config() -> RedisConfig:
    """Redis configuration for tests."""
    return RedisConfig(
        host="localhost",
        port=6379,
        db=15,  # Use test database
        decode_responses=True
    )


@pytest.fixture
def worker_config() -> WorkerConfig:
    """Worker configuration for tests."""
    return WorkerConfig(
        id="test-worker",
        assigned_users=["test:user:1", "test:user:2"],
        poll_interval_seconds=0.1,  # Fast polling for tests
        task_timeout_seconds=5.0,
        max_concurrent_tasks=2,
        graceful_shutdown_timeout=5.0
    )


@pytest.fixture
def queue_config() -> QueueConfig:
    """Queue configuration for tests."""
    return QueueConfig(
        stats_prefix="test_fq",
        lua_script_cache_size=10,
        max_retry_attempts=2,
        default_task_timeout=5.0,
        default_max_retries=2,
        enable_pipeline_optimization=True,
        pipeline_batch_size=10,
        pipeline_timeout=1.0,
        queue_cleanup_interval=60,
        stats_aggregation_interval=30
    )


@pytest.fixture
def fairqueue_config(
    redis_config: RedisConfig,
    worker_config: WorkerConfig,
    queue_config: QueueConfig
) -> FairQueueConfig:
    """Complete FairQueue configuration for tests."""
    return FairQueueConfig(
        redis=redis_config,
        workers=[worker_config],
        queue=queue_config
    )


@pytest.fixture
def redis_client(redis_config: RedisConfig) -> Generator[MagicMock, None, None]:
    """Mocked Redis client for tests."""
    mock_client = MagicMock()
    mock_client.ping.return_value = True
    mock_client.flushdb.return_value = True
    mock_client.delete.return_value = 1
    mock_client.scan_iter.return_value = []
    mock_client.hget.return_value = None
    mock_client.close.return_value = None

    # Create different mocks for different scripts based on their registration
    scripts = {}

    def register_script_mock(script_content):
        """Mock script registration that tracks script types."""
        mock_script = MagicMock()

        if "pop" in script_content.lower():
            # Mock for pop script - return a task
            mock_script.return_value = '{"success": true, "task": {"task_id": "test_task_id", "user_id": "test_user", "priority": 3, "payload": "{\\"task_id\\": \\"test_task_id\\", \\"user_id\\": \\"test_user\\", \\"priority\\": 3, \\"payload\\": {\\"action\\": \\"test_action\\", \\"value\\": 42}, \\"state\\": \\"queued\\"}"}}'
        else:
            # Mock for push and other scripts
            mock_script.return_value = '{"success": true, "state": "queued", "task_id": "test_task_id"}'

        return mock_script

    mock_client.register_script.side_effect = register_script_mock

    yield mock_client


@pytest.fixture
def fairqueue(fairqueue_config: FairQueueConfig, redis_client: MagicMock) -> Generator[TaskQueue, None, None]:
    """FairQueue instance for tests with mocked Redis."""
    queue = TaskQueue(fairqueue_config, redis_client)
    yield queue
    # Cleanup
    queue.close()


@pytest.fixture
def sample_payload() -> dict:
    """Sample task payload for tests."""
    return {
        "action": "test_action",
        "data": {"key": "value", "number": 42},
        "metadata": {"test": True}
    }
