This system is an asynchronous task processing system composed of three main components: a **Task Queue**, **Workers**, and a **Scheduler**. It uses Redis as its backend, ensuring robustness and scalability.

### Architecture Overview Diagram

```
(User/Client)
       |
       | 1. Enqueue Task (Task Object)
       v
+----------------+      +----------------------+
| Task Scheduler |----->|      Task Queue      |<----- 3. Dequeue Task
| (Cron-based)   |      | (Redis-backed)       |
+----------------+      +----------------------+----------+
       ^                | - Priority Queues    |          |
       | 2. Periodic Run| - State Management   |          |
       |                | - Dependency Graph   |          v
       |                | - XCom (Data Sharing)|   +-------------+
       |                +----------------------+   |   Worker    |
       |                                            | (Processor) |
       +--------------------------------------------+-------------+
                                                    | 4. Execute Task
                                                    | (Task Handler)
                                                    |
                                                    v 5. Notify Result
                                                    (Finish/Fail)
```

### Main Components

1.  **`Task`**
    *   **Role**: The unit of work to be executed. (`fairque.core.models.Task`)
    *   **Features**:
        *   Has attributes like `task_id`, `user_id`, `priority`, and `payload` (data).
        *   Can directly encapsulate a Python function (`func`) to be executed, along with its arguments (`args`, `kwargs`). This allows treating a function as a task.
        *   The `@task` decorator (`fairque.decorator.task`) makes it easy to convert a regular Python function into a `Task` object.
        *   Can define dependencies between tasks (`depends_on`).

2.  **`TaskQueue`**
    *   **Role**: The central message queue of the system. (`fairque.queue.queue.TaskQueue`)
    *   **Features**:
        *   **Redis-based**: All state management, queuing, and data sharing are performed on Redis.
        *   **Fair Scheduling**: As the name `FairQueue` suggests, it is designed to prevent starvation by calculating a score (`calculate_score`) based on task enqueue time and priority, preventing any single user or high-priority task from monopolizing the system. However, the highest priority `CRITICAL` tasks are handled in a separate FIFO queue for immediate execution attempts.
        *   **Robust State Management**: Strictly manages the lifecycle of a task through `TaskState` (`QUEUED`, `STARTED`, `FINISHED`, `FAILED`, etc.).
        *   **Leverages Lua Scripts**: Complex operations against Redis (like fetching a task and updating its state) are executed atomically on the Redis server as Lua scripts (`push.lua`, `pop.lua`). This reduces the number of round-trips between the application and Redis, prevents race conditions, and ensures high performance and consistency.
        *   **Dependency Resolution**: When a task completes, it has the functionality to automatically transition other tasks that depend on it to a runnable state (`QUEUED`).

3.  **`Worker`**
    *   **Role**: The process that retrieves tasks from the `TaskQueue` and actually executes them. (`fairque.worker.worker.Worker`)
    *   **Features**:
        *   Polls the `TaskQueue` to asynchronously fetch executable tasks.
        *   Uses a `ThreadPoolExecutor` to process multiple tasks concurrently.
        *   Users can define their own task processing logic by implementing the `TaskHandler` abstract class. `FunctionTaskHandler` is the default implementation for executing Python functions associated with tasks.
        *   Once task execution is complete, it notifies the `TaskQueue` of success (`finish_task`) or failure (`fail_task`).

4.  **`TaskScheduler`**
    *   **Role**: Periodically runs tasks at specified times based on Cron expressions. (`fairque.scheduler.scheduler.TaskScheduler`)
    *   **Features**:
        *   Enables scheduling like Cron jobs, e.g., "run this task every day at 9 AM."
        *   Uses a distributed lock (`fairque:scheduler_lock`) to ensure that even if multiple schedulers are running simultaneously, only one instance will actually process the tasks.
        *   When the execution time arrives, it creates the corresponding `Task` and enqueues it into the `TaskQueue`.

### Key Concepts

*   **XCom (Cross-Communication)**: A mechanism for sharing small amounts of data between tasks. It is useful for building pipelines, for example, where the result of one task is used by a subsequent task. It can be easily used with the `@xcom_push` and `@xcom_pull` decorators.
*   **Configuration-driven**: The behavior of workers, Redis connection information, etc., can be flexibly configured for different environments using YAML files in the `config/` directory.

### Summary

This system is a scalable and robust distributed task queue system that leverages Redis not just as a simple queue, but as a **state machine capable of atomic operations**. This enables advanced features such as fairness, dependency resolution, and periodic execution.
