"""Unit tests for task scheduler functionality."""

import json
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from fairque.core.config import FairQueueConfig
from fairque.core.models import Priority, Task
from fairque.scheduler.models import ScheduledTask
from fairque.scheduler.scheduler import TaskScheduler


class TestScheduledTask(unittest.TestCase):
    """Test cases for ScheduledTask model."""

    def test_create_scheduled_task(self):
        """Test creating a scheduled task."""
        # Create a Task object first
        task = Task.create(
            user_id="user1",
            priority=Priority.NORMAL,
            payload={"action": "test"},
        )

        scheduled_task = ScheduledTask.create(
            cron_expr="0 9 * * *",
            task=task,
            timezone="UTC",
        )

        assert scheduled_task.schedule_id is not None
        assert scheduled_task.cron_expression == "0 9 * * *"
        assert scheduled_task.task.user_id == "user1"
        assert scheduled_task.task.priority == Priority.NORMAL
        assert scheduled_task.task.payload == {"action": "test"}
        assert scheduled_task.timezone == "UTC"
        assert scheduled_task.is_active is True
        assert scheduled_task.last_run is None
        assert scheduled_task.next_run is not None

    def test_calculate_next_run(self):
        """Test calculating next run time."""
        # Test with a simple cron expression
        task = Task.create(
            user_id="user1",
            priority=Priority.NORMAL,
            payload={},
        )

        scheduled_task = ScheduledTask.create(
            cron_expr="0 0 * * *",  # Daily at midnight
            task=task,
        )

        # Calculate next run
        base_time = datetime(2024, 1, 1, 10, 0, 0).timestamp()
        next_run = scheduled_task.calculate_next_run(from_time=base_time)

        # Should be next midnight (the next time "0 0 * * *" occurs after 10:00 AM on Jan 1)
        # That would be midnight on Jan 2
        import pytz
        from croniter import croniter

        tz = pytz.UTC
        base_dt = datetime.fromtimestamp(base_time, tz)
        cron = croniter("0 0 * * *", base_dt)
        expected_next = cron.get_next(datetime).timestamp()

        assert next_run == expected_next

    def test_invalid_cron_expression(self):
        """Test handling of invalid cron expression."""
        task = Task.create(
            user_id="user1",
            priority=Priority.NORMAL,
            payload={},
        )

        with pytest.raises(ValueError, match="Invalid cron expression"):
            ScheduledTask.create(
                cron_expr="invalid cron",
                task=task,
            )

    def test_invalid_timezone(self):
        """Test handling of invalid timezone."""
        task = Task.create(
            user_id="user1",
            priority=Priority.NORMAL,
            payload={},
        )

        with pytest.raises(ValueError, match="Unknown timezone"):
            ScheduledTask.create(
                cron_expr="0 0 * * *",
                task=task,
                timezone="Invalid/Timezone",
            )

    def test_create_task(self):
        """Test converting scheduled task to regular task."""
        original_task = Task.create(
            user_id="user1",
            priority=Priority.HIGH,
            payload={"action": "test", "value": 123},
        )

        scheduled_task = ScheduledTask.create(
            cron_expr="0 0 * * *",
            task=original_task,
        )

        task = scheduled_task.create_task()

        assert isinstance(task, Task)
        assert task.user_id == "user1"
        assert task.priority == Priority.HIGH
        assert task.payload["action"] == "test"
        assert task.payload["value"] == 123
        assert task.payload["__scheduled__"] is True
        assert task.payload["__schedule_id__"] == scheduled_task.schedule_id

    def test_update_after_run(self):
        """Test updating schedule after execution."""
        task = Task.create(
            user_id="user1",
            priority=Priority.NORMAL,
            payload={},
        )

        scheduled_task = ScheduledTask.create(
            cron_expr="0 * * * *",  # Hourly
            task=task,
        )

        original_next_run = scheduled_task.next_run
        run_time = time.time()

        scheduled_task.update_after_run(run_time)

        assert scheduled_task.last_run == run_time
        assert scheduled_task.next_run is not None
        assert original_next_run is not None
        # For "0 * * * *" (hourly), next run should be after current time
        assert scheduled_task.next_run >= run_time
        assert scheduled_task.updated_at >= run_time

    def test_serialization(self):
        """Test serialization to/from dict and JSON."""
        task = Task.create(
            user_id="user1",
            priority=Priority.LOW,
            payload={"key": "value"},
        )

        scheduled_task = ScheduledTask.create(
            cron_expr="*/5 * * * *",
            task=task,
            metadata={"description": "Test task"},
        )

        # Test to_dict
        data = scheduled_task.to_dict()
        assert data["schedule_id"] == scheduled_task.schedule_id
        assert data["cron_expression"] == "*/5 * * * *"
        # Priority gets serialized as string in task redis dict
        assert int(data["task"]["priority"]) == Priority.LOW.value

        # Test from_dict
        restored = ScheduledTask.from_dict(data)
        assert restored.schedule_id == scheduled_task.schedule_id
        assert restored.cron_expression == scheduled_task.cron_expression
        assert restored.task.priority == scheduled_task.task.priority

        # Test to_json/from_json
        json_str = scheduled_task.to_json()
        restored_from_json = ScheduledTask.from_json(json_str)
        assert restored_from_json.schedule_id == scheduled_task.schedule_id
        assert restored_from_json.task.payload == scheduled_task.task.payload


