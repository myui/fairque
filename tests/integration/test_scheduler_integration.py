"""Integration tests for scheduler functionality."""

import time
from datetime import datetime, timedelta

import pytest

from fairque.core.models import Priority, Task
from fairque.queue.queue import TaskQueue
from fairque.scheduler import TaskScheduler
from fairque.worker import TaskHandler, Worker


class TestSchedulerIntegration:
    """Integration tests for TaskScheduler with FairQueue."""

    @pytest.fixture
    def config(self, fairqueue_config):
        """Create test configuration."""
        return fairqueue_config

    @pytest.fixture
    def queue(self, config, redis_client):
        """Create FairQueue instance."""
        return TaskQueue(config, redis_client)

    @pytest.fixture
    def scheduler(self, config):
        """Create TaskScheduler instance."""
        scheduler = TaskScheduler(
            config=config,
            scheduler_id="test-scheduler",
            check_interval=1,  # 1 second for tests
        )
        yield scheduler
        # Cleanup: remove all schedules
        for schedule in scheduler.list_schedules():
            scheduler.remove_schedule(schedule.schedule_id)

    def test_schedule_and_execute_task(self, scheduler, queue):
        """Test scheduling and executing a task."""
        # Create task to be scheduled
        task = Task.create(
            user_id="test_user",
            priority=Priority.NORMAL,
            payload={"action": "test_action", "value": 42},
        )

        # Add a schedule that runs every minute
        schedule_id = scheduler.add_schedule(
            cron_expr="* * * * *",  # Every minute
            task=task,
        )

        assert schedule_id is not None

        # Get the schedule
        schedule = scheduler.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.task.user_id == "test_user"
        assert schedule.task.priority == Priority.NORMAL

        # Manually trigger task creation
        task = schedule.create_task()
        assert task.user_id == "test_user"
        assert task.payload["action"] == "test_action"
        assert task.payload["__scheduled__"] is True

        # Push task to queue
        result = queue.push(task)
        assert "task_id" in result

        # Pop task from queue
        popped_task = queue.pop(["test_user"])
        assert popped_task is not None
        assert popped_task.user_id == "test_user"
        # Note: task_id might be different due to mocking, that's OK for this test

    def test_scheduler_with_worker(self, scheduler, queue, config):
        """Test scheduler with worker processing."""
        # Track processed tasks
        processed_tasks = []

        class TestHandler(TaskHandler):
            def process(self, task_id: str, user_id: str, payload: dict) -> bool:
                processed_tasks.append({
                    "task_id": task_id,
                    "user_id": user_id,
                    "payload": payload,
                })
                return True

        # Create worker
        handler = TestHandler()
        worker = Worker(config, handler)

        # Add a schedule that runs frequently
        task = Task.create(
            user_id="test_user",
            priority=Priority.HIGH,
            payload={"action": "frequent_task"},
        )
        schedule_id = scheduler.add_schedule(
            cron_expr="* * * * * *",  # Every second (non-standard but supported by croniter)
            task=task,
        )

        # Start scheduler and worker
        scheduler.start()
        worker.start()

        try:
            # Wait for at least one task to be processed
            time.sleep(3)

            # Check that tasks were processed
            assert len(processed_tasks) > 0

            # Verify task details
            for task in processed_tasks:
                assert task["user_id"] == "test_user"
                assert task["payload"]["action"] == "frequent_task"
                assert task["payload"]["__scheduled__"] is True
                assert task["payload"]["__schedule_id__"] == schedule_id

        finally:
            # Stop scheduler and worker
            scheduler.stop()
            worker.stop()

    def test_multiple_schedules(self, scheduler):
        """Test managing multiple schedules."""
        # Add multiple schedules
        schedule_ids = []

        for i in range(3):
            task = Task.create(
                user_id=f"user_{i}",
                priority=Priority(i + 1),  # Different priorities
                payload={"task_number": i},
            )
            schedule_id = scheduler.add_schedule(
                cron_expr=f"0 {i} * * *",  # Different hours
                task=task,
            )
            schedule_ids.append(schedule_id)

        # List all schedules
        all_schedules = scheduler.list_schedules()
        assert len(all_schedules) == 3

        # Filter by user
        user_1_schedules = scheduler.list_schedules(user_id="user_1")
        assert len(user_1_schedules) == 1
        assert user_1_schedules[0].user_id == "user_1"

        # Update a schedule
        success = scheduler.update_schedule(
            schedule_ids[0],
            is_active=False,
            metadata={"updated": True},
        )
        assert success is True

        # Check active schedules
        active_schedules = scheduler.list_schedules(is_active=True)
        assert len(active_schedules) == 2

        # Remove a schedule
        removed = scheduler.remove_schedule(schedule_ids[1])
        assert removed is True

        # Verify removal
        remaining_schedules = scheduler.list_schedules()
        assert len(remaining_schedules) == 2

    def test_timezone_handling(self, scheduler):
        """Test scheduling with different timezones."""
        # Add schedules with different timezones
        task_utc = Task.create(
            user_id="user_utc",
            priority=Priority.NORMAL,
            payload={"timezone": "UTC"},
        )
        schedule_id_utc = scheduler.add_schedule(
            cron_expr="0 12 * * *",  # Noon
            task=task_utc,
            timezone="UTC",
        )

        task_ny = Task.create(
            user_id="user_ny",
            priority=Priority.NORMAL,
            payload={"timezone": "New York"},
        )
        schedule_id_ny = scheduler.add_schedule(
            cron_expr="0 12 * * *",  # Noon
            task=task_ny,
            timezone="America/New_York",
        )

        # Get schedules
        schedule_utc = scheduler.get_schedule(schedule_id_utc)
        schedule_ny = scheduler.get_schedule(schedule_id_ny)

        # Verify next run times are different (due to timezone difference)
        assert schedule_utc.next_run != schedule_ny.next_run

        # The difference should be the timezone offset
        utc_dt = datetime.fromtimestamp(schedule_utc.next_run)
        ny_dt = datetime.fromtimestamp(schedule_ny.next_run)

        # New York is typically 4-5 hours behind UTC
        time_diff = abs(utc_dt - ny_dt)
        assert timedelta(hours=3) <= time_diff <= timedelta(hours=6)

    def test_scheduler_statistics(self, scheduler):
        """Test scheduler statistics."""
        # Add some schedules
        for i in range(5):
            task = Task.create(
                user_id=f"user_{i % 2}",  # Two users
                priority=Priority((i % 3) + 1),  # Three priorities
                payload={"index": i},
            )
            scheduler.add_schedule(
                cron_expr="0 0 * * *",
                task=task,
            )

        # Deactivate one schedule
        all_schedules = scheduler.list_schedules()
        scheduler.update_schedule(all_schedules[0].schedule_id, is_active=False)

        # Get statistics
        stats = scheduler.get_statistics()

        assert stats["scheduler_id"] == "test-scheduler"
        assert stats["total_schedules"] == 5
        assert stats["active_schedules"] == 4
        assert stats["inactive_schedules"] == 1
        assert len(stats["schedules_by_user"]) == 2
        assert sum(stats["schedules_by_user"].values()) == 4  # Only active schedules
        assert len(stats["schedules_by_priority"]) > 0
