# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**FairQueue** is a production-ready fair queue implementation using Redis with work stealing and priority scheduling. It provides equitable task distribution across multiple users and workers in multi-tenant systems.

## Development Commands

**Testing:**
```bash
uv run pytest                                      # Run all tests
uv run pytest --cov=fairque --cov-report=html    # Run tests with coverage
uv run pytest tests/unit/                         # Unit tests only  
uv run pytest tests/integration/                  # Integration tests only
uv run pytest tests/performance/                  # Performance tests only
uv run pytest -k "test_specific_function"         # Run specific test
```

**Code Quality:**
```bash
uv run ruff check .                               # Lint code
uv run ruff format .                              # Format code
uv run mypy fairque/                              # Type checking
```

**Package Management:**
```bash
uv sync                                    # Install dependencies
uv add package-name                        # Add new dependency
```

## Architecture Overview

### Core Components

**Task Queue System:**
- `TaskQueue` (`fairque/queue/queue.py`) - Main synchronous queue with Redis-based fair scheduling
- `AsyncTaskQueue` - Asynchronous version for async applications
- Uses round-robin user selection and priority-based task ordering

**Worker System:**
- `Worker` (`fairque/worker/worker.py`) - Task processor with thread pool execution
- `TaskHandler` - Abstract base for custom task processing logic
- Work stealing: workers process assigned users first, then steal from targets

**Scheduler System:**
- `TaskScheduler` (`fairque/scheduler/scheduler.py`) - Cron-based scheduling with Redis distributed locking
- `ScheduledTask` - Model for recurring tasks with cron expressions

**Task Models:**
- `Task` (`fairque/core/models.py`) - Main task entity supporting function execution
- `Priority` enum (1-6: VERY_LOW to CRITICAL) with type safety
- Function tasks via `@task` and `@xcom_task` decorators

**Configuration:**
- `FairQueueConfig` - Main config container with Redis, worker, and queue settings
- YAML-based configuration files in `config/` directory
- Multi-worker support with assigned users and steal targets

### Redis Queue Structure
```
queue:user:{user_id}:critical  # CRITICAL priority tasks (FIFO)
queue:user:{user_id}:normal    # Priority 1-5 tasks (score-based)
queue:stats                   # Queue statistics
xcom:{key}                    # Cross-task communication data
```

## Key Patterns

**Function Tasks:**
```python
@task
def my_task(x: int, y: int) -> int:
    return x + y

# Submit as task
task_id = queue.push_function_task("user:1", my_task, args=(1, 2))
```

**Task Dependencies:**
```python
# Task with custom ID
@task(task_id="preprocessing")
def preprocessing_task():
    return "preprocessed"

# Task with dependencies using predictable IDs
@task(task_id="processing", depends_on=["preprocessing"])
def processing_task():
    return "executes after preprocessing completes"

# XCom + dependencies with auto result passing
@task(
    task_id="final_processing",
    depends_on=["preprocessing"],
    auto_xcom=True,
    enable_xcom=True,
    push_key="processed_result"
)
def final_task():
    return "result passed to dependents automatically"
```

**Pipeline Operators (Airflow-style):**
```python
# Simple pipeline: task1 >> task2 >> task3
extract = extract_data()
transform = transform_data()
load = load_data()

# Linear pipeline
pipeline = extract >> transform >> load

# Parallel execution: task1 >> (task2 | task3) >> task4
validate = validate_data()
parallel_pipeline = extract >> (transform | validate) >> load

# Reverse operator: task3 << task2 << task1
reverse_pipeline = load << transform << extract

# Enqueue pipeline (auto-expands to individual tasks)
with TaskQueue(config) as queue:
    results = queue.enqueue(pipeline)  # Enqueues all tasks with dependencies
```

**Task States:**
Tasks have states: `queued`, `started`, `deferred`, `finished`, `failed`, `canceled`, `scheduled`
- `deferred`: Task waiting for dependencies to complete
- Dependencies are user-scoped only
- Cycle detection prevents circular dependencies
- Failed dependencies keep dependents in `deferred` state

**XCom Usage:**
```python
@xcom_task("result_key")
def producer_task() -> dict:
    return {"data": "value"}

# Access in another task
result = xcom_manager.get("result_key")
```

**Task Scheduling:**
```python
from fairque.scheduler.scheduler import TaskScheduler

# Create scheduler
scheduler = TaskScheduler(config)

# Schedule a task with cron expression
task = my_task_function()
schedule_id = scheduler.add_schedule(
    cron_expr="0 9 * * *",  # Daily at 9 AM
    task=task,
    timezone="UTC"
)

# Schedule with custom task
task = Task.create(
    user_id="user1",
    priority=Priority.HIGH,
    payload={"data": "value"}
)
schedule_id = scheduler.add_schedule("0 12 * * *", task)
```

**Work Stealing Configuration:**
- Workers have `assigned_users` (primary responsibility)  
- Workers have `steal_targets` (secondary work source when idle)
- Processing order: assigned users first, then steal targets

## Testing

**Test Database:** Uses Redis database 15 (isolated from production)

**Key Fixtures:**
- `redis_client` - Redis client with automatic cleanup
- `fairqueue` - FairQueue instance with test configuration
- `worker_config` - Fast polling for quick tests

**Redis Connection:** Tests automatically clean up Redis data before/after execution

## CLI Tools

```bash
fairque-info --help                        # View monitoring options
fairque-info --config config/fairque_config.yaml --stats  # Get queue statistics
```