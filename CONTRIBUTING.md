# Contributing to Hubster

This guide covers code-quality tooling and the checks to run before opening a pull request. For running the stack locally, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#local-development). For testing, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#testing).

## Code quality

CI enforces lint, format, and type checks on every push to `main` and on every pull request targeting `main` (`.github/workflows/test.yml`, `unit-test` job). Run the same commands locally before pushing to catch failures early.

### Prerequisites

Backend dev tools (Ruff, mypy, pre-commit):

```bash
uv sync --group dev
```

Frontend linting (oxlint):

```bash
cd frontend && npm install
```

### Backend (Python)

| Tool | Purpose | Command |
|------|---------|---------|
| [Ruff](https://docs.astral.sh/ruff/) | Lint | `uv run ruff check .` |
| Ruff | Format | `uv run ruff format .` |
| [mypy](https://mypy.readthedocs.io/) | Static type check | `uv run mypy .` |

Configuration lives in `pyproject.toml`. Ruff targets Python 3.12 with rules `E`, `F`, `I`, `UP`, `B`. mypy uses `disallow_untyped_defs` and excludes `tests/` and `frontend/`.

Apply Ruff fixes and formatting locally:

```bash
uv run ruff check --fix .
uv run ruff format .
```

mypy is intentionally **not** included in pre-commit hooks — it is slower and runs in CI instead.

### Frontend (React)

```bash
cd frontend
npm run lint
```

CI runs oxlint in the `frontend-test` job alongside Vitest.

### Pre-commit hooks (optional)

Local hooks catch most issues at commit time. They run Ruff (check + format) on Python files and oxlint when `frontend/` paths change. mypy stays CI-only.

One-time setup:

```bash
uv sync --group dev
cd frontend && npm install && cd ..
uv run pre-commit install
```

Run all hooks manually:

```bash
uv run pre-commit run --all-files
```

Hook configuration lives in `.pre-commit-config.yaml`. Keep the Ruff pre-commit `rev` in sync with the `ruff` version in `pyproject.toml` / `uv.lock`.

### CI summary

| Job | Code-quality checks |
|-----|---------------------|
| `unit-test` | `ruff check .`, `ruff format --check .`, `mypy .`, unit pytest |
| `frontend-test` | `npm run lint`, Vitest |
| `retrieval-test` | retrieval/generation eval pytest only (no lint/type checks) |
