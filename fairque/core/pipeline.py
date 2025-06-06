"""Pipeline and TaskGroup system for FairQueue workflow composition."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Set

from fairque.core.models import Task, detect_dependency_cycle

logger = logging.getLogger(__name__)


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
        return Pipeline([self, other])

    def __lshift__(self, other: Executable) -> Pipeline:
        """Implement << operator for reverse dependencies."""
        return Pipeline([other, self])

    def __or__(self, other: Executable) -> ParallelGroup:
        """Implement | operator for parallel execution."""
        return ParallelGroup([self, other])


@dataclass
class TaskWrapper(Executable):
    """Wrapper for Task to implement Executable interface."""

    task: Task

    def get_tasks(self) -> List[Task]:
        return [self.task]

    def get_task_ids(self) -> Set[str]:
        return {self.task.task_id}

    def get_upstream_task_ids(self) -> Set[str]:
        return set(self.task.depends_on)

    def get_downstream_task_ids(self) -> Set[str]:
        return set(self.task.dependents)


class TaskGroup(Executable):
    """Virtual group of tasks that can be treated as a single unit."""

    def __init__(self, tasks: List[Executable], group_id: Optional[str] = None):
        self.tasks = tasks
        self.group_id = group_id or f"group_{id(self)}"
        self._upstream_dependencies: Set[str] = set()
        self._downstream_dependents: Set[str] = set()

    def get_tasks(self) -> List[Task]:
        """Get all tasks from all executables in this group."""
        all_tasks = []
        for executable in self.tasks:
            all_tasks.extend(executable.get_tasks())
        return all_tasks

    def get_task_ids(self) -> Set[str]:
        """Get all task IDs from all executables in this group."""
        all_ids = set()
        for executable in self.tasks:
            all_ids.update(executable.get_task_ids())
        return all_ids

    def get_upstream_task_ids(self) -> Set[str]:
        """Get upstream dependencies for this group."""
        return self._upstream_dependencies.copy()

    def get_downstream_task_ids(self) -> Set[str]:
        """Get downstream dependents for this group."""
        return self._downstream_dependents.copy()

    def add_upstream_dependency(self, task_ids: Set[str]) -> None:
        """Add upstream dependencies to this group."""
        self._upstream_dependencies.update(task_ids)

    def add_downstream_dependent(self, task_ids: Set[str]) -> None:
        """Add downstream dependents to this group."""
        self._downstream_dependents.update(task_ids)


class SequentialGroup(TaskGroup):
    """Group where tasks execute sequentially (A >> B >> C)."""

    def expand_dependencies(self) -> List[Task]:
        """Expand sequential dependencies and return modified tasks."""
        tasks = self.get_tasks()
        if len(tasks) <= 1:
            return tasks

        expanded_tasks = []

        # Set up sequential dependencies
        for i, task in enumerate(tasks):
            modified_task = task

            # Add upstream dependencies
            if i == 0:
                # First task gets group's upstream dependencies
                if self._upstream_dependencies:
                    new_depends_on = list(set(task.depends_on) | self._upstream_dependencies)
                    modified_task = task.__class__(
                        **{**task.__dict__, 'depends_on': new_depends_on}
                    )
            else:
                # Subsequent tasks depend on previous task
                prev_task_id = tasks[i-1].task_id
                new_depends_on = list(set(task.depends_on) | {prev_task_id})
                modified_task = task.__class__(
                    **{**task.__dict__, 'depends_on': new_depends_on}
                )

            # Add downstream dependents to last task
            if i == len(tasks) - 1 and self._downstream_dependents:
                new_dependents = list(set(modified_task.dependents) | self._downstream_dependents)
                modified_task = modified_task.__class__(
                    **{**modified_task.__dict__, 'dependents': new_dependents}
                )

            expanded_tasks.append(modified_task)

        return expanded_tasks


class ParallelGroup(TaskGroup):
    """Group where tasks execute in parallel (A | B | C)."""

    def expand_dependencies(self) -> List[Task]:
        """Expand parallel dependencies and return modified tasks."""
        tasks = self.get_tasks()
        expanded_tasks = []

        for task in tasks:
            modified_task = task

            # All tasks get group's upstream dependencies
            if self._upstream_dependencies:
                new_depends_on = list(set(task.depends_on) | self._upstream_dependencies)
                modified_task = task.__class__(
                    **{**task.__dict__, 'depends_on': new_depends_on}
                )

            # All tasks get group's downstream dependents
            if self._downstream_dependents:
                new_dependents = list(set(modified_task.dependents) | self._downstream_dependents)
                modified_task = modified_task.__class__(
                    **{**modified_task.__dict__, 'dependents': new_dependents}
                )

            expanded_tasks.append(modified_task)

        return expanded_tasks


class Pipeline(Executable):
    """Represents a pipeline of executables with dependencies."""

    def __init__(self, executables: List[Executable]):
        self.executables = executables
        self._validate_pipeline()

    def _validate_pipeline(self) -> None:
        """Validate that pipeline doesn't create cycles."""
        all_task_ids = set()
        for executable in self.executables:
            all_task_ids.update(executable.get_task_ids())

        # Build dependency graph
        task_dependencies = {}
        for executable in self.executables:
            for task in executable.get_tasks():
                task_dependencies[task.task_id] = task.depends_on.copy()

        # Add pipeline dependencies
        for i in range(len(self.executables) - 1):
            current_ids = self.executables[i].get_task_ids()
            next_ids = self.executables[i + 1].get_task_ids()

            for next_id in next_ids:
                if next_id not in task_dependencies:
                    task_dependencies[next_id] = []
                task_dependencies[next_id].extend(current_ids)

        # Check for cycles
        for executable in self.executables:
            for task_id in executable.get_task_ids():
                if task_id in task_dependencies:
                    if detect_dependency_cycle(task_dependencies, task_id, task_dependencies[task_id]):
                        raise ValueError(f"Pipeline would create dependency cycle involving task {task_id}")

    def get_tasks(self) -> List[Task]:
        """Get all tasks from the pipeline."""
        all_tasks = []
        for executable in self.executables:
            all_tasks.extend(executable.get_tasks())
        return all_tasks

    def get_task_ids(self) -> Set[str]:
        """Get all task IDs from the pipeline."""
        all_ids = set()
        for executable in self.executables:
            all_ids.update(executable.get_task_ids())
        return all_ids

    def get_upstream_task_ids(self) -> Set[str]:
        """Get upstream task IDs (from first executable)."""
        if self.executables:
            return self.executables[0].get_upstream_task_ids()
        return set()

    def get_downstream_task_ids(self) -> Set[str]:
        """Get downstream task IDs (from last executable)."""
        if self.executables:
            return self.executables[-1].get_downstream_task_ids()
        return set()

    def expand(self) -> List[Task]:
        """Expand pipeline into list of tasks with proper dependencies."""
        if not self.executables:
            return []

        # First, expand each executable individually
        all_groups = []
        for executable in self.executables:
            if isinstance(executable, TaskGroup):
                all_groups.append(executable)
            elif isinstance(executable, Pipeline):
                # Recursively expand nested pipelines
                nested_tasks = executable.expand()
                wrapper_group = SequentialGroup([TaskWrapper(task) for task in nested_tasks])
                all_groups.append(wrapper_group)
            else:
                # Wrap single tasks
                wrapper_group = SequentialGroup([executable])
                all_groups.append(wrapper_group)

        # Set up dependencies between groups
        for i in range(len(all_groups) - 1):
            current_group = all_groups[i]
            next_group = all_groups[i + 1]

            # Next group depends on current group
            next_group.add_upstream_dependency(current_group.get_task_ids())

        # Expand all groups and collect tasks
        all_tasks = []
        for group in all_groups:
            if hasattr(group, 'expand_dependencies'):
                all_tasks.extend(group.expand_dependencies())
            else:
                all_tasks.extend(group.get_tasks())

        return all_tasks


def create_pipeline(*executables: Executable) -> Pipeline:
    """Helper function to create a pipeline from executables."""
    return Pipeline(list(executables))


def parallel(*executables: Executable) -> ParallelGroup:
    """Helper function to create a parallel group."""
    return ParallelGroup(list(executables))


def sequential(*executables: Executable) -> SequentialGroup:
    """Helper function to create a sequential group."""
    return SequentialGroup(list(executables))
