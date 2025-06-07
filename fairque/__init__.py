"""
FairQueue: Production-ready fair queue implementation using Redis with work stealing and priority scheduling.

This package provides a comprehensive queue system with:
- Fair scheduling with round-robin user selection
- Priority-based task processing with work stealing
- Atomic operations using Lua scripts
- Configuration-based user management
- Pipeline optimization for high throughput
- Built-in monitoring and statistics
- Dual implementation: Synchronous and Asynchronous versions
- XCom (Cross Communication) for task data exchange
"""

__version__ = "0.1.0"
__author__ = "Makoto Yui"
__email__ = "myui@apache.org"

from fairque.core.config import (
    FairQueueConfig,
    QueueConfig,
    RedisConfig,
    WorkerConfig,
)
from fairque.core.exceptions import (
    ConfigurationError,
    FairQueueError,
    FunctionResolutionError,
    LuaScriptError,
    RedisConnectionError,
    TaskSerializationError,
    TaskValidationError,
)
from fairque.core.models import Priority, Task, TaskState
from fairque.core.pipeline import (
    Executable,
    ParallelGroup,
    Pipeline,
    SequentialGroup,
    TaskGroup,
    TaskWrapper,
    create_pipeline,
    parallel,
    sequential,
)
from fairque.core.xcom import XComManager, XComValue
from fairque.decorator import task, xcom_pull, xcom_push, xcom_task
from fairque.queue.async_queue import AsyncTaskQueue
from fairque.queue.queue import TaskQueue
from fairque.worker.async_worker import AsyncTaskHandler, AsyncWorker
from fairque.worker.worker import TaskHandler, Worker

__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__email__",
    # Core models
    "Priority",
    "Task",
    "TaskState",
    # Pipeline functionality
    "Executable",
    "Pipeline",
    "TaskGroup",
    "SequentialGroup",
    "ParallelGroup",
    "TaskWrapper",
    "create_pipeline",
    "parallel",
    "sequential",
    # XCom functionality
    "XComValue",
    "XComManager",
    # Configuration
    "FairQueueConfig",
    "RedisConfig",
    "WorkerConfig",
    "QueueConfig",
    # Queue implementation (sync and async)
    "TaskQueue",
    "AsyncTaskQueue",
    # Worker implementation (sync and async)
    "TaskHandler",
    "Worker",
    "AsyncTaskHandler",
    "AsyncWorker",
    # Task decorators and XCom decorators
    "task",
    "xcom_pull",
    "xcom_push",
    "xcom_task",
    # Exceptions
    "FairQueueError",
    "FunctionResolutionError",
    "LuaScriptError",
    "TaskValidationError",
    "RedisConnectionError",
    "TaskSerializationError",
    "ConfigurationError",
]
