"""Configuration classes for FairQueue with support for separated config files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import yaml
from redis import Redis

from fairque.core.exceptions import ConfigurationError


@dataclass
class RedisConfig:
    """Redis connection configuration."""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    username: Optional[str] = None
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    health_check_interval: int = 30
    decode_responses: bool = True

    # SSL configuration
    ssl: bool = False
    ssl_cert_reqs: Optional[str] = None
    ssl_ca_certs: Optional[str] = None
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None

    # Connection pool configuration
    max_connections: Optional[int] = None

    def validate(self) -> None:
        """Validate Redis configuration parameters.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        if not self.host:
            raise ConfigurationError("Redis host cannot be empty")

        if not (1 <= self.port <= 65535):
            raise ConfigurationError(f"Invalid Redis port: {self.port}. Must be 1-65535.")

        if not (0 <= self.db <= 15):
            raise ConfigurationError(f"Invalid Redis database: {self.db}. Must be 0-15.")

        if self.socket_timeout <= 0:
            raise ConfigurationError("socket_timeout must be positive")

        if self.socket_connect_timeout <= 0:
            raise ConfigurationError("socket_connect_timeout must be positive")

        if self.health_check_interval <= 0:
            raise ConfigurationError("health_check_interval must be positive")

    def create_redis_client(self) -> Redis:
        """Create Redis client from this configuration.

        Returns:
            Configured Redis client instance
        """
        self.validate()
        return cast(Redis, Redis(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password,
            username=self.username,
            socket_timeout=self.socket_timeout,
            socket_connect_timeout=self.socket_connect_timeout,
            health_check_interval=self.health_check_interval,
            decode_responses=self.decode_responses,
        ))


