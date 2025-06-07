"""Tests for core models: Priority, Task, and DLQEntry."""

import json
import time
from typing import Any, Dict

import pytest

from fairque.core.exceptions import TaskSerializationError
from fairque.core.models import Priority, Task, calculate_score


class TestPriority:
    """Test Priority enum functionality."""

    def test_priority_values(self) -> None:
        """Test priority enum values."""
        assert Priority.VERY_LOW == 1
        assert Priority.LOW == 2
        assert Priority.NORMAL == 3
        assert Priority.HIGH == 4
        assert Priority.VERY_HIGH == 5
        assert Priority.CRITICAL == 6

    def test_priority_weight(self) -> None:
        """Test priority weight calculation."""
        assert Priority.VERY_LOW.weight == 0.2
        assert Priority.LOW.weight == 0.4
        assert Priority.NORMAL.weight == 0.6
        assert Priority.HIGH.weight == 0.8
        assert Priority.VERY_HIGH.weight == 1.0

    def test_critical_priority_weight_error(self) -> None:
        """Test that CRITICAL priority raises error for weight."""
        with pytest.raises(ValueError, match="Critical priority does not use weight calculation"):
            _ = Priority.CRITICAL.weight

    def test_is_critical(self) -> None:
        """Test is_critical property."""
        assert not Priority.VERY_LOW.is_critical
        assert not Priority.LOW.is_critical
        assert not Priority.NORMAL.is_critical
        assert not Priority.HIGH.is_critical
        assert not Priority.VERY_HIGH.is_critical
        assert Priority.CRITICAL.is_critical

    def test_from_int(self) -> None:
        """Test creating Priority from integer."""
        assert Priority.from_int(1) == Priority.VERY_LOW
        assert Priority.from_int(3) == Priority.NORMAL
        assert Priority.from_int(6) == Priority.CRITICAL

    def test_from_int_invalid(self) -> None:
        """Test invalid integer values."""
        with pytest.raises(ValueError, match="Invalid priority value: 0"):
            Priority.from_int(0)

        with pytest.raises(ValueError, match="Invalid priority value: 7"):
            Priority.from_int(7)


