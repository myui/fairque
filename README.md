# FairQueue

Production-ready fair queue implementation using Redis with work stealing and priority scheduling.

## Features

- 🎯 **Fair Scheduling**: Round-robin user selection with work stealing
- 🏆 **Priority Queues**: Type-safe priority system (1-6) with critical/normal separation
- ⚡ **Atomic Operations**: Lua scripts ensure consistency and performance
- ⚙️ **Configuration-Based**: No Redis state for user management, fully configurable
- 🚀 **Pipeline Optimization**: Batch operations for high throughput
- 📊 **Comprehensive Monitoring**: Built-in statistics and alerting
- 🛡️ **Production Ready**: Error handling, graceful shutdown, health checks
- 🔧 **Function Decorators**: @task decorator for seamless function-to-task conversion
- 📡 **XCom Support**: Cross-task communication with automatic data management
- 🔄 **Task Dependencies**: Sophisticated dependency management with cycle detection
- 🔗 **Pipeline Operators**: Airflow-style workflow composition (>>, <<, |)
- ⏰ **Task Scheduling**: Cron-based task scheduling with distributed coordination
- 📊 **Task States**: Comprehensive state management with 7 states (queued, started, deferred, finished, failed, canceled, scheduled)

## Quick Start

### Installation

```bash
# Using uv (recommended)
uv add fairque

# Using pip
pip install fairque
```

### Basic Usage with @task Decorator

```python
from fairque import task, TaskQueue, FairQueueConfig, Priority

# Define tasks using the @task decorator with custom IDs
@task(task_id="process_order", priority=Priority.HIGH, max_retries=3)
def process_order(order_id: int, customer_id: str) -> dict:
    """Process customer order."""
    print(f"Processing order {order_id} for customer {customer_id}")
    
    result = {
        "order_id": order_id,
        "customer_id": customer_id,
        "status": "processed",
        "total": 99.99
    }
    return result

@task(task_id="send_confirmation", depends_on=["process_order"])
def send_confirmation(order_id: int):
    """Send order confirmation email."""
    print(f"Sending confirmation for order {order_id}")

# Create configuration
config = FairQueueConfig.create_default(
    worker_id="worker-001",
    assigned_users=["user:1", "user:2", "user:3"],
    steal_targets=["user:4", "user:5"]
)

# Create and execute tasks
with TaskQueue(config) as queue:
    # Create tasks by calling decorated functions
    order_task = process_order(12345, "customer@example.com")
    confirmation_task = send_confirmation(12345)
    
    # Execute immediately
    result = order_task()
    print(f"Order result: {result}")
    
    # Or push to queue for worker processing
    queue.push(order_task)
    queue.push(confirmation_task)  # Will wait for process_order to complete
    
    # Get queue statistics
    stats = queue.get_stats()
    print(f"Active tasks: {stats.get('tasks_active', 0)}")
```

### Pipeline Operators (Airflow-style)

```python
from fairque import task, TaskQueue, FairQueueConfig

# Define tasks with custom IDs
@task(task_id="extract")
def extract_data():
    return {"records": 1000}

@task(task_id="transform")  
def transform_data():
    return {"processed_records": 2000}

@task(task_id="validate")
def validate_data():
    return {"validation": "passed"}

@task(task_id="load")
def load_data():
    return {"status": "loaded"}

# Create pipelines using operators
with TaskQueue(config) as queue:
    # Simple linear pipeline: extract >> transform >> load
    pipeline = extract_data() >> transform_data() >> load_data()
    queue.enqueue(pipeline)
    
    # Parallel execution: extract >> (transform | validate) >> load
    parallel_pipeline = extract_data() >> (transform_data() | validate_data()) >> load_data()
    queue.enqueue(parallel_pipeline)
    
    # Reverse operator: load << transform << extract
    reverse_pipeline = load_data() << transform_data() << extract_data()
    queue.enqueue(reverse_pipeline)
```

### XCom (Cross Communication) Usage

```python
from fairque import xcom_task, Task

@xcom_task(push_key="extracted_data", auto_xcom=True)
def extract_data(source: str) -> dict:
    """Extract data and automatically store in XCom."""
    data = {"source": source, "records": 1000}
    return data  # Automatically stored in XCom

@task(task_id="transform", depends_on=["extract"], enable_xcom=True)
def transform_data():
    """Transform data using XCom."""
    # Pull data from previous task
    raw_data = self.xcom_pull("extracted_data")
    transformed = {
        "processed_records": raw_data["records"] * 2,
        "source": raw_data["source"]
    }
    self.xcom_push("transformed_data", transformed)
    return transformed

# Create tasks with XCom support
extract_task = extract_data("database")
transform_task = transform_data()

# Pipeline with automatic data passing
pipeline = extract_task >> transform_task
queue.enqueue(pipeline)
```