@dataclass
class CommonConfig:
    """Common configuration shared across processes."""

    # Redis configuration
    redis: RedisConfig = field(default_factory=RedisConfig)

    # Logging configuration
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Queue configuration
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
        """Validate common configuration parameters.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        self.redis.validate()

        if not self.stats_prefix:
            raise ConfigurationError("stats_prefix cannot be empty")

        if self.lua_script_cache_size <= 0:
            raise ConfigurationError("lua_script_cache_size must be positive")

        if self.max_retry_attempts < 0:
            raise ConfigurationError("max_retry_attempts cannot be negative")

        if self.default_task_timeout <= 0:
            raise ConfigurationError("default_task_timeout must be positive")

        if self.default_max_retries < 0:
            raise ConfigurationError("default_max_retries cannot be negative")

        if self.pipeline_batch_size <= 0:
            raise ConfigurationError("pipeline_batch_size must be positive")

        if self.pipeline_timeout <= 0:
            raise ConfigurationError("pipeline_timeout must be positive")

        if self.queue_cleanup_interval <= 0:
            raise ConfigurationError("queue_cleanup_interval must be positive")

        if self.stats_aggregation_interval <= 0:
            raise ConfigurationError("stats_aggregation_interval must be positive")

    def get_stats_key(self, key_suffix: str) -> str:
        """Get prefixed statistics key.

        Args:
            key_suffix: Suffix to append to stats prefix

        Returns:
            Full statistics key with prefix
        """
        return f"{self.stats_prefix}:{key_suffix}"

    def create_redis_client(self) -> Redis:
        """Create Redis client from configuration.

        Returns:
            Configured Redis client instance
        """
        return self.redis.create_redis_client()


@dataclass
class WorkerConfig:
    """Worker-specific configuration."""

    # Common configuration (will be merged from common_config)
    common: CommonConfig = field(default_factory=CommonConfig)

    # Worker-specific settings
    id: str = "worker-001"
    assigned_users: List[str] = field(default_factory=list)
    steal_targets: List[str] = field(default_factory=list)
    poll_interval_seconds: float = 1.0
    task_timeout_seconds: float = 300.0
    max_concurrent_tasks: int = 10
    graceful_shutdown_timeout: float = 30.0

    def __post_init__(self) -> None:
        """Validate configuration after initialization.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        self.validate()

    def validate(self) -> None:
        """Validate worker configuration parameters.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        self.common.validate()

        if not self.id:
            raise ConfigurationError("Worker ID cannot be empty")

        if not self.assigned_users:
            raise ConfigurationError("Worker must have at least one assigned user")

        # Check for duplicates in assigned users
        if len(self.assigned_users) != len(set(self.assigned_users)):
            raise ConfigurationError("Assigned users cannot contain duplicates")

        # Check for duplicates in steal targets
        if len(self.steal_targets) != len(set(self.steal_targets)):
            raise ConfigurationError("Steal targets cannot contain duplicates")

        # Check for overlap between assigned and steal targets
        assigned_set = set(self.assigned_users)
        steal_set = set(self.steal_targets)
        overlap = assigned_set & steal_set
        if overlap:
            raise ConfigurationError(
                f"Assigned users and steal targets cannot overlap: {overlap}"
            )

        if self.poll_interval_seconds <= 0:
            raise ConfigurationError("poll_interval_seconds must be positive")

        if self.task_timeout_seconds <= 0:
            raise ConfigurationError("task_timeout_seconds must be positive")

        if self.max_concurrent_tasks <= 0:
            raise ConfigurationError("max_concurrent_tasks must be positive")

        if self.graceful_shutdown_timeout <= 0:
            raise ConfigurationError("graceful_shutdown_timeout must be positive")

    def get_all_users(self) -> List[str]:
        """Get all users this worker can process (assigned + steal targets).

        Returns:
            List of all user IDs this worker can process
        """
        return list(set(self.assigned_users + self.steal_targets))

    def create_redis_client(self) -> Redis:
        """Create Redis client from configuration.

        Returns:
            Configured Redis client instance
        """
        return self.common.create_redis_client()


@dataclass
class SchedulerConfig:
    """Scheduler-specific configuration."""

    # Common configuration (will be merged from common_config)
    common: CommonConfig = field(default_factory=CommonConfig)

    # Scheduler-specific settings
    id: str = "scheduler-001"
    check_interval: int = 60  # seconds
    max_scheduled_tasks: int = 1000
    lock_timeout: int = 300  # seconds
    timezone: str = "UTC"
    enable_distributed_locking: bool = True
    lock_renewal_interval: int = 30  # seconds

    def __post_init__(self) -> None:
        """Validate configuration after initialization.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        self.validate()

    def validate(self) -> None:
        """Validate scheduler configuration parameters.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        self.common.validate()

        if not self.id:
            raise ConfigurationError("Scheduler ID cannot be empty")

        if self.check_interval <= 0:
            raise ConfigurationError("check_interval must be positive")

        if self.max_scheduled_tasks <= 0:
            raise ConfigurationError("max_scheduled_tasks must be positive")

        if self.lock_timeout <= 0:
            raise ConfigurationError("lock_timeout must be positive")

        if self.lock_renewal_interval <= 0:
            raise ConfigurationError("lock_renewal_interval must be positive")

        if self.lock_renewal_interval >= self.lock_timeout:
            raise ConfigurationError("lock_renewal_interval must be less than lock_timeout")

    def create_redis_client(self) -> Redis:
        """Create Redis client from configuration.

        Returns:
            Configured Redis client instance
        """
        return self.common.create_redis_client()


# Configuration loading functions

def _load_config_file(filename: str, config_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load configuration from YAML file.

    Args:
        filename: Name of the configuration file
        config_dir: Directory containing config files (defaults to ./config)

    Returns:
        Dictionary containing configuration data

    Raises:
        ConfigurationError: If file loading fails
    """
    if config_dir is None:
        config_dir = Path("config")

    file_path = config_dir / filename

    try:
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data or {}
    except FileNotFoundError:
        # Return empty dict if file doesn't exist
        return {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigurationError(f"Failed to load configuration from {file_path}: {e}") from e


def _merge_configs(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two configuration dictionaries.

    Args:
        base: Base configuration dictionary
        override: Override configuration dictionary

    Returns:
        Merged configuration dictionary
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_configs(result[key], value)
        else:
            result[key] = value

    return result


def load_worker_config(
    config_name: str = "worker",
    config_dir: Optional[Path] = None,
    common_config_name: str = "common"
) -> WorkerConfig:
    """Load worker configuration with automatic common config merging.

    Args:
        config_name: Worker config name (loads {config_name}_config.yaml)
        config_dir: Configuration directory (defaults to ./config)
        common_config_name: Common config name (loads {common_config_name}_config.yaml)

    Returns:
        WorkerConfig instance with merged configuration

    Raises:
        ConfigurationError: If configuration loading or validation fails
    """
    # Load common configuration
    common_data = _load_config_file(f"{common_config_name}_config.yaml", config_dir)

    # Load worker-specific configuration
    worker_data = _load_config_file(f"{config_name}_config.yaml", config_dir)

    # Merge configurations
    merged_data = _merge_configs(common_data, worker_data)

    try:
        # Create CommonConfig from merged data
        common_config = CommonConfig()
        if "redis" in merged_data:
            common_config.redis = RedisConfig(**merged_data["redis"])

        # Update common config with other common fields
        for field_name in ["log_level", "log_format", "stats_prefix", "lua_script_cache_size",
                          "max_retry_attempts", "default_task_timeout", "default_max_retries",
                          "enable_pipeline_optimization", "pipeline_batch_size", "pipeline_timeout",
                          "queue_cleanup_interval", "stats_aggregation_interval"]:
            if field_name in merged_data:
                setattr(common_config, field_name, merged_data[field_name])

        # Create WorkerConfig
        worker_config_data = merged_data.copy()
        worker_config_data["common"] = common_config

        # Remove common fields from worker data to avoid conflicts
        for field_name in ["redis", "log_level", "log_format", "stats_prefix", "lua_script_cache_size",
                          "max_retry_attempts", "default_task_timeout", "default_max_retries",
                          "enable_pipeline_optimization", "pipeline_batch_size", "pipeline_timeout",
                          "queue_cleanup_interval", "stats_aggregation_interval"]:
            worker_config_data.pop(field_name, None)

        return WorkerConfig(**worker_config_data)

    except TypeError as e:
        raise ConfigurationError(f"Invalid worker configuration structure: {e}") from e


def load_scheduler_config(
    config_name: str = "scheduler",
    config_dir: Optional[Path] = None,
    common_config_name: str = "common"
) -> SchedulerConfig:
    """Load scheduler configuration with automatic common config merging.

    Args:
        config_name: Scheduler config name (loads {config_name}_config.yaml)
        config_dir: Configuration directory (defaults to ./config)
        common_config_name: Common config name (loads {common_config_name}_config.yaml)

    Returns:
        SchedulerConfig instance with merged configuration

    Raises:
        ConfigurationError: If configuration loading or validation fails
    """
    # Load common configuration
    common_data = _load_config_file(f"{common_config_name}_config.yaml", config_dir)

    # Load scheduler-specific configuration
    scheduler_data = _load_config_file(f"{config_name}_config.yaml", config_dir)

    # Merge configurations
    merged_data = _merge_configs(common_data, scheduler_data)

    try:
        # Create CommonConfig from merged data
        common_config = CommonConfig()
        if "redis" in merged_data:
            common_config.redis = RedisConfig(**merged_data["redis"])

        # Update common config with other common fields
        for field_name in ["log_level", "log_format", "stats_prefix", "lua_script_cache_size",
                          "max_retry_attempts", "default_task_timeout", "default_max_retries",
                          "enable_pipeline_optimization", "pipeline_batch_size", "pipeline_timeout",
                          "queue_cleanup_interval", "stats_aggregation_interval"]:
            if field_name in merged_data:
                setattr(common_config, field_name, merged_data[field_name])

        # Create SchedulerConfig
        scheduler_config_data = merged_data.copy()
        scheduler_config_data["common"] = common_config

        # Remove common fields from scheduler data to avoid conflicts
        for field_name in ["redis", "log_level", "log_format", "stats_prefix", "lua_script_cache_size",
                          "max_retry_attempts", "default_task_timeout", "default_max_retries",
                          "enable_pipeline_optimization", "pipeline_batch_size", "pipeline_timeout",
                          "queue_cleanup_interval", "stats_aggregation_interval"]:
            scheduler_config_data.pop(field_name, None)

        return SchedulerConfig(**scheduler_config_data)

    except TypeError as e:
        raise ConfigurationError(f"Invalid scheduler configuration structure: {e}") from e


# Legacy support for existing FairQueueConfig
@dataclass
class StateConfig:
    """Task state management configuration."""

    finished_ttl: int = 86400  # 1 day
    failed_ttl: int = 604800   # 7 days
    canceled_ttl: int = 3600   # 1 hour

    def validate(self) -> None:
        """Validate state configuration parameters.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        if self.finished_ttl <= 0:
            raise ConfigurationError("finished_ttl must be positive")
        if self.failed_ttl <= 0:
            raise ConfigurationError("failed_ttl must be positive")
        if self.canceled_ttl <= 0:
            raise ConfigurationError("canceled_ttl must be positive")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "finished_ttl": self.finished_ttl,
            "failed_ttl": self.failed_ttl,
            "canceled_ttl": self.canceled_ttl
        }

@dataclass
class QueueConfig:
    """Queue configuration with performance settings (legacy support)."""

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
        """Validate configuration parameters.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        if not self.stats_prefix:
            raise ConfigurationError("stats_prefix cannot be empty")

        if self.lua_script_cache_size <= 0:
            raise ConfigurationError("lua_script_cache_size must be positive")

        if self.max_retry_attempts < 0:
            raise ConfigurationError("max_retry_attempts cannot be negative")

        if self.default_task_timeout <= 0:
            raise ConfigurationError("default_task_timeout must be positive")

        if self.default_max_retries < 0:
            raise ConfigurationError("default_max_retries cannot be negative")

        if self.pipeline_batch_size <= 0:
            raise ConfigurationError("pipeline_batch_size must be positive")

        if self.pipeline_timeout <= 0:
            raise ConfigurationError("pipeline_timeout must be positive")

        if self.queue_cleanup_interval <= 0:
            raise ConfigurationError("queue_cleanup_interval must be positive")

        if self.stats_aggregation_interval <= 0:
            raise ConfigurationError("stats_aggregation_interval must be positive")

    def get_stats_key(self, key_suffix: str) -> str:
        """Get prefixed statistics key.

        Args:
            key_suffix: Suffix to append to stats prefix

        Returns:
            Full statistics key with prefix
        """
        return f"{self.stats_prefix}:{key_suffix}"


@dataclass
class FairQueueConfig:
    """Unified configuration class supporting multiple workers."""

    redis: RedisConfig
    workers: List[WorkerConfig]
    queue: QueueConfig = field(default_factory=QueueConfig)
    state: StateConfig = field(default_factory=StateConfig)

    def __post_init__(self) -> None:
        """Validate configuration after initialization.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        self.validate_all()

    def validate_workers(self) -> None:
        """Validate worker configurations for multi-worker setup.

        Raises:
            ConfigurationError: If worker configuration is invalid
        """
        if not self.workers:
            raise ConfigurationError("At least one worker must be configured")

        # Check for duplicate worker IDs
        worker_ids = [w.id for w in self.workers]
        if len(worker_ids) != len(set(worker_ids)):
            duplicates = [wid for wid in set(worker_ids) if worker_ids.count(wid) > 1]
            raise ConfigurationError(f"Duplicate worker IDs found: {duplicates}")

        # Check for duplicate assigned users across workers
        all_assigned = []
        for worker in self.workers:
            all_assigned.extend(worker.assigned_users)

        if len(all_assigned) != len(set(all_assigned)):
            duplicates = [uid for uid in set(all_assigned) if all_assigned.count(uid) > 1]
            raise ConfigurationError(f"Users assigned to multiple workers: {duplicates}")

    def get_worker_by_id(self, worker_id: str) -> Optional[WorkerConfig]:
        """Get worker configuration by ID.

        Args:
            worker_id: Worker ID to search for

        Returns:
            WorkerConfig if found, None otherwise
        """
        return next((w for w in self.workers if w.id == worker_id), None)

    def get_all_users(self) -> List[str]:
        """Get all users covered by all workers (assigned + steal targets).

        Returns:
            Sorted list of all unique user IDs covered by workers
        """
        all_users = set()
        for worker in self.workers:
            all_users.update(worker.get_all_users())
        return sorted(all_users)

    def get_coverage_info(self) -> Dict[str, Any]:
        """Get worker coverage statistics.

        Returns:
            Dictionary containing coverage information and statistics
        """
        total_assigned = sum(len(w.assigned_users) for w in self.workers)
        total_steal_targets = sum(len(w.steal_targets) for w in self.workers)
        unique_users = len(self.get_all_users())

        return {
            "total_workers": len(self.workers),
            "total_assigned_users": total_assigned,
            "total_steal_targets": total_steal_targets,
            "unique_users_covered": unique_users,
            "worker_details": [
                {
                    "id": w.id,
                    "assigned_count": len(w.assigned_users),
                    "steal_targets_count": len(w.steal_targets),
                    "total_users": len(w.get_all_users())
                }
                for w in self.workers
            ]
        }

    # Legacy property for backward compatibility
    @property
    def worker(self) -> WorkerConfig:
        """Legacy property for single worker access (backward compatibility).

        Returns:
            Single WorkerConfig when only one worker is configured

        Raises:
            ConfigurationError: If multiple workers are configured
        """
        if len(self.workers) != 1:
            raise ConfigurationError(
                f"Cannot access single worker when {len(self.workers)} workers are configured. "
                "Use 'workers' property or 'get_worker_by_id()' method instead."
            )
        return self.workers[0]

    @worker.setter
    def worker(self, value: WorkerConfig) -> None:
        """Legacy setter for single worker (backward compatibility).

        Args:
            value: WorkerConfig to set as the single worker
        """
        self.workers = [value]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FairQueueConfig":
        """Create FairQueueConfig from dictionary data.

        Supports both single worker (legacy) and multi-worker configurations.

        Args:
            data: Dictionary containing configuration data

        Returns:
            FairQueueConfig instance created from dictionary

        Raises:
            ConfigurationError: If dictionary structure is invalid

        Examples:
            # Single worker (legacy format)
            config_dict = {
                "redis": {"host": "localhost", "port": 6379},
                "worker": {
                    "id": "worker1",
                    "assigned_users": ["user1", "user2"]
                },
                "queue": {"stats_prefix": "fq"}
            }
            config = FairQueueConfig.from_dict(config_dict)

            # Multiple workers (new format)
            config_dict = {
                "redis": {"host": "localhost", "port": 6379},
                "workers": [
                    {
                        "id": "worker1",
                        "assigned_users": ["user1", "user2"],
                        "steal_targets": ["user3", "user4"]
                    },
                    {
                        "id": "worker2",
                        "assigned_users": ["user3", "user4"],
                        "steal_targets": ["user1", "user2"]
                    }
                ],
                "queue": {"stats_prefix": "fq"}
            }
            config = FairQueueConfig.from_dict(config_dict)
        """
        if not isinstance(data, dict):
            raise ConfigurationError("Configuration data must be a dictionary")

        try:
            # Parse Redis configuration
            redis_config = RedisConfig(**data.get("redis", {}))

            # Parse Queue configuration
            queue_config = QueueConfig(**data.get("queue", {}))

            # Parse State configuration
            state_config = StateConfig(**data.get("state", {}))

            # Parse Worker configuration(s)
            workers = []

            if "workers" in data and "worker" in data:
                raise ConfigurationError(
                    "Cannot specify both 'worker' and 'workers' in configuration. "
                    "Use 'workers' for multiple workers or 'worker' for single worker (legacy)."
                )
            elif "workers" in data:
                # Multi-worker format
                workers_data = data["workers"]
                if not isinstance(workers_data, list):
                    raise ConfigurationError("'workers' must be a list")

                for i, worker_data in enumerate(workers_data):
                    if not isinstance(worker_data, dict):
                        raise ConfigurationError(f"Worker {i} configuration must be a dictionary")
                    workers.append(WorkerConfig(**worker_data))

            elif "worker" in data:
                # Single worker format (legacy)
                worker_data = data["worker"]
                if not isinstance(worker_data, dict):
                    raise ConfigurationError("'worker' configuration must be a dictionary")
                workers.append(WorkerConfig(**worker_data))
            else:
                raise ConfigurationError(
                    "Configuration must contain either 'worker' or 'workers' section"
                )

            return cls(
                redis=redis_config,
                workers=workers,
                queue=queue_config,
                state=state_config
            )

        except TypeError as e:
            raise ConfigurationError(f"Invalid configuration structure: {e}") from e

    @classmethod
    def from_yaml(cls, path: str) -> "FairQueueConfig":
        """Load configuration from YAML file.

        Supports both single worker and multi-worker configurations.

        Args:
            path: Path to YAML configuration file

        Returns:
            FairQueueConfig instance loaded from YAML

        Raises:
            ConfigurationError: If YAML loading or parsing fails
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as e:
            raise ConfigurationError(f"Failed to load configuration from {path}: {e}") from e

        if not isinstance(data, dict):
            raise ConfigurationError("Configuration file must contain a YAML dictionary")

        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert FairQueueConfig to dictionary.

        Always uses multi-worker format with 'workers' array.

        Returns:
            Dictionary representation of configuration
        """
        result: dict[str, Any] = {
            "redis": {
                "host": self.redis.host,
                "port": self.redis.port,
                "db": self.redis.db,
                "password": self.redis.password,
                "username": self.redis.username,
                "socket_timeout": self.redis.socket_timeout,
                "socket_connect_timeout": self.redis.socket_connect_timeout,
                "health_check_interval": self.redis.health_check_interval,
                "decode_responses": self.redis.decode_responses,
                "ssl": self.redis.ssl,
                "ssl_cert_reqs": self.redis.ssl_cert_reqs,
                "ssl_ca_certs": self.redis.ssl_ca_certs,
                "ssl_certfile": self.redis.ssl_certfile,
                "ssl_keyfile": self.redis.ssl_keyfile,
                "max_connections": self.redis.max_connections
            },
            "queue": {
                "stats_prefix": self.queue.stats_prefix,
                "lua_script_cache_size": self.queue.lua_script_cache_size,
                "max_retry_attempts": self.queue.max_retry_attempts,
                "default_task_timeout": self.queue.default_task_timeout,
                "default_max_retries": self.queue.default_max_retries,
                "enable_pipeline_optimization": self.queue.enable_pipeline_optimization,
                "pipeline_batch_size": self.queue.pipeline_batch_size,
                "pipeline_timeout": self.queue.pipeline_timeout,
                "queue_cleanup_interval": self.queue.queue_cleanup_interval,
                "stats_aggregation_interval": self.queue.stats_aggregation_interval
            },
            "state": {
                "finished_ttl": self.state.finished_ttl,
                "failed_ttl": self.state.failed_ttl,
                "canceled_ttl": self.state.canceled_ttl
            },
            "workers": []
        }

        # Add all workers configuration
        for worker in self.workers:
            result["workers"].append({
                "id": worker.id,
                "assigned_users": worker.assigned_users,
                "steal_targets": worker.steal_targets,
                "poll_interval_seconds": worker.poll_interval_seconds,
                "task_timeout_seconds": worker.task_timeout_seconds,
                "max_concurrent_tasks": worker.max_concurrent_tasks,
                "graceful_shutdown_timeout": worker.graceful_shutdown_timeout
            })

        # Remove None values to keep dict clean
        return {k: v for k, v in result.items() if v is not None}

    def to_yaml(self, path: str) -> None:
        """Save configuration to YAML file.

        Always uses multi-worker format.

        Args:
            path: Path where to save YAML configuration file

        Raises:
            ConfigurationError: If YAML saving fails
        """
        data = self.to_dict()

        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=True)
        except OSError as e:
            raise ConfigurationError(f"Failed to save configuration to {path}: {e}") from e

    def create_redis_client(self) -> Redis:
        """Create Redis client from configuration.

        Returns:
            Configured Redis client instance
        """
        return self.redis.create_redis_client()

    def validate_all(self) -> None:
        """Validate all configuration sections.

        Raises:
            ConfigurationError: If any configuration section is invalid
        """
        self.redis.validate()
        self.queue.validate()
        self.state.validate()
        self.validate_workers()

        # Validate each worker
        for worker in self.workers:
            worker.validate()

        # Cross-section validation
        for worker in self.workers:
            if worker.task_timeout_seconds > self.queue.default_task_timeout:
                raise ConfigurationError(
                    f"Worker '{worker.id}' task_timeout_seconds should not exceed "
                    f"queue default_task_timeout"
                )

    @classmethod
    def create_default(
        cls,
        worker_id: str,
        assigned_users: List[str],
        steal_targets: Optional[List[str]] = None,
    ) -> "FairQueueConfig":
        """Create default configuration with single worker (legacy support).

        Args:
            worker_id: Unique worker identifier
            assigned_users: List of users this worker is responsible for
            steal_targets: List of users this worker can steal from (optional)

        Returns:
            FairQueueConfig with default settings and single worker
        """
        return cls(
            redis=RedisConfig(),
            workers=[WorkerConfig(
                id=worker_id,
                assigned_users=assigned_users,
                steal_targets=steal_targets or [],
            )],
            queue=QueueConfig(),
        )

    @classmethod
    def create_multi_worker(
        cls,
        workers: List[WorkerConfig],
        redis_config: Optional[RedisConfig] = None,
        queue_config: Optional[QueueConfig] = None,
    ) -> "FairQueueConfig":
        """Create configuration with multiple workers.

        Args:
            workers: List of worker configurations
            redis_config: Redis configuration (optional, uses default if None)
            queue_config: Queue configuration (optional, uses default if None)

        Returns:
            FairQueueConfig with multiple workers
        """
        return cls(
            redis=redis_config or RedisConfig(),
            workers=workers,
            queue=queue_config or QueueConfig(),
        )
