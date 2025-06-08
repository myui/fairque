"""Tests for pipeline and task group functionality."""

import pytest

from fairque.core.models import Task
from fairque.core.pipeline import (
    ParallelGroup,
    Pipeline,
    SequentialGroup,
    TaskWrapper,
    create_pipeline,
    parallel,
    sequential,
)


class TestTaskWrapper:
    """Test TaskWrapper functionality."""

    def test_task_wrapper_basic(self):
        """Test basic TaskWrapper functionality."""
        task = Task.create(task_id="test_task", user_id="user1")
        wrapper = TaskWrapper(task)

        assert wrapper.get_tasks() == [task]
        assert wrapper.get_task_ids() == {"test_task"}
        assert wrapper.get_upstream_task_ids() == set()
        assert wrapper.get_downstream_task_ids() == set()

    def test_task_wrapper_with_dependencies(self):
        """Test TaskWrapper with dependencies."""
        task = Task.create(
            task_id="test_task",
            user_id="user1",
            depends_on=["dep1", "dep2"]
        )
        wrapper = TaskWrapper(task)

        assert wrapper.get_upstream_task_ids() == {"dep1", "dep2"}


class TestSequentialGroup:
    """Test SequentialGroup functionality."""

    def test_sequential_group_creation(self):
        """Test creating a sequential group."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")

        wrapper1 = TaskWrapper(task1)
        wrapper2 = TaskWrapper(task2)

        group = SequentialGroup([wrapper1, wrapper2])

        assert len(group.get_tasks()) == 2
        assert group.get_task_ids() == {"task1", "task2"}

    def test_sequential_group_expansion(self):
        """Test sequential dependency expansion."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")
        task3 = Task.create(task_id="task3", user_id="user1")

        wrappers = [TaskWrapper(t) for t in [task1, task2, task3]]
        group = SequentialGroup(wrappers)

        expanded = group.expand_dependencies()

        # Check that dependencies were set up correctly
        assert expanded[0].depends_on == []  # First task has no internal deps
        assert expanded[1].depends_on == ["task1"]  # Second depends on first
        assert expanded[2].depends_on == ["task2"]  # Third depends on second


class TestParallelGroup:
    """Test ParallelGroup functionality."""

    def test_parallel_group_creation(self):
        """Test creating a parallel group."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")

        wrapper1 = TaskWrapper(task1)
        wrapper2 = TaskWrapper(task2)

        group = ParallelGroup([wrapper1, wrapper2])

        assert len(group.get_tasks()) == 2
        assert group.get_task_ids() == {"task1", "task2"}

    def test_parallel_group_expansion(self):
        """Test parallel group expansion."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")

        wrappers = [TaskWrapper(t) for t in [task1, task2]]
        group = ParallelGroup(wrappers)

        # Add upstream dependency
        group.add_upstream_dependency({"upstream_task"})

        expanded = group.expand_dependencies()

        # Both tasks should get the upstream dependency
        assert "upstream_task" in expanded[0].depends_on
        assert "upstream_task" in expanded[1].depends_on