### Task Scheduling

```python
from fairque.scheduler.scheduler import TaskScheduler

# Create scheduler
scheduler = TaskScheduler(config)

# Schedule a task with cron expression
daily_task = Task.create(
    task_id="daily_report",
    user_id="system",
    priority=Priority.HIGH,
    payload={"report_type": "daily"}
)

schedule_id = scheduler.add_schedule(
    cron_expr="0 9 * * *",  # Daily at 9 AM
    task=daily_task,
    timezone="UTC"
)

# Start the scheduler
scheduler.start()
```

### Worker Usage

```python
from fairque import TaskHandler, Worker, FairQueueConfig

class MyTaskHandler(TaskHandler):
    def _process_task(self, task) -> bool:
        """Process tasks with automatic function execution."""
        # TaskHandler automatically executes task.func if available
        # Only implement custom logic for non-function tasks
        action = task.payload.get("action")
        
        if action == "custom_processing":
            print(f"Custom processing for task {task.task_id}")
            return True
        
        # For function tasks, parent class handles execution
        return super()._process_task(task)
    
    def on_task_success(self, task, duration: float) -> None:
        print(f"✓ Task {task.task_id} completed in {duration:.2f}s")
    
    def on_task_failure(self, task, error: Exception, duration: float) -> None:
        print(f"✗ Task {task.task_id} failed: {error}")

# Create configuration and worker
config = FairQueueConfig.create_default(
    worker_id="worker-001",
    assigned_users=["user:1", "user:2"],
    steal_targets=["user:3", "user:4"]
)

# Start worker
with Worker(config, MyTaskHandler()) as worker:
    worker.start()
    # Worker automatically processes function tasks and custom tasks
```

### Legacy Manual Task Creation

```python
from fairque import TaskQueue, FairQueueConfig, Priority, Task

# Create configuration
config = FairQueueConfig.create_default(
    worker_id="worker-001",
    assigned_users=["user:1", "user:2", "user:3"],
    steal_targets=["user:4", "user:5"]
)

# Initialize TaskQueue
with TaskQueue(config) as queue:
    # Create and push a task manually
    task = Task.create(
        user_id="user:1",
        priority=Priority.HIGH,
        payload={"action": "process_data", "data_id": 123}
    )
    
    # Push task to queue
    result = queue.push(task)
    print(f"Task pushed: {result['success']}")
    
    # Pop and process tasks
    task = queue.pop()
    if task:
        print(f"Processing task {task.task_id} from user {task.user_id}")
        print(f"Payload: {task.payload}")
        
        # Clean up after processing
        queue.delete_task(task.task_id)
    
    # Get statistics
    stats = queue.get_stats()
    print(f"Active tasks: {stats.get('tasks_active', 0)}")
```

### Configuration

```yaml
# fairque_config.yaml
redis:
  host: "localhost"
  port: 6379
  db: 0

workers:
  - id: "worker-001"
    assigned_users: ["user:1", "user:3", "user:5"]
    steal_targets: ["user:2", "user:4", "user:6"]
    poll_interval_seconds: 1.0
    max_concurrent_tasks: 10
  - id: "worker-002"
    assigned_users: ["user:2", "user:4", "user:6"]
    steal_targets: ["user:1", "user:3", "user:5"]
    poll_interval_seconds: 1.0
    max_concurrent_tasks: 10

queue:
  stats_prefix: "fq"
  default_max_retries: 3
  enable_pipeline_optimization: true
  xcom_ttl_seconds: 3600
```

Load configuration:

```python
# Multi-worker configuration
config = FairQueueConfig.from_yaml("fairque_config.yaml")

# Single worker configuration (legacy)
config = FairQueueConfig.create_default(
    worker_id="worker-001",
    assigned_users=["user:1", "user:2"],
    steal_targets=["user:3", "user:4"]
)
```

## Key Differentiators vs. Existing Task Queues (RQ, Celery, etc.)

FairQueue goes beyond simple task queuing with production-ready features for complex multi-tenant applications:

### 🏢 **1. Multi-Tenancy with Fair Resource Allocation**
**Problem**: Traditional queues like RQ use simple FIFO, allowing high-volume users to monopolize resources.
**Solution**: FairQueue implements true fair scheduling with round-robin user selection.

```python
# RQ: Tasks processed in order submitted - user1 can starve user2
# user1 submits 1000 tasks, user2 submits 1 task → user2 waits behind all 1000

# FairQueue: Guaranteed fair access across users
config = FairQueueConfig.create_default(
    assigned_users=["user:1", "user:2", "user:3"]  # Equal processing opportunity
)
# Round-robin: user1 → user2 → user3 → user1, regardless of task volume
```

### ⚡ **2. Intelligent Resource Utilization with Work Stealing**
**Problem**: Traditional workers are idle when their assigned queues are empty, even if other queues have work.
**Solution**: FairQueue workers can steal tasks from other users when idle, maximizing throughput.