class TestTaskScheduler(unittest.TestCase):
    """Test cases for TaskScheduler."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock Redis client and config
        self.mock_redis = MagicMock()
        self.mock_config = MagicMock(spec=FairQueueConfig)
        self.mock_config.create_redis_client.return_value = self.mock_redis

        # Configure Redis mock
        self.mock_redis.ping.return_value = True
        self.mock_redis.register_script.return_value = MagicMock()

        # Create scheduler
        self.scheduler = TaskScheduler(
            config=self.mock_config,
            scheduler_id="test-scheduler",
            check_interval=1,  # 1 second for tests
            lock_timeout=60,
        )

    def tearDown(self):
        """Clean up test fixtures."""
        pass

    def test_add_schedule(self):
        """Test adding a new schedule."""
        # Mock Redis hset
        self.mock_redis.hset.return_value = True

        # Create a task to schedule
        task = Task.create(
            user_id="user1",
            priority=Priority.NORMAL,
            payload={"action": "test"},
        )

        schedule_id = self.scheduler.add_schedule(
            cron_expr="0 0 * * *",
            task=task,
        )

        assert schedule_id is not None
        self.mock_redis.hset.assert_called_once()

        # Verify the call arguments
        call_args = self.mock_redis.hset.call_args[0]
        assert call_args[0] == self.scheduler.schedules_key
        assert call_args[1] == schedule_id

        # Verify the stored data
        stored_data = json.loads(call_args[2])
        assert stored_data["schedule_id"] == schedule_id
        assert stored_data["cron_expression"] == "0 0 * * *"
        assert stored_data["task"]["user_id"] == "user1"

    def test_get_schedule(self):
        """Test retrieving a schedule."""
        # Create a proper ScheduledTask and serialize it
        task = Task.create(
            user_id="user1",
            priority=Priority.NORMAL,
            payload={"action": "test"},
        )

        scheduled_task = ScheduledTask.create(
            cron_expr="0 0 * * *",
            task=task,
        )
        scheduled_task.schedule_id = "test-id"  # Set specific ID for test

        # Mock the Redis response with serialized data
        self.mock_redis.hget.return_value = scheduled_task.to_json()

        schedule = self.scheduler.get_schedule("test-id")

        assert schedule is not None
        assert schedule.schedule_id == "test-id"
        assert schedule.task.user_id == "user1"
        assert schedule.task.priority == Priority.NORMAL
        self.mock_redis.hget.assert_called_once_with(
            self.scheduler.schedules_key, "test-id"
        )

    def test_update_schedule(self):
        """Test updating a schedule."""
        # Create original schedule
        task = Task.create(
            user_id="user1",
            priority=Priority.NORMAL,
            payload={"action": "test"},
        )

        original_schedule = ScheduledTask.create(
            cron_expr="0 0 * * *",
            task=task,
        )

        self.mock_redis.hget.return_value = original_schedule.to_json()
        self.mock_redis.hset.return_value = True

        # Create updated task for update
        updated_task = Task.create(
            user_id="user1",
            priority=Priority.HIGH,
            payload={"action": "test"},
        )

        # Update schedule
        result = self.scheduler.update_schedule(
            original_schedule.schedule_id,
            cron_expr="0 */2 * * *",  # Every 2 hours
            task=updated_task,
        )

        assert result is True

        # Verify update was saved
        self.mock_redis.hset.assert_called_once()
        call_args = self.mock_redis.hset.call_args[0]
        updated_data = json.loads(call_args[2])

        assert updated_data["cron_expression"] == "0 */2 * * *"
        # Priority gets serialized as string in task redis dict
        assert int(updated_data["task"]["priority"]) == Priority.HIGH.value

    def test_remove_schedule(self):
        """Test removing a schedule."""
        self.mock_redis.hdel.return_value = 1

        result = self.scheduler.remove_schedule("test-id")

        assert result is True
        self.mock_redis.hdel.assert_called_once_with(
            self.scheduler.schedules_key, "test-id"
        )

    def test_list_schedules(self):
        """Test listing schedules with filters."""
        # Create test schedules
        task1 = Task.create(user_id="user1", priority=Priority.NORMAL, payload={})
        task2 = Task.create(user_id="user2", priority=Priority.HIGH, payload={})
        task3 = Task.create(user_id="user1", priority=Priority.LOW, payload={})

        schedules_data = {
            "id1": ScheduledTask.create(
                cron_expr="0 0 * * *",
                task=task1,
            ).to_json(),
            "id2": ScheduledTask.create(
                cron_expr="0 0 * * *",
                task=task2,
            ).to_json(),
            "id3": ScheduledTask.create(
                cron_expr="0 0 * * *",
                task=task3,
            ).to_json(),
        }

        self.mock_redis.hgetall.return_value = schedules_data

        # Test listing all schedules
        all_schedules = self.scheduler.list_schedules()
        assert len(all_schedules) == 3

        # Test filtering by user
        user1_schedules = self.scheduler.list_schedules(user_id="user1")
        assert len(user1_schedules) == 2
        assert all(s.task.user_id == "user1" for s in user1_schedules)

    def test_distributed_locking(self):
        """Test distributed locking mechanism."""
        # Test acquiring lock
        self.mock_redis.set.return_value = True
        assert self.scheduler._try_acquire_lock() is True

        self.mock_redis.set.assert_called_once()
        call_args = self.mock_redis.set.call_args
        assert call_args[0][0] == self.scheduler.lock_key
        assert call_args[1]["nx"] is True
        assert call_args[1]["ex"] == self.scheduler.lock_timeout

        # Test failing to acquire lock
        self.mock_redis.set.return_value = None
        assert self.scheduler._try_acquire_lock() is False

    def test_process_scheduled_tasks(self):
        """Test processing scheduled tasks."""
        # Create a schedule that's ready to run
        current_time = time.time()

        task = Task.create(
            user_id="user1",
            priority=Priority.NORMAL,
            payload={"action": "test"},
        )

        schedule = ScheduledTask.create(
            cron_expr="* * * * *",  # Every minute
            task=task,
        )
        schedule.next_run = current_time - 10  # Past due

        # Mock methods
        self.scheduler.list_schedules = MagicMock(return_value=[schedule])
        self.scheduler.queue.push = MagicMock(return_value={"task_id": "new-task-id"})
        self.mock_redis.hset.return_value = True

        # Process tasks
        self.scheduler._process_scheduled_tasks()

        # Verify task was pushed to queue
        self.scheduler.queue.push.assert_called_once()
        pushed_task = self.scheduler.queue.push.call_args[0][0]
        assert pushed_task.user_id == "user1"
        assert pushed_task.payload["__scheduled__"] is True

        # Verify schedule was updated
        self.mock_redis.hset.assert_called_once()

    def test_start_stop(self):
        """Test starting and stopping scheduler."""
        assert self.scheduler.is_running is False

        # Start scheduler
        self.scheduler.start()
        assert self.scheduler.is_running is True
        assert self.scheduler._scheduler_thread is not None
        assert self.scheduler._scheduler_thread.is_alive()

        # Stop scheduler
        self.scheduler.stop()
        assert self.scheduler.is_running is False

        # Wait a bit for thread to stop
        time.sleep(0.1)
        assert not self.scheduler._scheduler_thread.is_alive()

    def test_get_statistics(self):
        """Test getting scheduler statistics."""
        # Mock some schedules
        task1 = Task.create(user_id="user1", priority=Priority.NORMAL, payload={})
        task2 = Task.create(user_id="user1", priority=Priority.HIGH, payload={})
        task3 = Task.create(user_id="user2", priority=Priority.NORMAL, payload={})

        schedules = [
            ScheduledTask.create(
                cron_expr="0 0 * * *",
                task=task1,
            ),
            ScheduledTask.create(
                cron_expr="0 0 * * *",
                task=task2,
            ),
            ScheduledTask.create(
                cron_expr="0 0 * * *",
                task=task3,
            ),
        ]
        schedules[2].is_active = False  # One inactive

        self.scheduler.list_schedules = MagicMock(return_value=schedules)

        stats = self.scheduler.get_statistics()

        assert stats["scheduler_id"] == "test-scheduler"
        assert stats["total_schedules"] == 3
        assert stats["active_schedules"] == 2
        assert stats["inactive_schedules"] == 1
        assert stats["schedules_by_user"]["user1"] == 2
        assert "user2" not in stats["schedules_by_user"]  # Inactive not counted
        assert stats["schedules_by_priority"]["NORMAL"] == 1
        assert stats["schedules_by_priority"]["HIGH"] == 1
