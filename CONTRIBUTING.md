# Contributing

Know-Do Graph uses Python 3.11+ for the backend, agent, CLI, and package code,
and Node.js 20+ for the Vite frontend.

## Local Setup

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

npm --prefix frontend ci
```

Use `npm --prefix frontend install` instead of `ci` when intentionally changing
`frontend/package-lock.json`.

## Common Commands

```bash
# Python tests
python -m pytest

# Python lint
ruff check .

# Python format
ruff format .

# Python typing
mypy

# Frontend build
npm --prefix frontend run build
```

For a full local pre-PR pass, run:

```bash
ruff check .
ruff format --check .
mypy
python -m pytest
npm --prefix frontend ci
npm --prefix frontend run build
```

## Style

- Keep Python compatible with Python 3.11 and newer.
- Use Ruff for import sorting, linting, and formatting.
- Keep the configured Mypy baseline green, and expand `tool.mypy.files` as
  modules are made type-clean.
- Keep source files UTF-8 encoded.
- Prefer typed public boundaries for new code.
- Keep refactors scoped to the responsibility being changed.
- Avoid committing generated files, local databases, virtual environments,
  build outputs, caches, or secrets.

## Release Notes

Before publishing a release, build the frontend, run the Python quality gates,
confirm the starter database is included, and build the Python distribution:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
ruff check .
ruff format --check .
mypy
python -m pytest
python -m build
```