class TestTask:
    """Test Task model functionality."""

    def test_task_creation(self, sample_payload: Dict[str, Any]) -> None:
        """Test creating a task."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.HIGH,
            payload=sample_payload
        )

        assert task.user_id == "test:user:1"
        assert task.priority == Priority.HIGH
        assert task.payload == sample_payload
        assert task.retry_count == 0
        assert task.max_retries == 3
        assert isinstance(task.task_id, str)
        assert len(task.task_id) == 36  # UUID4 format
        assert task.created_at > 0
        assert task.execute_after > 0

    def test_task_with_custom_retries(self, sample_payload: Dict[str, Any]) -> None:
        """Test creating task with custom retry settings."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.NORMAL,
            payload=sample_payload,
            max_retries=5
        )

        assert task.max_retries == 5

    def test_task_with_future_execution(self, sample_payload: Dict[str, Any]) -> None:
        """Test creating task with future execution time."""
        future_time = time.time() + 3600  # 1 hour from now

        task = Task.create(
            user_id="test:user:1",
            priority=Priority.NORMAL,
            payload=sample_payload,
            execute_after=future_time
        )

        assert task.execute_after == future_time

    def test_is_ready_to_execute(self, sample_payload: Dict[str, Any]) -> None:
        """Test ready to execute check."""
        # Task ready now
        task_now = Task.create(
            user_id="test:user:1",
            priority=Priority.NORMAL,
            payload=sample_payload
        )
        assert task_now.is_ready_to_execute()

        # Task ready in future
        future_time = time.time() + 3600
        task_future = Task.create(
            user_id="test:user:1",
            priority=Priority.NORMAL,
            payload=sample_payload,
            execute_after=future_time
        )
        assert not task_future.is_ready_to_execute()

    def test_can_retry(self, sample_payload: Dict[str, Any]) -> None:
        """Test retry capability check."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.NORMAL,
            payload=sample_payload,
            max_retries=2
        )

        # Initial state
        assert task.can_retry()

        # After increments
        task.retry_count = 1
        assert task.can_retry()

        task.retry_count = 2
        assert not task.can_retry()

    def test_get_retry_delay(self, sample_payload: Dict[str, Any]) -> None:
        """Test retry delay calculation."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.NORMAL,
            payload=sample_payload
        )

        assert task.get_retry_delay() == 1.0  # 2^0

        task.retry_count = 1
        assert task.get_retry_delay() == 2.0  # 2^1

        task.retry_count = 3
        assert task.get_retry_delay() == 8.0  # 2^3

    def test_increment_retry(self, sample_payload: Dict[str, Any]) -> None:
        """Test retry increment."""
        original_time = time.time()
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.NORMAL,
            payload=sample_payload
        )

        # Increment retry
        new_task = task.increment_retry()

        assert new_task.retry_count == 1
        assert new_task.execute_after > original_time + 1.0  # Should have delay
        assert new_task.task_id == task.task_id  # Same task ID
        assert new_task is not task  # Different instance

    def test_to_redis_dict(self, sample_payload: Dict[str, Any]) -> None:
        """Test serialization to Redis dictionary."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.HIGH,
            payload=sample_payload
        )

        redis_dict = task.to_redis_dict()

        assert redis_dict["task_id"] == task.task_id
        assert redis_dict["user_id"] == "test:user:1"
        assert redis_dict["priority"] == "4"
        assert json.loads(redis_dict["payload"]) == sample_payload
        assert redis_dict["retry_count"] == "0"
        assert redis_dict["max_retries"] == "3"
        assert float(redis_dict["created_at"]) == task.created_at
        assert float(redis_dict["execute_after"]) == task.execute_after

    def test_from_redis_dict(self, sample_payload: Dict[str, Any]) -> None:
        """Test deserialization from Redis dictionary."""
        original_task = Task.create(
            user_id="test:user:1",
            priority=Priority.HIGH,
            payload=sample_payload
        )

        # Serialize and deserialize
        redis_dict = original_task.to_redis_dict()
        restored_task = Task.from_redis_dict(redis_dict)

        assert restored_task.task_id == original_task.task_id
        assert restored_task.user_id == original_task.user_id
        assert restored_task.priority == original_task.priority
        assert restored_task.payload == original_task.payload
        assert restored_task.retry_count == original_task.retry_count
        assert restored_task.max_retries == original_task.max_retries
        assert abs(restored_task.created_at - original_task.created_at) < 1e-5
        assert abs(restored_task.execute_after - original_task.execute_after) < 1e-5

    def test_from_redis_dict_invalid(self) -> None:
        """Test deserialization with invalid data."""
        # Missing fields
        with pytest.raises(TaskSerializationError):
            Task.from_redis_dict({"task_id": "test"})

        # Invalid JSON payload
        with pytest.raises(TaskSerializationError):
            Task.from_redis_dict({
                "task_id": "test",
                "user_id": "user:1",
                "priority": "3",
                "payload": "invalid-json",
                "retry_count": "0",
                "max_retries": "3",
                "created_at": "123.456",
                "execute_after": "123.456"
            })

    def test_to_lua_args(self, sample_payload: Dict[str, Any]) -> None:
        """Test conversion to Lua arguments."""
        task = Task.create(
            user_id="test:user:1",
            priority=Priority.HIGH,
            payload=sample_payload
        )

        lua_args = task.to_lua_args()

        assert len(lua_args) == 8
        assert lua_args[0] == task.task_id
        assert lua_args[1] == "test:user:1"
        assert lua_args[2] == "4"
        assert json.loads(lua_args[3]) == sample_payload

    def test_from_lua_result(self, sample_payload: Dict[str, Any]) -> None:
        """Test restoration from Lua result."""
        original_task = Task.create(
            user_id="test:user:1",
            priority=Priority.HIGH,
            payload=sample_payload
        )

        # Convert to Lua args and back
        lua_args = original_task.to_lua_args()
        restored_task = Task.from_lua_result(lua_args)

        assert restored_task.task_id == original_task.task_id
        assert restored_task.user_id == original_task.user_id
        assert restored_task.priority == original_task.priority
        assert restored_task.payload == original_task.payload

    def test_from_lua_result_invalid(self) -> None:
        """Test invalid Lua result."""
        with pytest.raises(TaskSerializationError, match="Invalid lua_args length"):
            Task.from_lua_result(["too", "few", "args"])


class TestCalculateScore:
    """Test score calculation function."""

    def test_calculate_score_normal_priority(self) -> None:
        """Test score calculation for normal priorities."""
        created_at = time.time() - 100  # 100 seconds ago

        # High priority task (weight = 0.8)
        task = Task(
            task_id="test",
            user_id="user:1",
            priority=Priority.HIGH,
            payload={},
            created_at=created_at,
            execute_after=created_at
        )

        score = calculate_score(task)
        expected_score = created_at + (0.8 * 100)  # created_at + (weight * elapsed_time)

        assert abs(score - expected_score) < 1.0  # Allow small time difference

    def test_calculate_score_critical_priority(self) -> None:
        """Test that critical priority raises error."""
        task = Task(
            task_id="test",
            user_id="user:1",
            priority=Priority.CRITICAL,
            payload={},
            created_at=time.time(),
            execute_after=time.time()
        )

        with pytest.raises(ValueError, match="Critical tasks do not use score calculation"):
            calculate_score(task)
