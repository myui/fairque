"""Abstract interfaces for FairQueue core components."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Set

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fairque.core.models import Task


class Executable(ABC):
    """Abstract base for executable items (Tasks and TaskGroups)."""

    @abstractmethod
    def get_tasks(self) -> List[Task]:
        """Get all tasks in this executable."""
        pass

    @abstractmethod
    def get_task_ids(self) -> Set[str]:
        """Get all task IDs in this executable."""
        pass

    @abstractmethod
    def get_upstream_task_ids(self) -> Set[str]:
        """Get task IDs that should be dependencies for this executable."""
        pass

    @abstractmethod
    def get_downstream_task_ids(self) -> Set[str]:
        """Get task IDs that should depend on this executable."""
        pass

    def __rshift__(self, other: Executable) -> Pipeline:
        """Implement >> operator for task dependencies."""
        from fairque.core.pipeline import Pipeline
        return Pipeline([self, other])

    def __lshift__(self, other: Executable) -> Pipeline:
        """Implement << operator for reverse dependencies."""
        from fairque.core.pipeline import Pipeline
        return Pipeline([other, self])

    def __or__(self, other: Executable) -> ParallelGroup:
        """Implement | operator for parallel execution."""
        from fairque.core.pipeline import ParallelGroup
        return ParallelGroup([self, other])


if TYPE_CHECKING:
    from fairque.core.pipeline import Pipeline, ParallelGroup