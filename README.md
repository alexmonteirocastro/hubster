# Hubster

![Tests](https://github.com/alexmonteirocastro/hubster/actions/workflows/test.yml/badge.svg)

Hubster ingests job listings from [The Hub](https://thehub.io/) via their public API, embeds the content with FastEmbed, and stores the results in [Qdrant](https://qdrant.tech/) for semantic search.

Use it to build job-discovery tools, RAG chatbots, or analytics over Nordic/European startup job markets.

## Features

- **API-based ingestion** — fetches paginated job listings and full job details from The Hub REST API
- **Multi-country support** — Denmark, Sweden, Norway, Finland, Iceland, and Europe
- **Vector storage** — embeds job title, company info, and descriptions into Qdrant
- **Semantic search** — query jobs by natural language (e.g. "Python developer in Denmark")
- **Optional CSV export** — dump scraped jobs to `tmp/jobs_preview.csv`
- **Streamlit dashboard** — explore job counts by role and country (chat UI is a work in progress)

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

## Quick start (Docker)

### 1. Configure environment

```bash
cd hubster
cp .env.example .env
```

| Variable | Description | Example |
|----------|-------------|---------|
| `QDRANT_URL` | Qdrant HTTP endpoint (required) | `http://localhost:6333` (host) / set automatically in Compose |
| `QDRANT_API_KEY` | Qdrant Cloud API key (optional) | *(leave empty for local Qdrant)* |
| `QDRANT_COLLECTION_NAME` | Qdrant collection name (required) | `JOBS_ON_THE_HUB` |
| `QDRANT_DEV_COLLECTION_NAME` | Dev/test collection for retrieval evaluation (must differ from production) | `JOBS_DEV` |
| `EMBEDDING_MODEL` | FastEmbed model ID (required) | `BAAI/bge-small-en-v1.5` |
| `GEMINI_API_KEY` | Google AI Studio API key for `/chat` generation (required when using `/chat`) | *(set in `.env`)* |
| `GEMINI_MODEL` | Generation model name (optional) | `gemini-2.5-flash` |
| `GEMINI_MAX_RETRIES` | Retries for transient Gemini API failures (optional) | `3` |
| `GEMINI_BACKOFF_FACTOR` | Exponential backoff base between Gemini retries (optional) | `1.0` |
| `GEMINI_TIMEOUT` | Per-request timeout in seconds for Gemini (optional) | `30.0` |
| `HUB_CLIENT_MAX_RETRIES` | Retries for transient Hub API failures (optional) | `3` |
| `HUB_CLIENT_BACKOFF_FACTOR` | Exponential backoff base between retries (optional) | `1.0` |
| `HUB_CLIENT_REQUEST_DELAY` | Minimum seconds between outbound Hub requests (optional) | `0.25` |
| `HUB_CLIENT_TIMEOUT` | Per-request timeout in seconds (optional) | `30.0` |

Configuration is loaded via a `Settings` class (`pydantic-settings`) in `db/settings.py`. All required variables must be set in `.env` — missing values raise a clear validation error at first use, not a silently empty string. The Qdrant client is constructed lazily via `get_qdrant_client()` on first real use, so importing `db` does not open a network connection.

> In Docker Compose, `QDRANT_URL` is overridden to `http://qdrant:6333` so the app container reaches Qdrant by service name.

### 2. Start the stack

```bash
docker compose up --build
```

This starts:

- **qdrant** — vector database on `localhost:6333` (persisted volume)
- **app** — Streamlit dashboard on [localhost:8501](http://localhost:8501)
- **api** — FastAPI backend on [localhost:8000](http://localhost:8000) ([Swagger UI](http://localhost:8000/docs))

### 3. Run ingestion

Ingestion is gated behind a Compose profile so it never runs accidentally on `docker compose up`:

```bash
# Incremental sync (default) — add new jobs, remove delisted ones
docker compose --profile ingestion run --rm ingestion

# Full bootstrap seed (first run only)
docker compose --profile ingestion run --rm ingestion --seed
```

**Sync vs seed**

| Mode | Command | When to use |
|------|---------|-------------|
| **Sync** (default) | `python main.py` | Scheduled runs — diffs live listings vs Qdrant, fetches detail only for new jobs, deletes delisted ones |
| **Seed** | `python main.py --seed` | First-time bootstrap of an empty collection |

Sync never drops the collection, so search stays available throughout. A second sync with no upstream changes makes zero detail fetches and zero Qdrant writes.

> **Limitation:** Sync does not detect in-place edits to an existing listing (same `job_id`, changed description). Only additions and removals are reconciled. Hash-based change detection may be added later.

**Scheduling (cron example)**

```cron
0 */6 * * * cd /path/to/hubster && docker compose --profile ingestion run --rm ingestion
```

Runs incremental sync every 6 hours inside the ingestion container.

### Local dev with bind mounts

`docker-compose.override.yml` is loaded automatically and bind-mounts your source code into the containers. Edit a `.py` file and restart the service — no image rebuild needed. The image's `.venv` is preserved via an anonymous volume.

## Quick start (local, without Docker)

### 1. Install dependencies

```bash
cd hubster
uv sync
# or: pip install -e .
```

### 2. Start Qdrant

```bash
docker run -p 6333:6333 -p 6334:6334 \
  -v "$(pwd)/qdrant_data:/qdrant/storage" \
  qdrant/qdrant
```

### 3. Configure environment

```bash
cp .env.example .env
```

Ensure `QDRANT_URL=http://localhost:6333` is set in `.env`.

### 4. Run ingestion

```bash
# Incremental sync (default)
uv run python main.py

# Full bootstrap seed (first run only)
uv run python main.py --seed
```

### 5. Launch the Streamlit app

```bash
uv run streamlit run streamlit_app.py
```

- **Jobs tab** — live stats from The Hub API (totals and breakdown by role)
- **Chat tab** — placeholder demo; not yet wired to Qdrant

## REST API

The FastAPI service exposes a stable JSON contract for any frontend or client. It wraps existing Hubster logic — it does not reimplement ingestion or retrieval.

| Endpoint | Description |
|----------|-------------|
| `GET /jobs/stats?country={code}` | Job totals and role breakdown for a country (`DK`, `SE`, `NO`, `FI`, `IS`, `EU`) |
| `GET /jobs/search?q={query}&limit={n}&country={code}&remote={true|false}` | Semantic search over the Qdrant collection (default `limit=5`, max `50`). Optional `country` filter (`DK`, `SE`, `NO`, `FI`, `IS`, `EU`) and optional `remote` filter constrain results via Qdrant payload filtering. |
| `POST /chat` | Single-turn RAG chat: retrieve jobs from Qdrant, then generate a grounded answer via the `Generator` interface (Gemini 2.5 Flash by default). Optional `country`/`remote` in the request body apply payload filters; when omitted, `/chat` infers them from the question text via deterministic keyword matching. Explicit request fields always override inferred values. See [ADR-0001](docs/adr/0001-llm-provider-strategy.md) and [ADR-0002](docs/adr/0002-retrieval-filtering-strategy.md). |

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs) when the `api` service is running.

**Run locally (without Docker):**

```bash
uv run uvicorn api.main:app --reload --port 8000
```

Requires `.env` with Qdrant settings and a running Qdrant instance (see above). Search uses the same `query_jobs_in_qdrant` path verified by the retrieval golden-set tests. `/chat` additionally requires `GEMINI_API_KEY` and uses the provider-agnostic `llm_client` package described in [ADR-0001](docs/adr/0001-llm-provider-strategy.md).

> Any future frontend should call this API rather than Qdrant or The Hub directly.

## Project structure

```
hubster/
├── main.py                      # Sync/seed Qdrant, test search
├── streamlit_app.py             # Simple dashboard / demo UI
├── api/
│   ├── main.py                  # FastAPI app (jobs stats, semantic search, /chat)
│   └── schemas.py               # API request/response models
├── llm_client/
│   ├── base.py                  # Generator interface
│   ├── gemini.py                # Gemini 2.5 Flash implementation
│   └── settings.py              # LLM settings (pydantic-settings)
├── Dockerfile                   # Multi-stage image (uv build, slim runtime)
├── docker-compose.yml           # Qdrant + Streamlit app + ingestion/test profiles
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

`Country` and `Remote` are indexed as payload fields at collection creation time (`Country` as keyword, `Remote` as boolean) so filtered semantic search stays efficient as the collection grows (see [ADR-0002](docs/adr/0002-retrieval-filtering-strategy.md)). Indexes are only created when a collection is first created; existing collections deployed before this change need to be re-created or migrated manually to gain them.

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

## The Hub API endpoints used

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
- **Retrieval golden-set tests** — evaluate semantic search quality against a fixed query set in the dev Qdrant collection (`JOBS_DEV`). See [tests/README.md](tests/README.md).
- **Generation eval tests** — evaluate `/chat` wiring (retrieval → context → `Generator`) against the same dev collection with a scripted generator. No live Gemini calls. See [tests/README.md](tests/README.md).

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

Retrieval golden-set and generation eval tests (require Qdrant — see [tests/README.md](tests/README.md)):

```bash
docker compose --profile test run --rm test-retrieval
```

This runs both `@pytest.mark.retrieval` and `@pytest.mark.generation` tests.

This uses the `test` build target (includes pytest + responses). Unit tests need no Qdrant or network access. With `docker-compose.override.yml` active, edits under the mounted source packages apply without rebuilding the image (rebuild only when dependencies change).

Tests live under `tests/` and use `responses` to mock HTTP at the Hub client boundary (`hub_get`).

## Roadmap / known limitations

- [ ] Wire Streamlit chat to `/chat` RAG endpoint
- [x] Dockerize the full stack (Qdrant + app + ingestion)
- [x] FastAPI backend for job stats and semantic search
- [x] `/chat` RAG endpoint with provider-agnostic generation layer (see [ADR-0001](docs/adr/0001-llm-provider-strategy.md))
- [x] Incremental sync (skip already-ingested jobs instead of full reset)
- [ ] Split dev/eval tooling (`seed_dev_qdrant_db`) out of `db/db_utils.py` into its own module
- [x] Rate limiting and retry logic for API calls
- [ ] Backoff jitter and retry metrics for outbound Hub API calls (before parallel ingestion)
