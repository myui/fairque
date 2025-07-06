# FairQueue Implementation Design Specification

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture Design](#architecture-design)
3. [Priority System](#priority-system)
4. [Task Specification](#task-specification)
5. [Configuration System](#configuration-system)
6. [Error Handling](#error-handling)
7. [Statistics and Monitoring](#statistics-and-monitoring)
8. [Lua Scripts](#lua-scripts)
9. [Core Implementation](#core-implementation)
10. [Worker Implementation](#worker-implementation)
11. [Project Structure](#project-structure)
12. [Usage Examples](#usage-examples)
13. [Testing Strategy](#testing-strategy)
14. [Implementation Phases](#implementation-phases)
15. [Dependencies](#dependencies)
16. [Performance Considerations](#performance-considerations)
17. [Summary](#summary)

## Project Overview

### Basic Information
- **Project Name**: `fairque`
- **Directory**: `/Users/myui/workspace/myui/fairque`
- **Package Manager**: uv
- **Python Version**: 3.10+
- **Type Annotations**: Required (Full Typing)
- **Language Policy**: All code and documentation in English
- **Documentation**: English only (comprehensive)

### Supported Platforms
- Redis 7.2.5+
- Valkey 7.2.6+
- Amazon MemoryDB for Redis

### Key Features
- **Fair Scheduling**: Round-robin user selection with work stealing
- **Priority Queues**: Type-safe priority system with critical/normal separation
- **Atomic Operations**: Lua scripts ensure consistency and performance
- **Configuration-Based**: No Redis state for user management, fully configurable
- **Pipeline Optimization**: Batch operations for high throughput
- **Comprehensive Monitoring**: Built-in statistics and alerting
- **Production Ready**: Error handling, graceful shutdown, health checks

## Architecture Design

### Core Design Principles
1. **Redis/Valkey as persistent storage** (not in-memory cache)
2. **Lua scripts for server-side atomic operations** with integrated statistics
3. **Minimized lock scope** with atomic processing
4. **Configuration-based user management** (no all_users Redis key)
5. **Dual implementation**: Synchronous and Asynchronous versions
6. **Unified DLQ** for failed tasks with embedded failure types
7. **Type-safe Priority system** using IntEnum
8. **Integrated statistics** with Lua-side updates for consistency
9. **Redis Pipeline optimization** for batch operations
10. **Enhanced error handling** with structured responses

### Queue Structure
```
queue:user:{user_id}:critical  # Priority.CRITICAL tasks (List, FIFO)
queue:user:{user_id}:normal    # Priority 1-5 tasks (Sorted Set, Score-based)
dlq                           # Single DLQ for all failure types (List)
queue:stats                   # Unified statistics (Hash)
schedules                     # Scheduled tasks (Hash) [Optional]
schedule_lock                 # Scheduler distributed lock (String) [Optional]
```

**Key Changes from Traditional Designs:**
- ❌ **Removed**: `all_users` Redis key
- ✅ **Added**: Configuration-based user management in Workers
- ✅ **Enhanced**: All statistics updates integrated into Lua scripts
- ✅ **Optimized**: Pipeline operations for batch processing

### Processing Priority
1. **User Selection**: Configuration-based with Work Stealing
   - Workers have assigned_users (primary responsibility)
   - Workers have steal_targets (work stealing sources)
   - Round-robin within each category
2. **Queue Priority**: Critical → Normal (strict priority)
3. **Critical Queue**: FIFO (First In, First Out)
4. **Normal Queue**: Priority + Time-weighted Scoring

### Work Stealing Strategy
```python
# Worker configuration example
worker_config = {
    "id": "worker-001",
    "assigned_users": ["user:1", "user:3", "user:5"],  # Primary responsibility
    "steal_targets": ["user:2", "user:4", "user:6"]    # Can steal from these
}

# Processing order:
# 1. Try assigned_users (user:1, user:3, user:5)
# 2. If empty, try steal_targets (user:2, user:4, user:6)
# 3. For each user: critical queue first, then normal queue
```

## Priority System

### Priority Enum Definition
```python
from enum import IntEnum

class Priority(IntEnum):
    """Task priority levels with type safety"""
    VERY_LOW = 1    # Lowest priority, minimal time weight
    LOW = 2         # Low priority
    NORMAL = 3      # Standard priority
    HIGH = 4        # High priority
    VERY_HIGH = 5   # Very high priority, maximum time weight
    CRITICAL = 6    # Critical priority, uses separate FIFO queue
    
    @property
    def weight(self) -> float:
        """Get priority weight for score calculation (1-5 only)"""
        if self == Priority.CRITICAL:
            raise ValueError("Critical priority does not use weight calculation")
        return self.value / 5.0
    
    @property
    def is_critical(self) -> bool:
        """Check if priority is critical"""
        return self == Priority.CRITICAL
    
    @classmethod
    def from_int(cls, value: int) -> "Priority":
        """Create Priority from integer with validation"""
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"Invalid priority value: {value}. Must be 1-6.")

def calculate_score(task: "Task") -> float:
    """Calculate priority score for normal queue ordering
    
    Higher score = higher priority for processing
    Formula: created_at + (priority_weight * elapsed_time)
    This prevents starvation while respecting priority levels
    """
    if task.priority.is_critical:
        raise ValueError("Critical tasks do not use score calculation")
    
    current_time = time.time()
    elapsed_time = current_time - task.created_at
    priority_weight = task.priority.weight
    
    return task.created_at + (priority_weight * elapsed_time)
```

### Queue Selection Logic
- **Priority 6 (CRITICAL)**: → Critical queue (FIFO List)
- **Priority 1-5**: → Normal queue (Sorted Set with score)

## Task Specification

### Enhanced Task Model with Optimized Serialization
```python
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import time
import uuid
import json

@dataclass
class Task:
    """Optimized Task model with efficient serialization"""
    task_id: str           # UUID4 auto-generated by system
    user_id: str
    priority: Priority     # Priority enum (1-6)
    payload: Dict[str, Any]
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    execute_after: float = field(default_factory=time.time)
    
    @classmethod
    def create(
        cls,
        user_id: str,
        priority: Priority,
        payload: Dict[str, Any],
        max_retries: int = 3,
        execute_after: Optional[float] = None
    ) -> "Task":
        """Create new task with auto-generated UUID and timestamps"""
        current_time = time.time()
        return cls(
            task_id=str(uuid.uuid4()),
            user_id=user_id,
            priority=priority,
            payload=payload,
            retry_count=0,
            max_retries=max_retries,
            created_at=current_time,
            execute_after=execute_after or current_time
        )
    
    def is_ready_to_execute(self) -> bool:
        """Check if task is ready to execute based on execute_after timestamp"""
        return time.time() >= self.execute_after
    
    def can_retry(self) -> bool:
        """Check if task can be retried"""
        return self.retry_count < self.max_retries
    
    def get_retry_delay(self) -> float:
        """Calculate exponential backoff delay for retry"""
        return 2.0 ** self.retry_count
    
    def increment_retry(self) -> "Task":
        """Return new task instance with incremented retry count and updated execute_after"""
        delay = self.get_retry_delay()
        return dataclasses.replace(
            self,
            retry_count=self.retry_count + 1,
            execute_after=time.time() + delay
        )
    
    # Optimized serialization methods
    def to_redis_dict(self) -> Dict[str, str]:
        """Redis storage optimized dictionary (minimized JSON encoding)"""
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "priority": str(self.priority.value),  # int as string
            "payload": json.dumps(self.payload, separators=(',', ':')),  # minimal JSON
            "retry_count": str(self.retry_count),
            "max_retries": str(self.max_retries),
            "created_at": f"{self.created_at:.6f}",  # limited precision
            "execute_after": f"{self.execute_after:.6f}"
        }
    
    @classmethod
    def from_redis_dict(cls, data: Dict[str, str]) -> "Task":
        """Efficiently restore from Redis dictionary"""
        try:
            return cls(
                task_id=data["task_id"],
                user_id=data["user_id"],
                priority=Priority(int(data["priority"])),
                payload=json.loads(data["payload"]),
                retry_count=int(data["retry_count"]),
                max_retries=int(data["max_retries"]),
                created_at=float(data["created_at"]),
                execute_after=float(data["execute_after"])
            )
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            raise TaskSerializationError(f"Failed to deserialize task from Redis: {e}")
    
    def to_lua_args(self) -> List[str]:
        """Lua script argument list (optimized for array transmission)"""
        redis_dict = self.to_redis_dict()
        return [
            redis_dict["task_id"],
            redis_dict["user_id"], 
            redis_dict["priority"],
            redis_dict["payload"],
            redis_dict["retry_count"],
            redis_dict["max_retries"],
            redis_dict["created_at"],
            redis_dict["execute_after"]
        ]
    
    @classmethod
    def from_lua_result(cls, lua_args: List[str]) -> "Task":
        """Restore from Lua script result (optimized array format)"""
        if len(lua_args) != 8:
            raise TaskSerializationError(f"Invalid lua_args length: expected 8, got {len(lua_args)}")
        
        return cls(
            task_id=lua_args[0],
            user_id=lua_args[1],
            priority=Priority(int(lua_args[2])),
            payload=json.loads(lua_args[3]),
            retry_count=int(lua_args[4]),
            max_retries=int(lua_args[5]),
            created_at=float(lua_args[6]),
            execute_after=float(lua_args[7])
        )
```

### Dead Letter Queue (DLQ) Entry
```python
@dataclass
class DLQEntry:
    """Simplified DLQ entry with failure type embedded"""
    entry_id: str           # UUID4 for DLQ entry
    original_task: Task     # Failed original task
    failure_type: str       # "failed"|"expired"|"poisoned"
    reason: str            # Failure reason description
    moved_at: float        # Timestamp when moved to DLQ
    retry_history: List[Dict[str, Any]] = field(default_factory=list)
    
    @classmethod
    def create(cls, task: Task, failure_type: str, reason: str) -> "DLQEntry":
        """Create new DLQ entry"""
        return cls(
            entry_id=str(uuid.uuid4()),
            original_task=task,
            failure_type=failure_type,
            reason=reason,
            moved_at=time.time(),
            retry_history=[]
        )
    
    def get_age_seconds(self) -> float:
        """Get age of this DLQ entry in seconds"""
        return time.time() - self.moved_at
```

## Configuration System

### Unified Configuration Classes
```python
from dataclasses import dataclass, field
from typing import Optional, List
import yaml
import redis

@dataclass
class RedisConfig:
    """Redis connection configuration"""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    username: Optional[str] = None
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    health_check_interval: int = 30
    decode_responses: bool = True

@dataclass
class WorkerConfig:
    """Worker configuration with validation"""
    id: str                                    # Unique worker identifier
    assigned_users: List[str]                  # Users this worker is responsible for
    steal_targets: List[str]                   # Users this worker can steal from
    poll_interval_seconds: float = 1.0        # Polling interval
    task_timeout_seconds: float = 300.0       # Task execution timeout
    max_concurrent_tasks: int = 10             # Maximum concurrent tasks
    graceful_shutdown_timeout: float = 30.0   # Graceful shutdown timeout
    
    def __post_init__(self):
        """Validate configuration"""
        if not self.id:
            raise ValueError("Worker ID cannot be empty")
        
        # Check for overlap between assigned and steal targets
        assigned_set = set(self.assigned_users)
        steal_set = set(self.steal_targets)
        overlap = assigned_set & steal_set
        if overlap:
            raise ValueError(f"Assigned users and steal targets cannot overlap: {overlap}")

@dataclass
class QueueConfig:
    """Queue configuration with performance settings"""
    stats_prefix: str = "fq"
    lua_script_cache_size: int = 100
    max_retry_attempts: int = 3
    default_task_timeout: float = 300.0
    default_max_retries: int = 3
    
    # Pipeline settings
    enable_pipeline_optimization: bool = True
    pipeline_batch_size: int = 100
    pipeline_timeout: float = 5.0
    
    # Performance settings
    queue_cleanup_interval: int = 3600  # seconds
    stats_aggregation_interval: int = 300  # seconds
    
    def validate(self) -> None:
        """Validate configuration parameters"""
        if self.pipeline_batch_size <= 0:
            raise ValueError("pipeline_batch_size must be positive")
        if self.pipeline_timeout <= 0:
            raise ValueError("pipeline_timeout must be positive")
        if self.max_retry_attempts < 0:
            raise ValueError("max_retry_attempts cannot be negative")

@dataclass
class FairQueueConfig:
    """Unified configuration class"""
    redis: RedisConfig
    worker: WorkerConfig
    queue: QueueConfig = field(default_factory=QueueConfig)
    
    @classmethod
    def from_yaml(cls, path: str) -> "FairQueueConfig":
        """Load unified configuration from single YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        return cls(
            redis=RedisConfig(**data.get("redis", {})),
            worker=WorkerConfig(**data.get("worker", {})),
            queue=QueueConfig(**data.get("queue", {}))
        )
    
    def to_yaml(self, path: str) -> None:
        """Save unified configuration to YAML file"""
        data = {
            "redis": self.redis.__dict__,
            "worker": self.worker.__dict__,
            "queue": self.queue.__dict__
        }
        
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=True)
    
    def create_redis_client(self) -> redis.Redis:
        """Create Redis client from configuration"""
        return redis.Redis(
            host=self.redis.host,
            port=self.redis.port,
            db=self.redis.db,
            password=self.redis.password,
            username=self.redis.username,
            socket_timeout=self.redis.socket_timeout,
            socket_connect_timeout=self.redis.socket_connect_timeout,
            health_check_interval=self.redis.health_check_interval,
            decode_responses=self.redis.decode_responses
        )
    
    def validate_all(self) -> None:
        """Validate all configuration sections"""
        self.queue.validate()
        # Additional cross-section validation can be added here
```

### Configuration File Example (fairque_config.yaml)
```yaml
redis:
  host: "localhost"
  port: 6379
  db: 0
  password: null
  username: null
  socket_timeout: 5.0
  socket_connect_timeout: 5.0
  health_check_interval: 30
  decode_responses: true

worker:
  id: "worker-001"
  assigned_users: ["user:1", "user:3", "user:5"]
  steal_targets: ["user:2", "user:4", "user:6", "user:7"]
  poll_interval_seconds: 1.0
  task_timeout_seconds: 300.0
  max_concurrent_tasks: 10
  graceful_shutdown_timeout: 30.0

queue:
  stats_prefix: "fq"
  lua_script_cache_size: 100
  max_retry_attempts: 3
  default_task_timeout: 300.0
  default_max_retries: 3
  enable_pipeline_optimization: true
  pipeline_batch_size: 100
  pipeline_timeout: 5.0
  queue_cleanup_interval: 3600
  stats_aggregation_interval: 300
```

## Error Handling

### Exception Classes
```python
class FairQueueError(Exception):
    """Base FairQueue exception class"""
    pass

class LuaScriptError(FairQueueError):
    """Lua script execution error"""
    def __init__(self, script_name: str, error_details: Dict[str, Any]):
        self.script_name = script_name
        self.error_details = error_details
        super().__init__(f"Lua script '{script_name}' failed: {error_details}")

class TaskValidationError(FairQueueError):
    """Task validation error"""
    pass

class RedisConnectionError(FairQueueError):
    """Redis connection error"""
    pass

class TaskSerializationError(FairQueueError):
    """Task serialization/deserialization error"""
    pass

class ConfigurationError(FairQueueError):
    """Configuration validation error"""
    pass
```

## Implementation Phases

### Phase 1: Core Infrastructure (Priority 1)
1. **Setup project structure with uv**
   - Initialize project with pyproject.toml
   - Create package structure
   - Setup testing framework

2. **Implement core models**
   - Priority enum with validation
   - Task model with optimized serialization
   - Configuration classes (RedisConfig, WorkerConfig, QueueConfig, FairQueueConfig)
   - Exception classes

3. **Implement Lua scripts with common functions**
   - Create common.lua with shared functions
   - Implement push/pop scripts with integrated statistics
   - Add comprehensive error handling and validation

4. **Basic FairQueue implementation**
   - Core push/pop functionality
   - Lua script integration
   - Error handling and logging

### Phase 2: Worker and Advanced Features (Priority 2)
1. **Worker implementation**
   - Configuration-based user management
   - Work stealing logic
   - Task execution with timeout
   - Performance monitoring

2. **Batch operations and pipeline optimization**
   - push_batch implementation
   - get_queue_sizes_batch
   - Pipeline-based operations

3. **DLQ implementation**
   - Send to DLQ functionality
   - Requeue from DLQ
   - DLQ cleanup operations

### Phase 3: Monitoring and Production Features (Priority 3)
1. **Statistics and monitoring**
   - StatsFormatter implementation
   - StatsMonitor with alerting
   - Health check endpoints

2. **Configuration management**
   - YAML configuration loading
   - Configuration validation
   - Environment variable support

3. **Async implementation**
   - AsyncFairQueue class
   - AsyncWorker class
   - API compatibility with sync version

### Phase 4: Testing and Documentation (Priority 4)
1. **Comprehensive testing**
   - Unit tests for all components
   - Integration tests
   - Performance tests
   - Error handling tests

2. **Documentation**
   - API documentation
   - User guide
   - Architecture documentation
   - Examples and tutorials

### Phase 5: Production Readiness (Priority 5)
1. **Performance optimization**
   - Benchmarking and profiling
   - Memory usage optimization
   - Connection pool tuning

2. **Deployment support**
   - Docker containers
   - Kubernetes manifests
   - Production configuration examples
   - Monitoring and alerting setup

## Dependencies (pyproject.toml)

```toml
[project]
name = "fairque"
version = "0.1.0"
description = "Production-ready fair queue implementation using Redis with work stealing and priority scheduling"
requires-python = ">=3.10"
readme = "README.md"
license = {text = "MIT"}
authors = [
    {name = "Makoto Yui", email = "myui@apache.org"}
]
dependencies = [
    "redis>=5.0.0",
    "aioredis>=2.0.1", 
    "pydantic>=2.0.0",
    "pyyaml>=6.0",
    "typing-extensions>=4.5.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
    "mypy>=1.5.0",
    "ruff>=0.1.0",
]
scheduler = [
    "croniter>=1.4.0",
    "pytz>=2023.3",
]
monitoring = [
    "prometheus-client>=0.17.0",
    "structlog>=23.1.0",
]
examples = [
    "requests>=2.31.0",
    "aiofiles>=23.0.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0", 
    "pytest-cov>=4.0.0",
    "mypy>=1.5.0",
    "ruff>=0.1.0",
]

[tool.mypy]
python_version = "3.10"
strict = true
warn_return_any = true
warn_unused_configs = true
exclude = ["build/", "dist/"]

[tool.ruff]
target-version = "py310"
line-length = 100
exclude = ["build", "dist"]

[tool.ruff.lint]
select = ["E", "F", "W", "C90", "I", "N", "UP", "S", "B", "A", "C4", "DTZ", "EM", "G", "PIE", "T20", "PT", "Q", "RSE", "RET", "SLF", "SIM", "ARG", "PTH", "PL", "TRY", "PERF", "RUF"]
ignore = ["E501", "S101", "PLR0913"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "--cov=fairque --cov-report=html --cov-report=term-missing"
```

## Summary

This comprehensive design specification provides a complete blueprint for implementing a production-ready FairQueue system with the following key achievements:

### ✅ **Solved Core Issues**
1. **Enhanced Error Handling**: Comprehensive Lua script error handling with structured responses
2. **Unified Statistics**: Consistent naming and Lua-integrated updates for atomic consistency
3. **Simplified APIs**: Configuration-based worker management and optimized queue operations
4. **Unified Configuration**: Single YAML file for all components with validation
5. **Optimized Serialization**: Efficient task serialization with minimal JSON overhead
6. **Common Functions**: Shared Lua functions eliminating code duplication
7. **Pipeline Operations**: Batch operations for high-throughput scenarios

### 🚀 **Production-Ready Features**
- **Atomic Operations**: All operations maintain ACID properties through Lua scripts
- **Work Stealing**: Intelligent load balancing with configuration-based user management
- **Priority Scheduling**: Type-safe priority system with time-weighted scoring
- **Dead Letter Queue**: Unified DLQ with failure type classification
- **Comprehensive Monitoring**: Built-in statistics, performance metrics, and alerting
- **Scalability**: Pipeline operations and batch processing for enterprise workloads
- **Reliability**: Graceful error handling, recovery mechanisms, and health monitoring

### 📋 **Clear Implementation Path**
The specification includes a detailed 5-phase implementation plan with:
- Clear priorities and dependencies
- Comprehensive testing strategy  
- Production deployment guidance
- Performance benchmarking targets
- Real-world usage examples

This design ensures the FairQueue system can handle enterprise-scale workloads while maintaining simplicity, reliability, and ease of use. The implementation can begin immediately following the phase-by-phase roadmap provided.