```python
# Traditional: Worker assigned to user:1 sits idle if user:1 has no tasks
# FairQueue: Worker processes assigned users first, then steals from targets
config = FairQueueConfig.create_default(
    worker_id="worker-001",
    assigned_users=["user:1", "user:2"],      # Primary responsibility
    steal_targets=["user:3", "user:4"]        # Secondary work when idle
)
# Result: 100% worker utilization + maintains fairness guarantees
```

### 🔗 **3. Built-in XCom for Cross-Task Communication**
**Problem**: RQ has no native way for tasks to share data - requires external storage or manual Redis operations.
**Solution**: FairQueue includes XCom system for seamless task-to-task data passing.

```python
# RQ: Manual data passing via external storage
def task1():
    result = process_data()
    redis.set("shared_data", json.dumps(result))  # Manual

def task2():
    data = json.loads(redis.get("shared_data"))   # Manual

# FairQueue: Built-in XCom with automatic data management
@xcom_task(push_key="processed_data", auto_xcom=True)
def task1():
    return process_data()  # Automatically stored

@task(depends_on=["task1"], enable_xcom=True)
def task2():
    data = self.xcom_pull("processed_data")  # Automatic retrieval
```

### 🔄 **4. DAG Workflows Beyond Simple Task Queues**
**Problem**: RQ is a simple job queue - complex workflows require external orchestration tools.
**Solution**: FairQueue includes dependencies, pipelines, and DAG support built-in.

```python
# RQ: No dependency management - manual orchestration required
# Must manually track completion and trigger dependent tasks

# FairQueue: Full DAG support with pipeline operators
@task(task_id="extract")
def extract_data(): return {"records": 1000}

@task(task_id="transform", depends_on=["extract"])
def transform_data(): return {"processed": 2000}

@task(task_id="load", depends_on=["transform"])
def load_data(): return {"loaded": True}

# Airflow-style pipeline composition
pipeline = extract_data() >> transform_data() >> load_data()
parallel_pipeline = extract_data() >> (transform_data() | validate_data()) >> load_data()

queue.enqueue(pipeline)  # Automatic dependency resolution
```

### 🎯 **Multi-Tenant SaaS Applications**
Perfect for applications where fair resource allocation is critical:
- **E-commerce platforms**: Fair order processing across merchants
- **Data processing services**: Equitable resource sharing across customers
- **API gateways**: Preventing resource monopolization by high-volume clients
- **Batch processing systems**: Balanced workload distribution

### 🚀 **Horizontal Scaling with Intelligence**
Add workers dynamically with automatic work distribution:
```python
# Scale by adding workers with smart assignment
workers = [
    {"id": "worker-001", "assigned_users": ["user:1", "user:3"], "steal_targets": ["user:2", "user:4"]},
    {"id": "worker-002", "assigned_users": ["user:2", "user:4"], "steal_targets": ["user:1", "user:3"]},
    {"id": "worker-003", "assigned_users": ["user:5", "user:6"], "steal_targets": ["user:1", "user:2"]}
]
# Result: Perfect load balancing + no resource waste + maintained fairness
```

## Why "Fair"?

The name **FairQueue** reflects the core principle of **fairness** in task distribution and processing:

### 🎯 **Fair Task Distribution**
- **Round-robin user selection**: Each user gets equal opportunity for their tasks to be processed
- **No user starvation**: High-volume users cannot monopolize worker resources
- **Balanced workload**: Tasks are distributed evenly across workers through work stealing

### ⚖️ **Fair Resource Allocation**
- **Priority-aware fairness**: Critical tasks get immediate attention while maintaining fairness among normal priorities
- **Worker equity**: All workers have equal opportunity to process tasks from their assigned users
- **Dynamic load balancing**: Work stealing ensures optimal resource utilization without unfair advantage

### 🔄 **Fair Processing Order**
- **Within user fairness**: Tasks from the same user are processed in priority order
- **Cross-user fairness**: No single user can dominate the queue regardless of task volume
- **Temporal fairness**: Tasks are processed in a predictable, fair manner based on submission time and priority

This fairness model makes FairQueue ideal for multi-tenant systems, SaaS platforms, and any application where equitable resource sharing is crucial for user experience and system stability.

## Architecture

### Priority System

```python
from fairque import Priority

# Priority levels (1-6)
Priority.VERY_LOW    # 1 - Lowest priority
Priority.LOW         # 2 - Low priority  
Priority.NORMAL      # 3 - Standard priority
Priority.HIGH        # 4 - High priority
Priority.VERY_HIGH   # 5 - Very high priority
Priority.CRITICAL    # 6 - Critical priority (separate FIFO queue)
```

### Redis Key Structure

