"""Basic FairQueue usage example."""

import time

from fairque import FairQueueConfig, Priority, Task, TaskQueue


def main() -> None:
    """Demonstrate basic FairQueue operations."""

    # Create configuration
    config = FairQueueConfig.create_default(
        worker_id="example-worker",
        assigned_users=["user:1", "user:2", "user:3"],
        steal_targets=["user:4", "user:5"]
    )

    # Initialize FairQueue
    with TaskQueue(config) as queue:

        print("=== FairQueue Basic Example ===")

        # Create and push tasks
        tasks = [
            Task.create(
                user_id="user:1",
                priority=Priority.HIGH,
                payload={"action": "process_order", "order_id": 12345}
            ),
            Task.create(
                user_id="user:2",
                priority=Priority.CRITICAL,
                payload={"action": "urgent_notification", "user_id": 67890}
            ),
            Task.create(
                user_id="user:1",
                priority=Priority.NORMAL,
                payload={"action": "send_email", "template": "welcome"}
            ),
        ]

        # Push tasks to queue
        print("\n--- Pushing Tasks ---")
        for task in tasks:
            result = queue.push(task)
            if result["success"]:
                print(f"✓ Pushed task {task.task_id} (user:{task.user_id}, priority:{task.priority.name})")
            else:
                print(f"✗ Failed to push task {task.task_id}")

        # Get queue statistics
        print("\n--- Queue Statistics ---")
        stats = queue.get_stats()
        print(f"Active tasks: {stats.get('tasks_active', 0)}")
        print(f"Total pushed: {stats.get('tasks_pushed_total', 0)}")
        print(f"Critical tasks: {stats.get('tasks_pushed_critical', 0)}")
        print(f"Normal tasks: {stats.get('tasks_pushed_normal', 0)}")

        # Get queue sizes
        print("\n--- Queue Sizes ---")
        batch_sizes = queue.get_batch_queue_sizes()
        for user_id, sizes in batch_sizes.items():
            if user_id != "totals" and user_id != "checked_at":
                print(f"User {user_id}: {sizes['total_size']} tasks (critical: {sizes['critical_size']}, normal: {sizes['normal_size']})")

        totals = batch_sizes.get("totals", {})
        print(f"Total: {totals.get('total_size', 0)} tasks")

        # Pop and process tasks
        print("\n--- Processing Tasks ---")
        processed_count = 0
        while True:
            task = queue.pop()
            if not task:
                print("No more tasks available")
                break

            print(f"Processing task {task.task_id} from user {task.user_id}")
            print(f"  Priority: {task.priority.name}")
            print(f"  Payload: {task.payload}")

            # Simulate task processing
            time.sleep(0.1)

            # Clean up task data
            queue.delete_task(task.task_id)
            processed_count += 1

        print(f"\n--- Processed {processed_count} tasks ---")

        # Final statistics
        print("\n--- Final Statistics ---")
        final_stats = queue.get_stats()
        print(f"Active tasks: {final_stats.get('tasks_active', 0)}")
        print(f"Total popped: {final_stats.get('tasks_popped_total', 0)}")

        # Health check
        print("\n--- Health Check ---")
        health = queue.get_health()
        print(f"Status: {health.get('status', 'unknown')}")
        print(f"Active tasks: {health.get('active_tasks', 0)}")

        if health.get("warnings"):
            print("Warnings:")
            for warning in health["warnings"]:
                print(f"  - {warning}")


if __name__ == "__main__":
    main()
