# Architecture

Companion to the [README](../README.md) quick-start. Covers configuration, how ingestion works, project layout, the Qdrant data model, The Hub API client, local development paths, and testing.

## How it works

1. For each supported country, Hubster calls `/api/v2/jobs` to discover all job IDs (paginated).
2. For each ID, it fetches `/api/jobs/single/{id}` and maps the response to a `JobOpportunity` model.
3. HTML fields are converted to Markdown.
4. A document string is built from the job title, company name, company description, and job description.
5. Qdrant (via `qdrant-client[fastembed]`) embeds the text with `BAAI/bge-small-en-v1.5` and upserts points with metadata (role, location, remote, salary, equity, etc.).

## Requirements

- Python **3.12+** (for local development)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [Docker](https://www.docker.com/) and Docker Compose (recommended for running the full stack)

## Environment variables

Copy `.env.example` to `.env` before running anything locally or via Compose.

| Variable | Description | Example |
|----------|-------------|---------|
| `QDRANT_URL` | Qdrant HTTP endpoint (required) | `http://localhost:6333` (host) / set automatically in Compose |
| `QDRANT_API_KEY` | Qdrant Cloud API key (optional) | *(leave empty for local Qdrant)* |
| `QDRANT_COLLECTION_NAME` | Qdrant collection name (required) | `JOBS_ON_THE_HUB` |
| `QDRANT_DEV_COLLECTION_NAME` | Dev/test collection for retrieval evaluation (must differ from production) | `JOBS_DEV` |
| `EMBEDDING_MODEL` | FastEmbed model ID (required) | `BAAI/bge-small-en-v1.5` |
| `LLM_PROVIDER` | Generation backend for `/chat`: `gemini` (default) or `ollama` | `gemini` |
| `GEMINI_API_KEY` | Google AI Studio API key for `/chat` generation (required when `LLM_PROVIDER=gemini`) | *(set in `.env`)* |
| `GEMINI_MODEL` | Generation model name (optional) | `gemini-2.5-flash` |
| `GEMINI_MAX_RETRIES` | Retries for transient Gemini API failures (optional) | `3` |
| `GEMINI_BACKOFF_FACTOR` | Exponential backoff base between Gemini retries (optional) | `1.0` |
| `GEMINI_TIMEOUT` | Per-request timeout in seconds for Gemini (optional) | `30.0` |
| `OLLAMA_BASE_URL` | Ollama OpenAI-compatible API base URL (when `LLM_PROVIDER=ollama`) | `http://localhost:11434/v1` |
| `OLLAMA_MODEL` | Ollama model tag (when `LLM_PROVIDER=ollama`) | `qwen3:8b` |
| `OLLAMA_TIMEOUT_SECONDS` | Per-request timeout in seconds for Ollama (optional; higher than Gemini for CPU inference) | `60.0` |
| `HUB_CLIENT_MAX_RETRIES` | Retries for transient Hub API failures (optional) | `3` |
| `HUB_CLIENT_BACKOFF_FACTOR` | Exponential backoff base between retries (optional) | `1.0` |
| `HUB_CLIENT_REQUEST_DELAY` | Minimum seconds between outbound Hub requests (optional) | `0.25` |
| `HUB_CLIENT_TIMEOUT` | Per-request timeout in seconds (optional) | `30.0` |

Configuration is loaded via a `Settings` class (`pydantic-settings`) in `db/settings.py`. All required variables must be set in `.env` — missing values raise a clear validation error, not a silently empty string. The FastAPI app validates required settings eagerly at construction time (`create_app()` / `from api.main import app`), so a misconfigured API process fails to start rather than on the first request. The Qdrant client remains lazy — constructed via `get_qdrant_client()` on first real use — so importing `db` alone does not open a network connection.

> In Docker Compose, `QDRANT_URL` is overridden to `http://qdrant:6333` so the app container reaches Qdrant by service name.

## Ingestion

Ingestion is gated behind a Compose profile so it never runs accidentally on `docker compose up`:

```bash
# Incremental sync (default) — add new jobs, remove delisted ones
docker compose --profile ingestion run --rm ingestion

# Full bootstrap seed (first run only)
docker compose --profile ingestion run --rm ingestion python main.py --seed

# One-time backfill after deploying ALE-81 (adds job_title/company to existing points)
docker compose --profile ingestion run --rm ingestion python main.py --backfill
```

**Sync vs seed**

| Mode | Command | When to use |
|------|---------|-------------|
| **Sync** (default) | `python main.py` | Scheduled runs — diffs live listings vs Qdrant, fetches detail only for new jobs, deletes delisted ones |
| **Seed** | `python main.py --seed` | First-time bootstrap of an empty collection |
| **Backfill** | `python main.py --backfill` | One-time migration after deploying [ADR-0003](adr/0003-structured-job-title-company-metadata.md): adds `job_title`/`company` payload fields to points ingested before that change. Idempotent — safe to re-run. Use `--backfill-dev` for `QDRANT_DEV_COLLECTION_NAME`. In Docker: `docker compose --profile ingestion run --rm ingestion python main.py --backfill`. |

Sync never drops the collection, so search stays available throughout. A second sync with no upstream changes makes zero detail fetches and zero Qdrant writes.

> **Deploy note (ALE-81):** After upgrading to a build that promotes `job_title`/`company` to payload metadata, run `uv run python main.py --backfill` once against each production collection before relying on those fields in `/jobs/search` responses. New ingestions get the fields automatically; the backfill only updates already-indexed points.

> **Limitation:** Sync does not detect in-place edits to an existing listing (same `job_id`, changed description). Only additions and removals are reconciled. Hash-based change detection may be added later.

**Scheduling (cron example)**

```cron
0 */6 * * * cd /path/to/hubster && docker compose --profile ingestion run --rm ingestion
```

Runs incremental sync every 6 hours inside the ingestion container.

## Local development

### Docker bind mounts

`docker-compose.override.yml` is loaded automatically and bind-mounts your source code into the containers. Edit a `.py` file and restart the service — no image rebuild needed. The image's `.venv` is preserved via an anonymous volume.

### Without Docker

**1. Install dependencies**

```bash
cd hubster
uv sync
# or: pip install -e .
```

**2. Start Qdrant**

```bash
docker run -p 6333:6333 -p 6334:6334 \
  -v "$(pwd)/qdrant_data:/qdrant/storage" \
  qdrant/qdrant
```

**3. Configure environment**

```bash
cp .env.example .env
```

Ensure `QDRANT_URL=http://localhost:6333` is set in `.env`.

**4. Run ingestion**

```bash
# Incremental sync (default)
uv run python main.py

# Full bootstrap seed (first run only)
uv run python main.py --seed

# One-time backfill after deploying ALE-81 (adds job_title/company to existing points)
uv run python main.py --backfill
```

**5. Run the API and frontend**

API:

```bash
uv run uvicorn api.main:app --reload --port 8000
```

Frontend (in a second terminal):

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) for the chat UI. Job stats are available via `GET /jobs/stats` on the API ([Swagger UI](http://localhost:8000/docs)).

### REST API (local details)

Requires `.env` with Qdrant settings and a running Qdrant instance. Search uses the same `query_jobs_in_qdrant` path verified by the retrieval golden-set tests. `/chat` uses the provider-agnostic `llm_client` package described in [ADR-0001](adr/0001-llm-provider-strategy.md). By default it requires `GEMINI_API_KEY`; set `LLM_PROVIDER=ollama` for local Ollama generation instead (see [ADR-0007](adr/0007-local-generation-fallback-ollama-qwen3.md) and [CONTRIBUTING.md](../CONTRIBUTING.md#local-ollama-generation-optional)).

**CORS:** Browser clients (e.g. a Vite dev server on port 5173) must be listed in `CORS_ALLOWED_ORIGINS` (comma-separated). The default allows `http://localhost:5173`. Override in `.env` when the frontend runs on a different origin.

> Any frontend should call this API rather than Qdrant or The Hub directly. The React chat UI is scoped in [ADR-0004](adr/0004-frontend-architecture-for-chat-interface.md); its visual language (colors, spacing, type, radii) is defined in [ADR-0005](adr/0005-visual-design-tokens-for-the-chat-ui.md). Design tokens live in `frontend/src/styles/tokens.css` as CSS custom properties — components reference tokens by name, never hardcoded hex or px values.

### Frontend (React chat UI)

A minimal React + Vite + TypeScript app in `frontend/` that calls `POST /chat` through a typed API client (`frontend/src/api/client.ts`). Each question is sent independently — conversation history is display-only and never sent to the API (see [ADR-0004](adr/0004-frontend-architecture-for-chat-interface.md)).

Run locally:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

`VITE_API_BASE_URL` defaults to `http://localhost:8000` — the browser-reachable URL, not a Docker-internal hostname.

Via Docker Compose, the `frontend` service is included in `docker compose up --build` and serves the production build at [localhost:5173](http://localhost:5173). The image is built with `VITE_API_BASE_URL` (default `http://localhost:8000` via `.env` or Compose) so the browser (on the host) can reach the published API port.

**Frontend tests**

```bash
cd frontend
npm test
```

Component tests (Vitest + React Testing Library) cover message rendering, loading state, network/HTTP error handling, and the `generated: false` no-match case. They run in CI via the `frontend-test` job in `.github/workflows/test.yml`.

## Project structure

```
hubster/
├── main.py                      # Sync/seed Qdrant, test search
├── frontend/                    # React + Vite chat UI (POST /chat)
│   ├── src/
│   │   ├── api/                 # Typed API client and request/response types
│   │   ├── components/          # Chat view, messages, sources, input
│   │   └── styles/              # Design tokens (tokens.css) and global styles
│   ├── Dockerfile
│   └── package.json
├── api/
│   ├── main.py                  # FastAPI app (jobs stats, semantic search, /chat)
│   └── schemas.py               # API request/response models
├── llm_client/
│   ├── base.py                  # Generator interface
│   ├── gemini.py                # Gemini 2.5 Flash implementation
│   ├── ollama.py                # Ollama (qwen3:8b) implementation
│   └── settings.py              # LLM settings (pydantic-settings)
├── Dockerfile                   # Multi-stage image (uv build, slim runtime)
├── docker-compose.yml           # Qdrant + API + frontend + ingestion/test profiles
├── docker-compose.override.yml  # Dev bind mounts (auto-loaded)
├── the_hub_client/
│   ├── models.py                # Pydantic models (JobOpportunity, CountryCode, …)
│   └── utils.py                 # The Hub API client
├── db/
│   ├── settings.py              # Settings (pydantic-settings) + lazy Qdrant client factory
│   ├── database.py              # Qdrant collection CRUD, embedding, search
│   ├── query_filters.py         # Deterministic country/remote extraction from question text
│   └── db_utils.py              # seed_qdrant_db(), sync_qdrant_db(), CSV export
├── pyproject.toml
├── tests/
│   ├── fixtures/              # Mock Hub API JSON payloads
│   └── the_hub_client/        # Unit tests for API client parsing
└── .env.example
```

## Stored data

Each Qdrant point includes:

**Embedded text**

```
Job Title: …
Company: …
Company Description: …
Job Description: …
```

**Payload metadata**

- `job_url_identifier`, `job_title`, `company`, `job_role`, `Country`, `location`, `Remote`
- `Salary Type`, `Salary`, `Equity`
- `document_text` (full embedded string)

`Country` and `Remote` are indexed as payload fields at collection creation time (`Country` as keyword, `Remote` as boolean) so filtered semantic search stays efficient as the collection grows (see [ADR-0002](adr/0002-retrieval-filtering-strategy.md)). Indexes are only created when a collection is first created; existing collections deployed before this change need to be re-created or migrated manually to gain them.

Point IDs are deterministic UUID5 values derived from the Hub job ID.

## Programmatic usage

```python
from db import create_collection, get_qdrant_client, get_settings, query_jobs_in_qdrant
from the_hub_client import CountryCode

settings = get_settings()
client = get_qdrant_client()

create_collection(client, settings.qdrant_collection_name)

results = query_jobs_in_qdrant(
    db_client=client,
    collection_name=settings.qdrant_collection_name,
    query_text="Looking for a Python developer in Denmark",
    country=CountryCode.DENMARK,
)

for hit in results.points:
    print(hit.score, hit.payload["job_role"])
```

Export to CSV instead of Qdrant:

```python
from db import load_jobs_data_into_csv

load_jobs_data_into_csv("jobs_preview.csv")  # writes to tmp/
```

## The Hub API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/jobs?countryCode={code}&page={n}` | Paginated job listings |
| `GET /api/jobs/single/{job_id}` | Full job details |

Base URL: `https://thehub.io`

Outbound calls go through `the_hub_client/http.py`, which wraps `requests` with:

- **Retries with exponential backoff** on timeouts, connection errors, and 5xx responses (configurable via `HUB_CLIENT_MAX_RETRIES` and `HUB_CLIENT_BACKOFF_FACTOR`)
- **Fail-fast on 4xx** — e.g. a delisted job returning 404 is not retried
- **Client-side pacing** — a small delay between requests (`HUB_CLIENT_REQUEST_DELAY`, default 0.25s) as a courteous default when scraping many pages

During ingestion, a job that still fails after bounded retries is skipped; the overall run continues with remaining jobs.

> **Note:** Pacing and the shared session assume sequential ingestion. Parallel fetch workers require revisiting `the_hub_client/http.py` (see module docstring).

## Testing

Hubster has three test layers:

- **Unit tests** — mock The Hub API responses and verify parsing logic. No network or Qdrant required.
- **Retrieval golden-set tests** — evaluate semantic search quality against a fixed query set in the dev Qdrant collection (`JOBS_DEV`). See [tests/README.md](../tests/README.md).
- **Generation eval tests** — evaluate `/chat` wiring (retrieval → context → `Generator`) against the same dev collection with a scripted generator. No live Gemini calls. See [tests/README.md](../tests/README.md).

The unit test suite runs automatically on every push to `main` and on every pull request targeting `main` via [GitHub Actions](https://github.com/alexmonteirocastro/hubster/actions/workflows/test.yml). CI runs unit tests (`-m "not retrieval and not generation"`) and retrieval/generation eval tests (against a Qdrant service container) in parallel jobs. Local runs use `uv sync --frozen --group dev` directly on the runner for faster feedback; the Docker `test` profile below remains the parity path for local/container runs.

### Run unit tests

**Local (host):**

```bash
uv sync --group dev
uv run pytest -m "not retrieval and not generation"
```

Verbose output:

```bash
uv run pytest -v
```

**Docker:**

```bash
docker compose --profile test run --rm test
```

After changing dependencies in `pyproject.toml` / `uv.lock`, rebuild the shared test image (used by both `test` and `test-retrieval`):

```bash
docker compose --profile test build test
```

The test containers bind-mount source packages (`tests/`, `the_hub_client/`, `api/`, `db/`) but use the Linux virtualenv baked into the image — not your host `.venv`. This avoids stale cached volumes when dependencies change.

Retrieval golden-set and generation eval tests (require Qdrant — see [tests/README.md](../tests/README.md)):

```bash
docker compose --profile test run --rm test-retrieval
```

This runs both `@pytest.mark.retrieval` and `@pytest.mark.generation` tests.

This uses the `test` build target (includes pytest + responses). Unit tests need no Qdrant or network access. With `docker-compose.override.yml` active, edits under the mounted source packages apply without rebuilding the image (rebuild only when dependencies change).

Tests live under `tests/` and use `responses` to mock HTTP at the Hub client boundary (`hub_get`).

## Roadmap / known limitations

- [x] React frontend for `/chat` demo (see [ADR-0004](adr/0004-frontend-architecture-for-chat-interface.md) and [ADR-0005](adr/0005-visual-design-tokens-for-the-chat-ui.md); tracked in ALE-74)
- [x] Dockerize the full stack (Qdrant + API + frontend + ingestion)
- [x] FastAPI backend for job stats and semantic search
- [x] `/chat` RAG endpoint with provider-agnostic generation layer (see [ADR-0001](adr/0001-llm-provider-strategy.md))
- [x] Incremental sync (skip already-ingested jobs instead of full reset)
- [ ] Split dev/eval tooling (`seed_dev_qdrant_db`) out of `db/db_utils.py` into its own module
- [x] Rate limiting and retry logic for API calls
- [ ] Backoff jitter and retry metrics for outbound Hub API calls (before parallel ingestion)
