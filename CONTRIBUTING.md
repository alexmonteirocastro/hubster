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

Configuration lives in `pyproject.toml` — see `[tool.ruff]` and `[tool.mypy]` there for the exact rule set and type-check options.

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

## Local generation for development

Gemini is the default `/chat` provider. For local work without Gemini quota or Ollama latency, use the options below. See [ADR-0007](docs/adr/0007-local-generation-fallback-ollama-qwen3.md) for the Ollama design.

### Stub generator (recommended for UI testing)

Instant, deterministic answers with markdown (`**bold**`, bullet lists). No network, no quota, no CPU wait — ideal for exercising the chat UI and frontend tests against a live API.

In `.env`:

```bash
LLM_PROVIDER=stub
# GEMINI_API_KEY is not required
```

Restart the API after changing provider: `docker compose up -d --force-recreate api`.

### Local Ollama generation (optional)

For exercising the full RAG pipeline with a real local model when Gemini is rate-limited.

**Setup:**

```bash
brew install ollama
ollama pull qwen3:4b
ollama serve
ollama run qwen3:4b   # preload model into memory (avoids cold-start on first /chat)
```

Ollama loads the model lazily on the first request. On CPU, that load can add significant latency to the first `/chat` call. Running `ollama run qwen3:4b` once after `ollama serve` preloads the model so subsequent requests only pay inference time.

When the API runs in Docker and Ollama on the host, set `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` in `.env`.

In `.env`:

```bash
LLM_PROVIDER=ollama
# GEMINI_API_KEY is not required when using Ollama
```

Defaults: `OLLAMA_BASE_URL=http://localhost:11434/v1`, `OLLAMA_MODEL=qwen3:4b`, `OLLAMA_TIMEOUT_SECONDS=60.0`, `OLLAMA_MAX_CHARS_PER_JOB=1200`, `OLLAMA_NUM_PREDICT=256`.

The Ollama adapter calls Ollama's native `/api/chat` endpoint with streaming and `think: false` (see ADR-0007 implementation notes). Job context sent to Ollama is truncated per listing to keep prompts within CPU-friendly limits.

On CPU-only hardware, expect roughly **3–12 tokens/second** — slower than Gemini's cloud API. Use `LLM_PROVIDER=stub` for rapid UI iteration; use Ollama when you specifically need to validate end-to-end generation quality.

### CI summary

| Job | Code-quality checks |
|-----|---------------------|
| `unit-test` | `ruff check .`, `ruff format --check .`, `mypy .`, unit pytest |
| `frontend-test` | `npm run lint`, Vitest |
| `retrieval-test` | retrieval/generation eval pytest only (no lint/type checks) |
