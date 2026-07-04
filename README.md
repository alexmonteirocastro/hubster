# Hubster

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
| `QDRANT_URL` | Qdrant HTTP endpoint | `http://localhost:6333` (host) / set automatically in Compose |
| `QDRANT_API_KEY` | Qdrant Cloud API key (optional) | *(leave empty for local Qdrant)* |
| `QDRANT_COLLECTION_NAME` | Qdrant collection name | `JOBS_ON_THE_HUB` |
| `EMBEDDING_MODEL` | FastEmbed model ID | `BAAI/bge-small-en-v1.5` |

> In Docker Compose, `QDRANT_URL` is overridden to `http://qdrant:6333` so the app container reaches Qdrant by service name.

### 2. Start the stack

```bash
docker compose up --build
```

This starts:

- **qdrant** — vector database on `localhost:6333` (persisted volume)
- **app** — Streamlit dashboard on [localhost:8501](http://localhost:8501)

### 3. Run ingestion (optional)

Ingestion is gated behind a Compose profile so it never runs accidentally on `docker compose up`:

```bash
docker compose --profile ingestion run --rm ingestion
```

This scrapes all jobs from The Hub and seeds Qdrant. It also runs a sample semantic search at the end.

> **Warning:** `main.py` currently calls `main(reset_db=True)`, which **deletes the collection before each run**. Change to `main(reset_db=False)` for incremental updates.

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

### 4. Run the scraper

```bash
uv run python main.py
```

### 5. Launch the Streamlit app

```bash
uv run streamlit run streamlit_app.py
```

- **Jobs tab** — live stats from The Hub API (totals and breakdown by role)
- **Chat tab** — placeholder demo; not yet wired to Qdrant

## Project structure

```
hubster/
├── main.py                      # Scrape, seed Qdrant, test search
├── streamlit_app.py             # Simple dashboard / demo UI
├── Dockerfile                   # Multi-stage image (uv build, slim runtime)
├── docker-compose.yml           # Qdrant + Streamlit app + ingestion profile
├── docker-compose.override.yml  # Dev bind mounts (auto-loaded)
├── the_hub_client/
│   ├── models.py                # Pydantic models (JobOpportunity, CountryCode, …)
│   └── utils.py                 # The Hub API client
├── db/
│   ├── database.py              # Qdrant client, collection CRUD, embedding, search
│   └── db_utils.py              # seed_qdrant_db(), CSV export
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

- `job_url_identifier`, `job_role`, `Country`, `location`, `Remote`
- `Salary Type`, `Salary`, `Equity`
- `document_text` (full embedded string)

Point IDs are deterministic UUID5 values derived from the Hub job ID.

## Programmatic usage

```python
from db import client, create_collection, query_jobs_in_qdrant

create_collection(client, "JOBS_ON_THE_HUB")

results = query_jobs_in_qdrant(
    db_client=client,
    collection_name="JOBS_ON_THE_HUB",
    query_text="Looking for a Python developer in Denmark",
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

## Testing

Hubster has two test layers:

- **Unit tests** (this section) — mock The Hub API responses and verify parsing logic. No network or Qdrant required.
- **Retrieval golden-set tests** (planned) — evaluate semantic search quality against a fixed query set in Qdrant.

### Run unit tests

```bash
uv sync --group dev
uv run pytest
```

Verbose output:

```bash
uv run pytest -v
```

Tests live under `tests/` and use `responses` to mock HTTP at the `requests.get` boundary.

## Roadmap / known limitations

- [ ] Wire Streamlit chat to Qdrant semantic search (RAG)
- [x] Dockerize the full stack (Qdrant + app + ingestion)
- [ ] Incremental sync (skip already-ingested jobs instead of full reset)
- [ ] Rate limiting and retry logic for API calls