class TestTaskOperators:
    """Test task operators (>>, <<, |)."""

    def test_right_shift_operator(self):
        """Test >> operator."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")

        pipeline = task1 >> task2

        assert isinstance(pipeline, Pipeline)
        assert len(pipeline.get_tasks()) == 2
        assert pipeline.get_task_ids() == {"task1", "task2"}

    def test_left_shift_operator(self):
        """Test << operator."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")

        pipeline = task2 << task1  # task2 depends on task1

        assert isinstance(pipeline, Pipeline)
        assert len(pipeline.get_tasks()) == 2

    def test_or_operator(self):
        """Test | operator."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")

        parallel_group = task1 | task2

        assert isinstance(parallel_group, ParallelGroup)
        assert len(parallel_group.get_tasks()) == 2
        assert parallel_group.get_task_ids() == {"task1", "task2"}


class TestPipeline:
    """Test Pipeline functionality."""

    def test_simple_pipeline(self):
        """Test simple pipeline creation."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")
        task3 = Task.create(task_id="task3", user_id="user1")

        pipeline = task1 >> task2 >> task3

        expanded = pipeline.expand()

        assert len(expanded) == 3
        # Check dependencies were set up
        assert expanded[0].task_id == "task1"
        assert expanded[1].task_id == "task2"
        assert expanded[2].task_id == "task3"
        assert "task1" in expanded[1].depends_on
        assert "task2" in expanded[2].depends_on

    def test_parallel_in_pipeline(self):
        """Test pipeline with parallel section."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")
        task3 = Task.create(task_id="task3", user_id="user1")
        task4 = Task.create(task_id="task4", user_id="user1")

        # task1 >> (task2 | task3) >> task4
        pipeline = task1 >> (task2 | task3) >> task4

        expanded = pipeline.expand()

        assert len(expanded) == 4

        # Find tasks by ID
        tasks_by_id = {t.task_id: t for t in expanded}

        # task2 and task3 should both depend on task1
        assert "task1" in tasks_by_id["task2"].depends_on
        assert "task1" in tasks_by_id["task3"].depends_on

        # task4 should depend on both task2 and task3
        task4_deps = set(tasks_by_id["task4"].depends_on)
        assert {"task2", "task3"}.issubset(task4_deps)

    def test_nested_pipeline_complex(self):
        """Test complex nested pipeline: task0 << (task1 << (task2 || task3)) >> task4."""
        task0 = Task.create(task_id="task0", user_id="user1")
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")
        task3 = Task.create(task_id="task3", user_id="user1")
        task4 = Task.create(task_id="task4", user_id="user1")

        # Build the expression: task0 << (task1 << (task2 || task3)) >> task4
        parallel_group = task2 | task3  # (task2 || task3)
        task1_pipeline = task1 << parallel_group  # task1 << (task2 || task3)
        task0_pipeline = task0 << task1_pipeline  # task0 << (task1 << (task2 || task3))
        final_pipeline = task0_pipeline >> task4  # >> task4

        expanded_tasks = final_pipeline.expand()

        # Should have 5 tasks
        assert len(expanded_tasks) == 5

        # Check dependencies
        task_dict = {task.task_id: task for task in expanded_tasks}

        # task2 and task3 should have no dependencies
        assert task_dict["task2"].depends_on == []
        assert task_dict["task3"].depends_on == []

        # task1 should depend on task2 and task3
        assert set(task_dict["task1"].depends_on) == {"task2", "task3"}

        # task0 should depend only on task1
        assert task_dict["task0"].depends_on == ["task1"]

        # task4 should depend only on task0
        assert task_dict["task4"].depends_on == ["task0"]

    def test_cycle_detection(self):
        """Test that cycles are detected and prevented."""
        task1 = Task.create(task_id="task1", user_id="user1", depends_on=["task2"])
        task2 = Task.create(task_id="task2", user_id="user1")

        # This should create a cycle: task1 depends on task2, but pipeline makes task2 depend on task1
        with pytest.raises(ValueError, match="cycle"):
            task1 >> task2


class TestHelperFunctions:
    """Test helper functions."""

    def test_create_pipeline(self):
        """Test create_pipeline helper."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")

        wrapper1 = TaskWrapper(task1)
        wrapper2 = TaskWrapper(task2)

        pipeline = create_pipeline(wrapper1, wrapper2)

        assert isinstance(pipeline, Pipeline)
        assert len(pipeline.get_tasks()) == 2

    def test_parallel_helper(self):
        """Test parallel helper function."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")

        wrapper1 = TaskWrapper(task1)
        wrapper2 = TaskWrapper(task2)

        group = parallel(wrapper1, wrapper2)

        assert isinstance(group, ParallelGroup)
        assert len(group.get_tasks()) == 2

    def test_sequential_helper(self):
        """Test sequential helper function."""
        task1 = Task.create(task_id="task1", user_id="user1")
        task2 = Task.create(task_id="task2", user_id="user1")

        wrapper1 = TaskWrapper(task1)
        wrapper2 = TaskWrapper(task2)

        group = sequential(wrapper1, wrapper2)

        assert isinstance(group, SequentialGroup)
        assert len(group.get_tasks()) == 2
