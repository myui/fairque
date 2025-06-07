"""FairQueue implementation with unified state management and fq: prefix."""

import json
import logging
from typing import Any, Dict, List, Optional, cast

import redis

from fairque.core.config import FairQueueConfig
from fairque.core.exceptions import (
    LuaScriptError,
    RedisConnectionError,
    StateTransitionError,
    TaskSerializationError,
    TaskValidationError,
)
from fairque.core.models import Task, TaskState
from fairque.core.redis_keys import RedisKeys
from fairque.utils.lua_manager import LuaScriptManager

logger = logging.getLogger(__name__)


class TaskQueue:
    """FairQueue with unified state management and dependency resolution.

    This implementation provides:
    - Unified state management with fq: prefix
    - Integrated dependency resolution
    - Enhanced failure tracking
    - TTL-based cleanup
    - Comprehensive monitoring
    """

    def __init__(
        self,
        config: FairQueueConfig,
        redis_client: Optional[redis.Redis] = None
    ) -> None:
        """Initialize FairQueue with unified state management.

        Args:
            config: FairQueue configuration
            redis_client: Optional Redis client (will create from config if not provided)

        Raises:
            RedisConnectionError: If Redis connection fails
        """
        self.config = config
        config.validate_all()

        # Initialize Redis client
        if redis_client:
            self.redis = redis_client
        else:
            try:
                self.redis = config.create_redis_client()
                self.redis.ping()
            except redis.RedisError as e:
                raise RedisConnectionError(f"Failed to connect to Redis: {e}") from e

        # Initialize Lua script manager
        self.lua_manager = LuaScriptManager(self.redis)

        # Load scripts
        self._load_scripts()

        logger.info(f"FairQueue initialized with worker ID: {config.worker.id}")

    def _load_scripts(self) -> None:
        """Load all required Lua scripts."""
        try:
            script_files = [
                "push",
                "pop",
                "state_ops"
            ]

            for script_name in script_files:
                self.lua_manager.load_script(script_name)

            logger.debug(f"Loaded {len(script_files)} Lua scripts")
        except LuaScriptError as e:
            logger.error(f"Failed to load Lua scripts: {e}")
            raise

    def enqueue(self, task: Task) -> Dict[str, Any]:
        """Enqueue a task with unified state management and dependency handling.

        Args:
            task: Task to enqueue

        Returns:
            Dictionary with operation result and state information

        Raises:
            TaskValidationError: If task validation fails
            LuaScriptError: If Lua script execution fails
        """
        # Validate task
        if not task.task_id:
            raise TaskValidationError("Task ID cannot be empty")

        if not task.user_id:
            raise TaskValidationError("User ID cannot be empty")

        # Convert task to JSON for Lua script
        try:
            task_json = task.to_json()
        except Exception as e:
            raise TaskSerializationError(f"Failed to serialize task: {e}") from e

        # Execute push script
        try:
            result = self.lua_manager.execute_script("push", args=[task_json])
            response: Dict[str, Any] = json.loads(result)

            if not response.get("success", False):
                error_code = response.get("error_code", "UNKNOWN")
                error_message = response.get("message", "Unknown error")
                raise LuaScriptError("push", {
                    "error_code": error_code,
                    "message": error_message,
                    "task_id": task.task_id
                })

            state = response.get("state", "unknown")
            logger.info(f"Task {task.task_id} enqueued in {state} state for user {task.user_id}")
            return response

        except json.JSONDecodeError as e:
            raise LuaScriptError("push", {
                "error": "json_decode_error",
                "details": str(e),
                "task_id": task.task_id
            }) from e

    def dequeue(self, user_list: Optional[List[str]] = None, worker_id: Optional[str] = None) -> Optional[Task]:
        """Dequeue a task with fair scheduling and automatic state transition.

        Args:
            user_list: List of user IDs to check (defaults to worker's configuration)
            worker_id: Worker identifier (defaults to config worker ID)

        Returns:
            Task if available, None if no tasks ready

        Raises:
            LuaScriptError: If Lua script execution fails
        """
        # Use worker configuration if not provided
        if user_list is None:
            user_list = self.config.worker.get_all_users()

        if worker_id is None:
            worker_id = self.config.worker.id

        if not user_list:
            logger.warning("No users to check for tasks")
            return None

        # Convert user list to comma-separated string
        user_list_str = ",".join(user_list)

        try:
            result = self.lua_manager.execute_script("pop", args=[user_list_str, worker_id])
            response: Dict[str, Any] = json.loads(result)

            if not response.get("success", False):
                error_code = response.get("error_code", "UNKNOWN")
                error_message = response.get("message", "Unknown error")
                raise LuaScriptError("pop", {
                    "error_code": error_code,
                    "message": error_message,
                    "user_list": user_list
                })

            # Check if task was found
            task_data = response.get("task")
            if not task_data:
                logger.debug("No ready tasks available")
                return None

            # Convert response to Task object
            try:
                task = Task.from_json(task_data["payload"])

                # Update with execution metadata
                task.state = TaskState.STARTED
                task.started_at = task_data.get("popped_at")

                selected_user = task_data.get("selected_user")
                logger.info(f"Dequeued task {task.task_id} from user {selected_user} by worker {worker_id}")
                return task

            except (KeyError, ValueError) as e:
                raise TaskSerializationError(f"Failed to deserialize task from dequeue result: {e}") from e

        except json.JSONDecodeError as e:
            raise LuaScriptError("pop", {
                "error": "json_decode_error",
                "details": str(e),
                "user_list": user_list
            }) from e

    def finish_task(self, task_id: str, result: Any = None) -> List[str]:
        """Mark task as finished and resolve dependencies.

        Args:
            task_id: Task identifier
            result: Optional task result

        Returns:
            List of task IDs that became ready due to dependency resolution

        Raises:
            StateTransitionError: If state transition fails
        """
        result_json = json.dumps(result) if result is not None else "null"

        try:
            response_str = self.lua_manager.execute_script("state_ops", args=[
                "finish", task_id, result_json
            ])
            response: Dict[str, Any] = json.loads(response_str)

            if not response.get("success", False):
                error_message = response.get("message", "Unknown error")
                raise StateTransitionError(f"Failed to finish task {task_id}: {error_message}")

            ready_tasks: List[str] = response.get("ready_tasks", [])
            if ready_tasks:
                logger.info(f"Task {task_id} completion unblocked {len(ready_tasks)} tasks: {ready_tasks}")

            return ready_tasks

        except json.JSONDecodeError as e:
            raise StateTransitionError(f"Invalid response from finish operation: {e}") from e

    def fail_task(self, task_id: str, error: str, failure_type: str = "failed") -> None:
        """Mark task as failed with enhanced failure tracking.

        Args:
            task_id: Task identifier
            error: Error message
            failure_type: Type of failure (failed, expired, poisoned, timeout)

        Raises:
            StateTransitionError: If state transition fails
        """
        try:
            response_str = self.lua_manager.execute_script("state_ops", args=[
                "fail", task_id, error, failure_type
            ])
            response: Dict[str, Any] = json.loads(response_str)

            if not response.get("success", False):
                error_message = response.get("message", "Unknown error")
                raise StateTransitionError(f"Failed to mark task {task_id} as failed: {error_message}")

            logger.warning(f"Task {task_id} failed with type '{failure_type}': {error}")

        except json.JSONDecodeError as e:
            raise StateTransitionError(f"Invalid response from fail operation: {e}") from e

    def cancel_task(self, task_id: str, reason: str = "Manually canceled") -> None:
        """Cancel a task and clean up dependencies.

        Args:
            task_id: Task identifier
            reason: Cancellation reason

        Raises:
            StateTransitionError: If state transition fails
        """
        try:
            response_str = self.lua_manager.execute_script("state_ops", args=[
                "cancel", task_id, reason
            ])
            response: Dict[str, Any] = json.loads(response_str)

            if not response.get("success", False):
                error_message = response.get("message", "Unknown error")
                raise StateTransitionError(f"Failed to cancel task {task_id}: {error_message}")

            logger.info(f"Task {task_id} canceled: {reason}")

        except json.JSONDecodeError as e:
            raise StateTransitionError(f"Invalid response from cancel operation: {e}") from e

    def process_scheduled_tasks(self) -> int:
        """Process scheduled tasks that are ready to run.

        Returns:
            Number of tasks processed

        Raises:
            LuaScriptError: If Lua script execution fails
        """
        try:
            response_str = self.lua_manager.execute_script("state_ops", args=["process_scheduled"])
            response: Dict[str, Any] = json.loads(response_str)

            if not response.get("success", False):
                error_message = response.get("message", "Unknown error")
                raise LuaScriptError("state_ops", {"message": error_message})

            processed: int = response.get("processed", 0)
            if processed > 0:
                logger.info(f"Processed {processed} scheduled tasks")

            return processed

        except json.JSONDecodeError as e:
            raise LuaScriptError("state_ops", {"error": "json_decode_error", "details": str(e)}) from e

    def get_state_stats(self) -> Dict[str, int]:
        """Get comprehensive state statistics including DEFERRED tasks.

        Returns:
            Dictionary with state counts

        Raises:
            LuaScriptError: If Lua script execution fails
        """
        try:
            response_str = self.lua_manager.execute_script("state_ops", args=["stats"])
            response: Dict[str, Any] = json.loads(response_str)

            if not response.get("success", False):
                error_message = response.get("message", "Unknown error")
                raise LuaScriptError("state_ops", {"message": error_message})

            base_stats: Dict[str, int] = response.get("stats", {})

            # Break down queued registry into QUEUED and DEFERRED
            deferred_count: int = len(self.get_tasks_by_state(TaskState.DEFERRED))
            ready_count: int = len(self.get_tasks_by_state(TaskState.QUEUED))

            # Update stats with breakdown
            base_stats["queued"] = ready_count
            base_stats["deferred"] = deferred_count

            return base_stats

        except json.JSONDecodeError as e:
            raise LuaScriptError("state_ops", {"error": "json_decode_error", "details": str(e)}) from e

    def get_user_queue_sizes(self, user_id: str) -> Dict[str, int]:
        """Get queue sizes for a specific user.

        Args:
            user_id: User identifier

        Returns:
            Dictionary with critical_size, normal_size, and total_size
        """
        critical_key = RedisKeys.user_critical_queue(user_id)
        normal_key = RedisKeys.user_normal_queue(user_id)

        critical_size: int = cast(int, self.redis.llen(critical_key))
        normal_size: int = cast(int, self.redis.zcard(normal_key))

        return {
            "critical_size": critical_size,
            "normal_size": normal_size,
            "total_size": critical_size + normal_size
        }

    def get_dependency_info(self, task_id: str) -> Dict[str, List[str]]:
        """Get dependency information for a task.

        Args:
            task_id: Task identifier

        Returns:
            Dictionary with blocking and blocked_by task lists
        """
        waiting_key = RedisKeys.deps_waiting(task_id)
        blocked_key = RedisKeys.deps_blocked(task_id)

        return {
            "blocking": list(cast(set[str], self.redis.smembers(waiting_key))),
            "blocked_by": list(cast(set[str], self.redis.smembers(blocked_key)))
        }

    def get_tasks_by_state(self, state: TaskState, limit: int = 100) -> List[str]:
        """Get task IDs in specific state.

        Args:
            state: Task state to query
            limit: Maximum number of tasks to return

        Returns:
            List of task IDs in the specified state
        """
        if state in [TaskState.QUEUED, TaskState.DEFERRED]:
            # Both QUEUED and DEFERRED tasks are stored in fq:state:queued
            # Filter by actual state field in task data
            all_queued = list(cast(list[str], self.redis.zrange(RedisKeys.state_registry("queued"), 0, -1)))
            filtered_tasks: List[str] = []

            for task_id in all_queued:
                if len(filtered_tasks) >= limit:
                    break

                task_key = RedisKeys.task_data(task_id)
                task_state = self.redis.hget(task_key, "state")

                if task_state == state.value:
                    filtered_tasks.append(task_id)

            return filtered_tasks
        else:
            # Other states have their own registries
            key = RedisKeys.state_registry(state.value)
            return list(cast(list[str], self.redis.zrange(key, 0, limit-1)))

    def get_failed_tasks(self, failure_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get failed tasks with optional filtering by failure type.

        Args:
            failure_type: Optional filter by failure type
            limit: Maximum number of tasks to return

        Returns:
            List of failed task information
        """
        failed_task_ids = self.get_tasks_by_state(TaskState.FAILED, limit)
        failed_tasks: List[Dict[str, Any]] = []

        for task_id in failed_task_ids:
            task_key = RedisKeys.task_data(task_id)
            task_data: Dict[str, Any] = cast(Dict[str, Any], self.redis.hgetall(task_key))

            if task_data:
                # Filter by failure type if specified
                if failure_type and task_data.get("failure_type") != failure_type:
                    continue

                failed_tasks.append({
                    "task_id": task_id,
                    "failure_type": task_data.get("failure_type", "failed"),
                    "error_message": task_data.get("error_message", ""),
                    "failed_at": float(task_data.get("finished_at", 0)),
                    "retry_count": int(task_data.get("retry_count", 0)),
                    "user_id": task_data.get("user_id", "")
                })

        return failed_tasks

    def cleanup_expired_tasks(self, state: Optional[TaskState] = None) -> Dict[str, int]:
        """Clean up expired tasks with TTL-based removal.

        Args:
            state: Optional specific state to clean (defaults to all terminal states)

        Returns:
            Dictionary with cleanup counts per state
        """
        results = {}

        # Define states to clean with their TTL
        states_to_clean = {}
        if state:
            ttl = getattr(self.config.state, f"{state.value}_ttl", 86400)
            states_to_clean[state.value] = ttl
        else:
            states_to_clean = {
                "finished": getattr(self.config.state, "finished_ttl", 86400),
                "failed": getattr(self.config.state, "failed_ttl", 604800),
                "canceled": getattr(self.config.state, "canceled_ttl", 3600)
            }

        for state_name, ttl in states_to_clean.items():
            try:
                response_str = self.lua_manager.execute_script("state_ops", args=[
                    "cleanup", state_name, str(ttl)
                ])
                response: Dict[str, Any] = json.loads(response_str)
                results[state_name] = response.get("removed", 0)

            except (LuaScriptError, json.JSONDecodeError) as e:
                logger.error(f"Failed to cleanup {state_name} state: {e}")
                results[state_name] = 0

        total_cleaned = sum(results.values())
        if total_cleaned > 0:
            logger.info(f"Cleaned up {total_cleaned} expired tasks: {results}")

        return results

    # Backward compatibility aliases
    def push(self, task: Task) -> Dict[str, Any]:
        """Alias for enqueue method for backward compatibility."""
        return self.enqueue(task)

    def push_batch(self, tasks: List[Task]) -> List[Dict[str, Any]]:
        """Push multiple tasks in a batch."""
        results = []
        for task in tasks:
            try:
                result = self.enqueue(task)
                results.append(result)
            except Exception as e:
                # Convert exception to error result
                results.append({
                    "success": False,
                    "error": str(e),
                    "task_id": getattr(task, 'task_id', None)
                })
        return results

    def pop(self, user_list: Optional[List[str]] = None, worker_id: Optional[str] = None) -> Optional[Task]:
        """Alias for dequeue method for backward compatibility."""
        return self.dequeue(user_list, worker_id)

    def delete_task(self, task_id: str) -> bool:
        """Delete a task permanently."""
        try:
            # Delete the task data
            task_key = RedisKeys.task_data(task_id)
            result = self.redis.delete(task_key)
            return result > 0
        except redis.RedisError as e:
            logger.error(f"Failed to delete task {task_id}: {e}")
            return False

    def get_metrics(self) -> Dict[str, Any]:
        """Get queue metrics."""
        try:
            stats = self.get_state_stats()
            return {
                "total_tasks": sum(stats.values()),
                "state_counts": stats,
                "timestamp": __import__('time').time()
            }
        except redis.RedisError as e:
            logger.error(f"Failed to get metrics: {e}")
            return {"error": str(e)}

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive queue statistics.

        Returns:
            Dictionary with queue statistics
        """
        try:
            response_str = self.lua_manager.execute_script("stats")
            response: Dict[str, Any] = json.loads(response_str)

            if not response.get("success", False):
                error_message = response.get("message", "Unknown error")
                logger.error(f"Failed to get stats: {error_message}")
                return {}

            return response.get("data", {})
        except (LuaScriptError, json.JSONDecodeError) as e:
            logger.error(f"Failed to get stats: {e}")
            return {}

    def get_health(self) -> Dict[str, Any]:
        """Get queue health information.

        Returns:
            Dictionary with health status
        """
        try:
            stats = self.get_stats()
            active_tasks = stats.get("tasks_active", 0)

            # TODO: Determine health status
            status = "healthy"

            return {
                "status": status,
                "active_tasks": active_tasks,
            }
        except Exception as e:
            logger.error(f"Failed to get health: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

    def get_queue_sizes(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get queue sizes for a specific user or overall stats.

        Args:
            user_id: Optional user ID to get sizes for specific user

        Returns:
            Dictionary with queue size information
        """
        if user_id:
            return self.get_user_queue_sizes(user_id)
        else:
            return self.get_state_stats()

    def get_batch_queue_sizes(self, user_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """Get queue sizes for multiple users."""
        result = {}
        totals = {"critical_size": 0, "normal_size": 0, "total_size": 0}

        for user_id in user_ids:
            user_sizes = self.get_user_queue_sizes(user_id)
            result[user_id] = user_sizes
            totals["critical_size"] += user_sizes.get("critical_size", 0)
            totals["normal_size"] += user_sizes.get("normal_size", 0)
            totals["total_size"] += user_sizes.get("total_size", 0)

        result["totals"] = totals
        return result

    def cleanup_expired_tasks(self, max_age_seconds: int = 86400) -> int:
        """Clean up expired tasks.

        Args:
            max_age_seconds: Maximum age for tasks before cleanup

        Returns:
            Number of tasks cleaned up
        """
        import time
        current_time = time.time()
        cutoff_time = current_time - max_age_seconds

        try:
            # Scan for task keys
            task_keys = list(self.redis.scan_iter(match="task:*"))
            cleaned_count = 0

            for task_key in task_keys:
                # Get task creation time
                created_at_str = self.redis.hget(task_key, "created_at")
                if created_at_str:
                    try:
                        created_at = float(created_at_str)
                        if created_at < cutoff_time:
                            # Task is expired, delete it
                            if self.redis.delete(task_key):
                                cleaned_count += 1
                    except (ValueError, TypeError):
                        # Invalid timestamp, skip
                        continue

            return cleaned_count
        except Exception as e:
            logger.error(f"Failed to cleanup expired tasks: {e}")
            return 0

    def close(self) -> None:
        """Close Redis connection and cleanup resources."""
        try:
            if hasattr(self.redis, "close"):
                self.redis.close()
            logger.info("FairQueue connection closed")
        except Exception as e:
            logger.warning(f"Error closing FairQueue: {e}")

    def __enter__(self) -> "TaskQueue":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()