```
# Queue keys with fq: prefix
fq:queue:user:{user_id}:critical    # Priority.CRITICAL tasks (List, FIFO)
fq:queue:user:{user_id}:normal      # Priority 1-5 tasks (Sorted Set, Score-based)

# State management keys
fq:state:{state}                    # Task state registries (Set)
fq:task:{task_id}                   # Task metadata & dependencies (Hash)

# Dependency tracking keys  
fq:deps:waiting:{task_id}           # Tasks waiting on this task (Set)
fq:deps:blocked:{task_id}           # Tasks this task is blocked by (Set)

# XCom and other keys
fq:xcom:{key}                       # XCom data storage (Hash with TTL)
fq:stats                           # Unified statistics (Hash)
fq:schedules                       # Scheduled tasks (Hash)
fq:scheduler:lock                  # Scheduler distributed lock
```

### Work Stealing Strategy

Workers have:
- **assigned_users**: Primary responsibility users
- **steal_targets**: Users they can steal work from when idle

Processing order:
1. Try assigned_users (round-robin)
2. If empty, try steal_targets (round-robin)
3. For each user: critical queue first, then normal queue

### Task Dependencies and States

FairQueue provides sophisticated dependency management:

```python
# Tasks with dependencies
@task(task_id="step1")
def first_step():
    return "data"

@task(task_id="step2", depends_on=["step1"])
def second_step():
    return "processed"

# Task states
from fairque import TaskState

# Available states:
TaskState.QUEUED     # Ready for execution
TaskState.STARTED    # Currently executing  
TaskState.DEFERRED   # Waiting for dependencies
TaskState.FINISHED   # Successfully completed
TaskState.FAILED     # Execution failed
TaskState.CANCELED   # Manually canceled
TaskState.SCHEDULED  # Waiting for execute_after time
```

### Pipeline Operators

Airflow-style workflow composition:

```python
# Sequential execution: A >> B >> C
pipeline = extract_data() >> transform_data() >> load_data()

# Parallel execution: A >> (B | C) >> D  
parallel = extract_data() >> (transform_data() | validate_data()) >> load_data()

# Reverse operator: C << B << A
reverse = load_data() << transform_data() << extract_data()

# Complex workflows
complex = (
    extract_data() >> 
    (transform_data() | validate_data()) >> 
    (load_data() | backup_data()) >> 
    notify_completion()
)

# Enqueue entire pipeline
queue.enqueue(complex)
```

### XCom (Cross Communication)

XCom enables data sharing between tasks:

```python
# Automatic XCom with dependencies
@xcom_task(push_key="result", auto_xcom=True)
def producer():
    return {"data": "value"}

@task(depends_on=["producer"], enable_xcom=True)
def consumer():
    data = self.xcom_pull("result")
    return f"Processed: {data}"
```

### Task Scheduling

Cron-based scheduling with distributed coordination:

```python
from fairque.scheduler.scheduler import TaskScheduler

scheduler = TaskScheduler(config)

# Schedule tasks
task = my_task_function()
scheduler.add_schedule("0 9 * * *", task)  # Daily at 9 AM

# Start scheduler with distributed locking
scheduler.start()
```

## Development Status

This project is **production-ready** with comprehensive feature set and testing coverage.

### ✅ Core Features Complete
- [x] Project setup and structure
- [x] Core models (Priority, Task, TaskState)
- [x] Configuration system with multi-worker support
- [x] Exception handling
- [x] Lua scripts implementation
- [x] TaskQueue core implementation
- [x] Worker implementation with work stealing
- [x] Comprehensive testing suite
- [x] Async implementation (AsyncTaskQueue, AsyncWorker)
- [x] Function execution support with @task decorator
- [x] XCom (Cross Communication) system
- [x] Task dependencies and pipeline operators
- [x] Task scheduling with cron expressions
- [x] Performance testing suite
- [x] Multi-worker configuration support
- [x] Comprehensive state management (7 states)

### 🚧 Optional Extensions
- [ ] Advanced monitoring and alerting
- [ ] Extended documentation and tutorials

## Testing

Run the test suite:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=fairque --cov-report=html

# Run specific test categories
pytest tests/unit/          # Unit tests only
pytest tests/integration/   # Integration tests only
pytest tests/performance/   # Performance tests only

# Run benchmarks
python tests/performance/run_benchmarks.py
```

**Note**: Tests require Redis running on `localhost:6379` with database 15 available for testing.

## Requirements

- Python 3.10+
- Redis 7.2.5+ / Valkey 7.2.6+ / Amazon MemoryDB for Redis

## License

MIT License - see LICENSE file for details.

## Contributing

This project follows strict development guidelines:
- All code and documentation in English
- Full type annotations required
- Comprehensive docstrings
- Follow PEP 8 style guidelines
- Use uv for package management

Please see the development documentation for more details.
