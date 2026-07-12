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

## Branching

Every branch maps to exactly one Linear ticket (`ALE-NNN`) — this keeps branch, ticket, and PR traceable to each other, consistent with treating Linear as the source of truth for decisions and history.

**Format:**

```
<type>/ALE-<NNN>-<short-slug>
```

- **type** — one of `feat`, `fix`, `docs`, `chore`, `spike`, `refactor`, `test`
- **ALE-NNN** — the Linear ticket this branch implements, exact case
- **short-slug** — 3–6 words, kebab-case, taken from the ticket title

**Examples:**

| Ticket | Branch |
|---|---|
| ALE-125 (write ADR-0013 doc) | `docs/ALE-125-adr-0013-deployment-doc` |
| ALE-126 (deploy implementation) | `feat/ALE-126-deploy-render-cloudflare` |
| ALE-121 (frontend auth modal) | `feat/ALE-121-frontend-auth-lock-modal` |
| ALE-127 (DevOps observability spike) | `spike/ALE-127-devops-observability` |

**Rules:**

- No ticket, no branch. If a change doesn't have an `ALE-NNN` yet, create the ticket first rather than branching without one. Trivial one-line chores (typo fixes, lint config) are the only exception.
- `type` reflects the *ticket's* nature, not the diff's mechanics — an ADR-landing ticket is always `docs/`, even if the PR happens to touch code comments.
- One branch per ticket. Since frontend and backend implementation are always scoped as separate tickets, don't combine them into a single branch.
- All lowercase, hyphen-separated, no underscores or spaces.

This convention is also encoded as a Cursor rule (`.cursor/rules/branch-naming.mdc`) so branch names created via Cursor Agent follow it automatically.

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

#### Docker Compose (host Ollama)

When the API runs inside `docker compose up` and Ollama runs on the host (`ollama serve` outside Docker), **`localhost` inside the API container is not the host machine**. With the default `OLLAMA_BASE_URL=http://localhost:11434/v1`, the container tries to reach itself — `/chat` fails with **502** (`GenerationUnavailableError`).

On macOS and Windows Docker Desktop, set in `.env`:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

Recreate the API after changing provider or URL: `docker compose up -d --force-recreate api`.

Keep the preload step above (`ollama run qwen3:4b`) — it applies whether the API runs natively or in Compose.

On Linux Docker, `host.docker.internal` is not always available out of the box; you may need Compose `extra_hosts` or bind Ollama to `0.0.0.0` — see Docker and Ollama docs if the URL above does not connect.

#### Timeouts on CPU

Default `OLLAMA_TIMEOUT_SECONDS=60` may **502** on full RAG prompts with the default `/chat` `limit=5` (~five retrieved jobs in context). On CPU-only hardware, expect roughly **5–12 tokens/second** (see [ADR-0007 Decision 2](docs/adr/0007-local-generation-fallback-ollama-qwen3.md#decision-2-model-is-qwen38b-served-via-ollama)) — a large prompt plus the default `OLLAMA_NUM_PREDICT=256` output cap can exceed 60 seconds.

For local testing, either:

- Raise `OLLAMA_TIMEOUT_SECONDS` in `.env` (e.g. `180`–`300`), or
- Lower `limit` in `POST /chat` requests (e.g. `2`–`3`) to shrink the retrieved context.

In `.env`:

```bash
LLM_PROVIDER=ollama
# GEMINI_API_KEY is not required when using Ollama
```

Defaults: `OLLAMA_BASE_URL=http://localhost:11434/v1`, `OLLAMA_MODEL=qwen3:4b`, `OLLAMA_TIMEOUT_SECONDS=60.0`, `OLLAMA_MAX_CHARS_PER_JOB=1200`, `OLLAMA_NUM_PREDICT=256`.

The Ollama adapter calls Ollama's native `/api/chat` endpoint with streaming and `think: false` (see ADR-0007 implementation notes). Job context sent to Ollama is truncated per listing to keep prompts within CPU-friendly limits.

Use `LLM_PROVIDER=stub` for rapid UI iteration; use Ollama when you specifically need to validate end-to-end generation quality against a real local model.

### CI summary

| Job | Code-quality checks |
|-----|---------------------|
| `unit-test` | `ruff check .`, `ruff format --check .`, `mypy .`, unit pytest |
| `frontend-test` | `npm run lint`, Vitest |
| `retrieval-test` | retrieval/generation eval pytest only (no lint/type checks) |
| `markdown-link-check` | lychee offline check on `**/*.md` (relative paths and anchors only) |