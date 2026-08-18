# Release Checklist

Use this checklist before publishing a new package release.

## Version

- Create releases from tags such as `v0.2.0`.
- The Python package version is derived from Git tags through `hatch-vcs`.
- Confirm `core/_version.py` is generated during the build.

## Frontend

- Install frontend dependencies with `npm --prefix frontend ci`.
- Run `npm --prefix frontend run lint`.
- Run `npm --prefix frontend run test`.
- Run `npm --prefix frontend run format:check`.
- Run `npm --prefix frontend run build`.
- Confirm `frontend/dist/index.html` exists before building the Python wheel.

## Starter Database

- Confirm `assets/starter.db` is present and intended for release.
- If refreshing it, stop the API server and run `scripts/build_starter.sh`.
- Verify the wheel contains `core/resources/starter.db`.

## Package Contents

- `frontend/dist` ships in the wheel so installed deployments can serve `/ui`.
- `assets/starter.db` ships in the wheel as `core/resources/starter.db`.
- `examples/` intentionally ships in the wheel as runnable reference material,
  not only in the source distribution.
- `main.py` ships as a compatibility wrapper.

## Smoke Tests

Run the regular gates:

```bash
ruff format --check .
ruff check .
mypy
python -m pytest
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

Run the wheel install smoke test:

```bash
python scripts/smoke_wheel_install.py
```

The smoke test builds the wheel, verifies package data, installs the wheel and
its dependencies into a temporary virtual environment, runs
`know-do-graph init --starter --force`, runs `know-do-graph serve --help`, and
performs a minimal Python client lifecycle.

## Publish

Push the version tag and publish a GitHub release for that tag. The
`.github/workflows/release-pypi.yml` workflow builds the frontend, builds the
Python artifacts, and publishes to PyPI using trusted publishing.
