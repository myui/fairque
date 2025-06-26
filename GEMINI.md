# Gemini Code Assistant Workspace Configuration

This document provides project-specific guidance for the Gemini code assistant to ensure its actions align with the repository's conventions and standards.

## Project Overview

This project is a fair queue implementation using Redis, featuring work-stealing and priority scheduling. It is written in Python and uses `uv` for dependency management.

## Development Workflow

### Installation

To set up the development environment and install all necessary dependencies, including optional ones for testing and development, run the following command:

```bash
uv sync --all-extras --dev
```

### Linting and Formatting

The project uses `ruff` for code linting and formatting. To check for linting errors, run:

```bash
uv run ruff check .
```

To automatically fix linting errors and format the code, run:

```bash
uv run ruff format .
```

### Type Checking

The project uses `mypy` for static type checking. To run the type checker, use the following command:

```bash
uv run mypy .
```

### Testing

The project uses `pytest` for running tests. The tests are located in the `tests/` directory, divided into `unit` and `integration` subdirectories.

To run all unit tests, execute:

```bash
uv run pytest tests/unit
```

To run all tests (including integration tests, which may require services like Redis to be running), execute:

```bash
uv run pytest
```

The CI pipeline (`.github/workflows/ci.yml`) confirms that `uv run pytest tests/unit` is the standard command for running unit tests.
